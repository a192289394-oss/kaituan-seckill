# 把本仓库换到另一台电脑

本文只做一件事：把**已经在跑的**开团与秒杀，换到另一台电脑上继续维护、继续跑。

不是公开安装文档，也不是每人各装一套生产。现网仍是一台 Ubuntu 网关加一台 Mac 执行机。两台机器同时对同一队列收单会双写。

迁入经营台域名是另一件事，材料在 [`migration/`](migration/)。

现网参考（2026-10-16，以旧机上的真实文件为准）：

| | |
|---|---|
| 工作台 | `https://1.12.208.101/kaituan/` |
| 网关代码 | `/opt/uiautomator2-trigger/` |
| Mac worker | LaunchAgent `cn.keyframe.web-kaituan`，worker-id `zhongjiawei-mac-native` |

密钥、token、sqlite 内容不要写入本文，也不要提交回仓库。

---

## 1. 适用范围

- 新 Mac 接上**现有**服务器，继续跑现在这一个 worker。
- 可选：服务器也迁到另一台 Ubuntu。见第 5 节。做完之前，Mac 的 `--server` 不要改。
- 不覆盖：第二台执行机同时在线、把队列并进经营台后端、对外多租户部署。

仓库里各目录：

| 路径 | 是什么 |
|---|---|
| `server/` | 服务器网关与静态工作台。现网对应 `/opt/uiautomator2-trigger/`，对外入口 `/kaituan/` |
| `mac/` | Mac 侧 BlueStacks、执行与 LaunchAgent 相关源码。LaunchAgent 的工作目录是这一层，不是仓库根 |
| `migration/` | 迁入经营台 dashboard 的准备材料 |
| `mac-EXCLUDED.md` | 故意没进仓的大目录（`.venv`、BlueStacks 镜像、android-sdk 等） |

---

## 2. 前置

1. GitHub 账号已被仓库 Owner 加为 **Settings → Collaborators**。私有仓，没有权限 `git clone` 会失败。
2. 新电脑能访问 `github.com/a192289394-oss/kaituan-seckill`。
3. 旧电脑还在手边，能拷出第 3 节的文件。只 clone、不拷这些文件，新机器起不来。
4. 换 Mac 时，新机器是 macOS，能装 BlueStacks，并保持不休眠（LaunchAgent 用 `caffeinate -is` 保活，合盖休眠后执行会停）。

---

## 3. 从旧电脑带走什么

代码走 git。下面这些 **gitignore 已排除**，clone 不会带来。用 U 盘、`scp` 或加密压缩包拷贝。拷完不要 `git add`。

### 3.1 代码（不要手拷整仓）

```sh
git clone git@github.com:a192289394-oss/kaituan-seckill.git
```

仓库明确不包含（见根目录 `.gitignore`）：

- `gateway.env`、各类 `.env`
- `credentials.json`（及 `.bak*`）
- `*.sqlite3` 队列库、目录库、本机任务库（及 `.bak*`、WAL 旁路文件）
- `private/`、`state/`
- `.venv`、`__pycache__`、android-sdk、BlueStacks 镜像（体积见 `mac-EXCLUDED.md`）

### 3.2 必须另拷的清单

先在**旧 Mac 停掉 worker**（第 4.1 节），再拷。sqlite 使用 WAL，主文件旁边的 `-wal`、`-shm` 有则一起拷，只拷主文件会丢最近写入。

