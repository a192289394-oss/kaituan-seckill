"""Install/run the outbound Mac agent; keep credentials outside the plist.

Server and worker id are read at run time. Priority: KAITUAN_SERVER /
KAITUAN_WORKER_ID, then mac/work/trigger-worker/launch.json. There is no
built-in address or worker id. See docs/AI-INSTALL.md §7.
"""
import argparse, json, os, plistlib, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABEL = 'cn.keyframe.web-kaituan'
STATE = ROOT / 'work/trigger-worker'
DOC = 'docs/AI-INSTALL.md §7'
WORKER_ID = re.compile(r'^[A-Za-z0-9_.:-]{1,96}$')


def fail(message):
    print(message, file=sys.stderr)
    raise SystemExit(1)


def env_text(name):
    raw = os.environ.get(name)
    if raw is None:
        return None
    text = raw.strip()
    return text or None


def launch_file():
    path = STATE / 'launch.json'
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail(f'无法读取 {path}：{exc}。配置见 {DOC}')
    if not isinstance(data, dict):
        fail(f'{path} 必须是 JSON 对象。配置见 {DOC}')
    return data


def json_text(data, key):
    if key not in data or data[key] is None:
        return None
    value = data[key]
    if not isinstance(value, str):
        fail(f'launch.json 的 {key} 必须是字符串。配置见 {DOC}')
    text = value.strip()
    return text or None


def validate_server(server):
    if (not server.startswith('https://') or server.endswith('/')
            or any(ch.isspace() for ch in server)):
        fail(f'server 必须以 https:// 开头且不能有尾斜杠。见 {DOC}')


def validate_worker_id(worker_id):
    if WORKER_ID.fullmatch(worker_id) is None:
        fail(f'worker_id 必须匹配 ^[A-Za-z0-9_.:-]{{1,96}}$。见 {DOC}')


def resolve_launch():
    """Return (server, worker_id, ca_file). ca_file may be None."""
    server = env_text('KAITUAN_SERVER')
    worker_id = env_text('KAITUAN_WORKER_ID')
    ca_file = env_text('KAITUAN_CA_FILE')
    if server is None or worker_id is None:
        data = launch_file()
        if server is None:
            server = json_text(data, 'server')
        if worker_id is None:
            worker_id = json_text(data, 'worker_id')
    missing = []
    if not server:
        missing.append('KAITUAN_SERVER 或 launch.json 的 server')
    if not worker_id:
        missing.append('KAITUAN_WORKER_ID 或 launch.json 的 worker_id')
    if missing:
        fail(
            '缺少 Mac 启动配置：' + '；'.join(missing) + '。\n'
            f'请按 {DOC} 设置环境变量，或将 mac/outputs/launch.example.json '
            '复制为 mac/work/trigger-worker/launch.json 后填写。'
            '不会使用任何预置地址或 worker-id。'
        )
    validate_server(server)
    validate_worker_id(worker_id)
    return server, worker_id, ca_file


def worker_config_path():
    return ROOT / 'outputs/trigger-worker.json'


def arguments(action=None):
    server, worker_id, ca_file = resolve_launch()
    config = worker_config_path()
    if not config.is_file():
        fail(
            f'缺少本机执行配置 {config}。\n'
            '请将 mac/outputs/trigger-worker.example.json 复制为该路径后再启动。'
            '仓库不提交这份运行态文件；找不到配置时启动器以非 0 退出。'
        )
    args = [
        str(ROOT / '.venv/bin/python'),
        str(ROOT / 'outputs/trigger_worker.py'),
        '--server', server,
        '--worker-id', worker_id,
        '--config', str(config),
        '--catalog-db', str(STATE / 'catalog.sqlite3'),
    ]
    if ca_file:
        args.extend(['--ca-file', ca_file])
    if action:
        args.append('--' + action)
    return args


def agent_plist():
    # `run` reads env or launch.json. Do not store server, worker id, or token here.
    return {
        'Label': LABEL,
        'ProgramArguments': [
            '/usr/bin/caffeinate', '-is',
            str(ROOT / '.venv/bin/python'),
            str(Path(__file__).resolve()),
            'run',
        ],
        'WorkingDirectory': str(ROOT),
        'KeepAlive': True,
        'RunAtLoad': True,
        'ThrottleInterval': 30,
        'EnvironmentVariables': {
            'PYTHONUNBUFFERED': '1',
            'PATH': str(ROOT / 'work/android-sdk/platform-tools') + ':/usr/bin:/bin:/usr/sbin:/sbin',
        },
        'StandardOutPath': str(STATE / 'stdout.log'),
        'StandardErrorPath': str(STATE / 'stderr.log'),
    }


def install():
    target = Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')
    config = agent_plist()
    raw = plistlib.dumps(config)
    for forbidden in (b'--server', b'--worker-id', b'--ca-file', b'KAITUAN_SERVER',
                      b'KAITUAN_WORKER_ID', b'KAITUAN_CA_FILE', b'GATEWAY_WORKER_TOKEN',
                      b'worker_token'):
        if forbidden in raw:
            raise RuntimeError('LaunchAgent plist must not embed launch settings or credentials')
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(raw)
    target.chmod(0o600)
    subprocess.run(['launchctl', 'bootstrap', 'gui/' + str(os.getuid()), str(target)], check=True)
    print('Web worker installed; verify gateway heartbeat and business readback.')


def worker_token():
    cred = STATE / 'credentials.json'
    if cred.stat().st_mode & 0o077:
        raise RuntimeError('Worker credentials must have permission 0600')
    return json.loads(cred.read_text(encoding='utf-8'))['worker_token']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['install', 'run', 'probe', 'once'])
    args = parser.parse_args()
    os.umask(0o077)
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    if args.command == 'install':
        install()
        return
    command_args = arguments(None if args.command == 'run' else args.command)
    env = dict(os.environ, GATEWAY_WORKER_TOKEN=worker_token())
    os.execve(command_args[0], command_args, env)


if __name__ == '__main__':
    main()
