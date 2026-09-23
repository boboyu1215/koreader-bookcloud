import unittest,tempfile,time,sys,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import app
class PreparationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();app.DATA=Path(self.tmp.name);app.init();app.JOBS.clear()
  self.s={'id':'text','type':'legado','enabled':True,'name':'Text','rules':{}}
  with app.db() as c:c.execute('INSERT INTO sources VALUES (?,?)',('text',json.dumps(self.s)))
  self.e={'edition_id':'a'*24,'source_id':'text','url':'https://example.org/book','format':'epub','title':'Test','authors':['Author']}
 def tearDown(self):self.tmp.cleanup()
 def finish(self):
  deadline=time.time()+3
  while time.time()<deadline:
   with app.LOCK:j=dict(app.JOBS.get(self.e['edition_id'],{}))
   if j.get('status') in ('ready','failed'):return j
   time.sleep(.01)
  self.fail('Preparation never finished')
 def test_job_to_real_epub_and_cache(self):
  with patch.object(app.legado,'chapters',return_value=[('One','https://example.org/1'),('Two','https://example.org/2')]),patch.object(app.legado,'chapter_text',return_value='Readable chapter content for testing.'):
   self.assertEqual(app.download_state(self.e,True)['status'],'preparing')
   self.assertEqual(self.finish()['status'],'ready')
  result=app.download_state(self.e);self.assertEqual(result['status'],'ready');self.assertIn('/files/',result['url'])
  app.validate_file(app.prepared_path(self.e['edition_id']).read_bytes(),'epub')
 def test_failed_chapter_cannot_produce_partial_download(self):
  with patch.object(app.legado,'chapters',return_value=[('One','https://example.org/1')]),patch.object(app.legado,'chapter_text',side_effect=ValueError('正文缺失')):
   app.download_state(self.e,True);self.assertEqual(self.finish()['status'],'failed')
  self.assertFalse(app.prepared_path(self.e['edition_id']).exists());self.assertIn('正文缺失',app.download_state(self.e)['error'])
 def test_concurrent_preparations_are_bounded(self):
  app.PREPARE_SLOTS.acquire()
  try:
   with self.assertRaisesRegex(ValueError,'其他书籍'):app.download_state(self.e,True)
  finally:app.PREPARE_SLOTS.release()

 def test_transient_connection_retried(self):
  def toc(rules,url,fetch):
   fetch(url)
   return [('One','https://example.org/1')]
  with patch.object(app.legado,'chapters',side_effect=toc),patch.object(app.legado,'chapter_text',return_value='Readable chapter content.'),patch.object(app,'fetch',side_effect=[TimeoutError(),b'ok']) as fetch:
   app.download_state(self.e,True);self.assertEqual(self.finish()['status'],'ready');self.assertEqual(fetch.call_count,2)
