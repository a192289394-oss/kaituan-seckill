import sys,json,sqlite3
sys.path.insert(0,'outputs')
import android_runtime,trigger_worker
from native_runtime import NativeRuntime
from native_activity_executor import Activities
from native_activity import lookup_body,resolve_creators,authorization_payload,LOOKUP_PATH,PRECHECK_PATH
cfg=trigger_worker.load_config('outputs/trigger-worker.json')
db=sqlite3.connect('work/trigger-worker/worker.sqlite3')
jid,aid=sys.argv[1],sys.argv[2]
t=json.loads(db.execute("select target from activity_jobs where id=?",(jid,)).fetchone()[0])
root=str(t.get('root_id') or t['merchant_id']);life=str(t.get('merchant_id') or root)
with NativeRuntime(trigger_worker.adb_executable(),android_runtime.endpoint(cfg),root,life) as rt:
    src=[a for a in Activities(rt.api).read() if str(a['activity_id'])==aid][0]
    acc=['73850724291']
    _,res=rt.api.read(LOOKUP_PATH,body=lookup_body(src,acc))
    print('lookup rows',[{k:(v if k!='avatar' else '...') for k,v in r.items()} for r in res.get('success_anchor_list',[])],res.get('fail_douyin_ids'),res.get('duplicate_anchor_sku_infos'))
    cr=resolve_creators(res,acc);print('creators',cr)
    p=authorization_payload(src,acc,cr,rt.api.expected_root)
    _,pc=rt.api.read(PRECHECK_PATH,body=p['body'])
    print('precheck',json.dumps(pc,ensure_ascii=False)[:800])
