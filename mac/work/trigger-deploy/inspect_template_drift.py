import sys,json,sqlite3,os,time
from pathlib import Path
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'outputs'))
from native_runtime import NativeRuntime
from execution_store import adb_executable
from pc_authorization import parse_activity_response
from web_activity import fingerprint,stable,DISCOUNT_TYPE
os.umask(0o077)
d=sqlite3.connect((root/'work/trigger-worker/worker.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)
target=json.loads(d.execute('SELECT target FROM activity_jobs ORDER BY created DESC LIMIT 1').fetchone()[0]);d.close()
r=str(target.get('root_id') or target['merchant_id']);life=str(target.get('merchant_id') or r);snapshots=[]
with NativeRuntime(adb_executable(),'127.0.0.1:5555',r,life,autostart=False) as runtime:
 for i in range(2):
  raw,_=runtime.api.read('/life/marketing/v1/minus_activity/info',params={'activity_id':'7670514139019167770','selected_account_id':'','discount_type':DISCOUNT_TYPE})
  a=parse_activity_response(raw,'7670514139019167770');snapshots.append(a)
  (root/'work/trigger-deploy/private'/('template-drift-'+str(i)+'.json')).write_text(json.dumps(a,ensure_ascii=False))
  print('read',i,'fingerprint',fingerprint(a))
def diffs(a,b,path=''):
 if type(a)!=type(b):return [path]
 if isinstance(a,dict):return sum([diffs(a.get(k),b.get(k),path+'.'+k) for k in set(a)|set(b)],[])
 if isinstance(a,list):
  if len(a)!=len(b):return [path+'.length']
  return sum([diffs(x,y,path+'['+str(i)+']') for i,(x,y) in enumerate(zip(a,b))],[])
 return [] if a==b else [path]
print('stable_difference_paths',json.dumps(diffs(stable(snapshots[0]),stable(snapshots[1])),ensure_ascii=False))
