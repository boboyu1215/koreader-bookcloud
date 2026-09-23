import sys,tempfile,unittest,json,threading,http.client,io,zipfile,time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import app

class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();app.DATA=Path(self.tmp.name);app.init()
  app.AUTH_FAILURES.clear()
 def tearDown(self):self.tmp.cleanup()
 def test_private_networks_rejected(self):
  for ip in ['127.0.0.1','169.254.169.254','10.0.0.1','::1','198.18.0.1']:
   with patch.object(app.socket,'getaddrinfo',return_value=[(2,1,6,'',(ip,443))]):
    with self.assertRaises(ValueError):app.public_target('https://example.com/book')
 def test_url_restrictions(self):
  for url in ['http://example.com','file:///etc/passwd','https://u:p@example.com','https://example.com:8080']:
   with self.assertRaises(ValueError):app.public_target(url)
 def test_legado_not_silently_accepted(self):
  with self.assertRaisesRegex(ValueError,'Legado'):app.validate_source({'bookSourceUrl':'https://example.com','ruleSearch':{}})
 def test_versions_preserved(self):
  a={'id':'one','name':'One'};b={'id':'two','name':'Two'}
  book={'title':'Example','authors':['Author'],'url':'https://example.com/a.epub'}
  first=app.normalized_book(a,book);second=app.normalized_book(b,{**book,'language':'zh-Hant','url':'https://example.com/b.epub'})
  self.assertEqual(first['work_id'],second['work_id']);self.assertNotEqual(first['edition_id'],second['edition_id'])
  self.assertNotEqual(app.normalized_book(a,{**book,'authors':[]})['work_id'],app.normalized_book(b,{**book,'authors':[]})['work_id'])
 def test_opds_detail_feeds_and_format_variants(self):
  search=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Book</title><author><name>A</name></author><link rel="subsection" type="application/atom+xml" href="/book.opds"/></entry></feed>'
  detail=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>1</id><title>Book</title><author><name>A</name></author><link rel="http://opds-spec.org/acquisition" type="application/epub+zip" title="EPUB3" href="/a.epub" length="1000"/><link rel="http://opds-spec.org/acquisition" type="application/epub+zip" title="EPUB2" href="/b.epub"/></entry></feed>'
  src={'id':'one','name':'One','type':'opds','url':'https://example.com/search?q={query}'}
  with patch.object(app,'fetch',side_effect=[search,detail]):result=app.provider_search(src,'Book')
  self.assertEqual(len(result),2);self.assertEqual(result[0]['work_id'],result[1]['work_id'])
  self.assertNotEqual(result[0]['edition_id'],result[1]['edition_id']);self.assertEqual(result[0]['version_label'],'EPUB3')
 def test_gutenberg_authorless_search_skips_navigation(self):
  body=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Authors</title><link rel="subsection" type="application/atom+xml" href="/ebooks/authors/search.opds"/></entry><entry><title>Book</title><content>Jane Austen</content><link rel="subsection" type="application/atom+xml;profile=opds-catalog" href="/ebooks/1342.opds"/></entry></feed>'
  books,details=app.opds_parse(body,'https://www.gutenberg.org/ebooks/search/')
  self.assertEqual(details,['https://www.gutenberg.org/ebooks/1342.opds']);self.assertEqual(books,[])
 def test_source_scoped_query_aliases(self):
  s={'url':'https://www.gutenberg.org/ebooks/search/?query={query}'}
  self.assertEqual(app.source_query(s,'鲁迅'),'Lu Xun')
  self.assertEqual(app.source_query(s,'呐喊'),'吶喊')
  self.assertEqual(app.source_query({'url':'https://example.com'},'鲁迅'),'鲁迅')
  self.assertEqual(app.source_query({**s,'query_aliases':{'鲁迅':'custom'}},'鲁迅'),'custom')
 def test_legado_inbox_deduplicates_without_enabling(self):
  source={'bookSourceName':'Test','bookSourceUrl':'https://example.com','ruleSearch':{'name':'h1'}}
  result=app.import_sources([source,source]);self.assertEqual(result['pending_count'],1);self.assertEqual(result['duplicates'],1)
  result=app.import_sources([source]);self.assertEqual(result['pending_count'],0);self.assertEqual(result['duplicates'],1)
  self.assertEqual(len(app.source_list()),1)
  with self.assertRaises(ValueError):app.import_sources([source,{'type':'unknown'}])
 def test_xml_entities_rejected(self):
  with self.assertRaises(ValueError):app.opds_parse(b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><feed/>','https://example.com')
 def test_invalid_book_download_rejected(self):
  for fmt in ['epub','pdf','txt']:
   with self.assertRaises(ValueError):app.validate_file(b'<html>login</html>',fmt)
  buf=io.BytesIO()
  with zipfile.ZipFile(buf,'w') as z:z.writestr('mimetype','application/epub+zip');z.writestr('META-INF/container.xml','<container/>')
  app.validate_file(buf.getvalue(),'epub')
 def test_partial_results_and_disabled_source(self):
  with app.db() as c:
   c.execute('INSERT INTO sources VALUES (?,?)',('bad',json.dumps({'id':'bad','name':'Bad','enabled':True,'type':'gutendex','url':'https://example.com'})))
  def provider(s,q):
   if s['id']=='bad':raise ValueError('timeout')
   return [app.normalized_book(s,{'title':'Example','authors':['A'],'url':'https://example.com/a.epub'})]
  with patch.object(app,'provider_search',side_effect=provider):r=app.search('Example')
  self.assertTrue(r['partial']);self.assertEqual(len(r['works']),1)
  eid=r['works'][0]['editions'][0]['edition_id']
  self.assertNotIn('url',r['works'][0]['editions'][0])
  with app.db() as c:c.execute('DELETE FROM sources WHERE id=?',('gutenberg',))
  with self.assertRaises(ValueError):app.get_edition(eid)
 def test_http_auth_admin_isolation_and_expiry(self):
  srv=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
  t=threading.Thread(target=srv.serve_forever,daemon=True);t.start()
  def req(path,headers=None,method='GET',body=None):
   c=http.client.HTTPConnection('127.0.0.1',srv.server_port,timeout=3)
   c.request(method,path,body=json.dumps(body) if body is not None else None,headers=headers or {})
   r=c.getresponse();data=r.read();c.close();return r.status,json.loads(data)
  try:
   self.assertEqual(req('/bookcloud/health')[0],200)
   self.assertEqual(req('/bookcloud/api/v1/search?q=test')[0],401)
   h={'Authorization':'Bearer '+app.token('device-token')}
   self.assertEqual(req('/bookcloud/admin/sources',h)[0],403)
   self.assertEqual(req('/bookcloud/files/test?expires=1&sig=wrong')[0],403)
   self.assertEqual(req('/bookcloud/admin/login',method='POST',body={'token':app.token('admin-token')})[0],403)
   self.assertEqual(req('/bookcloud/admin/login',headers={'X-BookCloud':'1'},method='POST',body={'token':app.token('admin-token')})[0],200)
  finally:srv.shutdown();srv.server_close();t.join()

if __name__=='__main__':unittest.main()
