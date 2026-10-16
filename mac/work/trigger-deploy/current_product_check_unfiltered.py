import sys,json,os,sqlite3
from pathlib import Path
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'outputs'))
from native_runtime import NativeRuntime
from execution_store import adb_executable
os.umask(0o077)
d=sqlite3.connect((root/'work/trigger-worker/worker.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)
target=json.loads(d.execute('SELECT target FROM activity_jobs ORDER BY created DESC LIMIT 1').fetchone()[0]);expected=json.loads(d.execute('SELECT data FROM activity_journal ORDER BY commit_at DESC LIMIT 1').fetchone()[0]);d.close()
r=str(target.get('root_id') or target['merchant_id']);life=str(target.get('merchant_id') or r);activity=expected['preview']['body']['activity'];ids=[s['product_id'] for s in activity['sku_list']]
with NativeRuntime(adb_executable(),'127.0.0.1:5555',r,life,autostart=True) as runtime:
 raw,data=runtime.api.read('/life/marketing/v1/marketing/account/product/list',params={'selected_account_id':r,'coupon_type':20,'mkt_activity_type':2,'size':100,'cursor':0,'activity_start_time':activity['start_time'],'activity_end_time':activity['end_time']})
(root/'work/trigger-deploy/private/current-product-check-unfiltered.json').write_text(raw)
print('status',data.get('status_code'),'total',data.get('total'),'rows',len(data.get('product_list',[])))
for p in data.get('product_list',[]):
 print(json.dumps({k:p.get(k) for k in ['product_id','product_name','sold_start_time','sold_end_time','is_deny','deny_reason','avail_qty']},ensure_ascii=False))
