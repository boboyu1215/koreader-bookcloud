import tempfile,unittest,sys,json,time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import app,source_manager
class SourceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();app.DATA=Path(self.tmp.name);app.init()
 def tearDown(self):self.tmp.cleanup()
 def test_partial_titles_and_author(self):
  self.assertGreater(app.relevance('方法论',{'title':'社会科学方法论','authors':[]}),0)
  self.assertGreater(app.relevance('方法论',{'title':'方法论','authors':[]}),app.relevance('方法论',{'title':'社会科学方法论','authors':[]}))
  self.assertEqual(app.relevance('方法论',{'title':'西游记','authors':[]}),0)
  self.assertGreater(app.relevance('pride',{'title':'Pride and Prejudice','authors':[]}),0)
 def test_cache_partial_match_respects_disabled_sources(self):
  e=app.normalized_book({'id':'gutenberg','name':'G'},{'title':'社会科学方法论','authors':['A'],'url':'https://example.org/a.epub'})
  with app.db() as c:c.execute('INSERT INTO editions VALUES (?,?,?,?)',(e['edition_id'],e['work_id'],json.dumps(e),int(time.time())))
  with patch.object(app,'provider_search',return_value=[]):self.assertEqual(len(app.search('方法论')['works']),1)
  with app.db() as c:c.execute('DELETE FROM sources')
  self.assertEqual(app.search('方法论')['works'],[])
 def test_batch_does_not_enable_unsupported_or_empty_sources(self):
  for i in range(3):
   app.import_sources([{'bookSourceName':'Source'+str(i),'bookSourceUrl':'https://example.org/'+str(i),'ruleSearch':{}}])
  source_manager.start(app,'方法论')
  for _ in range(100):
   if not source_manager.STATE['running']:break
   time.sleep(.01)
  result=source_manager.listing(app)
  self.assertEqual(result['total'],3);self.assertEqual(result['counts'],{'unsupported':3})
  self.assertEqual(len(app.source_list()),1)

 def test_remote_recommendations_are_not_search_matches(self):
  source={'id':'gutenberg','name':'G'}
  books=[app.normalized_book(source,{'title':title,'authors':['A'],'url':'https://example.org/'+str(i)+'.epub'}) for i,title in enumerate(['社会科学方法论','西游记'])]
  with patch.object(app,'provider_search',return_value=books):
   result=app.search('方法论')
  self.assertEqual([w['title'] for w in result['works']],['社会科学方法论'])
