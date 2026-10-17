# G1–G18 缺口状态

对照产品化安装缺口（G1–G18）。本表只记状态。

> 目标已按 [GitHub issue #2](https://github.com/a192289394-oss/kaituan-seckill/issues/2) 改定：别的 Mac 跑通「API 或自写前端下单 → Mac 来客（开团路径会用到销帮）执行 → API 读回执」。主执行来客 `com.bytedance.ls.merchant`；销帮 `com.bytedance.lifeservice.crm`。交付链路与 API，不是现网皮。ALIGN 拷皮挂起。不像现网皮**不算**缺口。

状态取值：`open` / `in this PR` / `merged`。`merged` 表示对应改动已在 main（注明 PR）。不再使用「blocked on other PR」：#3 / #4 / #5 已合入。

| # | 缺口 | 状态 | 说明 |
|---|---|---|---|
| G1 | 没有产品化主安装文档 | merged | [GitHub #5](https://github.com/a192289394-oss/kaituan-seckill/pull/5) 已合入 `docs/AI-INSTALL.md`、`docs/README-人类安装.md` |
| G2 | Mac 启动器写死现网 server / worker-id | merged | [GitHub #4](https://github.com/a192289394-oss/kaituan-seckill/pull/4) 已合入。`trigger_launch.py` 读 `KAITUAN_SERVER` / `KAITUAN_WORKER_ID` 或本机 `launch.json`，缺任一值非 0 退出。现网值只留在 `EXAMPLE_LIVE_ONLY` |
| G3 | 仓库内没有 nginx example 文件 | merged | [GitHub #3](https://github.com/a192289394-oss/kaituan-seckill/pull/3) 已合入。样板是 `server/nginx-kaituan.example.conf`；site-entry 仍为 OPTIONAL |
| G4 | 文档默认独立登录 | merged | #5 已合入。默认是网关 `POST /api/login` 与 Bearer。仓内静态页标为 OPTIONAL 调试壳 / 非交付皮。site-entry 仍为 OPTIONAL |
| G5 | `migration/` 喧宾夺主 | merged | #5 已合入。每个 `migration/*.md` 顶部有历史横幅，指向 `docs/AI-INSTALL.md` |
| G6 | 外部依赖无自备清单 | merged | #5 已合入。清单在 AI-INSTALL §7.1 与安卓绿场文档。`catalog.sqlite3` 自备；缺文件则目录为空、不崩溃 |
| G7 | 无空库新装与第二套说明 | merged | #5 已合入。AI-INSTALL §3.3、§8.1 P10 |
| G8 | 根 README 不指向安装文档 | merged | #5 已合入。第一屏是 API 链路、部署单元、三种安装文档链接 |
| G9 | `deploy_gateway.py` 绑定现网 | merged | [GitHub #3](https://github.com/a192289394-oss/kaituan-seckill/pull/3) 已合入。无 `--live-operator`（或 `KAITUAN_LIVE_OPERATOR=1`）时退出码 2。新装走 AI-INSTALL 第 6 章 |
| G10 | 能力契约散落 | merged | AI-INSTALL §4 写成链路与 API 清单（含 `plan` / `authorization` / `inspect`）。验收是 API 读回。不像现网皮不算缺。风控全文为 `docs/risk-rules.md`。随 #5 合入 |
| G11 | worker-id 先到先绑定 | in this PR | 启动时 `GATEWAY_WORKER_ID` 必填，未设置拒绝启动。不再先到先绑定。见 `gateway.env.example` 与 AI-INSTALL §5.1 |
| G12 | systemd 样板路径/用户写死在仓库样板文件 | merged | [GitHub #3](https://github.com/a192289394-oss/kaituan-seckill/pull/3) 已提供参数化 `server/kaituan-gateway.service.example`。本轮补上 `CapabilityBoundingSet=` 与 `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6`（专用用户、ProtectSystem/Home、PrivateTmp、ReadWritePaths 已在样板中） |
| G13 | `*.bak*` 混在部署源 | open | #3/#4/#5 未删除已入库备份。`.gitignore` 的 `*.bak-*` 只管未跟踪文件。留给后续卫生，不在本轮删历史文件 |
| G14 | 网关部署件双份 | in this PR | 唯一源码是 `server/trigger_gateway.py`。已删除 `mac/outputs/trigger_gateway.py` |
| G15 | 运行态文件误当模板 | in this PR | 已从树中删除 `mac/outputs/trigger-worker.json`（`autostart=true`），`.gitignore` 忽略该路径，只留 `trigger-worker.example.json`（`autostart=false`）。启动器找不到该文件以非 0 退出。`merchant-catalog.json` / `merchant-directory.json` 仍在树里，本轮不删 |
| G16 | 无匿名 `/healthz` | open | 可选；本轮不做。探活继续用带凭证的 `GET /api/status` |
| G17 | `autostart` 新装取值无说明 | merged | #5 已合入。AI-INSTALL §5.5：新装建议 `false`。仓内 example 为 `false`；已跟踪的 `autostart=true` 运行态文件已删除 |
| G18 | 离线自测未写入安装流程 | merged | #5 已合入。AI-INSTALL §7.2 将 `mac/work/web_offline_tests.py` 标为可选自检，并写明不等于探活或上线验收 |
