import sys,unittest,tempfile,json,threading,http.client,time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import app
class KoboTransportTests(unittest.TestCase):
 def test_absent_size_is_not_json_null(self):
  e=app.normalized_book({'id':'s','name':'S'},{'title':'Test','url':'https://example.org/book','authors':['Author']})
  self.assertIsNone(e['size_bytes'])
  self.assertNotIn('size_bytes',app.public_edition(e))
  self.assertNotIn('null',json.dumps(app.public_edition(e)))
 def test_headers_and_whitespace_arrive_before_search_finishes(self):
  with tempfile.TemporaryDirectory() as d:
   app.DATA=Path(d);app.init()
   started=threading.Event();finish=threading.Event()
   def slow(q):started.set();finish.wait(3);return {'works':[],'source_count':20}
   server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
   threading.Thread(target=server.serve_forever,daemon=True).start()
   conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=2)
   try:
    with patch.object(app,'search',side_effect=slow):
     conn.request('GET','/bookcloud/api/v1/search?q=test',headers={'Authorization':'Bearer '+app.token('device-token')})
     response=conn.getresponse();self.assertEqual(response.status,200)
     self.assertEqual(response.getheader('X-Accel-Buffering'),'no')
     self.assertEqual(response.read(1),b'\n');self.assertTrue(started.is_set());self.assertFalse(finish.is_set())
     finish.set();self.assertEqual(json.loads(response.read())['source_count'],20)
   finally:finish.set();conn.close();server.shutdown();server.server_close()
