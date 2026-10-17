# trigger-worker.json 配置键

样例文件是 `trigger-worker.example.json`。这里只解释本机执行配置，不含网关地址、worker-id 或凭证。地址和 worker-id 见 `launch.example.json`，安装步骤见 docs/AI-INSTALL.md §7。

新装时复制样例为 `mac/outputs/trigger-worker.json`，再按本机情况修改。样例里的 `autostart` 是 `false`。

## execution_max_age_seconds

任务自创建起允许发送的最长秒数。worker 在提交前检查当前时间与任务创建时间之差是否落在 `0` 到该值之间；超出则拒绝发送。样例为 `86400`（24 小时）。未填写时同样按 `86400` 秒处理。必须是有限正数。

## android_device

- `backend`：`bluestacks`。
- `execution_backend`：`native_api`。
- `adb_endpoint`：`127.0.0.1:5555`。worker 只接受本机回环 `127.0.0.1` 上的端口（1024–65535）。
- `instance`：`Tiramisu64`。未填写时也使用该实例名。
- `autostart`：新装默认 `false`。为 `false` 时，执行前不会自行拉起模拟器。环境稳定后再评估是否改为 `true`。心跳探测不因该键去连接设备。

## pc_activity

- `allow_authorization_copy`：为 `true` 时允许复制已有授权范围。该键不打开写入。
