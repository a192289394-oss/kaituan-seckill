# Mac 执行侧 · 迁入 dashboard 准备注意点

换一台 Mac 重装执行机，看 [DEPLOY.md](../DEPLOY.md)。下文只列迁 dashboard 域名时要改的网关地址。

状态：先准备、不真迁。执行机仍是 macOS（BlueStacks + 来客）。

## 现状（2026-10-16）

| 项 | 值 |
|---|---|
| LaunchAgent | `cn.keyframe.web-kaituan` |
| 入口 | `outputs/trigger_launch.py run`（caffeinate 保活） |
| 网关地址 | 写死在 `trigger_launch.py`：`--server https://1.12.208.101/kaituan` |
| worker-id | `zhongjiawei-mac-native` |
| 凭证 | `work/trigger-worker/credentials.json`（权限 0600，不进 plist；环境变量 `GATEWAY_WORKER_TOKEN`） |
| 配置 | `outputs/trigger-worker.json` |
| 目录库 | `work/trigger-worker/catalog.sqlite3` |
| 日志 | `work/trigger-worker/stdout.log` / `stderr.log` |

业务硬规则（拒建、只提交一次、掉登停写、自愈、限流）在 Mac 本地执行逻辑里，**迁域名不应重写**，只改连哪台网关。

## 迁站必须改的

1. **网关 base URL**：`trigger_launch.py` 里 `--server` → 新前缀（最终路径等架构钉死，例如挂在 `https://dashboard.keyframe-gz.com/...`）。
2. **改前备份**：`trigger_launch.py`、LaunchAgent plist、`credentials.json`（不打印 token）。
3. **鉴权**：新域名 HTTPS 证书、worker token 是否仍被网关认；迁后先只看心跳/顶栏闸，确认可写再放业务。
4. **接口路径**：claim / heartbeat / gate / report 若只是换域名或子路径前缀，Mac 只改 base；若路径形态变了，要同步改 worker 客户端，不能 silently 404。

## 迁站不用动的

- BlueStacks Tiramisu64、adb `127.0.0.1:5555`、frida-server、来客登录态
- `residency_heal` 自愈、session 巡检、秒杀拒建、只提交一次与回读
- 本机 `work/android-sdk/platform-tools` PATH（plist 已配）

## 建议切换顺序

1. 新地址可心跳（worker probe/heartbeat 绿）
2. kickstart LaunchAgent，worker 指新 `--server`
3. 旧站停收单（避免双写）
4. 顶栏确认可写后再试一单只读/开团（按风控清单）

## 回滚

把 `--server` 改回 `https://1.12.208.101/kaituan` 并 kickstart 即可打回；保留备份文件。

## 交给总文档的一句话

Mac 侧变更点 = **网关 URL +（如有）token/路径前缀**；执行硬规则代码不因迁站重写。新路径钉死后可再出「改哪几行」补丁清单。
