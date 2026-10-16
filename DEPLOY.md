# 把本仓库换到新服务器和新 Mac

主路径：服务器和 Mac **一起换**。新 Ubuntu 跑网关，新 Mac 跑 BlueStacks / worker。旧机器停干净之后，只有这一套在收单。

文档里的主机写成 `<旧主机>`、`<新主机>`（IP 或域名）。仓库里 `mac/outputs/trigger_launch.py` 目前仍写着换机前的 `https://1.12.208.101/kaituan`，那是旧入口，迁完要改掉，不要再当成默认地址。

一台网关加一台 Mac。两台服务器各拿一份队列，或两台 Mac 用同一个 worker-id，都会双写。

迁入经营台域名是另一件事，材料在 [`migration/`](migration/)。只换 Mac、服务器不动，见第 10 节。

密钥、token、sqlite 内容不要写入本文，也不要提交回仓库。

---

## 1. 适用范围

- 新服务器 + 新 Mac，继续跑现在这一套开团与秒杀。
- 入口路径仍是 `/kaituan/`。主机换成新机。
- 不覆盖：第二台执行机同时在线、把队列并进经营台后端、对外多租户部署。

| 路径 | 是什么 |
|---|---|
| `server/` | 服务器网关与静态工作台。部署到 `/opt/uiautomator2-trigger/`，对外路径 `/kaituan/` |
| `mac/` | Mac 侧 BlueStacks、执行与 LaunchAgent。工作目录是这一层，不是仓库根 |
| `migration/` | 迁入经营台 dashboard 的准备材料 |
| `mac-EXCLUDED.md` | 故意没进仓的大目录（`.venv`、BlueStacks 镜像、android-sdk 等） |

---

## 2. 迁后必须改的配置

以旧机文件为底稿拷到新机，然后改下面几项。token 可以原样沿用；Host 相关项留着旧值时，新入口会 403、cookie 带不上，或 Mac 仍往旧地址打。

| 配置 | 放在哪 | 迁后 |
|---|---|---|
| `GATEWAY_PUBLIC_ORIGIN` | 新机 `/opt/uiautomator2-trigger/gateway.env` | 改成 `https://<新主机>`。纯 origin，不带 `/kaituan`、query、fragment。`/kaituan/` 由 nginx 去掉后再进网关 |
| `GATEWAY_ALLOWED_HOSTS` | 同上 | 改成新域名或新 IP，逗号分隔。旧文件若写了 `<旧主机>` 必须换掉。不设则跟 `GATEWAY_PUBLIC_ORIGIN` 的主机名 |
| `GATEWAY_COOKIE_PATH` | 同上 | 按新入口核对。路径仍是 `/kaituan/`、网关看到去掉前缀后的 `/` 时，值经常仍是 `/`。Path 和真实入口不一致时，登录后 `gateway_session` 带不上 |
| Mac `--server` | 新 Mac `mac/outputs/trigger_launch.py` 的 `arguments()` | 改成 `https://<新主机>/kaituan`。不要带 hash 路由。worker-id 仍是 `zhongjiawei-mac-native` |
| DNS | 新主机名的解析 | 先指到新服务器，再切 Mac |
| HTTPS 证书 | 新机 nginx | 覆盖 `<新主机>`。site-entry 的 cookie 带 `Secure`，没有可用的 HTTPS 时操作员登不稳 |
| nginx 里写死的旧主机 | `portal-ip-https.conf` 及它 include 的站点配置 | `server_name`、证书路径、门户卡片上的旧 URL 改成新机。`snippets/kaituan-trigger.conf` 反代目标一般仍是 `http://127.0.0.1:8792/`，不用改端口 |

`GATEWAY_USER_TOKEN`、`GATEWAY_WORKER_TOKEN` 通常原样拷贝，换机器本身不必轮换。一旦轮换：nginx 里写死的操作员 Bearer（`snippets/kaituan-trigger.conf` 或 `kaituan-auth-header.conf`）和 Mac `credentials.json` 的 `worker_token` 一起改。

---

## 3. 前置

1. GitHub 账号已被仓库 Owner 加为 **Settings → Collaborators**。私有仓，没有权限 clone 会失败。
2. 新服务器、新 Mac 能访问 `github.com/a192289394-oss/kaituan-seckill`。
3. 旧服务器、旧 Mac 还在手边，能拷出第 4 节的文件。只 clone、不拷这些文件，新机器起不来。
4. 新服务器是 Ubuntu，有 `ubuntu` 用户（systemd 单元以它运行），系统 `python3` 可用。网关只用标准库。
5. 新 Mac 能装 BlueStacks，并保持不休眠（LaunchAgent 用 `caffeinate -is`，合盖休眠后执行会停）。