| 旧位置 | 新位置 | 换 Mac 时 |
|---|---|---|
| `mac/work/trigger-worker/credentials.json` | 同一相对路径 | **要拷。** 权限保持 `0600`。内容是 JSON，键名为 `worker_token`，值等于服务器 `GATEWAY_WORKER_TOKEN`。不要打开后贴到聊天或提交 |
| `mac/work/trigger-worker/catalog.sqlite3`（及 `-wal`/`-shm`） | 同一相对路径 | **要拷。** 酒店目录库。没有它，店名对不上 |
| `mac/outputs/trigger-worker.json` | 已在 git 中 | 旧机若改过且没提交，用旧机这份覆盖 clone 结果。现网提交版是 BlueStacks 实例 `Tiramisu64`、adb `127.0.0.1:5555`、`autostart: true` |
| `mac/work/trigger-worker/worker.sqlite3`（及 `-wal`/`-shm`） | 同一相对路径 | **有未完成的本机执行记录就拷。** 这是 Mac 本地任务库，不是服务器队列。空库可以不拷，进程会自己建 |
| `~/Library/LaunchAgents/cn.keyframe.web-kaituan.plist` | 不要原样丢进新用户目录 | **只作对照。** 里面是旧机器的绝对路径。新 Mac 在依赖装好后重新 `install`（第 4.6 节） |
| 模拟器里的 `/data/local/tmp/kaituan-frida-server` | 新实例同一路径 | **要准备。** 仓库不带这个二进制（`mac-EXCLUDED.md`）。程序只负责拉起已安装的文件，不会自动 push 或替换 |
| BlueStacks 实例 `Tiramisu64`、来客登录态 | 新 Mac 上重做 | **git 带不过去。** 见第 4.5 节 |

服务器若一起搬，再加第 5 节的 `gateway.env` 和 `state/queue.sqlite3`。只换 Mac、服务器仍是 `1.12.208.101` 时，不要把服务器密钥拷到 Mac 上。

### 3.3 旧任务留不留

- **服务器队列** `queue.sqlite3`：只换 Mac 时留在原服务器，不要拷一份到新机器上再起第二个网关。
- **要保留进行中的单**：旧 worker 先停干净，服务器队列留在原地；Mac 侧把 `worker.sqlite3` 一起带走，这样本机「已经提交过」的记录还在。
- **接受任务历史不要了**：不拷 `worker.sqlite3`。服务器上已有任务仍在原队列里，新 worker 会按原 worker-id 去领。不要另起一个 worker-id（队列库把第一台 worker 钉死，换 id 会 409 `worker_pinned`）。

---

## 4. 新 Mac

以下命令都在 clone 出来的 `mac/` 目录执行。`trigger_launch.py` 把自身的上一级当作根：虚拟环境、配置、`work/` 都相对这一层。

### 4.1 旧 Mac 先停

在旧 Mac 上：

```sh
launchctl bootout "gui/$(id -u)/cn.keyframe.web-kaituan"
```

确认已经卸掉（这条应失败或显示找不到服务）：

```sh
launchctl print "gui/$(id -u)/cn.keyframe.web-kaituan"
```

再确认没有残留进程：`ps aux | grep trigger_worker` 不应再有本项目的 worker。旧机停稳之前，不要在新机 `install`。

### 4.2 clone 与 Python 依赖

```sh
git clone git@github.com:a192289394-oss/kaituan-seckill.git
cd kaituan-seckill/mac
python3 -m venv .venv
.venv/bin/pip install -r outputs/requirements.lock.txt
```

`.venv` 不进仓，必须在新机器重建。锁文件里的 `frida` 版本是 `16.7.19`。模拟器里 `kaituan-frida-server --version` 必须打出同一版本，否则执行期会拒绝替换二进制并停写。

对照 [`mac-EXCLUDED.md`](mac-EXCLUDED.md) 看还有哪些大目录没进仓。换机至少要补：

- `work/android-sdk/platform-tools/adb`（LaunchAgent 的 `PATH` 写死这一处；也可从旧机 `work/android-sdk/` 整目录拷来，不要提交）
- BlueStacks 应用本身（装到 `/Applications/BlueStacks.app`）
- 第 3.2 节的凭证、目录库、按需的 `worker.sqlite3`

`work/bluestacks-root-*` 镜像、apk 分析包、浏览器 profile 不是启动所必需的源码。没有旧机那份 root 镜像时，新实例要自己准备好 root（程序发现不是 root 会停，不会改镜像）。

### 4.3 放回凭证与配置

```sh
mkdir -p work/trigger-worker
chmod 700 work/trigger-worker
# 把旧机的 credentials.json、catalog.sqlite3（及 -wal/-shm）放进 work/trigger-worker/
chmod 600 work/trigger-worker/credentials.json
```

`credentials.json` 形如（值用旧机那一串，不要新编一个除非第 5 节换了服务器密钥）：

