import sys,json,urllib.request
from pathlib import Path
env=dict(line.split('=',1) for line in Path('/opt/uiautomator2-trigger/gateway.env').read_text().splitlines() if '=' in line)
def req(path,body=None):
 data=None if body is None else json.dumps(body).encode()
 r=urllib.request.Request('http://127.0.0.1:8792/api/'+path,data=data,headers={'Host':'1.12.208.101','Authorization':'Bearer '+env['GATEWAY_USER_TOKEN'],'Content-Type':'application/json'})
 return json.load(urllib.request.urlopen(r,timeout=15))
task=next(t for t in req('tasks')['tasks'] if t['id']=='828f23c7dc50b17f3527142e1d5b2458')
if task['status'] in ('waiting_device','waiting_review'):
 result=req('tasks/'+task['id']+'/retry',{'expected_revision':task['revision']})
 print('recovery retry original revision',result['task']['revision'])
elif task['status']=='needs_input' and not task['committed']:
 result=req('tasks/'+task['id']+'/resume',{'expected_revision':task['revision'],'params':{'note':'只读刷新模板，修正展示素材地址漂移的指纹误判'}})
 print('same task requeued read-only revision',result['task']['revision'])
else:print('No requeue:',task['status'])