---

## 4. 从旧机带走什么

代码走 git。下面这些被 `.gitignore` 排除，clone 不会带来。用 `scp`、U 盘或加密压缩包。拷完不要 `git add`。

```sh
git clone git@github.com:a192289394-oss/kaituan-seckill.git
```

仓库里没有：`gateway.env`、各类 `.env`、`credentials.json`、`*.sqlite3`（及 WAL 旁路文件）、`private/`、`state/`、`.venv`、android-sdk、BlueStacks 镜像（体积见 `mac-EXCLUDED.md`）。

sqlite 使用 WAL。主文件旁边的 `-wal`、`-shm` 有则一起拷，只拷主文件会丢最近写入。

### 4.1 旧服务器

| 旧位置 | 新服务器 | 说明 |
|---|---|---|
| `/opt/uiautomator2-trigger/gateway.env` | 同一路径，`0600`，属主 `ubuntu` | 要拷，再按第 2 节改 Host 相关键。键名见 [`server/gateway.env.example`](server/gateway.env.example)。文件里多出来的键保留 |
| `/opt/uiautomator2-trigger/state/queue.sqlite3` 及 `-wal`/`-shm` | 同一路径，`0600` | **留任务就拷，拷之前先停旧网关。** 空库起步就不要拷 |
| nginx：`portal-ip-https.conf`、`snippets/kaituan-trigger.conf`，以及仍被 include 的 `kaituan-auth-header.conf` | 新机对应路径 | 要拷结构，再改证书、`server_name`、写死的旧主机 |
| site-entry 配置 | 新机同一套 | 操作员登录仍走全站 site-entry。库在 `/var/lib/site-entry/sessions.db` |

`__Host-site_session` 绑在旧 Host 上。`<新主机>` 和 `<旧主机>` 不同时，浏览器不会带旧 cookie，操作员在新入口重新登录。会话库可以拷过去，Host 变了也不代替重新登录。

代码不要从旧机整目录对拷。新机用仓库 `server/`（见第 6 节）。

### 4.2 旧 Mac

| 旧位置 | 新 Mac | 说明 |
|---|---|---|
| `mac/work/trigger-worker/credentials.json` | 同一相对路径，`0600` | 要拷。JSON 键名 `worker_token`，值等于服务器 `GATEWAY_WORKER_TOKEN` |
| `mac/work/trigger-worker/catalog.sqlite3` 及 `-wal`/`-shm` | 同一相对路径 | 要拷。酒店目录库，没有它店名对不上 |
| `mac/work/trigger-worker/worker.sqlite3` 及 `-wal`/`-shm` | 同一相对路径 | 有未完成的本机执行记录就拷。这是 Mac 本地任务库，不是服务器队列。不要可以不拷，进程会自己建 |
| `mac/outputs/trigger-worker.json` | 已在 git 中 | 旧机改过且没提交时，用旧机这份覆盖。提交版是实例 `Tiramisu64`、adb `127.0.0.1:5555`、`autostart: true` |
| `~/Library/LaunchAgents/cn.keyframe.web-kaituan.plist` | 不要原样放进新用户目录 | 只作对照。里面是旧 Mac 的绝对路径。新 Mac 在第 7 节重新 `install` |
| 模拟器内 `/data/local/tmp/kaituan-frida-server` | 新实例同一路径 | 仓库不带这个二进制。程序只拉起已安装的文件，不会自动 push 或替换 |
| BlueStacks 实例 `Tiramisu64`、来客登录态 | 新 Mac 上重做 | git 带不过去 |

服务器上的 `gateway.env` 不要拷到 Mac。

### 4.3 队列留不留

- **留任务**：旧网关先 `systemctl stop`，再拷 `queue.sqlite3` 及 `-wal`/`-shm`。库里 `meta.worker_id` 已钉死，新 Mac 继续用 `zhongjiawei-mac-native`。旧网关保持停止。同时进行的本机记录要带上 `worker.sqlite3`。
- **空库**：不拷服务器 sqlite。新进程首次启动会建库。第一台心跳成功的 worker-id 会被钉死，让 `zhongjiawei-mac-native` 第一个连上。旧队列里的任务不会出现在新库。

---

## 5. 主路径顺序

