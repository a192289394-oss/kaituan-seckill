"""Exact business directory and plan target binding for the web executor."""
import json,re,unicodedata

def name_key(name):
 return re.sub(r'[\s\W_]+','',unicodedata.normalize('NFKC',name).casefold())

def init_schema(db):
 db.executescript('''CREATE TABLE IF NOT EXISTS merchant_catalog(entity_id TEXT PRIMARY KEY,name TEXT NOT NULL,data TEXT NOT NULL,updated REAL NOT NULL);
 CREATE TABLE IF NOT EXISTS task_targets(task_id TEXT PRIMARY KEY,generation REAL NOT NULL,data TEXT NOT NULL);''')

def bind_target(store,task,target):
 with store.connect() as db:
  db.execute('BEGIN IMMEDIATE')
  live=db.execute('SELECT status,created FROM tasks WHERE task_id=?',(task['task_id'],)).fetchone()
  if not live or live['status']!='running' or live['created']!=task['created']:raise RuntimeError('任务已更新，未绑定旧目标')
  db.execute('INSERT OR REPLACE INTO task_targets VALUES(?,?,?)',(task['task_id'],task['created'],json.dumps(target,ensure_ascii=False)))
