# G1–G18 缺口状态

对照产品化安装缺口（G1–G18）。本表只记状态，不改运行代码。

> 目标已按 [GitHub issue #2](https://github.com/a192289394-oss/kaituan-seckill/issues/2) 改定：别的 Mac 跑通「API 或自写前端下单 → Mac 来客（开团路径会用到销帮）执行 → API 读回执」。主执行来客 `com.bytedance.ls.merchant`；销帮 `com.bytedance.lifeservice.crm`。交付链路与 API，不是现网皮。ALIGN 拷皮挂起。不像现网皮**不算**缺口。

状态取值：`open` / `in this PR` / `blocked on other PR`。

| # | 缺口 | 状态 | 说明 |
|---|---|---|---|
| G1 | 没有产品化主安装文档 | in this PR | `docs/AI-INSTALL.md`、`docs/README-人类安装.md` |
| G2 | Mac 启动器写死现网 server / worker-id | blocked on other PR | **新装必配**自己的 server 与 worker-id。参数化在 [GitHub #4](https://github.com/a192289394-oss/kaituan-seckill/pull/4)（原 PR-3），**合入等 Mac 回归书面确认**。本 PR 不改 `trigger_launch.py`。现网值只在 `EXAMPLE_LIVE_ONLY` |
| G3 | 仓库内没有 nginx example 文件 | blocked on other PR | 样板文件属后续 PR。AI-INSTALL §6.5 已给出独立登录（不注入 Bearer）的 nginx 正文 |
| G4 | 文档默认独立登录 | in this PR | 默认是网关 `POST /api/login` 与 Bearer。仓内静态页标为 OPTIONAL 调试壳 / 非交付皮。site-entry 仍为 OPTIONAL |
| G5 | `migration/` 喧宾夺主 | in this PR | 每个 `migration/*.md` 顶部加了历史横幅，指向 `docs/AI-INSTALL.md` |
| G6 | 外部依赖无自备清单 | in this PR | 清单写在 AI-INSTALL §7.1 与安卓绿场文档。`catalog.sqlite3` 按已定口径：自备同结构种子库；缺文件则目录为空、不崩溃；仓库无生成脚本；本轮不做导入 |
| G7 | 无空库新装与第二套说明 | in this PR | AI-INSTALL §3.3、§8.1 P10 |
| G8 | 根 README 不指向安装文档 | in this PR | 第一屏是 API 链路、部署单元、三种安装文档链接。不把现网皮当入口 |
| G9 | `deploy_gateway.py` 绑定现网 | blocked on other PR | 防误跑与横幅属后续 PR。本 PR 不改该脚本；AI-INSTALL 将其标为 `EXAMPLE_LIVE_ONLY`，新装走第 6 章 |
| G10 | 能力契约散落 | in this PR | AI-INSTALL §4 写成链路与 API 清单（含 `plan` / `authorization` / `inspect`）。验收是 API 读回。不像现网皮不算缺。风控全文为 `docs/risk-rules.md` |
| G11 | worker-id 先到先绑定未写进文档 | in this PR | AI-INSTALL §5.1、§10 |
| G12 | systemd 样板路径/用户写死在仓库样板文件 | blocked on other PR | `server/kaituan-gateway.service.example` 属后续 PR。AI-INSTALL §6.4 已给参数化单元正文 |
| G13 | `*.bak*` 混在部署源 | blocked on other PR | 仓库卫生，本 PR 不删文件 |
| G14 | 网关部署件双份 | blocked on other PR | 约定唯一来源属后续 PR |
| G15 | 运行态文件误当模板 | blocked on other PR | 跟踪与忽略规则的收口属后续卫生 PR。本 PR 只在文档里禁止拷贝 `gateway.env`、凭证、`queue.sqlite3`、`worker.sqlite3` |
| G16 | 无匿名 `/healthz` | open | 可选；本轮不做。探活继续用带凭证的 `GET /api/status` |
| G17 | `autostart` 新装取值无说明 | in this PR | AI-INSTALL §5.5：新装建议 `false`，环境稳定后再评估 |
| G18 | 离线自测未写入安装流程 | in this PR | AI-INSTALL §7.2 将 `mac/work/web_offline_tests.py` 标为可选自检，并写明不等于探活或上线验收 |
