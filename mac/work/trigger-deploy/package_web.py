from pathlib import Path
import hashlib,json,tarfile,os
root=Path(__file__).resolve().parents[2]
out=Path('/Users/zhongjiawei/Documents/Codex/2026-10-14/users-zhongjiawei-documents-codex-2026-09-2/outputs')
modules=['trigger_gateway','trigger_worker','trigger_launch','execution_store','web_catalog','web_activity','native_backend','native_activity','native_activity_executor','native_commit','native_plan','native_plan_executor','native_plan_journal','native_account','native_runtime','native_bootstrap','native_http_api','native_webview_api','adb_android','android_runtime','pc_jobs','pc_authorization','pc_executor','pc_ui_authorization','plan_owner','service_runtime']
files=[root/'outputs'/(n+'.py') for n in modules]
files += [root/'outputs'/n for n in ['native_account_agent.js','native_http_agent.js','requirements.lock.txt','trigger-worker.example.json','README.md']]
files += sorted(p for p in (root/'outputs/trigger-ui').glob('*') if p.is_file())
files += [root/'work/web_offline_tests.py']+[root/'work'/('test_'+n+'.py') for n in ['trigger_gateway','trigger_worker','web_activity','native_plan','native_plan_executor','native_activity','native_account','native_bootstrap','native_runtime','native_webview_api']]
manifest={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
path=out/'开团与秒杀-纯网页源码-20261014.tar.gz'
with tarfile.open(path,'w:gz') as a:
 for p in files:a.add(p,arcname=str(p.relative_to(root)),recursive=False)
(out/'源码校验清单.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print('Package files:',len(files),'bytes:',path.stat().st_size)
