"""Imported-source inventory and bounded, resumable validation."""
import json,threading,time,concurrent.futures
LOCK=threading.Lock()
STATE={'running':False,'completed':0,'total':0}

def setup(app):
 with app.db() as c:c.execute('CREATE TABLE IF NOT EXISTS inbox_status (digest TEXT PRIMARY KEY, state TEXT, message TEXT, tested INTEGER, source_id TEXT)')

def listing(app,query='',offset=0):
 setup(app)
 with app.db() as c:
  rows=c.execute('SELECT i.*, s.state,s.message,s.tested,s.source_id FROM source_inbox i LEFT JOIN inbox_status s USING(digest) ORDER BY i.name').fetchall()
 enabled={s['id']:s['enabled'] for s in app.source_list()};items=[];counts={}
 for row in rows:
  state=row['state'] or 'untested';counts[state]=counts.get(state,0)+1
  if query.casefold() not in row['name'].casefold():continue
  items.append({'digest':row['digest'],'name':row['name'],'state':state,'message':row['message'] or '尚未检测','source_id':row['source_id'],'enabled':enabled.get(row['source_id'],False)})
 with LOCK:job=dict(STATE)
 return {'items':items[offset:offset+40],'total':len(items),'counts':counts,'job':job}

def start(app,query):
 setup(app)
 with LOCK:
  if STATE['running']:return dict(STATE)
  with app.db() as c:rows=[dict(r) for r in c.execute('SELECT * FROM source_inbox')]
  STATE.update(running=True,completed=0,total=len(rows),query=query)
 def check(row):
  source=json.loads(row['data']);sid='legado_'+row['digest'][:24];state='unsupported';message='';enabled_id=None
  try:
   app.legado.validate(source)
   # Exercise the actual request/selection code, not just HTTP reachability.
   state='error'
   config=app.validate_source({'id':sid,'name':row['name'],'type':'legado','enabled':True,'rules':source})
   state='error';books=[b for b in app.provider_search(config,query) if app.relevance(query,b)>0]
   if not books:books=[b for b in app.provider_search(config,'西游记') if app.relevance('西游记',b)>0]
   if not books:state='no_match';message='两次搜索均无结果，未证明书源有效'
   else:
    sample=books[0];chapters=app.legado.chapters(source,sample['url'],app.fetch)
    text=app.legado.chapter_text(source,chapters[0][1],app.fetch,{u for _,u in chapters})
    state='sample_passed';message='搜索、目录和首章通过；整本下载时逐章校验'
    # Preserve manual enable/disable decisions when rechecking.
    with app.db() as c:
     existing=c.execute('SELECT config FROM sources WHERE id=?',(sid,)).fetchone()
     if existing:config['enabled']=json.loads(existing['config'])['enabled']
     duplicate=next((s for s in app.source_list() if s.get('type')=='legado' and s.get('rules',{}).get('bookSourceUrl')==source.get('bookSourceUrl')),None)
     if duplicate:enabled_id=duplicate['id']
     else:
      c.execute('INSERT OR REPLACE INTO sources VALUES (?,?)',(sid,json.dumps(config,ensure_ascii=False)));enabled_id=sid
  except app.legado.Unsupported as exc:state='unsupported';message=str(exc)
  except Exception as exc:message=str(exc)[:180]
  with app.db() as c:
   if state!='sample_passed':
    existing=c.execute('SELECT config FROM sources WHERE id=?',(sid,)).fetchone()
    if existing:
     config=json.loads(existing['config']);config['enabled']=False
     c.execute('UPDATE sources SET config=? WHERE id=?',(json.dumps(config,ensure_ascii=False),sid));enabled_id=sid
   c.execute('INSERT OR REPLACE INTO inbox_status VALUES (?,?,?,?,?)',(row['digest'],state,message,int(time.time()),enabled_id))
  with LOCK:STATE['completed']+=1
 def run():
  try:
   with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(check,rows))
  finally:
   with LOCK:STATE['running']=False
 threading.Thread(target=run,daemon=True).start()
 with LOCK:return dict(STATE)
