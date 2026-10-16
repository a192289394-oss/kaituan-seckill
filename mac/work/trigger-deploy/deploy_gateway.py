"""EXAMPLE_LIVE_ONLY: live-ops installer bound to the production host/portal/Bearer inject.
New installs MUST follow docs/AI-INSTALL.md §6 (independent login + example unit/nginx).
Refuse to run unless --live-operator is passed or KAITUAN_LIVE_OPERATOR=1.
Secrets never printed.
"""
from pathlib import Path
import json, os, shutil, subprocess, datetime, sys

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    live = ("--live-operator" in argv) or (os.environ.get("KAITUAN_LIVE_OPERATOR") == "1")
    if not live:
        print("EXAMPLE_LIVE_ONLY: refuse to run without --live-operator (or KAITUAN_LIVE_OPERATOR=1).")
        print("New install: see docs/AI-INSTALL.md §6 (do not use this script).")
        sys.exit(2)
    # --- original live-ops body (unchanged behavior when authorized) ---
    root=Path('/opt/uiautomator2-trigger');stage=Path('/tmp/uiautomator2-trigger-stage');stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S');backup=Path('/opt/uiautomator2-trigger-backups')/stamp
    backup.mkdir(parents=True,mode=0o700)
    nginx=Path('/etc/nginx/conf.d/dsh-ip-https.conf')
    for p in [nginx,Path('/opt/portal/services.json'),Path('/opt/portal/portal-template.html'),Path('/var/www/portal/index.html')]:shutil.copy2(p,backup/p.name)
    if root.exists():
     for p in root.glob('*.py'):shutil.copy2(p,backup/p.name)
    root.mkdir(exist_ok=True,mode=0o750);(root/'state').mkdir(exist_ok=True,mode=0o700)
    shutil.copy2(stage/'trigger_gateway.py',root/'trigger_gateway.py')
    if (root/'static').exists():shutil.copytree(root/'static',backup/'static')
    shutil.copytree(stage/'static',root/'static',dirs_exist_ok=True)
    if not (root/'gateway.env').exists():shutil.copy2(stage/'gateway.env',root/'gateway.env')
    (root/'gateway.env').chmod(0o600)
    subprocess.run(['chown','-R','ubuntu:ubuntu',str(root)],check=True)
    shutil.copy2(stage/'uiautomator2-trigger.service','/etc/systemd/system/uiautomator2-trigger.service')
    env=dict(line.split('=',1) for line in (root/'gateway.env').read_text().splitlines() if '=' in line)
    route='''    location = /kaituan { return 302 /kaituan/; }
        location ^~ /kaituan/api/worker/ {
            auth_request off;
            client_max_body_size 64k;
            proxy_pass http://127.0.0.1:8792/api/worker/;
            proxy_set_header Host $host;
            proxy_set_header Authorization $http_authorization;
            proxy_set_header X-Forwarded-Proto https;
            proxy_read_timeout 30s;
            access_log off;
        }
        location /kaituan/ {
            client_max_body_size 64k;
            proxy_pass http://127.0.0.1:8792/;
            proxy_set_header Host $host;
            proxy_set_header X-Forwarded-Proto https;
            proxy_set_header Authorization "Bearer USER_TOKEN";
            proxy_read_timeout 30s;
            access_log off;
        }
    '''.replace('USER_TOKEN',env['GATEWAY_USER_TOKEN'])
    snippet=Path('/etc/nginx/snippets/kaituan-trigger.conf');snippet.write_text(route);snippet.chmod(0o600)
    content=nginx.read_text()
    if 'include /etc/nginx/snippets/kaituan-trigger.conf;' not in content:
     content=content.replace('    index index.html;','    index index.html;\n    include /etc/nginx/snippets/kaituan-trigger.conf;')
     nginx.write_text(content)
    try:subprocess.run(['nginx','-t'],check=True)
    except Exception:
     shutil.copy2(backup/nginx.name,nginx);raise
    conf=Path('/opt/portal/services.json');cfg=json.loads(conf.read_text())
    if not any(s['key']=='kaituan' for s in cfg['services']):cfg['services'].append({'key':'kaituan','name':'开团与秒杀','desc':'网页收单，Mac 核验执行','domain':'1.12.208.101/kaituan/','ip':'/kaituan/','ip_scheme':'https','tag':'主站已登录','expect_any':['<title>开团与秒杀']})
    conf.write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n')
    tpl=Path('/opt/portal/portal-template.html');text=tpl.read_text()
    if 'data-ip="https://1.12.208.101/kaituan/"' not in text:
     text=text.replace('      </div>\n    </section>','''        <a class="card project-link" href="//1.12.208.101/kaituan/" data-ip="https://1.12.208.101/kaituan/">
              <div class="card-head"><span class="icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M5 4h14v16H5zM9 8h6M9 12h6M9 16h3"/></svg></span><span class="badge">Mac 执行</span></div>
              <div class="card-body"><h3>开团与秒杀</h3><p>提交计划与账号，查看核验结果和待处理事项</p></div>
              <div class="card-foot"><span>网页收单 · 主站已登录</span><span class="launch">打开项目</span></div>
            </a>
          </div>
        </section>''',1)
     tpl.write_text(text)
    subprocess.run(['python3','/opt/portal/portal.py','build'],check=True)
    subprocess.run(['systemctl','daemon-reload'],check=True)
    subprocess.run(['systemctl','enable','--now','uiautomator2-trigger.service'],check=True)
    subprocess.run(['systemctl','restart','uiautomator2-trigger.service'],check=True)
    subprocess.run(['systemctl','reload','nginx'],check=True)
    print('gateway installed; backup='+str(backup))

if __name__ == '__main__':
    main()