1. 按第 4 节拷文件。要留任务时，这一步先停旧网关再拷队列。
2. 第 6 节：新服务器装好网关（代码、`gateway.env`、队列、systemd、nginx、证书、site-entry）。
3. 浏览器打开 `https://<新主机>/kaituan/`，过 site-entry，能看到「开团与秒杀」。这一步心跳可以是离线，Mac 还没改地址。
4. 第 7 节：新 Mac 把 `--server` 改成 `https://<新主机>/kaituan`，再装 LaunchAgent，心跳变绿。
5. 第 8 节：旧服务器停收单，旧 Mac `bootout`。两台不要同时收单。

空库方案里，第 3 步完成时旧服务器还可以开着（旧 Mac 仍指向它）。第 4 步一切地址，马上做第 5 步。这段空窗里旧服务器仍可能收下新单，那些单只在旧库。要空窗也不收单，就在改 `--server` 之前先停旧网关。

---

## 6. 新服务器

旧布局（用于对照要拷哪些文件，主机换成新机）：

| 项 | 值 |
|---|---|
| 目录 | `/opt/uiautomator2-trigger/`（`trigger_gateway.py`、`static/`、`state/`、`gateway.env`） |
| 属主 | `ubuntu:ubuntu` |
| systemd | `uiautomator2-trigger.service` |
| 环境文件 | `EnvironmentFile=/opt/uiautomator2-trigger/gateway.env` |
| 启动 | `ExecStart=/usr/bin/python3 /opt/uiautomator2-trigger/trigger_gateway.py --bind 127.0.0.1 --port 8792 --db /opt/uiautomator2-trigger/state/queue.sqlite3 --static /opt/uiautomator2-trigger/static` |
| 单元文件 | 仓库 `mac/work/trigger-deploy/uiautomator2-trigger.service` 与上面一致，无密钥 |
| Nginx | `portal-ip-https.conf` include `snippets/kaituan-trigger.conf` |
| 路径 | `/kaituan/` |
| 操作员 | 全站 site-entry（`auth_request`）。cookie `__Host-site_session`，库 `/var/lib/site-entry/sessions.db` |
| Worker API | 仅 `/kaituan/api/worker/` 关闭主站鉴权；`Authorization` 原样转给网关，核对 `GATEWAY_WORKER_TOKEN` |

`mac/work/trigger-deploy/deploy_gateway.py` 仍把 include 写进 `/etc/nginx/conf.d/dsh-ip-https.conf`，并把 `GATEWAY_USER_TOKEN` 嵌进 snippet，还把入口写成旧 IP。换机不要未读就重跑它。

在新服务器的**仓库根**执行：

```sh
sudo mkdir -p /opt/uiautomator2-trigger/state
sudo cp server/trigger_gateway.py /opt/uiautomator2-trigger/
sudo cp -a server/static /opt/uiautomator2-trigger/static
sudo cp /path/to/旧机拷来的/gateway.env /opt/uiautomator2-trigger/gateway.env
# 留任务时再拷 queue.sqlite3、-wal、-shm 到 state/
sudo chown -R ubuntu:ubuntu /opt/uiautomator2-trigger
sudo chmod 750 /opt/uiautomator2-trigger
sudo chmod 700 /opt/uiautomator2-trigger/state
sudo chmod 600 /opt/uiautomator2-trigger/gateway.env
```

编辑 `gateway.env`：改 `GATEWAY_PUBLIC_ORIGIN`、`GATEWAY_ALLOWED_HOSTS`、`GATEWAY_COOKIE_PATH`（第 2 节）。两个 token 非空且彼此不同。

```sh
sudo cp mac/work/trigger-deploy/uiautomator2-trigger.service /etc/systemd/system/uiautomator2-trigger.service
sudo systemctl daemon-reload
sudo systemctl enable --now uiautomator2-trigger.service
```

确认只听 `127.0.0.1:8792`。源码缺省端口是 `8793`，手工裸跑会和单元不一致。用 systemd，不要另起一份。

然后：

1. DNS 把 `<新主机>` 指到这台机器。证书装好，nginx 的 `ssl_certificate` 指向它。
2. 放上 `portal-ip-https.conf` 与 `snippets/kaituan-trigger.conf`（有 `kaituan-auth-header.conf` 也放上）。改掉里面的旧主机和证书路径。保持：
   - `/kaituan` 进到 `/kaituan/`
   - `/kaituan/` 反代 `http://127.0.0.1:8792/`
   - `/kaituan/api/worker/` 为 `auth_request off`，客户端 `Authorization` 原样转发
   - 操作员路径若写死 `Authorization: Bearer …`，那一串等于 `GATEWAY_USER_TOKEN`
   - 整段 `/kaituan/` 仍走 site-entry。不要为了消 401 关掉它
