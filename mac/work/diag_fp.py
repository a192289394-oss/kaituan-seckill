import sys,json,time,sqlite3
sys.path.insert(0,'outputs')
import android_runtime,trigger_worker
from native_runtime import NativeRuntime
from native_activity_executor import Activities,_stable,authorization_fingerprint
from copy import deepcopy
cfg=trigger_worker.load_config('outputs/trigger-worker.json')
db=sqlite3.connect('work/trigger-worker/worker.sqlite3')
t=json.loads(db.execute("select target from activity_jobs where id='gateway:363860f8ff04fe088aaf5198284cf1de'").fetchone()[0])
root=str(t.get('root_id') or t['merchant_id']);life=str(t.get('merchant_id') or root)
def snap():
    with NativeRuntime(trigger_worker.adb_executable(),android_runtime.endpoint(cfg),root,life) as rt:
        s=[a for a in Activities(rt.api).read() if str(a['activity_id'])=='7694578234016614409'][0]
    x=deepcopy(s)
    for a in x.get('anchor_info_list',[]):
        if isinstance(a.get('avatar'),dict):a['avatar'].pop('url_list',None)
    for k in x.get('sku_list',[]):
        if isinstance(k.get('product_info'),dict):k['product_info'].pop('image_list',None)
    return _stable(x),authorization_fingerprint(s,['73850724291'],['73850724291'])
def diff(x,y,p=''):
    if type(x)!=type(y):return [p]
    if isinstance(x,dict):return sum((diff(x.get(k),y.get(k),p+'.'+k) for k in set(x)|set(y)),[])
    if isinstance(x,list):return [p+'[len]'] if len(x)!=len(y) else sum((diff(i,j,p+f'[{n}]') for n,(i,j) in enumerate(zip(x,y))),[])
    return [] if x==y else [p+f' {x!r}->{y!r}'[:200]]
a,fa=snap();time.sleep(int(sys.argv[1]));b,fb=snap()
print(fa,fb);print('\n'.join(diff(a,b)[:40]))
