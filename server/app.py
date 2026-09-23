"""BookCloud V1: isolated source management, search, editions and signed downloads.
Provider rules are data, never executable code.
"""
import concurrent.futures, hashlib, hmac, http.client, io, ipaddress, json, os
import re, secrets, socket, sqlite3, ssl, threading, time, unicodedata, zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, urljoin, urlencode, parse_qs, quote
import xml.etree.ElementTree as ET
import legado
import source_manager
import difflib

ROOT = Path(__file__).parent
DATA = Path(os.environ.get('BOOKCLOUD_DATA', './data'))
PREFIX = '/bookcloud'
MAX_FILE = 50 * 1024 * 1024
LOCK = threading.Lock()
DOWNLOAD_SLOTS = threading.BoundedSemaphore(2)
SEARCH_SLOTS = threading.BoundedSemaphore(3)
PREPARE_SLOTS = threading.BoundedSemaphore(1)
JOBS = {}
AUTH_FAILURES = {}

def db():
    c = sqlite3.connect(DATA / 'bookcloud.db', timeout=10)
    c.row_factory = sqlite3.Row
    return c

def init():
    DATA.mkdir(parents=True, exist_ok=True)
    for name in ('admin-token', 'device-token', 'signing-key'):
        p = DATA / name
        if not p.exists():
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as f: f.write(secrets.token_urlsafe(32))
    with db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS source_inbox (digest TEXT PRIMARY KEY, name TEXT, data TEXT NOT NULL, imported INTEGER NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS sources (id TEXT PRIMARY KEY, config TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS editions (id TEXT PRIMARY KEY, work_id TEXT NOT NULL, data TEXT NOT NULL, updated INTEGER NOT NULL)')
        c.execute('CREATE INDEX IF NOT EXISTS edition_work ON editions(work_id)')
        c.execute('CREATE TABLE IF NOT EXISTS source_status (id TEXT PRIMARY KEY, tested INTEGER, ok INTEGER, message TEXT)')
        if not c.execute('SELECT 1 FROM sources LIMIT 1').fetchone():
            s = {'id':'gutenberg','name':'古登堡公共书库','type':'opds','enabled':True,'url':'https://www.gutenberg.org/ebooks/search/?query={query}&format=opds'}
            c.execute('INSERT INTO sources VALUES (?,?)',(s['id'],json.dumps(s)))

def token(name): return (DATA / name).read_text().strip()
def stable(s): return hashlib.sha256(s.encode()).hexdigest()[:24]
def public_target(url):
    u = urlsplit(url)
    if u.scheme != 'https' or not u.hostname or u.username or u.password or u.fragment:
        raise ValueError('来源必须是无账号信息的 HTTPS 地址')
    if u.port not in (None,443): raise ValueError('只允许 HTTPS 443 端口')
    hosts = socket.getaddrinfo(u.hostname,443,type=socket.SOCK_STREAM)
    if not hosts or any(not ipaddress.ip_address(h[4][0]).is_global for h in hosts):
        raise ValueError('不允许访问内网或保留地址')
    return u, hosts[0][4][0]

class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, ip):
        super().__init__(host, timeout=12, context=ssl.create_default_context()); self.ip=ip
    def connect(self):
        raw=socket.create_connection((self.ip,443),timeout=self.timeout)
        self.sock=self._context.wrap_socket(raw,server_hostname=self.host)

def fetch(url, limit=4*1024*1024, method="GET", body=None):
    """Validate every redirect and pin the validated public IP for TLS connection."""
    deadline=time.monotonic()+35
    for _ in range(4):
        u,ip=public_target(url)
        conn=PinnedHTTPS(u.hostname,ip)
        try:
            headers={'User-Agent':'BookCloud/0.1 (+personal ereader)','Accept-Encoding':'identity'}
            if body is not None:headers['Content-Type']='application/x-www-form-urlencoded'
            conn.request(method,(u.path or '/')+('?' + u.query if u.query else ''),body=body,headers=headers)
            r=conn.getresponse()
            if r.status in (301,302,303,307,308):
                url=urljoin(url,r.getheader('Location',''))
                if r.status in (301,302,303):method='GET';body=None
                continue
            if r.status != 200: raise ValueError('来源返回 HTTP '+str(r.status))
            length=r.getheader('Content-Length')
            if length and int(length)>limit:raise ValueError('文件超过下载大小限制')
            chunks=[];total=0
            while True:
                if time.monotonic()>deadline:raise ValueError('来源响应超时，请重试')
                chunk=r.read(min(65536,limit-total+1))
                if not chunk:break
                total+=len(chunk)
                if total>limit:raise ValueError('来源内容过大')
                chunks.append(chunk)
            return b''.join(chunks)
        finally:conn.close()
    raise ValueError('来源跳转次数过多')

def source_list():
    with db() as c:return [json.loads(r['config']) for r in c.execute('SELECT config FROM sources ORDER BY id')]

def validate_source(s):
    if not isinstance(s,dict):raise ValueError('书源必须是 JSON 对象')
    if 'bookSourceUrl' in s or 'ruleSearch' in s:
        raise ValueError('V1 不执行 Legado 规则；请使用 OPDS、Gutendex 或 catalog 格式')
    if s.get('type') not in ('gutendex','opds','catalog','legado'):raise ValueError('不支持的书源类型')
    sid=s.get('id') or secrets.token_hex(6)
    if not isinstance(sid,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,60}',sid):raise ValueError('书源 ID 无效')
    if not isinstance(s.get('name'),str) or not s['name'].strip():raise ValueError('请输入书源名称')
    if not isinstance(s.get('enabled',True),bool):raise ValueError('enabled 必须是布尔值')
    out={'id':sid,'name':s['name'][:100],'type':s['type'],'enabled':bool(s.get('enabled',True))}
    aliases=s.get('query_aliases',{})
    if not isinstance(aliases,dict) or len(aliases)>200 or any(not isinstance(k,str) or not isinstance(v,str) or not k.strip() or not v.strip() or len(k)>120 or len(v)>120 for k,v in aliases.items()):raise ValueError('查询别名须为最多 200 项的文字映射')
    out['query_aliases']=aliases
    if s['type']=='legado':
        rules=s.get('rules',{})
        legado.validate(rules)
        public_target(legado.source_base(rules))
        out['rules']=rules
    elif s['type']=='catalog':
        books=s.get('books',[])
        if not isinstance(books,list) or len(books)>1000:raise ValueError('catalog 最多 1000 个版本')
        for b in books:
            if not isinstance(b,dict) or not isinstance(b.get('title'),str) or not b.get('title'):raise ValueError('每个版本必须有书名')
            if b.get('format','epub') not in ('epub','pdf','txt'):raise ValueError('支持 EPUB / PDF / TXT')
            public_target(b.get('url',''))
        out['books']=books
    else:
        url=s.get('url','')
        if not isinstance(url,str):raise ValueError('地址无效')
        if s['type']=='opds' and '{query}' not in url:raise ValueError('OPDS 搜索地址须包含 {query}')
        public_target(url.replace('{query}','test'))
        out['url']=url
    return out

def normalized_book(s,b):
    title=str(b.get('title','')).strip()[:400]
    if not title:return None
    authors=b.get('authors') or []
    if isinstance(authors,str):authors=[authors]
    authors=[str(a)[:200] for a in authors if a]
    fmt=str(b.get('format','epub')).lower()
    if fmt not in ('epub','pdf','txt'):return None
    key=unicodedata.normalize('NFKC',title).casefold()+'|'+ '|'.join(sorted(a.casefold() for a in authors))
    # Unknown authors are deliberately not merged across sources.
    if not authors:key+='|'+s['id']+'|'+str(b.get('id',b.get('url')))
    eid=stable(s['id']+'|'+str(b.get('id',b['url']))+'|'+fmt+'|'+b['url'])
    return {'edition_id':eid,'work_id':stable(key),'title':title,'authors':authors,
            'source_id':s['id'],'source_name':s['name'],'format':fmt,'url':b['url'],
            'language':str(b.get('language') or '未提供')[:80],
            'publisher':str(b.get('publisher') or '')[:150], 'translator':str(b.get('translator') or '')[:150],
            'version_label':str(b.get('version_label') or '')[:160],
            'size_bytes':b.get('size_bytes') if isinstance(b.get('size_bytes'),int) and b['size_bytes']>0 else None}

def opds_parse(body,base):
    if b'<!DOCTYPE' in body.upper() or b'<!ENTITY' in body.upper():raise ValueError('不支持含实体声明的 XML')
    root=ET.fromstring(body);ns={'a':'http://www.w3.org/2005/Atom','dc':'http://purl.org/dc/terms/'}
    entries=[root] if root.tag=='{http://www.w3.org/2005/Atom}entry' else root.findall('a:entry',ns)
    books=[];details=[]
    for entry in entries[:80]:
        authors=[a.text for a in entry.findall('a:author/a:name',ns)]
        for link in entry.findall('a:link',ns):
            href=urljoin(base,link.get('href',''));mime=link.get('type','');rel=link.get('rel','')
            # Gutenberg's search entries put the author in content, not atom:author.
            gutenberg_detail = urlsplit(href).hostname in ('www.gutenberg.org','gutenberg.org') and re.fullmatch(r'/ebooks/\d+\.opds',urlsplit(href).path)
            if rel in ('subsection','alternate') and 'atom+xml' in mime and (authors or gutenberg_detail or 'type=entry' in mime) and urlsplit(href).scheme=='https':
                if href not in details:details.append(href)
            fmt={'application/epub+zip':'epub','application/pdf':'pdf','text/plain':'txt'}.get(mime.split(';')[0])
            if not fmt or not rel.startswith('http://opds-spec.org/acquisition') or urlsplit(href).scheme!='https':continue
            length=link.get('length','')
            books.append({'id':entry.findtext('a:id',default=href,namespaces=ns),
                'title':entry.findtext('a:title',default='',namespaces=ns),'authors':authors,
                'language':entry.findtext('dc:language',default='',namespaces=ns),
                'publisher':entry.findtext('dc:publisher',default='',namespaces=ns),
                'version_label':link.get('title',''),'size_bytes':int(length) if length.isdigit() else None,
                'format':fmt,'url':href})
    return books,details

def source_query(s,q):
    aliases={}
    if urlsplit(s.get('url','')).hostname in ('www.gutenberg.org','gutenberg.org'):
        aliases={'鲁迅':'Lu Xun','魯迅':'Lu Xun','呐喊':'吶喊','彷徨':'徬徨','中国小说史略':'中國小說史略'}
    aliases.update(s.get('query_aliases',{}))
    return aliases.get(unicodedata.normalize('NFKC',q).strip(),q)

def provider_search(s,q):
    q=source_query(s,q)
    books=[]
    if s['type']=='legado':
        books=legado.search(s['rules'],q,fetch)
    elif s['type']=='catalog':
        books=[b for b in s.get('books',[]) if relevance(q,b)>0]
    elif s['type']=='gutendex':
        u=s['url']+ ('&' if '?' in s['url'] else '?') + urlencode({'search':q})
        raw=json.loads(fetch(u))
        for b in raw.get('results',[])[:32]:
            for mime,link in b.get('formats',{}).items():
                fmt='epub' if mime=='application/epub+zip' else 'pdf' if mime=='application/pdf' else None
                if fmt and urlsplit(link).scheme=='https':
                    books.append({'id':str(b['id']),'title':b['title'],'authors':[a['name'] for a in b.get('authors',[])],
                                  'language':', '.join(b.get('languages',[])),'format':fmt,'url':link})
    else:
        search_url=s['url'].replace('{query}',quote(q,safe=''))
        books,details=opds_parse(fetch(search_url),search_url)
        # A number of OPDS catalogs expose a separate acquisition feed per book.
        if details:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                futures=[pool.submit(lambda u: opds_parse(fetch(u),u)[0],u) for u in details[:12]]
                for f in futures:
                    try:books.extend(f.result())
                    except Exception:pass
            if not books:raise ValueError('书籍详情暂不可用，请稍后重试')
    return [x for x in (normalized_book(s,b) for b in books) if x]

def search_text(value):
    return re.sub(r'[^\w]+','',unicodedata.normalize('NFKC',value).casefold())

def relevance(q,book):
    tokens=re.findall(r'\w+',unicodedata.normalize('NFKC',q).casefold())
    q=search_text(q);title=search_text(book['title']);authors=search_text(' '.join(book.get('authors',[])))
    if not q:return 0
    if q==title:return 100
    if q in title:return 80
    if q in authors:return 70
    if len(tokens)>1 and all(t in authors for t in tokens):return 65
    # Tolerate small misspellings only for longer titles; do not make a short
    # Chinese keyword match unrelated books sharing a single character.
    ratio=difflib.SequenceMatcher(None,q,title).ratio()
    return int(ratio*50) if len(q)>=4 and ratio>=.8 else 0

def search(q,only=None):
    sources=[s for s in source_list() if s['enabled'] and (not only or s['id']==only)]
    warnings=[]; editions=[]
    pool=concurrent.futures.ThreadPoolExecutor(max_workers=8)
    futures={pool.submit(provider_search,s,q):s for s in sources}
    try:
        for f in concurrent.futures.as_completed(futures,timeout=65):
            s=futures[f]
            try:
                result=[e for e in f.result() if relevance(q,e)>0 or relevance(source_query(s,q),e)>0];editions+=result;ok=True
                msg=('搜索返回 '+str(len(result))+' 个版本（正文另行校验）') if result else '本次搜索无结果'
            except Exception as exc:
                ok=False;msg=str(exc)[:160];warnings.append(s['name']+'：'+msg)
            with db() as c:c.execute('INSERT OR REPLACE INTO source_status VALUES (?,?,?,?)',(s['id'],int(time.time()),int(ok),msg))
    except concurrent.futures.TimeoutError:
        warnings.append('部分书源未在本次查询时限内返回，可再次搜索')
    finally:
        for f in futures:f.cancel()
        pool.shutdown(wait=False,cancel_futures=True)
    # Previously discovered titles remain searchable by partial title/author.
    active={s['id'] for s in sources};seen={e['edition_id'] for e in editions}
    with db() as c:
        for row in c.execute('SELECT data FROM editions WHERE updated>?',(int(time.time())-30*86400,)):
            e=json.loads(row['data'])
            if e['source_id'] in active and e['edition_id'] not in seen and relevance(q,e)>0:
                editions.append(e);seen.add(e['edition_id'])
    works={}
    with db() as c:
        for e in editions:
            c.execute('INSERT OR REPLACE INTO editions VALUES (?,?,?,?)',(e['edition_id'],e['work_id'],json.dumps(e,ensure_ascii=False),int(time.time())))
            w=works.setdefault(e['work_id'],{'work_id':e['work_id'],'title':e['title'],'authors':e['authors'],'editions':{}})
            w['editions'][e['edition_id']]=public_edition(e)
    result=[]
    for w in works.values():
        w['editions']=list(w['editions'].values()); w['edition_count']=len(w['editions']);result.append(w)
    result.sort(key=lambda w:relevance(q,w),reverse=True)
    return {'works':result,'partial':bool(warnings),'warnings':warnings,'source_count':len(sources),
            'note':'每个远程书源查询首批结果；请使用更具体的书名或作者缩小范围。'}

def public_edition(e):return {k:v for k,v in e.items() if k!='url' and v is not None}
def get_edition(eid):
    with db() as c:r=c.execute('SELECT data FROM editions WHERE id=?',(eid,)).fetchone()
    if not r:raise ValueError('版本已失效，请重新搜索')
    e=json.loads(r['data'])
    if not any(s['id']==e['source_id'] and s['enabled'] for s in source_list()):raise ValueError('此书源已停用')
    return e

def signature(eid,expires):return hmac.new(token('signing-key').encode(),f'{eid}:{expires}'.encode(),hashlib.sha256).hexdigest()
def download_url(eid):
    exp=int(time.time())+900
    return PREFIX+'/files/'+eid+'?'+urlencode({'expires':exp,'sig':signature(eid,exp)})
def validate_file(data,fmt):
    if not data:raise ValueError('来源返回空文件')
    if fmt=='epub':
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                info=z.getinfo('mimetype')
                if info.file_size>100 or z.read(info).strip()!=b'application/epub+zip':raise ValueError()
                if 'META-INF/container.xml' not in z.namelist():raise ValueError()
        except Exception:raise ValueError('来源未返回有效 EPUB，请选择其他版本')
    elif fmt=='pdf' and not data.startswith(b'%PDF-'):raise ValueError('来源未返回有效 PDF')
    elif fmt=='txt' and (b'<html' in data[:500].lower() or b'<!doctype' in data[:500].lower()):raise ValueError('来源返回网页而非文本')

def edition_source(e):
    return next(s for s in source_list() if s['id']==e['source_id'] and s['enabled'])

def prepared_path(eid):
    if not re.fullmatch(r'[a-f0-9]{24}',eid):raise ValueError('版本编号无效')
    return DATA/'prepared'/(eid+'.epub')

def prepare_book(e,source):
    eid=e['edition_id'];deadline=time.monotonic()+600
    def bounded_fetch(url):
        if time.monotonic()>deadline:raise ValueError('准备超时，请稍后重试')
        for attempt in range(3):
            try:return fetch(url)
            except (TimeoutError,ConnectionError,ssl.SSLError,http.client.HTTPException,OSError):
                if attempt==2 or time.monotonic()>deadline:raise ValueError('书源连接超时或中断，请稍后重试')
                time.sleep(attempt+1)
    try:
        chapters=legado.chapters(source['rules'],e['url'],bounded_fetch)
        with LOCK:JOBS[eid].update(total=len(chapters))
        urls={u for _,u in chapters};contents=[None]*len(chapters);size=0
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures={pool.submit(legado.chapter_text,source['rules'],url,bounded_fetch,urls):(i,name) for i,(name,url) in enumerate(chapters)}
            try:
                for f in concurrent.futures.as_completed(futures):
                    i,name=futures[f];text=f.result();size+=len(text.encode())
                    if size>MAX_FILE:raise ValueError('正文超过 50 MB，停止生成')
                    contents[i]=(name,text)
                    with LOCK:JOBS[eid]['completed']+=1
            except Exception:
                deadline=0
                for f in futures:f.cancel()
                raise
        data=legado.make_epub(e['title'],e['authors'],contents);validate_file(data,'epub')
        if len(data)>MAX_FILE:raise ValueError('文件超过 50 MB')
        path=prepared_path(eid);path.parent.mkdir(exist_ok=True)
        # At most four recently prepared books are cached; each expires after an hour.
        for old in path.parent.glob('*.epub'):
            if old.stat().st_mtime<time.time()-3600:old.unlink(missing_ok=True)
        existing=sorted(path.parent.glob('*.epub'),key=lambda p:p.stat().st_mtime)
        for old in existing[:-3]:old.unlink(missing_ok=True)
        tmp=path.with_suffix('.part');tmp.write_bytes(data);tmp.replace(path)
        with LOCK:JOBS[eid].update(status='ready')
    except Exception as exc:
        with LOCK:JOBS[eid].update(status='failed',error=str(exc)[:180])
    finally:PREPARE_SLOTS.release()

def download_state(e,start=False):
    source=edition_source(e);eid=e['edition_id']
    ready={'status':'ready','url':download_url(eid),'format':e['format'],'title':e['title'],'max_bytes':MAX_FILE}
    if source['type']!='legado':return ready
    path=prepared_path(eid)
    if path.exists() and path.stat().st_mtime>time.time()-3600:return ready
    with LOCK:
        job=JOBS.get(eid)
        if job and job['status']=='preparing':return dict(job)
        if not start:return dict(job) if job and job['status']=='failed' else {'status':'failed','error':'准备任务已失效，请重新下载'}
        if not PREPARE_SLOTS.acquire(blocking=False):raise ValueError('正在准备其他书籍，请稍后重试')
        if len(JOBS)>100:JOBS.clear()
        JOBS[eid]={'status':'preparing','completed':0,'total':0}
        threading.Thread(target=prepare_book,args=(e,source),daemon=True).start()
        return dict(JOBS[eid])

def import_sources(incoming):
    if isinstance(incoming,dict):incoming=[incoming]
    if not isinstance(incoming,list) or not incoming or len(incoming)>2000:raise ValueError('每次可导入 1–2000 个书源')
    configs=[];pending={};within_duplicates=0
    for item in incoming:
        if not isinstance(item,dict):raise ValueError('每个书源须为 JSON 对象')
        if 'bookSourceUrl' in item or 'ruleSearch' in item:
            if not isinstance(item.get('bookSourceName'),str) or not isinstance(item.get('ruleSearch'),dict):raise ValueError('Legado 书源缺少名称或搜索规则')
            canonical={k:v for k,v in item.items() if k not in ('customOrder','lastUpdateTime','respondTime','weight')}
            digest=hashlib.sha256(json.dumps(canonical,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            if digest in pending:within_duplicates+=1
            pending[digest]=item
        else:configs.append(validate_source(item))
    if len({s['id'] for s in configs})!=len(configs):raise ValueError('导入包含重复书源 ID')
    if len({s['id'] for s in configs+source_list()})>2000:raise ValueError('可运行书源最多配置 2000 个；Legado 待适配库不计入此限制')
    added=0;duplicates=within_duplicates
    with db() as c:
        for digest,item in pending.items():
            if c.execute('SELECT 1 FROM source_inbox WHERE digest=?',(digest,)).fetchone():duplicates+=1;continue
            c.execute('INSERT INTO source_inbox VALUES (?,?,?,?)',(digest,item['bookSourceName'][:150],json.dumps(item,ensure_ascii=False),int(time.time())))
            added+=1
        for item in configs:
            c.execute('INSERT OR REPLACE INTO sources VALUES (?,?)',(item['id'],json.dumps(item,ensure_ascii=False)))
            c.execute("DELETE FROM editions WHERE json_extract(data, '$.source_id')=?",(item['id'],))
    return {'ok':True,'count':len(configs),'pending_count':added,'duplicates':duplicates,
            'message':f'可运行书源保存 {len(configs)} 个；Legado 待适配入库 {added} 个；跳过重复 {duplicates} 个。待适配书源不会参与搜索。'}

class Handler(BaseHTTPRequestHandler):
    server_version='BookCloud/0.1'
    def log_message(self,fmt,*args): pass # URL signatures and authorization never logged.
    def send(self,status,body,ctype='application/json; charset=utf-8',headers=None):
        if isinstance(body,(dict,list)):body=json.dumps(body,ensure_ascii=False).encode()
        if isinstance(body,str):body=body.encode()
        self.send_response(status)
        self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        for k,v in (headers or {}).items():self.send_header(k,v)
        self.end_headers();self.wfile.write(body)
    def stream_search(self,q):
        # KOReader's socket has a 15-second idle timeout. Send JSON whitespace
        # while providers run; nginx must forward it rather than buffer it.
        done=threading.Event();result={}
        def run():
            try:result['body']=search(q)
            except Exception:result['body']={'error':'搜索服务暂不可用，请重试'}
            finally:done.set()
        threading.Thread(target=run,daemon=True).start()
        self.close_connection=True
        self.send_response(200)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Accel-Buffering','no')
        self.send_header('Connection','close')
        self.end_headers()
        try:
            while True:
                self.wfile.write(b'\n');self.wfile.flush()
                if done.wait(4):break
            self.wfile.write(json.dumps(result['body'],ensure_ascii=False).encode());self.wfile.flush()
        finally:
            # A disconnected client must not release the search slot while its
            # provider fan-out is still running.
            done.wait()

    def body(self):
        n=int(self.headers.get('Content-Length','0'))
        limit=16*1024*1024 if urlsplit(self.path).path==PREFIX+'/admin/import' else 1024*1024
        if n<0 or n>limit:raise ValueError('请求超过大小限制（书源导入最多 16 MB）')
        return json.loads(self.rfile.read(n) or b'{}')
    def is_admin(self):
        values=[x.strip().split('=',1) for x in self.headers.get('Cookie','').split(';') if '=' in x]
        return any(k=='bookcloud_admin' and hmac.compare_digest(v,token('admin-token')) for k,v in values)
    def authenticated(self):
        return self.is_admin() or hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+token('device-token'))
    def do_GET(self):self.handle_request('GET')
    def do_POST(self):self.handle_request('POST')
    def do_DELETE(self):self.handle_request('DELETE')
    def handle_request(self,method):
        try:self.route(method)
        except (ValueError,KeyError,json.JSONDecodeError) as exc:self.send(400,{'error':str(exc)[:200]})
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception:
            self.send(502,{'error':'服务暂不可用，请稍后重试'})
    def route(self,method):
        u=urlsplit(self.path);p=u.path;qs=parse_qs(u.query)
        if p==PREFIX and method=='GET':return self.send(302,b'',headers={'Location':PREFIX+'/'})
        if p in (PREFIX+'/',PREFIX+'/admin') and method=='GET':
            return self.send(200,(ROOT/'admin.html').read_bytes(),'text/html; charset=utf-8',{'Content-Security-Policy':"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'"})
        if p==PREFIX+'/health' and method=='GET':return self.send(200,{'ok':True,'version':'0.2.0-beta.1'})
        if p==PREFIX+'/admin/login' and method=='POST':
            if self.headers.get('X-BookCloud')!='1':return self.send(403,{'error':'请求无效'})
            now=time.time();ip=self.client_address[0]
            with LOCK:
                recent=[t for t in AUTH_FAILURES.get(ip,[]) if now-t<300]
                if len(recent)>=10:return self.send(429,{'error':'尝试过多，请五分钟后再试'})
            if not hmac.compare_digest(str(self.body().get('token','')),token('admin-token')):
                with LOCK:AUTH_FAILURES[ip]=recent+[now]
                return self.send(401,{'error':'管理口令不正确'})
            return self.send(200,{'ok':True},headers={'Set-Cookie':'bookcloud_admin='+token('admin-token')+'; Path=/bookcloud; Secure; HttpOnly; SameSite=Strict; Max-Age=28800'})
        if p==PREFIX+'/admin/logout' and method=='POST':return self.send(200,{'ok':True},headers={'Set-Cookie':'bookcloud_admin=; Path=/bookcloud; Secure; HttpOnly; SameSite=Strict; Max-Age=0'})
        if p.startswith(PREFIX+'/files/') and method=='GET':
            eid=p.rsplit('/',1)[-1];exp=int(qs.get('expires',['0'])[0]);sig=qs.get('sig',[''])[0]
            if exp<time.time() or exp>time.time()+901 or not hmac.compare_digest(sig,signature(eid,exp)):
                return self.send(403,{'error':'下载链接已过期，请重试'})
            if not DOWNLOAD_SLOTS.acquire(blocking=False):return self.send(429,{'error':'下载繁忙，请稍后重试'})
            try:
                e=get_edition(eid)
                if edition_source(e)['type']=='legado':
                    path=prepared_path(eid)
                    if not path.exists() or path.stat().st_mtime<time.time()-3600:raise ValueError('文件缓存已过期，请重新下载')
                    data=path.read_bytes()
                else:data=fetch(e['url'],MAX_FILE)
                validate_file(data,e['format'])
                mime={'epub':'application/epub+zip','pdf':'application/pdf','txt':'text/plain'}[e['format']]
                return self.send(200,data,mime,{'Content-Disposition':"attachment; filename=book."+e['format']+"; filename*=UTF-8''"+quote(e['title']+'.'+e['format'],safe=''),'X-Content-SHA256':hashlib.sha256(data).hexdigest()})
            finally:DOWNLOAD_SLOTS.release()
        if not self.authenticated():return self.send(401,{'error':'需要登录或设备凭据'})
        if p.startswith(PREFIX+'/admin/'):
            if not self.is_admin():return self.send(403,{'error':'需要管理员权限'})
            if method!='GET' and self.headers.get('X-BookCloud')!='1':return self.send(403,{'error':'请求无效'})
            if p==PREFIX+'/admin/sources' and method=='GET':
                with db() as c:status={r['id']:dict(r) for r in c.execute('SELECT * FROM source_status')}
                with db() as c:pending=c.execute('SELECT COUNT(*) FROM source_inbox').fetchone()[0]
                return self.send(200,{'sources':source_list(),'status':status,'pending_count':pending})
            if p==PREFIX+'/admin/inbox/export' and method=='GET':
                with db() as c:items=[json.loads(r['data']) for r in c.execute('SELECT data FROM source_inbox')]
                return self.send(200,items)
            if p==PREFIX+'/admin/inbox' and method=='GET':
                return self.send(200,source_manager.listing(__import__(__name__),qs.get('q',[''])[0],max(0,int(qs.get('offset',['0'])[0]))))
            if p==PREFIX+'/admin/inbox/check' and method=='POST':
                import sys
                query=str(self.body().get('q','方法论')).strip()[:120] or '方法论'
                return self.send(200,source_manager.start(sys.modules[__name__],query))
            if p==PREFIX+'/admin/import' and method=='POST':
                return self.send(200,import_sources(self.body()))
            if p==PREFIX+'/admin/sources' and method=='POST':
                s=validate_source(self.body())
                with db() as c:
                    if len(source_list())>=2000 and not any(x['id']==s['id'] for x in source_list()):raise ValueError('最多配置 2000 个书源')
                    c.execute('INSERT OR REPLACE INTO sources VALUES (?,?)',(s['id'],json.dumps(s,ensure_ascii=False)))
                    c.execute('DELETE FROM editions WHERE json_extract(data,\'$.source_id\')=?',(s['id'],))
                return self.send(200,{'ok':True})
            if p.startswith(PREFIX+'/admin/sources/') and method=='DELETE':
                sid=p.rsplit('/',1)[-1]
                with db() as c:
                    c.execute('DELETE FROM sources WHERE id=?',(sid,))
                    c.execute('DELETE FROM editions WHERE json_extract(data,\'$.source_id\')=?',(sid,))
                return self.send(200,{'ok':True})
            if p==PREFIX+'/admin/test' and method=='POST':
                b=self.body();q=str(b.get('q','')).strip()
                if not q or len(q)>120:raise ValueError('请输入 1–120 字的书名或作者')
                return self.send(200,search(q,str(b.get('id',''))))
        if p==PREFIX+'/api/v1/search' and method=='GET':
            q=qs.get('q',[''])[0].strip()
            if not q or len(q)>120:raise ValueError('请输入 1–120 字的书名或作者')
            if not SEARCH_SLOTS.acquire(blocking=False):return self.send(429,{'error':'正在处理其他搜索，请稍后重试'})
            try:return self.stream_search(q)
            finally:SEARCH_SLOTS.release()
        if p==PREFIX+'/api/v1/downloads' and method=='POST':
            e=get_edition(self.body()['edition_id'])
            return self.send(200,download_state(e,start=True))
        if p.startswith(PREFIX+'/api/v1/downloads/') and method=='GET':
            return self.send(200,download_state(get_edition(p.rsplit('/',1)[-1])))
        return self.send(404,{'error':'页面不存在'})

if __name__=='__main__':
    init();ThreadingHTTPServer(('0.0.0.0',int(os.environ.get('PORT','8080'))),Handler).serve_forever()
