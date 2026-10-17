> **交付说明：** 交付的是**链路与 API（协议与执行能力：queue / claim / gate / report、来客执行、API 回执）**，不是现网皮。ALIGN 拷皮挂起，不是合并必做。口径以 **[GitHub issue #2](https://github.com/a192289394-oss/kaituan-seckill/issues/2)** 为准。不宣称「装完 = 现网能力」或「装完 = 现网皮」。

# 开团与秒杀（kaituan-seckill）

**API 或自写前端下单 → Mac 来客（开团路径会用到销帮）执行 → API 读回执。**

主执行是来客 `com.bytedance.ls.merchant`。开团路径会用到销帮 `com.bytedance.lifeservice.crm`。

目的：让**别的 Mac**跑通这条链路。主交付 = 说明文档 + 可运行源码 + 标准接口（对方自写前端）。一套 = **1 个 gateway + 1 个 Mac worker**。要互不影响的第二套，就再装一套。

对接二选一，契约相同：本地 `http://127.0.0.1:<PORT>`，或服务器 `https://host/<前缀>/api/...`（样板前缀 `/kaituan/`）。

**端口规则：** 一套部署只有一个监听端口，就是该套 systemd 单元里的 `--port <PORT>`。nginx `proxy_pass` 必须转到同一个 `<PORT>`。样板里的 `8792` 只是这个 `<PORT>` 的示例值。`server/trigger_gateway.py` 不写 `--port` 时源码缺省监听 `8793`；只有 systemd 也写成 `8793`，nginx 才能指到 `8793`。

`/api/worker/*` 不对前端。仓内静态页是 **OPTIONAL 调试壳 / 非交付皮**。网关唯一源码是 `server/trigger_gateway.py`。

## 安装

- [给人看的一页](docs/README-人类安装.md)
- [AI 可读安装说明书](docs/AI-INSTALL.md)
- [Mac 安卓运行时绿场](docs/install-mac-android-runtime.md)

`migration/` 是历史材料，不是安装路径。

## 目录

- `server/` — 网关与可选调试静态页（非交付皮）
- `mac/` — Mac 侧执行源码
- `docs/` — 产品安装文档
- `migration/` — 历史材料
- `mac-EXCLUDED.md` — Mac 侧未纳入仓库的大目录说明

## 安全

仓库**不包含** `gateway.env`、凭证文件、队列库等运行时密钥与数据。新装时在服务器和 Mac 上单独生成。

## 协作

私有仓库。需要一起改的人由仓库 Owner 在 **Settings → Collaborators** 邀请 GitHub 账号。
