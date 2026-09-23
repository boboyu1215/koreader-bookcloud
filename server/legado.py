"""Conservative Legado text-source adapter. Supported rules are evaluated as data.
No JavaScript, WebView, login, network headers or executable URL options.
"""
import html,io,json,re,time,zipfile,hashlib,ast
from urllib.parse import urljoin,urlsplit,urlunsplit,quote
from bs4 import BeautifulSoup,Tag
import regex

class Unsupported(ValueError):pass

def validate(source):
    if source.get('bookSourceType',0)!=0:raise Unsupported('暂仅支持文本书源')
    if any(source.get(k) for k in ('loginUrl','loginUi','loginCheckJs')):raise Unsupported('登录相关书源须单独验证')
    if not source.get('searchUrl') or not source.get('ruleSearch',{}).get('bookList'):raise Unsupported('缺少搜索地址或列表规则')
    if not source.get('ruleToc',{}).get('chapterList') or not source.get('ruleContent',{}).get('content'):raise Unsupported('缺少目录或正文规则')
    fields=[source['searchUrl']]
    for name in ('ruleSearch','ruleBookInfo','ruleToc','ruleContent'):
        for key,value in source.get(name,{}).items():
            if key in ('webJs','sourceRegex','init') and value:raise Unsupported('暂不支持预处理或浏览器脚本')
            if isinstance(value,str):fields.append(value)
    for value in fields:
        if any(x in value for x in ('<js','@js:','java.','@put:','@get:','@xpath:','//','||')) and not value.startswith(('http://','https://')):
            raise Unsupported('此规则包含尚未支持的脚本、XPath 或组合语法')
    return source

def document(raw):
    if isinstance(raw,(Tag,dict,list)):return raw
    if isinstance(raw,bytes):
        # BeautifulSoup detects the declared HTML charset; JSON is UTF-8.
        if raw.lstrip().startswith((b'{',b'[')):return json.loads(raw)
        return BeautifulSoup(raw,'html.parser')
    if isinstance(raw,str) and raw.lstrip().startswith(('{','[')):return json.loads(raw)
    return BeautifulSoup(raw or '','html.parser')

def json_get(value,path):
    if not re.fullmatch(r'\$(?:\.[A-Za-z_][\w]*|\[\d+\])*',path):raise Unsupported('暂不支持此 JSONPath')
    for name,index in re.findall(r'\.([A-Za-z_][\w]*)|\[(\d+)\]',path[1:]):
        try:value=value[name] if name else value[int(index)]
        except (KeyError,IndexError,TypeError):return None
    return value

def select(root,rule):
    if not rule:return [root]
    if rule.startswith('$.'):
        value=json_get(root,rule);return value if isinstance(value,list) else ([] if value is None else [value])
    if rule.startswith('@css:'):rule=rule[5:]
    current=[root]
    for part in rule.strip('@').split('@'):
        if not part:continue
        exclude=[]
        if '!' in part:
            part,suffix=part.rsplit('!',1)
            if not re.fullmatch(r'-?\d+(?::-?\d+)*',suffix):raise Unsupported('不支持的排除规则')
            exclude=[int(x) for x in suffix.split(':')]
        match=re.search(r'\.(-?\d+)$',part)
        index=int(match[1]) if match else None
        if match:part=part[:match.start()]
        textmatch=re.fullmatch(r'text\.(.+)',part)
        part=re.sub(r'\bclass\.([\w-]+)',r'.\1',part)
        part=re.sub(r'\bid\.([\w-]+)',r'#\1',part)
        part=re.sub(r'\btag\.([\w-]+)',r'\1',part)
        part=part.replace(':contains(',':-soup-contains(')
        result=[]
        for node in current:
            if not isinstance(node,Tag):continue
            try:found=[a for a in node.find_all('a') if a.get_text(strip=True)==textmatch[1]] if textmatch else node.select(part)
            except Exception as e:raise Unsupported('无效的选择器规则') from e
            if exclude:found=[x for i,x in enumerate(found) if i not in {j if j>=0 else len(found)+j for j in exclude}]
            if index is not None:found=found[index:index+1] if index>=0 else found[len(found)+index:len(found)+index+1]
            result.extend(found)
        current=result
    return current