```json
{"worker_token": "<与服务器 GATEWAY_WORKER_TOKEN 相同>"}
```

LaunchAgent **不会**把 token 写进 plist。`outputs/trigger_launch.py` 在 `run` / `probe` / `once` 时读取该文件，检查权限必须是 `0600`，再放进环境变量 `GATEWAY_WORKER_TOKEN`。直接跑 `trigger_worker.py` 时也可以自己导出这个环境变量；走 LaunchAgent 时以文件为准。

确认 `outputs/trigger-worker.json`：

- `android_device.instance` 为 `Tiramisu64`
- `android_device.adb_endpoint` 为 `127.0.0.1:5555`
- 实例名或端口若在新机器上不同，改这份 json，不要改完提交进仓（除非团队决定改现网配置）

### 4.4 确认网关地址

打开 `outputs/trigger_launch.py` 的 `arguments()`。现网写死的是：

- `--server https://1.12.208.101/kaituan`
- `--worker-id zhongjiawei-mac-native`
- `--config` → `outputs/trigger-worker.json`
- `--catalog-db` → `work/trigger-worker/catalog.sqlite3`

服务器没搬时，`--server` 保持这一行。服务器搬了，先完成第 5 节，再把这一行改成新的 `https://<新主机>/kaituan`（不要带未定的 hash 路由）。worker-id 保持 `zhongjiawei-mac-native`，除非服务器是空队列且你们决定重钉（见第 5 节）。

改的是本机文件。不要把带真实环境差异的实验改动连同密钥一起提交。

### 4.5 来客与模拟器

这些 git 带不过去，新机器要重新准备：

1. 安装 BlueStacks，实例名 `Tiramisu64`（与 json 一致）。
2. 打开该实例的 adb，本机 `work/android-sdk/platform-tools/adb connect 127.0.0.1:5555` 后 `get-state` 为 `device`。
3. 实例内 root 可用（`su -c id` 含 `uid=0(root)`）。程序不会自动 root。
4. 把 `kaituan-frida-server` 放到 `/data/local/tmp/kaituan-frida-server`，`--version` 等于本机 venv 的 frida `16.7.19`。
5. 在该实例登录来客（包名 `com.bytedance.ls.merchant`）。旧机和新机同时登录同一抖音号会互踢，旧机模拟器上的来客先退出。

### 4.6 安装 LaunchAgent 并探活

依赖、凭证、adb 都就绪后再安装：

```sh
.venv/bin/python outputs/trigger_launch.py install
```

这会写入 `~/Library/LaunchAgents/cn.keyframe.web-kaituan.plist`（`0600`）并 `launchctl bootstrap`。plist 内容：`caffeinate -is` 包着 `.venv/bin/python outputs/trigger_launch.py run`，`KeepAlive` + `RunAtLoad`，日志在 `work/trigger-worker/stdout.log` 与 `stderr.log`。

已装过、只是改了 `--server` 或脚本时，在 `mac/` 下重新执行 `install` 之前要先 `bootout` 旧 label，否则 bootstrap 会报服务已存在。

探活：

- LaunchAgent **还没跑**时：`.venv/bin/python outputs/trigger_launch.py probe`。成功会打出带 `"gateway": "reachable"` 的 JSON。
- LaunchAgent **已经在跑**时，再 probe 会被单机全局锁拒绝（`Another Mac worker owns the global lock`）。这表示已有一个 worker，不要再起第二个。改看工作台心跳，或看 `stderr.log`。

---

## 5. 服务器也迁到新机（可选）

只换 Mac 时跳过本节。

现网是 Ubuntu。网关只听本机，公网走 nginx。