3. `sudo nginx -t` 通过后 reload。
4. 浏览器打开 `https://<新主机>/kaituan/`，过 site-entry，看到标题「开团与秒杀」。只看到 HTTP 200 不算通过。本机再确认 `systemctl is-active uiautomator2-trigger.service` 为 `active`，且只听 `127.0.0.1:8792`。此时 Mac 未切过来，收单心跳离线是预期。

---

## 7. 新 Mac

新入口已经能登录之后再做。命令在 clone 出来的 `mac/` 目录。`trigger_launch.py` 把自身的上一级当作根。

### 7.1 依赖

```sh
git clone git@github.com:a192289394-oss/kaituan-seckill.git
cd kaituan-seckill/mac
python3 -m venv .venv
.venv/bin/pip install -r outputs/requirements.lock.txt
```

`.venv` 不进仓。锁文件里的 `frida` 是 `16.7.19`。模拟器里 `kaituan-frida-server --version` 必须打出同一版本，否则执行期拒绝替换二进制并停写。

对照 [`mac-EXCLUDED.md`](mac-EXCLUDED.md)，换机至少再补：

- `work/android-sdk/platform-tools/adb`（LaunchAgent 的 `PATH` 写死这一处；可从旧 Mac 拷整个 `work/android-sdk/`，不要提交）
- `/Applications/BlueStacks.app`
- 第 4.2 节的凭证、目录库、按需的 `worker.sqlite3`

没有旧机那份 root 镜像时，新实例自己准备 root。程序发现不是 root 会停，不会改镜像。

### 7.2 凭证

```sh
mkdir -p work/trigger-worker
chmod 700 work/trigger-worker
# 放入 credentials.json、catalog.sqlite3（及 -wal/-shm），按需放入 worker.sqlite3
chmod 600 work/trigger-worker/credentials.json
```

```json
{"worker_token": "<与新服务器 GATEWAY_WORKER_TOKEN 相同>"}
```

`outputs/trigger_launch.py` 在 `run` / `probe` / `once` 时读这个文件，权限必须是 `0600`，再写入环境变量 `GATEWAY_WORKER_TOKEN`。token 不进 plist。

`outputs/trigger-worker.json`：实例 `Tiramisu64`，adb `127.0.0.1:5555`。新机器端口或实例名不同就改这份 json，不要把密钥一起提交。

### 7.3 改 `--server` 再安装

编辑 `outputs/trigger_launch.py` 的 `arguments()`：

- `--server` 改为 `https://<新主机>/kaituan`
- `--worker-id` 保持 `zhongjiawei-mac-native`
- `--config` → `outputs/trigger-worker.json`
- `--catalog-db` → `work/trigger-worker/catalog.sqlite3`

来客与模拟器（git 带不过去）：

1. BlueStacks 实例名 `Tiramisu64`。
2. `work/android-sdk/platform-tools/adb connect 127.0.0.1:5555` 后 `get-state` 为 `device`。
3. 实例内 `su -c id` 含 `uid=0(root)`。
4. `/data/local/tmp/kaituan-frida-server --version` 为 `16.7.19`。
5. 在该实例登录来客（包名 `com.bytedance.ls.merchant`）。旧 Mac 上的来客先退出，两边同时登录会互踢。

LaunchAgent 尚未安装时先探活：

```sh
.venv/bin/python outputs/trigger_launch.py probe
```

成功输出里有 `"gateway": "reachable"`。然后再：

```sh
.venv/bin/python outputs/trigger_launch.py install
```

这会写入 `~/Library/LaunchAgents/cn.keyframe.web-kaituan.plist`（`0600`）并 `launchctl bootstrap`。进程是 `caffeinate -is` 包着 `.venv/bin/python outputs/trigger_launch.py run`，日志在 `work/trigger-worker/stdout.log` 与 `stderr.log`。

已经 bootstrap 过又改了 `--server`：先 `bootout` 这个 label，再 `install`。Agent 已在跑时再 probe，会被全局锁拒绝（`Another Mac worker owns the global lock`），改看工作台心跳。

---

## 8. 旧机停干净

新工作台心跳变绿之后马上做。留任务的拷贝如果在第 4 节已经停过旧网关，这里再核对一次，确认没有被重新拉起。

旧服务器：

```sh
sudo systemctl stop uiautomator2-trigger.service
sudo systemctl disable uiautomator2-trigger.service
systemctl is-active uiautomator2-trigger.service
pgrep -af trigger_gateway.py
```