def value(root,rule,base=''):
    if not rule:return ''
    if '{{' in rule:
        def replace(m):
            expr=m[1].strip()
            if expr=='baseUrl':return base
            if expr.startswith('$.'):return str(json_get(root,expr) or '')
            raise Unsupported('不支持的模板表达式')
        rule=re.sub(r'\{\{(.*?)\}\}',replace,rule)
    parts=rule.split('##');expr=parts[0]
    if '&&' in expr:text=' '.join(value(root,p,base) for p in expr.split('&&'))
    elif expr.startswith(('https://','http://')):text=expr
    elif expr.startswith('$.'):text=str(json_get(root,expr) or '')
    else:
        expr=expr.removeprefix('@css:').strip('@')
        chain=expr.split('@');end=chain[-1]
        if end in ('text','textNodes','html','href','src','content','value','data-src','data-original'):
            nodes=select(root,'@'.join(chain[:-1]))
        else:nodes=select(root,expr);end='text'
        values=[]
        for node in nodes:
            if not isinstance(node,Tag):values.append(str(node));continue
            if end in ('text','textNodes'):values.append(node.get_text('\n' if end=='textNodes' else ' ',strip=True))
            elif end=='html':values.append(str(node))
            else:values.append(str(node.get(end,'')))
        text='\n'.join(values)
    if len(parts)>1:
        replacement=parts[2] if len(parts)>2 else ''
        replacement=re.sub(r'\$(\d+)',r'\\g<\1>',replacement)
        text=regex.sub(parts[1],replacement,text,timeout=.15)
    return text.strip()

def source_base(source):
    u=urlsplit(source['bookSourceUrl']);return urlunsplit(('https' if u.scheme=='http' else u.scheme,u.netloc,u.path,u.query,''))

def search(source,q,fetch):
    validate(source);base=source_base(source)
    parts=re.split(r',\s*(?=\{)',source['searchUrl'],maxsplit=1);path=parts[0];options={}
    if len(parts)>1:
        try:options=json.loads(parts[1])
        except json.JSONDecodeError:
            try:options=ast.literal_eval(parts[1])
            except (ValueError,SyntaxError):raise Unsupported('请求参数格式不兼容')
        if not isinstance(options,dict) or set(options)-{'method','body','charset'}:raise Unsupported('请求参数含尚未支持的选项')
    charset=str(options.get('charset','utf-8')).lower()
    if charset not in ('utf-8','utf8','gbk','gb2312','big5'):raise Unsupported('不支持的请求编码')
    def expand(text):
        text=text.replace('{{key}}',quote(q,safe='',encoding=charset)).replace('{{page}}','1')
        if '{{' in text:raise Unsupported('暂不支持动态请求参数')
        return text
    path=expand(path);url=urljoin(base,path)
    if url.startswith('http://'):url='https://'+url[7:]
    method=str(options.get('method','GET')).upper()
    if method not in ('GET','POST'):raise Unsupported('仅支持 GET 和 POST 搜索')
    if method=='POST':
        body=options.get('body','')
        if not isinstance(body,str):raise Unsupported('搜索表单必须是文本')
        raw=fetch(url,method='POST',body=expand(body).encode(charset))
    else:raw=fetch(url)
    if charset not in ('utf-8','utf8'):raw=raw.decode(charset,errors='replace')
    root=document(raw);rules=source['ruleSearch'];books=[]
    for node in select(root,rules['bookList'])[:30]:
        title=value(node,rules.get('name',''),url);link=value(node,rules.get('bookUrl',''),url)
        if not title or not link:continue
        author=value(node,rules.get('author',''),url)
        author=re.sub(r'^(作者[：:]\s*)','',author)
        books.append({'title':title,'authors':[author] if author else [],'format':'epub','language':'zh',
            'url':urljoin(url,link).replace('http://','https://',1),'version_label':'正文合成 EPUB','id':urljoin(url,link)})
    return books