| 项 | 现网 |
|---|---|
| 目录 | `/opt/uiautomator2-trigger/`（`trigger_gateway.py`、`static/`、`state/`、`gateway.env`） |
| 属主 | `ubuntu:ubuntu` |
| systemd | `uiautomator2-trigger.service` |
| 环境文件 | `EnvironmentFile=/opt/uiautomator2-trigger/gateway.env` |
| 启动 | `ExecStart=/usr/bin/python3 /opt/uiautomator2-trigger/trigger_gateway.py --bind 127.0.0.1 --port 8792 --db /opt/uiautomator2-trigger/state/queue.sqlite3 --static /opt/uiautomator2-trigger/static` |
| 单元文件 | 仓库内 `mac/work/trigger-deploy/uiautomator2-trigger.service` 与上述一致，可作副本；里面没有密钥 |
| Nginx | `portal-ip-https.conf` include `snippets/kaituan-trigger.conf` |
| 入口 | `https://1.12.208.101/kaituan/` |
| 操作员 | 全站 `site-entry`（`auth_request`）。会话 cookie `__Host-site_session`，库 `/var/lib/site-entry/sessions.db` |
| Worker API | 仅 `/kaituan/api/worker/` 关闭主站鉴权；请求带 worker 自己的 `Authorization`，由网关核对 `GATEWAY_WORKER_TOKEN` |

仓库里的 `mac/work/trigger-deploy/deploy_gateway.py` 仍把 include 写进 `/etc/nginx/conf.d/dsh-ip-https.conf`，并把 `GATEWAY_USER_TOKEN` 嵌进 snippet。这和现网文件名不一致。换机时拷旧机**正在使用**的 nginx 配置，不要未读就重跑该脚本。

### 5.1 建议顺序

1. 旧 Mac worker 已按第 4.1 节停掉。
2. 旧服务器：`sudo systemctl stop uiautomator2-trigger.service`。确认没有第二个 `trigger_gateway.py`。
3. 新机器安装系统 `python3`，并有 `ubuntu` 用户（单元文件以该用户运行）。网关只用标准库，不需要 Mac 那个 `.venv`。
4. 在 clone 的**仓库根**放代码（用 `server/`，不用 `mac/outputs/` 里的同名副本）：

   ```sh
   sudo mkdir -p /opt/uiautomator2-trigger/state
   sudo cp server/trigger_gateway.py /opt/uiautomator2-trigger/
   sudo cp -a server/static /opt/uiautomator2-trigger/static
   sudo chown -R ubuntu:ubuntu /opt/uiautomator2-trigger
   sudo chmod 750 /opt/uiautomator2-trigger
   sudo chmod 700 /opt/uiautomator2-trigger/state
   ```

5. 放入 `gateway.env`，`chmod 600`，属主 `ubuntu`。键见 [`server/gateway.env.example`](server/gateway.env.example)。**值从旧机原样拷贝。** 两个 token 必须都非空且彼此不同。`GATEWAY_PUBLIC_ORIGIN` 是不带路径的 origin（入口的 `/kaituan/` 由 nginx 去掉，不要写进这个变量）。现网文件里多出来的键一律保留。
6. 队列二选一：
   - **留任务**：停稳旧进程后，把 `state/queue.sqlite3` 以及 `-wal`、`-shm` 拷到新机同一路径，`chmod 600`。库里的 `meta.worker_id` 已经钉死，Mac 必须继续用 `zhongjiawei-mac-native`。
   - **空库**：不拷 sqlite。进程首次启动会建库。第一台心跳成功的 worker-id 会被钉死。现网就让 `zhongjiawei-mac-native` 第一个连上。空库没有旧任务。
7. 安装单元：把 `mac/work/trigger-deploy/uiautomator2-trigger.service` 放到 `/etc/systemd/system/uiautomator2-trigger.service`，然后 `sudo systemctl daemon-reload && sudo systemctl enable --now uiautomator2-trigger.service`。确认在听 `127.0.0.1:8792`。源码里端口缺省是 `8793`，手工裸跑会和单元不一致，用 systemd，不要另起一份。
8. Nginx：从旧机拷 `portal-ip-https.conf` 与 `snippets/kaituan-trigger.conf`（以及仍在 include 的 `kaituan-auth-header.conf`，若存在）。保持：
   - `/kaituan` 进到 `/kaituan/`
   - `/kaituan/` 反代到 `http://127.0.0.1:8792/`
   - `/kaituan/api/worker/` 为 `auth_request off`，并把客户端的 `Authorization` 原样转给网关
   - 操作员路径若写死了 `Authorization: Bearer …`，那一串必须等于 `GATEWAY_USER_TOKEN`
   - 全站 `site-entry` 继续罩住操作员页面。不要为了消 401 把整段 `/kaituan/` 的 site-entry 关掉
