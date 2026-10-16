"""Install/run the outbound Mac agent; keep credentials outside the plist."""
import argparse,json,os,plistlib,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
LABEL='cn.keyframe.web-kaituan'
STATE=ROOT/'work/trigger-worker'

def arguments(action=None):
    args=[str(ROOT/'.venv/bin/python'),str(ROOT/'outputs/trigger_worker.py'),'--server','https://1.12.208.101/kaituan','--worker-id','zhongjiawei-mac-native','--config',str(ROOT/'outputs/trigger-worker.json'),'--catalog-db',str(STATE/'catalog.sqlite3')]
    if action:args.append('--'+action)
    return args

def main():
 p=argparse.ArgumentParser();p.add_argument('command',choices=['install','run','probe','once']);a=p.parse_args();os.umask(0o077);STATE.mkdir(parents=True,exist_ok=True,mode=0o700)
 if a.command=='install':
  target=Path.home()/'Library/LaunchAgents'/(LABEL+'.plist')
  config={'Label':LABEL,'ProgramArguments':['/usr/bin/caffeinate','-is',str(ROOT/'.venv/bin/python'),str(Path(__file__).resolve()),'run'],'WorkingDirectory':str(ROOT),'KeepAlive':True,'RunAtLoad':True,'ThrottleInterval':30,'EnvironmentVariables':{'PYTHONUNBUFFERED':'1','PATH':str(ROOT/'work/android-sdk/platform-tools')+':/usr/bin:/bin:/usr/sbin:/sbin'},'StandardOutPath':str(STATE/'stdout.log'),'StandardErrorPath':str(STATE/'stderr.log')}
  target.parent.mkdir(exist_ok=True);target.write_bytes(plistlib.dumps(config));target.chmod(0o600)
  subprocess.run(['launchctl','bootstrap','gui/'+str(os.getuid()),str(target)],check=True);print('Web worker installed; verify gateway heartbeat and business readback.');return
 cred=STATE/'credentials.json'
 if cred.stat().st_mode&0o077:raise RuntimeError('Worker credentials must have permission 0600')
 token=json.loads(cred.read_text())['worker_token'];env=dict(os.environ,GATEWAY_WORKER_TOKEN=token)
 args=arguments(None if a.command=='run' else a.command)
 os.execve(args[0],args,env)
if __name__=='__main__':main()
