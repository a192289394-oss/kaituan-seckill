import sys,json,time
sys.path.insert(0,'outputs')
import sqlite3,android_runtime,trigger_worker
from adb_android import *  # noqa
from native_runtime import NativeRuntime
from native_activity_executor import Activities
from pc_executor import template_spec
cfg=trigger_worker.load_config('outputs/trigger-worker.json')
db=sqlite3.connect('work/trigger-worker/worker.sqlite3')
out={}
for jid in sys.argv[1:]:
    t=json.loads(db.execute("select data from merchant_catalog where entity_id=?",(jid,)).fetchone()[0])
    root=str(t.get('root_id') or t.get('root_life_account_id') or t['merchant_id']);life=str(t.get('merchant_id') or root)
    import inspect
    with NativeRuntime(trigger_worker.adb_executable(),android_runtime.endpoint(cfg),root,life,autostart=False) as rt:
        r=Activities(rt.api);a=r.read();time.sleep(2);b=r.read()
    def diff(x,y,p=''):
        if type(x)!=type(y):return [p]
        if isinstance(x,dict):return sum((diff(x.get(k),y.get(k),p+'.'+k) for k in set(x)|set(y)),[])
        if isinstance(x,list):return [p+'[len]'] if len(x)!=len(y) else sum((diff(i,j,p+f'[{n}]') for n,(i,j) in enumerate(zip(x,y))),[])
        return [] if x==y else [p]
    acts=[]
    for s in a:
        try:spec=template_spec(s)
        except Exception as e:spec=str(e)
        other=[o for o in b if str(o['activity_id'])==str(s['activity_id'])]
        acts.append({'activity_id':str(s['activity_id']),'name':s.get('activity_name'),'start':s.get('start_time'),'end':s.get('end_time'),
          'anchors':[x.get('douyin_id') or x.get('nickname') or x.get('uid') for x in s.get('anchor_info_list',[])],
          'spec':spec,'skus':[{'product_id':k.get('product_id'),'name':(k.get('product_info') or {}).get('product_name'),'total_quantity':k.get('total_quantity'),'left':k.get('left_quantity')} for k in s.get('sku_list',[])],
          'changed_between_reads':diff(s,other[0])[:30] if other else 'missing'})
    out[t.get('name') or jid]=acts
print(json.dumps(out,ensure_ascii=False,default=str,indent=1))
