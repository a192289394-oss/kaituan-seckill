# 开团与秒杀（kaituan-seckill）

酒店抖音预售券：给达人/团长开团、加秒杀的自动化与工作台。

## 目录

- `server/` — 服务器网关与静态工作台（部署到 `/opt/uiautomator2-trigger/`，入口路径 `/kaituan/`）
- `mac/` — Mac 侧 BlueStacks / 执行与部署相关源码（已瘦身）
- `migration/` — 迁入经营台 dashboard 的准备材料（与换电脑不是同一件事）
- `mac-EXCLUDED.md` — Mac 侧未纳入仓库的大目录说明

## 安全

仓库**不包含** `gateway.env`、凭证文件、队列库等运行时密钥与数据。部署时在服务器/本机单独放置。

## 换电脑 / 部署

把现有这一套换到另一台电脑上继续维护或运行（服务器和 Mac 一起换），按 [DEPLOY.md](DEPLOY.md) 做。先在新服务器放好网关、`gateway.env` 和队列库，新入口能登录后，再把 Mac 的 `--server` 指到新地址，并停掉旧服务器与旧 Mac。

## 协作

私有仓库。需要一起改的人由仓库 Owner 在 **Settings → Collaborators** 邀请 GitHub 账号。