9. `sudo nginx -t` 通过后再 reload。site-entry 的密码与 `/var/lib/site-entry/sessions.db` 按旧机现网方式迁移；本文不重写全站登录。
10. 新入口能打开后，再改 Mac `trigger_launch.py` 的 `--server` 并 `install`。旧服务器保持 stop，避免两台网关各拿一份队列。

### 5.2 回滚

- Mac：`--server` 改回 `https://1.12.208.101/kaituan`，`bootout` 后重新 `install`（或 kickstart）。
- 旧服务器单元若还在：确认新机单元已 stop，再在旧机 `systemctl start uiautomator2-trigger.service`。
- 队列只在一边是权威。回滚后看一眼进行中的租约，不要两台同时 `start`。

---

## 6. 验收

按这个顺序，不要颠倒：

1. 旧 Mac 的 `cn.keyframe.web-kaituan` 已 `bootout`，旧机没有 `trigger_worker` 进程。旧模拟器上来客已退出。
2. 浏览器打开工作台（现网 `https://1.12.208.101/kaituan/`；服务器若已迁，打开新入口）。先过 site-entry。页面标题为「开团与秒杀」。只看到 HTTP 200 不算通过，要能看到工作台内容。
3. 新 Mac LaunchAgent 在跑。工作台上 Mac 收单变为在线（心跳约 30 秒一次，超过 90 秒无心跳算离线）。
4. 顶栏或状态里执行环境不要被心跳冒充：Android、root、来客、原生接口要单独看。来客未登录、adb 不是 `device`、frida 版本不一致时，可以心跳在线但不可写。这是预期，先补第 4.5 节，不要改业务代码绕过。
5. 旧机不要再 `bootstrap` 同一个 label。验收完保持旧 worker 停止。

---

## 7. 常见坑

| 现象 | 原因 |
|---|---|
| clone 之后一启动就缺 token / 缺库 | 第 3.2 节没拷。`gateway.env`、`credentials.json`、`catalog.sqlite3` 都不在 git 里 |
| 主站登录成功，工作台接口仍 401 | `GATEWAY_USER_TOKEN` 轮换后，nginx 里写死的 Bearer 没一起改（现网可能在 `snippets/kaituan-trigger.conf`，也可能在 `kaituan-auth-header.conf`）。去同步那一处，不要关掉 `/kaituan/` 的 site-entry |
| worker 心跳 401，页面却正常 | Mac `credentials.json` 的 `worker_token` 和服务器 `GATEWAY_WORKER_TOKEN` 不是同一串。worker 路径走 token，不走浏览器登录 |
| `Worker credentials must have permission 0600` | `credentials.json` 权限过宽。`chmod 600` |
| 409 `worker_pinned` | 队列库已钉死 `zhongjiawei-mac-native`，新配置用了别的 `--worker-id` |
| 两台电脑任务乱跳或重复执行 | 旧机 LaunchAgent 没停，或两台服务器各跑一份 `queue.sqlite3`。worker 锁只防同一台 Mac 上的第二个进程，防不住两台电脑用同一个 worker-id |
| 来客刚登录就被踢下线 | 新旧模拟器同时登录同一抖音号。只留新机 |
| probe 报全局锁 | LaunchAgent 已经在跑。看工作台心跳即可 |
| 手工 `python3 trigger_gateway.py` 端口对不上 | 缺省端口是 8793，现网单元是 8792。用 systemd |
| 目录店名全不中 | 没拷 `catalog.sqlite3`，或只拷了主库、没拷 `-wal` |

---

## 8. 和 `migration/` 的区别

[`migration/`](migration/) 准备的是：操作入口并进经营台（`dashboard.keyframe-gz.com`），现网 IP 入口以后怎么切。那边默认执行机还是这一台 Mac，模拟器不搬。

本文是换电脑：新 Mac 重装执行环境，以及可选地把 `/opt/uiautomator2-trigger/` 搬到新 Ubuntu。域名没变时，`--server` 保持 `https://1.12.208.101/kaituan`。