`is-active` 应为 `inactive`，`pgrep` 无本服务进程，`127.0.0.1:8792` 上没有监听。旧入口再打开应无法收单（502 或页面不可用）。不要两台同时 `enable`。

旧 Mac：

```sh
launchctl bootout "gui/$(id -u)/cn.keyframe.web-kaituan"
launchctl print "gui/$(id -u)/cn.keyframe.web-kaituan"
pgrep -fl trigger_worker
```

`print` 应失败或找不到服务，`pgrep` 无本项目 worker。来客退出登录。不要再 `bootstrap` 这个 label。

---

## 9. 验收

1. `https://<新主机>/kaituan/` 过 site-entry 后能看到工作台，标题「开团与秒杀」。
2. 新 Mac 的 `cn.keyframe.web-kaituan` 在跑。工作台 Mac 收单在线（心跳约 30 秒，超过 90 秒无心跳算离线）。
3. Android、root、来客、原生接口单独看。未登录、adb 不是 `device`、frida 版本不一致时，可以心跳在线但不可写。先补第 7.3 节。
4. 旧服务器单元 inactive 且已 disable；旧 Mac 无 worker 进程、来客已退出。

---

## 10. 只换 Mac（次要）

服务器留在原地时用这一节，跳过第 6、8 节里的服务器步骤。

- 不拷 `gateway.env`，不新起网关，不复制 `queue.sqlite3`。
- `--server` 保持旧机当前入口（仓库里那行是 `https://1.12.208.101/kaituan`，以服务器实际入口为准）。`public_origin`、`allowed_hosts`、`cookie_path`、DNS、证书都不用改。
- 旧 Mac 先 `bootout` 并确认没有 `trigger_worker`，再在新 Mac 做第 7 节（不要改 `--server`）并 `install`。
- 来客只留在新 Mac。

---

## 11. 回滚

- 新服务器先 `systemctl stop` 并 `disable`，确认 8792 没有进程。
- 旧服务器再 `systemctl enable --now uiautomator2-trigger.service`。队列只认一边：留任务的那份库在哪台，哪台才是权威。
- 新 Mac `--server` 改回 `https://<旧主机>/kaituan`，`bootout` 后重新 `install`。若执行机也要退回旧 Mac，新 Mac 先 `bootout`，再在旧 Mac bootstrap。
- 两台网关不要同时 `start`。

---

## 12. 常见坑

| 现象 | 原因 |
|---|---|
| 新入口 403，或登录后接口仍失败 | `GATEWAY_PUBLIC_ORIGIN` / `GATEWAY_ALLOWED_HOSTS` 还是 `<旧主机>`。Host 不在白名单会被拒 |
| 主站登录成功，工作台接口 401 | cookie Path 不对，或 `GATEWAY_USER_TOKEN` 与 nginx 写死的 Bearer 不一致。同步 Bearer，不要关掉 `/kaituan/` 的 site-entry |
| 新工作台一直离线 | Mac `--server` 还指着旧地址，或旧 Mac 已停、新 Mac 还没 `install` |
| worker 心跳 401，页面正常 | `credentials.json` 的 `worker_token` 和新服务器 `GATEWAY_WORKER_TOKEN` 不是同一串 |
| `Worker credentials must have permission 0600` | `chmod 600 credentials.json` |
| 409 `worker_pinned` | 拷来的队列已钉死 `zhongjiawei-mac-native`，新配置用了别的 id |
| 任务乱跳或重复执行 | 旧网关没停，或两台各有一份 `queue.sqlite3`；或新旧 Mac 同时跑着同一个 worker-id。本机锁防不住两台电脑 |
| 来客刚登录就被踢下线 | 新旧模拟器同时登录同一抖音号 |
| probe 报全局锁 | 这台 Mac 上 LaunchAgent 已经在跑 |
| 手工 `python3 trigger_gateway.py` 端口不对 | 缺省 8793，单元是 8792 |
| 店名全不中 | 没拷 `catalog.sqlite3`，或没拷 `-wal` |
| 证书警告、site-entry 登不上 | 新主机 DNS 或证书还没换成 `<新主机>` |

---

## 13. 和 `migration/` 的区别

[`migration/`](migration/) 准备的是操作入口并进经营台（`dashboard.keyframe-gz.com`），执行机可以仍是原来那台 Mac。

本文是换机器：新 Ubuntu 接 `/opt/uiautomator2-trigger/`，新 Mac 的 `--server` 指向 `<新主机>`，旧服务器和旧 Mac 停干净。
