# trigger-deploy（EXAMPLE_LIVE_ONLY）

本目录下的 `deploy_gateway.py`、`remote_check.py`、`current_product_check*.py` 以及相关 `*.json` 均为**现网运维**材料，绑定现网主机 / portal / Bearer 注入。

新人自助安装请走 `docs/AI-INSTALL.md` §6（`server/*.example`），不要运行本目录脚本。若必须对现网执行 `deploy_gateway.py`，须显式加 `--live-operator`（或环境变量 `KAITUAN_LIVE_OPERATOR=1`）。
