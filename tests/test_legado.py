import sys,unittest,io,zipfile,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import legado
class RuleTests(unittest.TestCase):
 def setUp(self):
  self.source={'bookSourceName':'fixture','bookSourceUrl':'https://example.org','bookSourceType':0,'searchUrl':'/search?q={{key}}',
   'ruleSearch':{'bookList':'class.books@li','name':'a@text','bookUrl':'a@href','author':'p.0@text'},
   'ruleBookInfo':{},'ruleToc':{'chapterList':'#list a','chapterName':'text','chapterUrl':'href'},'ruleContent':{'content':'#content@html','nextContentUrl':'text.下一章@href'}}
 def test_complete_pipeline_and_next_chapter_not_duplicated(self):
  pages={'https://example.org/search?q=Test':b'<ul class="books"><li><a href="/book">Test</a><p>Author</p></li></ul>',
   'https://example.org/book':b'<div id="list"><a href="/1">One</a><a href="/2">Two</a></div>',
   'https://example.org/1':b'<div id="content">This is the first chapter. It has enough readable text.</div><a href="/2">\xe4\xb8\x8b\xe4\xb8\x80\xe7\xab\xa0</a>',
   'https://example.org/2':b'<div id="content">This is the second chapter. It also has enough text.</div>'}
  books=legado.search(self.source,'Test',pages.__getitem__);self.assertEqual(books[0]['title'],'Test')
  chapters=legado.chapters(self.source,books[0]['url'],pages.__getitem__);self.assertEqual(len(chapters),2)
  contents=[(name,legado.chapter_text(self.source,url,pages.__getitem__,{u for _,u in chapters})) for name,url in chapters]
  self.assertNotIn('second',contents[0][1]);data=legado.make_epub('Test',['Author'],contents)
  with zipfile.ZipFile(io.BytesIO(data)) as z:
   self.assertEqual(z.read('mimetype'),b'application/epub+zip');self.assertIn('OEBPS/c1.xhtml',z.namelist())
 def test_unsupported_never_executed(self):
  with self.assertRaises(legado.Unsupported):legado.validate({**self.source,'ruleContent':{'content':'@js:java.ajax("http://localhost")'}})
 def test_json_template_and_index(self):
  self.assertEqual(legado.value({'id':123},'https://example.org/{{$.id}}'),'https://example.org/123')
  self.assertEqual(legado.value(legado.document('<p>A</p><p>B</p>'),'p.1@text'),'B')
 def test_no_empty_book_created(self):
  with self.assertRaises(ValueError):legado.chapters(self.source,'https://example.org/book',lambda _:b'<html>Login required</html>')
 def test_post_search_options_are_data(self):
  source={**self.source,'searchUrl':'/search,{"method":"POST","body":"q={{key}}","charset":"gbk"}'}
  calls=[]
  def fetch(url,**kwargs):
   calls.append((url,kwargs));return b'<ul class="books"><li><a href="/book">Book</a><p>A</p></li></ul>'
  result=legado.search(source,'方法论',fetch)
  self.assertEqual(len(result),1);self.assertEqual(calls[0][1]['method'],'POST');self.assertTrue(calls[0][1]['body'].startswith(b'q=%'))
 def test_http_source_upgrades_to_verified_https(self):
  self.assertEqual(legado.source_base({'bookSourceUrl':'http://example.org'}),'https://example.org')
