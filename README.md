# 开团与秒杀（kaituan-seckill）

酒店抖音预售券：给达人/团长开团、加秒杀的自动化与工作台。

## 目录

- `server/` — 服务器网关与静态工作台（对应现网 `/opt/uiautomator2-trigger/`，入口 `/kaituan/`）
- `mac/` — Mac 侧 BlueStacks / 执行与部署相关源码（已瘦身）
- `migration/` — 迁移说明与脚本
- `mac-EXCLUDED.md` — Mac 侧未纳入仓库的大目录说明

## 安全

仓库**不包含** `gateway.env`、凭证文件、队列库等运行时密钥与数据。部署时在服务器/本机单独放置。

## 协作

私有仓库。需要一起改的人由仓库 Owner 在 **Settings → Collaborators** 邀请 GitHub 账号。
