# 当前项目：开团与秒杀纯网页入口

先读 `outputs/README.md`，再按模块查源码/测试。当前服务器入口 `https://1.12.208.101/kaituan/`，Mac `cn.keyframe.web-kaituan` 执行。新主运行模块为 `trigger_gateway.py`、`trigger_worker.py`、`execution_store.py`、`web_activity.py` 及 native 模块。

本项目只保留网页入口，不包含聊天机器人、消息收单或群通知链路。不要从历史材料恢复旧入口、旧事件或旧任务；当前行为只以 `outputs/README.md`、现行源码、离线回归和线上只读回读为准。

真实账号、原生登录与凭证在本机；`work/` 为私有中间证据，不上传或打包。新增商品/价格/库存/档期以用户明确授权为准。商家、计划、商品、草稿、账号必须核验；提交许可持久消费后只读复核，不得重复同意或保存。离线测试通过、服务在线、平台已保存与实际当前生效分别报告。

回归入口 `.venv/bin/python -B work/web_offline_tests.py`，只覆盖纯网页/原生当前路径。UI 检查包含桌面/手机及真实任务读回。持续 24h 和高活动量性能未有充分实测，禁止扩大战果。
