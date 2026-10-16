import sys,json,os,sqlite3
from pathlib import Path
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'outputs'))
from native_runtime import NativeRuntime
from execution_store import adb_executable
from web_activity import AllActivities,matches_saved,fingerprint
import time
os.umask(0o077)
d=sqlite3.connect((root/'work/trigger-worker/worker.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)
target=json.loads(d.execute('SELECT target FROM activity_jobs ORDER BY created DESC LIMIT 1').fetchone()[0]);expected=json.loads(d.execute('SELECT data FROM activity_journal ORDER BY commit_at DESC LIMIT 1').fetchone()[0]);d.close()
r=str(target.get('root_id') or target['merchant_id']);life=str(target.get('merchant_id') or r)
with NativeRuntime(adb_executable(),'127.0.0.1:5555',r,life,autostart=True) as runtime:rows=AllActivities(runtime.api).read()
(root/'work/trigger-deploy/private/commit-readback.json').write_text(json.dumps(rows,ensure_ascii=False))
(root/'work/trigger-deploy/private/commit-expected.json').write_text(json.dumps(expected,ensure_ascii=False))
new=[a for a in rows if str(a['activity_id']) not in expected['pre_existing_ids']]
print('activity count',len(rows),'new IDs',[(str(a['activity_id']),a['activity_status'],a['start_time'],a['end_time'],len(a['sku_list'])) for a in new])
print('expected template fp',expected['template_fingerprint'],'current',[fingerprint(a) for a in rows if str(a['activity_id'])==expected['template_id']])
print('saved payload matches',[(str(a['activity_id']),matches_saved(a,expected['preview']['body'],time.time())) for a in new])
