> **交付说明：** 交付的是**链路与 API（协议与执行能力：queue / claim / gate / report、来客执行、API 回执）**，不是现网皮。ALIGN 拷皮挂起，不是合并必做。口径以 **[GitHub issue #2](https://github.com/a192289394-oss/kaituan-seckill/issues/2)** 为准。不宣称「装完 = 现网能力」或「装完 = 现网皮」。

# 开团 / 秒杀自动化 · AI 可读安装说明书（AI-INSTALL）

> 状态：API-first 安装主文档（2026-10-16）。口径以 [GitHub issue #2](https://github.com/a192289394-oss/kaituan-seckill/issues/2) 为准。目录种子见 §5.8；风控全文见 [risk-rules.md](risk-rules.md)。下单 `kind` 见 §4.2。
> 适用仓库：`a192289394-oss/kaituan-seckill`
> 本文**不含任何真实密钥**。所有 token / 主机 / worker-id 均为假值，安装者必须自行生成。
> 标记 `EXAMPLE_LIVE_ONLY` 的内容 = 现网样板，**仅供对照，禁止当默认值**。

---

## 0. 一句话

**API 或自写前端下单 → Mac 来客（开团路径会用到销帮）执行 → API 读回执。**

目的：让**别的 Mac**跑通这条链路。主交付 = 本说明书 + 可运行的 gateway/worker 源码 + 标准接口（对方自写前端）。一套 = **1 gateway + 1 Mac worker**。第 6、7 章是安装步骤。

这里说的能力是**协议与执行能力**（队列、claim / gate / report、来客执行、API 回执），不是现网工作台皮肤。仓内静态页是 **OPTIONAL 调试壳 / 非交付皮**。ALIGN 把现网皮拷进仓库的做法**挂起**，不作为合并必做。验收看 API 读回；长得不像现网皮**不算**缺。

---

## 1. 文档角色与读者

| 读者 | 怎么用本文 |
|---|---|
| 人类运维 / 店主技术同学 | 按第 6、7、8 章顺序执行；遇到问题查第 10 章。非工程师先看 [README-人类安装.md](README-人类安装.md)。 |
| AI agent（Claude / Cursor 等） | 第 2 章 MUST / MUST NOT 是**硬约束**，任何步骤与之冲突时以第 2 章为准；第 5 章配置键表是键名来源；第 8 章用 **API 读回**判定链路，不用截图对皮。口径以 [GitHub issue #2](https://github.com/a192289394-oss/kaituan-seckill/issues/2) 为准。 |
| 架构师 | 第 3、4、9 章是部署、API 与风控契约。缺口见 [G-STATUS.md](G-STATUS.md)。不要把「拷现网皮 / 对 Soft Glass 验收」列为合并条件。 |

**AI agent 读本文时的执行纪律**

1. 不得从任何现有机器“拷贝” `gateway.env`、`credentials.json`、来客登录态、`worker.sqlite3`、`queue.sqlite3`。新装一律**新生成**。
2. 不得把第 11 章 `EXAMPLE_LIVE_ONLY` 的 IP、域名、worker-id 写进新环境配置。
3. 不得在日志、提交、聊天、PR 描述里输出 token 真值；需要展示时写 `<redacted>` 或本文假值。
4. 任何“链路已通”的结论必须给出第 8 章对应条目的 **API 读回**证据，不能只凭 HTTP 200、心跳在线，或页面长得像现网。
5. 不得把现网 Soft Glass 静态页灌进仓库或当作交付皮。不得为对皮而从现网拷 `index.html` / `style.css` / `guide.html`。

---

## 2. MUST / MUST NOT

### 2.1 MUST

- **M1 部署单元**：一套 = **1 gateway + 1 Mac worker**。gateway 通过 `GATEWAY_WORKER_ID` 钉死唯一 worker。
- **M2 新装自生成密钥**：`GATEWAY_USER_TOKEN` 与 `GATEWAY_WORKER_TOKEN` 都必须新生成、非空、且**互不相同**（网关启动时会校验，相同直接拒绝启动）。
- **M3 独立登录为默认，交付物是 API**：操作员用 `POST /api/login` 换 `gateway_session`，或直接 `Authorization: Bearer` 调操作员接口。仓内静态登录面板只是 OPTIONAL 调试壳。site-entry / 主站 `auth_request` 只是 OPTIONAL。
- **M4 公网只走 HTTPS**：gateway 只监听 `127.0.0.1:<port>`，由 nginx 做 TLS 终止与路径前缀反代。
- **M5 前缀三处一致**：若使用路径前缀（示例 `/kaituan/`），则 nginx `location`、`GATEWAY_COOKIE_PATH`、Mac 端 `--server` 必须**同时**使用同一前缀。
- **M6 凭证文件权限**：Mac 端 `mac/work/trigger-worker/credentials.json` 权限必须为 `0600`；服务器 `gateway.env` 权限 `0600`，属主为服务运行用户。
- **M7 人工登录**：来客（主执行，包名 `com.bytedance.ls.merchant`）与销帮（开团路径会用到，包名 `com.bytedance.lifeservice.crm`）都由人在模拟器里**手动登录**。禁止脚本自动登录。
- **M8 两层验收**：先过探活，再用操作员 API 做上线读回（下单、`/api/tasks`、`/api/tasks/<id>/audit`、`/api/status`）。通过表示**链路与协议**可用。不像现网皮不算失败。
- **M9 风控硬规则常开**：第 9 章所有规则在新装环境默认生效，不得为了“先跑通”关闭。
- **M10 Frida 同版本为宜**：Frida 是挂钩/注入工具，用来在模拟器里调用来客原生接口。Mac 侧与设备端 frida-server **宜同版本**。推荐参考 `16.7.19`（与 `mac/outputs/requirements.lock.txt` 及现网常用版本一致时更省事）。版本号不是唯一门槛；验收看能否稳定附加到来客并跑通原生调用。

### 2.2 MUST NOT

- **N1** 不得把安装叙事写成或执行成“换电脑继续跑”“迁账号”“一店一套账号”。本文只讲**新装一套**。
- **N2** 不得两套环境共享同一个 worker-id、同一个 `GATEWAY_WORKER_TOKEN`、同一个 sqlite 库。要互不影响的两套环境 → **装两套**（见第 3.4 节）。
- **N3** 不得把真实 token 写进 plist、URL、命令行参数、nginx 配置（独立登录模式下 nginx 不注入 Bearer）、git 仓库。
- **N4** 不得默认安装 site-entry / 主站鉴权，不得默认使用 `deploy_gateway.py`（它绑定现网 IP 与 portal，属 `EXAMPLE_LIVE_ONLY`）。
- **N5** 不得把心跳在线、Android 在线、HTTP 200 当作“可写 / 业务成功”。
- **N6** 不得自动化登录来客或销帮，不得自动绕过验证码 / 风控弹窗。
- **N7** 不得在无生效秒杀活动时新建活动（秒杀“零新建”）。
- **N8** 不得对已发出的提交重发；已发出只回读。
- **N9** 不得把 `migration/` 下文件作为安装主路径（那是历史材料）。
- **N10** 本文与安装过程**不 push、不改任何生产环境**，不灌 Soft Glass，不把现网静态页拷进 main。
- **N11** 不得把「必须 BlueStacks」或「必须实例名 Tiramisu64」写成硬门槛。硬条件是 adb 连上且 `su -c id` 含 `uid=0`。BlueStacks / `Tiramisu64` 只是推荐示例。

---

## 3. 部署单元与拓扑

### 3.1 拓扑（文字图）

```
 [操作员：自写前端或脚本]          仓内静态页 = OPTIONAL 调试壳，非交付皮
      │  二选一，契约相同
      │  A 本地  http://127.0.0.1:8792/api/...
      │  B 服务器 https://gateway.example.com/kaituan/api/...
      │  操作员：login/logout、status、tasks、audit、cancel|resume|retry
      │  不调用 /api/worker/*
      ▼
 ┌──────────────────────── 服务器（Ubuntu） ────────────────────────┐
 │ nginx :443  location /kaituan/  → proxy_pass http://127.0.0.1:8792/ │
 │ systemd: kaituan-gateway.service                                     │
 │   trigger_gateway.py --bind 127.0.0.1 --port 8792                    │
 │   --db <APP_DIR>/state/queue.sqlite3 --static <APP_DIR>/static        │
 │   EnvironmentFile=<APP_DIR>/gateway.env                              │
 │   SQLite 队列 / 90s 租约 / 两道提交闸门 / 审计                        │
 └──────────────────────────────────────────────────────────────────────┘
      ▲  HTTPS 出站（Mac 主动连服务器，服务器从不连 Mac）
      │  Authorization: Bearer <GATEWAY_WORKER_TOKEN>
      │  /api/worker/claim | heartbeat | gate | report
 ┌──────────────────────── Mac（worker-id = mac-worker-1） ─────────────┐
 │ LaunchAgent cn.keyframe.web-kaituan → trigger_launch.py run          │
 │   trigger_worker.py --server https://gateway.example.com/kaituan     │
 │   本机 worker.sqlite3 / 一次提交日志 / watchdog                       │
 │ 能 root 的模拟器（推荐示例：BlueStacks 实例 Tiramisu64）             │
 │   adb + su uid=0；Frida=挂钩/注入，调来客原生接口                    │
 │   来客（主执行）+ 销帮（开团路径）均人工登录                         │
 └──────────────────────────────────────────────────────────────────────┘
```

### 3.2 部署单元定义

- **一套 = 1 gateway + 1 Mac worker。**
- gateway 侧：一个 systemd 服务、一个 `gateway.env`、一个 `queue.sqlite3`、一个公网入口（域名 + 可选前缀）。
- Mac 侧：一台 Mac 上一个 worker 进程（单机全局锁保证不会起第二个实例）、一个 worker-id、一个 `credentials.json`、一个 `worker.sqlite3`、一个能 root 的模拟器，以及其中人工登录的来客与销帮。
- 两侧通过三个值绑定：`GATEWAY_WORKER_ID` ↔ `--worker-id`，`GATEWAY_WORKER_TOKEN` ↔ `credentials.json.worker_token`，操作员入口（本地端口或公网 origin+前缀）↔ `--server`。本地对接时 `--server` 用 `http://127.0.0.1:<PORT>`（无尾斜杠）；服务器对接时用 `https://<GATEWAY_HOST>/<前缀>`（无尾斜杠）。

### 3.3 两种对接（契约相同）

| 模式 | 入口 | 适用 |
|---|---|---|
| 本地 | `http://127.0.0.1:<PORT>/api/...`，示例端口 `8792`（源码缺省端口 8793，以部署单元为准） | 同机脚本，或经隧道转到环回 |
| 服务器 | `https://<GATEWAY_HOST>/<PREFIX>/api/...`，样板前缀 `/kaituan/` | 远程操作员。nginx 剥离前缀后转到 `127.0.0.1:<PORT>` |

路径、方法、鉴权在两种入口下相同。不支持 query string。没有匿名 `/healthz`；探活用带凭证的 `GET /api/status`。操作员最低接口：`POST /api/login`、`POST /api/logout`、`GET /api/status`、`GET /api/tasks`、`POST /api/tasks`、`GET /api/tasks/<id>/audit`、`POST /api/tasks/<id>/cancel|resume|retry`。`/api/worker/*` **不对**操作员前端。

### 3.4 需要第二套互不影响的环境？

**再装一套。** 第二套有自己独立的：

| 项 | 第一套（示例） | 第二套（示例） |
|---|---|---|
| 公网入口 | `https://gateway.example.com/kaituan/` | `https://gateway2.example.com/kaituan/` 或 `https://gateway.example.com/kaituan-b/` |
| 服务器目录 | `/opt/kaituan-gateway/` | `/opt/kaituan-gateway-b/` |
| 端口 | `8792` | `8794` |
| systemd 单元 | `kaituan-gateway.service` | `kaituan-gateway-b.service` |
| `GATEWAY_WORKER_ID` / `--worker-id` | `mac-worker-1` | `mac-worker-2` |
| token | 独立生成 | 独立生成 |
| Mac | Mac A | Mac B（另一台 Mac） |

禁止：让两个 gateway 指向同一台 Mac worker，或让一台 gateway 接两个 worker-id。

---

## 4. 能力契约（链路与 API）

> 验收对象是协议与执行能力。操作员 API 以 [GitHub issue #2](https://github.com/a192289394-oss/kaituan-seckill/issues/2) 为准。不像现网皮**不算**缺。仓内静态页不在本清单里。

### 4.1 链路清单

| 能力 | 契约 |
|---|---|
| 下单 | `POST /api/tasks`。`kind` 见 §4.2。自写前端或脚本均可。调试壳上的表单不是交付皮。 |
| 开团 | `kind=plan`。支持来客下载分享链接、`snssdk299467://webview` 深链、官方开团详情 URL、18–20 位纯计划号。逐层解码官方 `redirect_url`/`url`，计划号以字符串保留精度；异域名、混入不同计划号、异常编码、重复嵌套 → 拒绝。开团导航会进入销帮。 |
| 秒杀 | `kind=authorization`。**只往已有生效活动里加号**。无活动零新建。 |
| 只读 | `kind=inspect`。不写业务。 |
| 酒店匹配 | 目录精确名称优先；仅当零命中时允许去掉末尾一个 `秒杀`/`开团` 词再试，且仍须唯一精确命中。相似/包含匹配不放行。 |
| Mac 执行 | Mac 出站领取任务（90 秒租约），经来客正常账号与网络上下文执行；提交前过 `preflight` 与 `commit` 两道闸门。 |
| 回执 | `GET /api/status`、`GET /api/tasks`、`GET /api/tasks/<id>/audit` 读状态与证据。调试页若展示「Mac 收单在线」和 Android / root / 来客状态，只是同一份数据的可选视图。 |
| 成功判定 | 提交后进入 `waiting_review` 且 `committed=true`，并以**独立只读回读**平台业务结果为准。 |

### 4.2 下单 kind

操作员集成备忘。字段校验以 issue #2 与网关代码为准。

| kind | 人话 | 要点 |
|---|---|---|
| `plan` | 开团 | 要稳定 `request_id`，以及 18–20 位 `plan_id` |
| `authorization` | 秒杀加号 | 要 `request_id`、精确 `hotel`、1–40 个 `accounts`；不要带 `plan_id` |
| `inspect` | 只读 | 与开团一样带 `plan_id`；不可把这次下单当成写入 |

### 4.3 不能承诺什么

- 不承诺“取消”能撤销已发出的请求（取消只隔离未发出的部分）。
- 不承诺平台未返回的字段：禁选状态、价格语义未知即显示“未知”，**未知不当 0**、不当可用。
- 不承诺来客账号不会掉登录；掉登即停写，需人工重新登录。
- 不承诺新建秒杀活动（设计上禁止）。
- 不承诺 7×24 无人值守下模拟器永不异常；异常即停写 + 自愈尝试 + API/调试页告警。
- 不承诺页面长得像现网 Soft Glass。
- 不提供多 worker 并发、负载均衡。

---

## 5. 配置键表

### 5.1 服务器 `gateway.env`（`EnvironmentFile`，权限 0600）

| 键 | 必填 | 说明 | 假值示例 |
|---|---|---|---|
| `GATEWAY_USER_TOKEN` | 是 | 操作员凭证：`POST /api/login` 换 `gateway_session`，或直接 `Authorization: Bearer` 调操作员 `/api/*`。调试壳的登录框只是可选入口。 | `changeme-user-token` |
| `GATEWAY_WORKER_TOKEN` | 是 | Mac worker 专用凭证，仅用于 `/api/worker/*`。**必须与 USER 不同**，否则网关拒绝启动。 | `changeme-worker-token` |
| `GATEWAY_PUBLIC_ORIGIN` | 是 | **纯 origin**（scheme+host[+port]），**不带 path**。用于 Origin 校验与 cookie `Secure` 判定（https 才带 Secure）。 | `https://gateway.example.com` |
| `GATEWAY_ALLOWED_HOSTS` | 否 | 允许的 Host 头，逗号分隔；缺省取 `GATEWAY_PUBLIC_ORIGIN` 的 netloc。 | `gateway.example.com` |
| `GATEWAY_COOKIE_PATH` | 否 | `gateway_session` 的 Path；缺省 `/`。使用前缀时应设为前缀。 | `/kaituan/` |
| `GATEWAY_WORKER_ID` | 否（**产品化强烈建议填**） | 钉死唯一可领任务的 worker-id（字符集 `[A-Za-z0-9_.:-]`，≤96），落实“一套 = 1 gateway + 1 Mac worker”。不填时**第一个连上来的 worker-id 会被永久写入 `queue.sqlite3`**；之后其它 id 一律 409 `worker_pinned`。 | `mac-worker-1` |

完整假值样例：

```dotenv
# <APP_DIR>/gateway.env —— 新装自填，切勿从任何已有机器拷贝
# 生成：python3 -c 'import secrets;print(secrets.token_urlsafe(32))'（两次，结果不同）
GATEWAY_USER_TOKEN=changeme-user-token
GATEWAY_WORKER_TOKEN=changeme-worker-token
GATEWAY_PUBLIC_ORIGIN=https://gateway.example.com
GATEWAY_ALLOWED_HOSTS=gateway.example.com
GATEWAY_COOKIE_PATH=/kaituan/
GATEWAY_WORKER_ID=mac-worker-1
```

### 5.2 服务器启动参数（`trigger_gateway.py`）

| 参数 | 说明 | 产品化取值 |
|---|---|---|
| `--bind` | 监听地址 | `127.0.0.1`（固定，不对公网） |
| `--port` | 端口；**源码缺省 8793，以 systemd 单元为准** | `8792` |
| `--db` | 队列库（必填），新装为空库自动建表 | `<APP_DIR>/state/queue.sqlite3` |
| `--static` | **OPTIONAL** 调试壳目录。不配也能只用 API。不是交付皮 | `<APP_DIR>/static` |

### 5.3 网关 HTTP 接口（安装验收会用到）

| 方法 路径（网关内部，nginx 前缀会被剥离） | 鉴权 | 用途 |
|---|---|---|
| `POST /api/login` body `{"token": "..."}` | 需同源 `Origin` | 换 `gateway_session` cookie；同 IP 10 分钟内 ≥10 次 → 429 |
| `POST /api/logout` | 会话/Bearer | 清 cookie |
| `GET /api/status` | 会话或 Bearer USER | worker 在线/健康、队列计数 |
| `GET /api/tasks` / `POST /api/tasks` | 会话或 Bearer USER | 任务列表 / 下单 |
| `GET /api/tasks/<id>/audit` | 同上 | 审计 |
| `POST /api/tasks/<id>/cancel|resume|retry` | 同上 | 任务操作 |
| `POST /api/worker/claim|heartbeat|gate|report` | **仅** Bearer WORKER | Mac worker 专用。**不对操作员前端** |
| `GET /`、`/index.html` 等 | 无 | **OPTIONAL 调试壳 / 非交付皮**。不作为验收项 |

> 网关不支持 query string（带 `?` 返回 400）。没有独立的 `/healthz`；探活用 `GET /api/status`（带凭证）。上表操作员路径是最低对接集；`kind` 见 §4.2。

### 5.4 Mac 凭证 `mac/work/trigger-worker/credentials.json`（权限 0600）

```json
{ "worker_token": "changeme-worker-token" }
```

值 = 服务器 `GATEWAY_WORKER_TOKEN`。启动器读出后只经进程环境变量 `GATEWAY_WORKER_TOKEN` 传给 worker，不进 plist、不进 URL、不进命令行。

### 5.5 Mac 运行配置 `mac/outputs/trigger-worker.json`（由 example 复制）

| 键 | 说明 | 默认/样例 |
|---|---|---|
| `execution_max_age_seconds` | 任务从创建到执行的最大可接受时长，超过不执行 | `86400` |
| `android_device.backend` | 安卓宿主。推荐示例 `bluestacks`，不是唯一机型 | `bluestacks` |
| `android_device.execution_backend` | 执行通道 | `native_api` |
| `android_device.adb_endpoint` | ADB 地址。推荐本机环回；硬条件是能连上并 root | `127.0.0.1:5555` |
| `android_device.instance` | 模拟器实例名。推荐示例 `Tiramisu64`，须与你实际创建的实例一致，**不是强制机型** | `Tiramisu64` |
| `android_device.autostart` | worker 是否自动拉起模拟器。新装建议先 `false`，人工确认实例/登录稳定后再评估改 `true` | `false` |
| `pc_activity.allow_authorization_copy` | 允许复用既有授权做查重/授权复制 | `true` |

### 5.6 Mac 启动参数（`trigger_worker.py`，由 `trigger_launch.py` 拼装）

| 参数 | 说明 | 产品化取值 |
|---|---|---|
| `--server` | 网关公网基址 = `GATEWAY_PUBLIC_ORIGIN` + 前缀（无尾斜杠） | `https://gateway.example.com/kaituan` |
| `--worker-id` | 与 `GATEWAY_WORKER_ID` 一致；源码缺省 `mac-native-1` | `mac-worker-1` |
| `--config` | 运行配置 | `mac/outputs/trigger-worker.json` |
| `--catalog-db` | 酒店目录种子库。口径见 §5.8，不在仓库内生成 | `mac/work/trigger-worker/catalog.sqlite3` |
| `--state-dir` | 本机状态目录 | `mac/work/trigger-worker` |
| `--ca-file` | 可选：自签/私有 CA；主机名校验仍开启 | 空 |
| `--probe` / `--once` | 仅元数据心跳（不碰安卓、不领任务）/ 跑一轮 | 验收时用 |

> **新装必配（合入等 Mac 回归书面确认）：** 当前 `mac/outputs/trigger_launch.py` 把 `--server` 与 `--worker-id` 写死为现网值（对照见第 11 章，`EXAMPLE_LIVE_ONLY`）。新装必须改成自己的 gateway 与 worker-id，**不要把现网值当默认，也不要提交回仓库**。参数化在 [GitHub #4](https://github.com/a192289394-oss/kaituan-seckill/pull/4)（原 PR-3），**合入等 Mac 回归书面确认**（现网 Mac 先写好本地 `launch.json`）。本 PR 不改该脚本。参数化后的目标接口：

```sh
# 目标（PR 落地后）：环境变量或旁路 json，二选一
export KAITUAN_SERVER=https://gateway.example.com/kaituan
export KAITUAN_WORKER_ID=mac-worker-1
# 或 mac/work/trigger-worker/launch.json:
# {"server": "https://gateway.example.com/kaituan", "worker_id": "mac-worker-1"}
```

### 5.7 LaunchAgent

| 项 | 值 |
|---|---|
| Label | `cn.keyframe.web-kaituan` |
| plist | `~/Library/LaunchAgents/cn.keyframe.web-kaituan.plist`（权限 0600，由 `trigger_launch.py install` 生成） |
| 进程 | `/usr/bin/caffeinate -is <mac>/.venv/bin/python <mac>/outputs/trigger_launch.py run` |
| 策略 | `KeepAlive=true`、`RunAtLoad=true`、`ThrottleInterval=30` |
| 日志 | `mac/work/trigger-worker/stdout.log`、`stderr.log` |
| PATH | 前置 `mac/work/android-sdk/platform-tools` |

### 5.8 酒店目录种子 `catalog.sqlite3`

`catalog.sqlite3` = 酒店目录种子库（表 `merchant_catalog`）。

- worker 启动时**只读**打开该文件，把行拷进本机 `worker.sqlite3` **一次**（`meta.catalog_seeded` 已写入后不再重拷）。
- 缺文件：目录为空，worker **不崩溃**。
- 仓库内**没有**从 `merchant-*.json` 生成该 sqlite 的脚本。
- 新装：安装者**自备**同结构的 sqlite（业务导出，或从已有环境拷贝这份种子库），放到 `mac/work/trigger-worker/catalog.sqlite3`。
- **本轮不做** catalog 导入功能。

`worker.sqlite3` 与 `queue.sqlite3` 不是目录种子。这两份库新装保持为空，不要从已有环境拷来。

---

## 6. 服务器安装（Ubuntu，独立登录默认）

参数约定（下文全部用占位符，安装时替换）：

| 占位符 | 含义 | 示例 |
|---|---|---|
| `<GATEWAY_HOST>` | 公网域名 | `gateway.example.com` |
| `<PREFIX>` | 路径前缀（可改，改则 nginx / cookie_path / `--server` 三处同改） | `/kaituan/` |
| `<APP_DIR>` | 安装目录 | `/opt/kaituan-gateway` |
| `<PORT>` | 本机监听端口 | `8792` |
| `<SVC_USER>` | 服务用户 | `kaituan` |
| `<UNIT>` | systemd 单元名 | `kaituan-gateway` |

### 6.1 前置

- Ubuntu 22.04/24.04，`python3`（≥3.10，网关只用标准库），`nginx`，有效 TLS 证书（如 certbot）。
- DNS：`<GATEWAY_HOST>` 解析到服务器。防火墙只开 443（及 80 用于跳转/签证书）；`<PORT>` 不对外。

### 6.2 目录与代码

```sh
sudo useradd --system --home <APP_DIR> --shell /usr/sbin/nologin <SVC_USER>   # 已有用户可跳过
sudo install -d -m 0755 -o root -g root <APP_DIR>
sudo install -d -m 0700 -o <SVC_USER> -g <SVC_USER> <APP_DIR>/state
# 从仓库取部署件（以仓库 server/ 为部署源）
sudo install -m 0644 server/trigger_gateway.py <APP_DIR>/trigger_gateway.py
sudo rsync -a --delete --exclude '*.bak*' server/static/ <APP_DIR>/static/
```

> 不要把 `*.bak-*` 文件部署上去；不要拷贝任何已有 `queue.sqlite3`。新装空库，首次启动自动建表。

### 6.3 `gateway.env`

```sh
sudo install -m 0600 -o <SVC_USER> -g <SVC_USER> server/gateway.env.example <APP_DIR>/gateway.env
sudoedit <APP_DIR>/gateway.env      # 按第 5.1 节填写；两个 token 分别新生成
```

生成 token（各运行一次，结果分别填入 USER / WORKER）：

```sh
python3 -c 'import secrets;print(secrets.token_urlsafe(32))'
```

### 6.4 systemd 单元样板（参数化）

`/etc/systemd/system/<UNIT>.service`：

```ini
[Unit]
Description=Kaituan task web gateway (<UNIT>)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=<SVC_USER>
Group=<SVC_USER>
WorkingDirectory=<APP_DIR>
EnvironmentFile=<APP_DIR>/gateway.env
ExecStart=/usr/bin/python3 <APP_DIR>/trigger_gateway.py --bind 127.0.0.1 --port <PORT> --db <APP_DIR>/state/queue.sqlite3 --static <APP_DIR>/static
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=<APP_DIR>/state
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now <UNIT>.service
systemctl status <UNIT>.service --no-pager
journalctl -u <UNIT> -n 20 --no-pager    # 应见 "listening; native execution remains on the pinned Mac"
```

若启动即退出并提示 `Distinct nonempty GATEWAY_USER_TOKEN and GATEWAY_WORKER_TOKEN are required` 或 `GATEWAY_PUBLIC_ORIGIN is required`，回到 6.3 修正。

### 6.5 nginx 样板（独立登录默认，**不注入 Bearer**）

`/etc/nginx/sites-available/kaituan.conf`（`<PREFIX>` 以 `/kaituan/` 为例）：

```nginx
server {
    listen 80;
    server_name <GATEWAY_HOST>;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name <GATEWAY_HOST>;

    ssl_certificate     /etc/letsencrypt/live/<GATEWAY_HOST>/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/<GATEWAY_HOST>/privkey.pem;

    # 无尾斜杠访问时补斜杠，保证工作台相对路径 api/ 正确
    location = /kaituan { return 301 /kaituan/; }

    # 操作员 + worker 共用同一前缀；网关自身区分 /api/worker/*（WORKER token）与其它（USER 会话/token）
    location /kaituan/ {
        proxy_pass http://127.0.0.1:<PORT>/;      # 尾斜杠 = 剥离 /kaituan/ 前缀
        proxy_http_version 1.1;
        proxy_set_header Host $host;               # 必须在 GATEWAY_ALLOWED_HOSTS 内
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        # 原样透传客户端 Authorization 与 Cookie；独立登录模式下 nginx 不写入任何 token
        proxy_read_timeout 30s;
        client_max_body_size 1m;
    }
}
```

```sh
sudo ln -s /etc/nginx/sites-available/kaituan.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

**改前缀**：若把 `/kaituan/` 改为 `/foo/`，同时改：nginx 两处 `location`、`GATEWAY_COOKIE_PATH=/foo/`、Mac `--server https://<GATEWAY_HOST>/foo`。不用前缀时：`location /`、`GATEWAY_COOKIE_PATH=/`、`--server https://<GATEWAY_HOST>`。

### 6.6 独立登录（默认）

交付路径是 API，不是调试壳。本地对接把下面 URL 的主机换成 `http://127.0.0.1:<PORT>`，并带上与 `GATEWAY_PUBLIC_ORIGIN` 一致的 `Origin`。

1. `POST /api/login`，body `{"token":"<GATEWAY_USER_TOKEN>"}`。网关校验同源 `Origin` 后下发 `gateway_session`（`HttpOnly; SameSite=Strict; Path=<GATEWAY_COOKIE_PATH>`，https 下带 `Secure`）。也可以不走 cookie，直接在后续请求带 `Authorization: Bearer <GATEWAY_USER_TOKEN>`。
2. 退出：`POST /api/logout`。
3. 若启动时带了 `--static`，浏览器打开调试壳会看到「连接任务入口」。该页是 **OPTIONAL 调试壳 / 非交付皮**，外观不验收。

命令行等效验证（假值）：

```sh
curl -sS -i -X POST https://gateway.example.com/kaituan/api/login \
  -H 'Origin: https://gateway.example.com' -H 'Content-Type: application/json' \
  -d '{"token":"changeme-user-token"}' | grep -i '^set-cookie'
```

### 6.7 OPTIONAL：接入已有站点统一登录（site-entry）

仅当你**已有**站点级登录网关时才考虑。模式：nginx `auth_request` 校验站点会话，通过后由 nginx 在操作员路径写入 `Authorization: Bearer <USER_TOKEN>`；`/kaituan/api/worker/` 路径 `auth_request off` 并透传客户端 Authorization。代价：USER token 落在 nginx 配置里（需 0600 + 单独管理）、多一个故障点。**不是默认，不随本文安装。** 现网用法见第 11 章 `EXAMPLE_LIVE_ONLY`。

---

## 7. Mac 安装（worker）

### 7.1 安卓运行时绿场（先做）

完整步骤见同目录 **[install-mac-android-runtime.md](install-mac-android-runtime.md)**（权威）。`migration/` 下的安卓笔记是历史材料，勿作主路径。要点：

| 步骤 | 验收 |
|---|---|
| 能 root 的模拟器 | adb 连上。推荐示例：BlueStacks，实例名 `Tiramisu64`。换别的实例只要配置里的名字一致 |
| ADB | 推荐 `127.0.0.1:5555`；`adb -s <serial> get-state` → `device` |
| Root（硬条件） | `adb -s <serial> shell su -c id` 含 `uid=0` |
| Frida | 挂钩/注入工具，用来在模拟器里调用来客原生接口。推荐 Mac 与设备端同版本，参考 `16.7.19`（arm64）。验收是能稳定附加到来客 |
| 来客 | 包名 `com.bytedance.ls.merchant`。自备 APK；**人工登录**；身份核验通过。主执行端 |
| 销帮 | 包名 `com.bytedance.lifeservice.crm`。开团路径会用到；**人工登录**。不是另一套主执行 App |

**自备清单（不在仓库内，见 `mac-EXCLUDED.md`）**：能 root 的模拟器（推荐 BlueStacks）、`android-sdk/platform-tools`、frida-server（推荐 16.7.19 arm64，与 Mac 侧同版本）、来客 APK、销帮 APK、酒店目录种子 `catalog.sqlite3`（§5.8：自备同结构 sqlite；缺文件则目录为空、不崩溃；本轮不做导入）、Python 虚拟环境。

### 7.2 代码与依赖

```sh
cd <REPO>/mac
python3 -m venv .venv
.venv/bin/pip install -r outputs/requirements.lock.txt
# Frida = 挂钩/注入工具，用来在模拟器里调用来客原生接口。推荐与设备端同版本，参考 16.7.19
.venv/bin/python -c 'import frida;print(frida.__version__)'
# 可选自检（不连网关、不写业务）：通过只说明本机代码路径可跑，不等于探活或上线验收
.venv/bin/python -B work/web_offline_tests.py
```

### 7.3 运行配置与凭证

```sh
cp outputs/trigger-worker.example.json outputs/trigger-worker.json   # 按 5.5 调整
install -d -m 0700 work/trigger-worker
umask 077
printf '{ "worker_token": "%s" }\n' 'changeme-worker-token' > work/trigger-worker/credentials.json
chmod 0600 work/trigger-worker/credentials.json
# 自备 catalog.sqlite3 → work/trigger-worker/catalog.sqlite3（口径 §5.8）
# 没有该文件也可以启动：目录为空、不崩溃。不要在仓库里找生成脚本。
```

> 实际安装时把 `changeme-worker-token` 换成服务器 `GATEWAY_WORKER_TOKEN` 的值；用安全通道传递，不要经聊天工具明文发送。

### 7.4 指向自己的 gateway 与 worker-id

> **新装必配。** 参数化合入见 [GitHub #4](https://github.com/a192289394-oss/kaituan-seckill/pull/4)（原 PR-3），**合入等 Mac 回归书面确认**。本 PR 不改 `trigger_launch.py`。

合入前（本机临时修改，不提交）：把 `outputs/trigger_launch.py` 中 `'--server','…'` 改为你的入口（本地 `http://127.0.0.1:8792` 或 `https://gateway.example.com/kaituan`），`'--worker-id','…'` 改为 `'mac-worker-1'`。不要保留附录里的 `EXAMPLE_LIVE_ONLY` 值。
合入后：用 5.6 节的 `KAITUAN_SERVER` / `KAITUAN_WORKER_ID` 或 `work/trigger-worker/launch.json`。

### 7.5 单次探测 → 常驻

```sh
.venv/bin/python outputs/trigger_launch.py probe     # 只发元数据心跳，不碰安卓、不领任务
# 用 GET /api/status 看 worker 在线；Android/root/来客 必须各自就绪，不能由心跳推断。调试壳若打开，只是同一数据的可选视图
.venv/bin/python outputs/trigger_launch.py install   # 写 LaunchAgent 并 bootstrap
launchctl print gui/$(id -u)/cn.keyframe.web-kaituan | head -20
tail -n 50 work/trigger-worker/stderr.log
```

常驻运行时再跑 `probe` 会被单机全局锁拒绝——这是预期行为，说明没有第二实例。

---

## 8. 探活验收 vs 上线验收

> **探活 ≠ 可写。** 探活全绿只说明“连上了”。上线验收是操作员 API 读回（下单、任务列表、audit、status）。心跳在线不得冒充 Android / root / 来客 / Frida（挂钩注入）/ write_ready。页面不像现网**不算**失败。

### 8.1 探活验收（连通性，不产生业务写入）

| # | 检查 | 通过标准 |
|---|---|---|
| P1 | systemd | `<UNIT>` active (running)；日志含 `listening` |
| P2 | 本机端口 | `curl -s -o /dev/null -w '%{http_code}' -H 'Host: <GATEWAY_HOST>' http://127.0.0.1:<PORT>/` → 200（不带 Host 头会 403 `host`，属正常）；`ss -ltnp` 确认只监听 127.0.0.1 |
| P3 | 入口可达 | 服务器对接：`https://<GATEWAY_HOST>/kaituan/api/status` 无凭证 → 401（不是 nginx 默认页）。若启用了 OPTIONAL 调试壳，静态 HTML 只确认能打开，**不对皮** |
| P4 | 未登录拒绝 | `GET /kaituan/api/status` 无凭证 → 401 |
| P5 | 独立登录 | 6.6 节 curl 返回 `Set-Cookie: gateway_session=…; Path=/kaituan/; …HttpOnly; SameSite=Strict; Secure` |
| P6 | token 隔离 | 用 USER token 调 `/api/worker/heartbeat` → 401；用 WORKER token 调 `/api/tasks` → 401 |
| P7 | Mac 心跳 | `trigger_launch.py probe` 后，`/api/status` 中 worker 在线、worker-id = `mac-worker-1` |
| P8 | 钉死 worker | 用其它 worker-id 调 `/api/worker/heartbeat` 或 `claim` → 409 `worker_pinned` |
| P9 | 权限 | `gateway.env`、`credentials.json`、plist 均为 0600 |
| P10 | 空库 | 新装 `queue.sqlite3` 任务数为 0，无历史任务/事件 |

### 8.2 上线验收（能力，需真实但受控的业务操作）

| # | 检查 | 通过标准 |
|---|---|---|
| L1 | 安卓环境 | `GET /api/status`（或 worker health）里 Android / root / 来客 / 原生接口**各自**就绪（不能由心跳推断）。调试页只是可选视图 |
| L2 | 来客与销帮身份 | 来客人工登录且身份核验通过（见 [install-mac-android-runtime.md](install-mac-android-runtime.md)）；销帮已人工登录。无自动登录 |
| L3 | 只读单 | `kind=inspect`：完成、无写入、audit 可见 |
| L4 | 开团一单 | `kind=plan`：一次提交 → `waiting_review` + `committed=true` → audit 与独立回读 |
| L5 | 秒杀一单（有活动） | `kind=authorization`：往已有生效活动加一个号；一次提交 + 回读 |
| L6 | 秒杀零新建 | 对无生效活动的酒店下单：不新建，展示旧商品/原价/库存；`schedule` 类 resume 被拒 |
| L7 | 不重发 | 对已提交单点 retry/resume：只回读，不产生第二次提交 |
| L8 | 去重 | 同 request_id / business_key 重复下单被合并或拒绝 |
| L9 | 停写 | 人为让来客掉登或停模拟器：任务停写，status/audit 能看出不可写，恢复后才继续 |
| L10 | 常驻 | 重启 Mac 登录后 LaunchAgent 自动拉起，心跳与 L1 状态恢复 |
| L11 | 解析拒绝 | 异域名 / 混合计划号链接被拒 |

记录每项的 API 读回 JSON（**脱敏 token**）。全绿只宣布「本环境链路与 API 可用」。不宣布「装完 = 现网皮」。

---

## 9. 风控契约摘要（新装默认生效，不可关）

完整版：[docs/risk-rules.md](risk-rules.md)。语义以该文件为准；下文只作摘要，不放宽其中任何数字或闸门。

1. **每单只提交一次**；已发出只回读不重发；成功态 = `waiting_review` + `committed=true` + 独立回读。
2. **秒杀只加号不建活动**：无生效活动零新建；拒绝 `schedule` 类 resume。
3. **掉登停写**；**环境未就绪停写**（Android/root/来客/Frida/write_ready 任一未就绪）。Frida 是挂钩/注入工具，用来在模拟器里调用来客原生接口。
4. **连败熔断**：K=3 次 / 15 分钟内连续失败即停写。
5. **限流**：≤6 次/账号·小时；≤20 次/整机·小时；任意两次写间隔 ≥60 秒。
6. **未知不当 0**：平台未返回的状态/价格/库存显示“未知”。
7. **去重**：`request_id` + `business_key`。
8. **探活 ≠ 可写**：心跳在线不得冒充 Android/root/来客/Frida/write_ready。
9. 来客登录只人工；不自动处理验证码/风控弹窗。

读失败最多再读 2 次后进入 `waiting_device`，不提交。自愈连败停手 = 2、每小时不超过 3 次，且禁止触碰 gate/commit 与自动登录。这两条的过线标准以 [risk-rules.md](risk-rules.md) 的 R-A5、R-A6、R-C3 为准。上线逐条对照用 [S5-D组-上线验收表草稿.md](S5-D组-上线验收表草稿.md)（草稿，实跑搁置）。

---

## 10. 故障表

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 服务起不来：`Distinct nonempty … required` | 两个 token 有空值或相同 | 重新生成两个不同 token |
| 服务起不来：`GATEWAY_PUBLIC_ORIGIN is required` | 未填 | 填纯 origin，如 `https://gateway.example.com` |
| 403 `host` | Host 不在允许列表；nginx 未传 `Host $host`；本机直连未带 Host 头 | 校正 `GATEWAY_ALLOWED_HOSTS` 与 nginx |
| 403 `origin` / `origin_required` / `cross_site` | 写操作或登录的 `Origin` 与 `GATEWAY_PUBLIC_ORIGIN` 不一致 | 用公网地址访问；origin 填纯 origin |
| 登录 401/403 但 token 正确 | `GATEWAY_PUBLIC_ORIGIN` 带了 path 或与浏览器地址不一致（http/https、端口） | origin 必须与浏览器地址栏 origin 完全一致 |
| 登录成功但刷新又要登录 | `GATEWAY_COOKIE_PATH` 与前缀不一致；http 下 Secure cookie 不生效 | 设为 `/kaituan/`；全站 https |
| 登录 429 | 同 IP 10 分钟内 ≥10 次 | 等 10 分钟 |
| 静态页 404 / 资源 404 | 访问 `/kaituan` 无尾斜杠；`proxy_pass` 漏尾斜杠 | 按 6.5 补 301 与尾斜杠 |
| 400 `query` | URL 带 `?` 参数 | 网关不支持 query，去掉 |
| Mac probe 401 | `credentials.json` 与 `GATEWAY_WORKER_TOKEN` 不一致 | 重新写入 |
| `Worker credentials must have permission 0600` | 凭证权限过宽 | `chmod 0600` |
| Mac 报 409 `worker_pinned` | `--worker-id` 与 `GATEWAY_WORKER_ID` 或库内已绑定 id 不一致 | Mac 侧改成与网关一致的 id；**本套**新装阶段写错且库为空时，可停服务删空库重建 |
| 网关启动报 `worker_pinned` | `GATEWAY_WORKER_ID` 与已有 `queue.sqlite3` 中绑定的 id 不同 | 改回一致；需要另一个 worker 就**另装一套**（3.4 节） |
| Mac 连接 TLS 错误 | 自签证书 | 换正式证书，或 `--ca-file` 指私有 CA（主机名校验保持开启） |
| probe 报已有实例 | LaunchAgent 已常驻 | 正常；看日志或 `/api/status` |
| 在线但 Android/来客 未就绪，任务不写 | 设计如此（停写） | 按 install-mac-android-runtime 修环境 |
| Frida 附加失败 | Frida（挂钩/注入）未以 root 运行，或 Mac 与设备端版本差太远 | 两端用同一推荐版本再试（参考 16.7.19）；验收仍看能否附加到来客 |
| 秒杀单“无活动”不执行 | 零新建规则 | 先在平台侧有生效活动，再下单 |

---

## 11. 附录：`EXAMPLE_LIVE_ONLY` 现网对照（禁止当默认值）

> 以下仅用于读懂现网/旧文档。**新装不得照抄**任何一个值。

| 项 | 现网值 `EXAMPLE_LIVE_ONLY` | 产品化对应 |
|---|---|---|
| 服务器 IP | `1.12.208.101` | `<GATEWAY_HOST>` 解析到你的服务器 |
| 域名 | `www.zhoukenuan.top` | `gateway.example.com` |
| 目录 | `/opt/uiautomator2-trigger/` | `<APP_DIR>`（示例 `/opt/kaituan-gateway`） |
| systemd 单元 | `uiautomator2-trigger.service`，`User=ubuntu`，端口 `8792` | `<UNIT>` / `<SVC_USER>` / `<PORT>` |
| 路径前缀 | `/kaituan/` | `<PREFIX>`（可沿用 `/kaituan/`） |
| worker-id | `zhongjiawei-mac-native` | `mac-worker-1` |
| 登录 | nginx `auth_request` + site-entry；操作员路径 nginx 写死 `Authorization: Bearer <USER_TOKEN>`；worker 路径 `auth_request off` 透传 | 默认独立登录（第 6.6 节） |
| 部署脚本 | `mac/work/trigger-deploy/deploy_gateway.py`（写死 IP、nginx Bearer 注入、portal 卡片） | 本文第 6 章手工/脚本化步骤 |
| Mac 启动器 | `EXAMPLE_LIVE_ONLY`：`trigger_launch.py` 写死 `--server https://1.12.208.101/kaituan --worker-id zhongjiawei-mac-native`。新装必配自己的值。参数化在 GitHub #4，合入等 Mac 回归书面确认；本 PR 不改该脚本 | 5.6 节 |

---

## 12. 与 `migration/` 的关系

- `migration/` 是历史材料，**不是**产品安装主路径。其中每个 Markdown 顶部都有横幅。安装以本文为准。
- 安卓运行时绿场的权威副本是 [install-mac-android-runtime.md](install-mac-android-runtime.md)。
- 风控硬规则的产品化全文是 [risk-rules.md](risk-rules.md)；第 9 章只是摘要。`migration/风控-迁后验收硬规则清单.md` 保留为历史材料。
- 当前 `main` 没有根目录 `DEPLOY.md`，因此本轮不新增、也不改名任何部署笔记。新人入口不指向它。
- 新人入口顺序：仓库根 [README.md](../README.md) → [README-人类安装.md](README-人类安装.md) → 本文 → [install-mac-android-runtime.md](install-mac-android-runtime.md)。
- 缺口 G1–G18 见 [G-STATUS.md](G-STATUS.md)。
- 口径以 [GitHub issue #2](https://github.com/a192289394-oss/kaituan-seckill/issues/2) 为准。交付链路与 API，不交付现网皮。ALIGN 拷皮挂起，不是合并条件。

---

*本文件不含任何真实密钥；不涉及 push；不修改任何生产环境。*