def chapters(source,book_url,fetch):
    root=document(fetch(book_url));info=source.get('ruleBookInfo',{});toc_url=value(root,info.get('tocUrl',''),book_url)
    page=urljoin(book_url,toc_url).replace('http://','https://',1) if toc_url else book_url
    rules=source['ruleToc'];result=[];visited=set();urls=set()
    while page and page not in visited:
        if len(visited)>=30:raise ValueError('目录分页超过限制，未生成不完整书籍')
        visited.add(page);doc=root if page==book_url else document(fetch(page))
        for node in select(doc,rules['chapterList']):
            if value(node,rules.get('isVip',''),page):raise ValueError('目录含需授权章节，停止生成')
            name=value(node,rules.get('chapterName','text'),page);url=value(node,rules.get('chapterUrl','href'),page)
            if name and url:
                url=urljoin(page,url).replace('http://','https://',1)
                if url not in urls:urls.add(url);result.append((name,url))
        if len(result)>1000:raise ValueError('目录超过 1000 章，未生成不完整书籍')
        next_url=value(doc,rules.get('nextTocUrl',''),page).splitlines()
        page=urljoin(page,next_url[0]).replace('http://','https://',1) if next_url and next_url[0] else ''
    if not result:raise ValueError('书源目录规则没有提取到章节')
    return result

def chapter_text(source,url,fetch,chapter_urls):
    rules=source['ruleContent'];pieces=[];seen=set()
    while url and url not in seen:
        if len(seen)>=20:raise ValueError('章节分页过多')
        seen.add(url);doc=document(fetch(url));text=value(doc,rules['content'],url)
        replace=rules.get('replaceRegex','')
        if replace:
            parts=replace.split('##');pattern=parts[1] if parts[0]=='' and len(parts)>1 else parts[0]
            replacement=parts[2] if len(parts)>2 else ''
            text=regex.sub(pattern,replacement,text,timeout=.15)
        clean=BeautifulSoup(text,'html.parser')
        for tag in clean(['script','style']):tag.decompose()
        for tag in clean.find_all('br'):tag.replace_with('\n')
        text=clean.get_text('\n',strip=True)
        if len(text)<20:raise ValueError('正文为空或过短，停止生成')
        pieces.append(text)
        nxt=value(doc,rules.get('nextContentUrl',''),url)
        nxt=urljoin(url,nxt).replace('http://','https://',1) if nxt else ''
        if nxt in chapter_urls:break # 下一章 is not another page of this chapter.
        url=nxt
    return '\n\n'.join(pieces)

def make_epub(title,authors,contents):
    esc=html.escape;buf=io.BytesIO();identifier='urn:sha256:'+hashlib.sha256((title+str(authors)).encode()).hexdigest()
    with zipfile.ZipFile(buf,'w',compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('mimetype','application/epub+zip',compress_type=zipfile.ZIP_STORED)
        z.writestr('META-INF/container.xml','<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        manifest=[];spine=[];nav=[]
        for i,(name,text) in enumerate(contents):
            filename=f'c{i}.xhtml';manifest.append(f'<item id="c{i}" href="{filename}" media-type="application/xhtml+xml"/>');spine.append(f'<itemref idref="c{i}"/>')
            z.writestr('OEBPS/'+filename,'<?xml version="1.0" encoding="UTF-8"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>'+esc(name)+'</title></head><body><h1>'+esc(name)+'</h1>'+''.join('<p>'+esc(p)+'</p>' for p in text.splitlines() if p.strip())+'</body></html>')
            nav.append(f'<li><a href="{filename}">{esc(name)}</a></li>')
        z.writestr('OEBPS/nav.xhtml','<?xml version="1.0" encoding="UTF-8"?><html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>目录</title></head><body><nav epub:type="toc"><ol>'+''.join(nav)+'</ol></nav></body></html>')
        z.writestr('OEBPS/content.opf','<?xml version="1.0" encoding="UTF-8"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">'+esc(identifier)+'</dc:identifier><dc:title>'+esc(title)+'</dc:title><dc:language>zh</dc:language>'+''.join('<dc:creator>'+esc(a)+'</dc:creator>' for a in authors)+'<meta property="dcterms:modified">'+time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())+'</meta></metadata><manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'+''.join(manifest)+'</manifest><spine>'+''.join(spine)+'</spine></package>')
    return buf.getvalue()
