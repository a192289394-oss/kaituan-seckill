import json,urllib.request,urllib.error
from pathlib import Path
env=dict(line.split('=',1) for line in Path('/opt/uiautomator2-trigger/gateway.env').read_text().splitlines() if '=' in line)
def request(path,body=None):
 data=None if body is None else json.dumps(body).encode();r=urllib.request.Request('http://127.0.0.1:8792/api/'+path,data=data,headers={'Host':'1.12.208.101','Authorization':'Bearer '+env['GATEWAY_USER_TOKEN'],'Content-Type':'application/json'})
 return json.load(urllib.request.urlopen(r,timeout=15))
print(json.dumps({'status':request('status'),'tasks':request('tasks')},ensure_ascii=False))
