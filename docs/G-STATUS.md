# G1–G18 缺口状态

对照产品化安装缺口（G1–G18）。本表只记状态，不改运行代码。

状态取值：`open` / `in this PR` / `blocked on other PR`。

| # | 缺口 | 状态 | 说明 |
|---|---|---|---|
| G1 | 没有产品化主安装文档 | in this PR | `docs/AI-INSTALL.md`、`docs/README-人类安装.md` |
| G2 | Mac 启动器写死现网 server / worker-id | blocked on other PR | 启动器参数化；本 PR 不改 `trigger_launch.py`。文档只在 `EXAMPLE_LIVE_ONLY` 附录对照，并要求新装改本机副本、不提交 |
| G3 | 仓库内没有 nginx example 文件 | blocked on other PR | 样板文件属后续 PR。AI-INSTALL §6.5 已给出独立登录（不注入 Bearer）的 nginx 正文 |
| G4 | 文档默认独立登录 | in this PR | 根 README、人话一页、AI-INSTALL 均以网关登录面板为默认。site-entry 标为 OPTIONAL |
| G5 | `migration/` 喧宾夺主 | in this PR | 每个 `migration/*.md` 顶部加了历史横幅，指向 `docs/AI-INSTALL.md` |
| G6 | 外部依赖无自备清单 | in this PR | 清单写在 AI-INSTALL §7.1 与安卓绿场文档。`catalog.sqlite3` 按已定口径：自备同结构种子库；缺文件则目录为空、不崩溃；仓库无生成脚本；本轮不做导入 |
| G7 | 无空库新装与第二套说明 | in this PR | AI-INSTALL §3.3、§8.1 P10 |
| G8 | 根 README 不指向安装文档 | in this PR | 第一屏为一句话、部署单元、三个安装链接 |
| G9 | `deploy_gateway.py` 绑定现网 | blocked on other PR | 防误跑与横幅属后续 PR。本 PR 不改该脚本；AI-INSTALL 将其标为 `EXAMPLE_LIVE_ONLY`，新装走第 6 章 |
| G10 | 能力契约散落 | in this PR | 以 AI-INSTALL §4 为唯一能力契约，不另建契约文件。风控全文为 `docs/risk-rules.md` |
| G11 | worker-id 先到先绑定未写进文档 | in this PR | AI-INSTALL §5.1、§10 |
| G12 | systemd 样板路径/用户写死在仓库样板文件 | blocked on other PR | `server/kaituan-gateway.service.example` 属后续 PR。AI-INSTALL §6.4 已给参数化单元正文 |
| G13 | `*.bak*` 混在部署源 | blocked on other PR | 仓库卫生，本 PR 不删文件 |
| G14 | 网关部署件双份 | blocked on other PR | 约定唯一来源属后续 PR |
| G15 | 运行态文件误当模板 | blocked on other PR | 跟踪与忽略规则的收口属后续卫生 PR。本 PR 只在文档里禁止拷贝 `gateway.env`、凭证、`queue.sqlite3`、`worker.sqlite3` |
| G16 | 无匿名 `/healthz` | open | 可选；本轮不做。探活继续用带凭证的 `GET /api/status` |
| G17 | `autostart` 新装取值无说明 | in this PR | AI-INSTALL §5.5：新装建议 `false`，环境稳定后再评估 |
| G18 | 离线自测未写入安装流程 | in this PR | AI-INSTALL §7.2 将 `mac/work/web_offline_tests.py` 标为可选自检，并写明不等于探活或上线验收 |
