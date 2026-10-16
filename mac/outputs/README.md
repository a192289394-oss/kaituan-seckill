# 开团与秒杀网页工作台

入口与登录见 docs/AI-INSTALL.md；默认独立登录。服务器仅持久收单、审批、审计；本机 Mac 出站领取任务，通过当前来客 App 的正常账号和网络上下文执行。

## 配置

`trigger_launch.py` 在 `run`、`probe`、`once` 时读取网关地址和 worker-id，不把它们写进 LaunchAgent plist。

读取优先级：

1. 环境变量 `KAITUAN_SERVER`、`KAITUAN_WORKER_ID`。可选 `KAITUAN_CA_FILE`，有值时传给 `--ca-file`。
2. `mac/work/trigger-worker/launch.json`，形如 `{"server":"...","worker_id":"..."}`。示例见 `launch.example.json`。

缺 `server` 或 `worker_id` 任一值就以非 0 退出，并提示 docs/AI-INSTALL.md §7。不会回落到任何预置地址或 worker-id。`server` 必须以 `https://` 开头且不能有尾斜杠。`worker_id` 须与网关 `GATEWAY_WORKER_ID` 一致，否则网关返回 409 `worker_pinned`。

`install` 只注册 LaunchAgent 去执行 `run`。plist 不写入 server、worker-id 或 token。LaunchAgent 读不到交互 shell 里临时 export 的变量；常驻运行请把值写在本机 `launch.json`（建议权限 0600，只放在本机，不要提交）。

本机执行参数在 `trigger-worker.json`。键说明见 `trigger-worker.example.md`。样例 `trigger-worker.example.json` 中 `autostart` 为 `false`，`adb_endpoint` 为 `127.0.0.1:5555`，`instance` 为 `Tiramisu64`。该文件不含聊天、机器人或通知配置。

## 运行结构

- `trigger_gateway.py`：服务器 SQLite 队列，90 秒租约，固定单一 Mac，提交前两闸门；收单、补参、报告均幂等。页面把“Mac 收单在线”和 Android、root、来客 App、原生接口分别显示，不能再用心跳冒充执行环境可用。
- `trigger_worker.py` / `execution_store.py`：本机独立任务库、原生一次提交日志、报告重发、取消隔离、独立心跳和 600 秒 watchdog。心跳每 60 秒做一次只读、限时的运行环境探测，不连接设备、不附加 Frida、不切商家、不读取业务数据。
- `web_activity.py`：既有授权查重；过期模板预览；用户明确确认新档期后只授指定账号，保留商品价格及每达人库存。当前候选商品会完整翻页读取，平台未返回的禁选状态和价格语义保持“未知”，不会推成可用库存或实际成交价。
- `native_plan*`：商品 POI 反查门店、主计划及草稿条款冻结、一次确认、独立双轮复核。
- `trigger-ui/`：网页任务列表、待处理、证据、新档期表单。表单打开暂停轮询，手动刷新保留未变修订的草稿。
- `trigger_launch.py`：本机 LaunchAgent `cn.keyframe.web-kaituan`。凭证只从本机权限 0600 的文件读取，不进入 plist 或 URL。地址和 worker-id 在 `run` 时读取，不写入 plist。

## 使用与验证

粘贴开团计划或填写精确酒店与抖音号，默认只读。允许执行需勾选，或在原单明确确认。酒店名优先要求目录中的精确名称；仅当原输入零命中时，才可移除末尾一个 `秒杀` 或 `开团` 操作词，并且仍须唯一精确命中。相似店名和包含匹配不会自动放行。无生效秒杀模板时展示旧商品、原价、每达人库存；用户填写新档期后继续同一任务。北京时间明确换算为 epoch 秒。

开团入口支持完整的来客下载分享链接、`snssdk299467://webview` 深链、官方开团详情 URL 和 18–20 位纯计划号。会沿官方 `redirect_url` 与 `url` 层逐层解码，并消除复制链接时插入的空白与换行；计划号保持字符串精度。不同计划号混入同一链接、非官方域名、异常编码和重复嵌套入口均拒绝提交。

```sh
.venv/bin/python -B work/web_offline_tests.py
.venv/bin/python outputs/trigger_launch.py probe
```

运行常驻时 probe 会因单机全局锁拒绝第二实例；可直接读服务器状态与本机 SQLite。不能将 Mac 心跳、Android 在线或 HTTP 200 视作业务成功。提交边界之后只读复核，取消不承诺撤销已发送请求，平台业务结果以独立读取为准。

EXAMPLE_LIVE_ONLY：下面描述的是一套已部署环境的服务名、监听地址和公网路径，不是新装样板。新装见 docs/AI-INSTALL.md。

服务器服务 `uiautomator2-trigger.service`，只监听 `127.0.0.1:8792`，公网经 HTTPS `/kaituan/`。重启和主站访问验证应检查实际内容，不能只看 HTTP 200。工作状态在 `work/trigger-worker/worker.sqlite3`，凭证与登录态不打包。

仍需持续运行证据才可声称 24h 稳定。大酒店全量活动详情读取可能触发 600 秒 watchdog，应实测后优化，不能把 8 活动样本扩成所有酒店覆盖。

## 历史

目录仅一次导入酒店映射；从未复制旧任务、旧事件和回执。旧消息机器人、迁移包、备份、测试、依赖与服务器服务均已删除；旧主桥与旧 dashboard LaunchAgent 已移除，只保留网页入口和当前原生执行链路。
