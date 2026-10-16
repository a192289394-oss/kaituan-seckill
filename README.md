> **合前阻塞：** 本文描述的是**目标对齐**（安装骨架与目标能力清单）。**仓↔现网对齐完成前，不宣称「装完 = 现网能力」**。是否已对齐，以 **[GitHub issue #2](https://github.com/a192289394-oss/kaituan-seckill/issues/2)** 的哈希比对 / 验收结论为准。

# 开团与秒杀（kaituan-seckill）

**网页下单 → Mac 来客执行 → 回网页。**

一套 = **1 个 gateway（服务器）+ 1 个 Mac worker（执行机）**。默认用网关自带的登录面板进入。要互不影响的第二套，就再装一套。

## 安装

- [给人看的一页](docs/README-人类安装.md)
- [AI 可读安装说明书](docs/AI-INSTALL.md)
- [Mac 安卓运行时绿场](docs/install-mac-android-runtime.md)

`migration/` 是历史材料，不是安装路径。

## 目录

- `server/` — 网关与静态工作台
- `mac/` — Mac 侧执行源码
- `docs/` — 产品安装文档
- `migration/` — 历史材料
- `mac-EXCLUDED.md` — Mac 侧未纳入仓库的大目录说明

## 安全

仓库**不包含** `gateway.env`、凭证文件、队列库等运行时密钥与数据。新装时在服务器和 Mac 上单独生成。

## 协作

私有仓库。需要一起改的人由仓库 Owner 在 **Settings → Collaborators** 邀请 GitHub 账号。
