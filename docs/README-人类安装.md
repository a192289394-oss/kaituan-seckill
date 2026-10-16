> **交付说明：** 交付的是**链路与 API（协议与执行能力：queue / claim / gate / report、来客执行、API 回执）**，不是现网皮。ALIGN 拷皮挂起，不是合并必做。口径以 **[GitHub issue #2](https://github.com/a192289394-oss/kaituan-seckill/issues/2)** 为准。不宣称「装完 = 现网能力」或「装完 = 现网皮」。

# 开团 / 秒杀自动化 · 一页安装说明（给人看的）

> 想看完整技术细节或让 AI 帮你装：看同目录 [AI-INSTALL.md](AI-INSTALL.md)。
> 本页没有任何真实密码。看到 `changeme-…`、`gateway.example.com` 都是示例，要换成你自己的。
> 操作员 API 以 [GitHub issue #2](https://github.com/a192289394-oss/kaituan-seckill/issues/2) 为准，字段细节见 AI-INSTALL。

## 它是干什么的

**API 或自写前端下单 → Mac 来客（开团路径会用到销帮）执行 → API 读回执。**

你用自己的页面或脚本向网关下单。你的 Mac 把单子领走，在模拟器里的「来客」里执行；开团路径还会用到「销帮」。做完用 API 读状态和审计回执。页面长得像不像现网工作台，**不算**装好。

## 你要装的是“一套”

**一套 = 1 个 gateway（收单）+ 1 台 Mac（干活）。**

- 网关：收 API 下单，记下结果。仓里自带的网页只是 **OPTIONAL 调试壳**，不是要交给别人的皮。
- Mac：装一个**能拿到 root** 的安卓模拟器，人工登录来客和销帮，真正去执行。
- 想要两套互不影响的环境？**就再装一套**（另一套网关入口 + 另一台 Mac），两套各用各的密码和名字。

对接可以二选一，接口一样：

| 方式 | 入口 |
|---|---|
| 本地 | `http://127.0.0.1:<PORT>`。**端口以这套部署单元的 systemd `--port` 为准。** 产品化示例常用 `8792`；`trigger_gateway.py` 源码缺省是 `8793`。二者都不是唯一正确端口 |
| 服务器 | `https://你的域名/kaituan/api/...`（前缀样板是 `/kaituan/`，可以改，但要和 cookie、Mac 地址一起改） |

操作员只用这些：登录、退出、看状态、看任务、下单、看某一单的审计、取消 / 恢复 / 重试。Mac 专用的 `/api/worker/*` **不要**写进你的前端。

下单时的 `kind`：`plan` = 开团，`authorization` = 秒杀加号，`inspect` = 只读。

## 开始前准备好

| 东西 | 说明 |
|---|---|
| 一台 Linux 云服务器（Ubuntu），或先在本机环回联调 | 能跑 python3；要给别人远程用时再加 nginx 和 HTTPS |
| 一个域名 + HTTPS 证书 | 只在走服务器对接时需要，例如 `gateway.example.com` |
| 一台 Mac | 长期开机、不休眠 |
| 能 root 的安卓模拟器 | **硬条件**是 adb 连上，并且 `su -c id` 能看到 `uid=0`。BlueStacks、实例名 `Tiramisu64` 只是推荐示例，不是必须 |
| 来客 App | 包名 `com.bytedance.ls.merchant`。自己准备，**人工登录** |
| 销帮 App | 包名 `com.bytedance.lifeservice.crm`。开团路径会用到，**也要人工登录**。主执行仍是来客 |
| Frida | 挂钩/注入工具，用来在模拟器里调用来客原生接口。自己准备。推荐 Mac 与模拟器里的 frida-server 同版本（参考 16.7.19），版本号不是唯一门槛 |
| 酒店目录 `catalog.sqlite3` | 酒店目录种子库（表 `merchant_catalog`）。自己准备一份**同结构**的 sqlite：业务导出，或从已有环境拷贝这份种子。worker 启动时只读拷进 `worker.sqlite3` 一次；没有这个文件则目录为空、不会崩。仓库里没有从 `merchant-*.json` 生成它的脚本，本轮也不做导入功能 |

## 六步装好

1. **生成两把钥匙**（在任意电脑上跑两次，得到两串不一样的字符）：
   `python3 -c 'import secrets;print(secrets.token_urlsafe(32))'`
   第一串叫「操作员钥匙」，第二串叫「Mac 干活钥匙」。**两把必须不一样**，谁都别发到群里。
2. **装网关**：按 [AI-INSTALL.md](AI-INSTALL.md) 第 6 章。本机联调听 `127.0.0.1:<PORT>`，这个端口就是 systemd 里的 `--port`。产品化示例常用 `8792`；源码不写 `--port` 时缺省是 `8793`。要远程再用 nginx，并转到同一个端口。默认用网关自己的登录接口，不必接别的网站登录。
3. **用 API 试登录**：按第 6 章的 curl 示例（假 token）确认能拿到 `gateway_session`。仓内静态页若打开了，只当调试壳，不拿它的样子当验收。
4. **装 Mac 的模拟器**：按 [install-mac-android-runtime.md](install-mac-android-runtime.md)：模拟器 → adb → root → Frida（挂钩/注入）→ 装来客和销帮 → **两边都手动登录**。
5. **装 Mac 干活程序**：按 [AI-INSTALL.md](AI-INSTALL.md) 第 7 章。凭证权限 0600。服务器地址和 worker 名字要和网关一致（示例 `https://你的域名/kaituan` 与 `mac-worker-1`）。启动器里写死的现网地址是样板，新装必须改成自己的；参数化合入等 Mac 回归书面确认（GitHub #4），本说明不改那份代码。若有酒店目录种子，放到 `work/trigger-worker/catalog.sqlite3`；没有也能启动，目录为空。
6. **先试连接，再常驻**：先跑 `probe`，用 `GET /api/status` 看到 Mac 在线；再跑 `install` 让它开机自动运行。在线还不等于能写。

## 怎么算“链路通了”

用操作员 API 走通「下单 → Mac 执行 → `status` / `audit` 读回」就是链路通。长得像不像现网工作台**不算**缺。

- **连上了**：未登录调 `status` 会被拒绝；登录后能读到 worker 在线。
- **能执行**：Android / root / 来客各自就绪（不能只看心跳）。先下一张 `inspect` 只读单；再各走一张 `plan` 开团、一张 `authorization` 秒杀加号，各**只提交一次**，并用 audit 读回。

## 系统自带的安全刹车（不能关）

完整规则见同目录 [risk-rules.md](risk-rules.md)。下面是给人看的摘要，不代替那份清单。

- 每张单只提交一次，已提交的只查不重发。
- 秒杀只往**已有**活动里加人，没有活动**绝不新建**。
- 来客掉登录、模拟器没准备好 → 自动停，不乱写。销帮要事先人工登录，也不要自动重登。
- 连续失败 3 次（15 分钟内）→ 停。
- 每个账号每小时最多 6 次，整台 Mac 每小时最多 20 次，两次之间至少隔 60 秒。
- 不知道的数据显示「未知」，不会当成 0。
- 「Mac 在线」≠「能干活」。

## 常见问题

| 遇到 | 先试 |
|---|---|
| API 登录总失败 | 钥匙复制多了空格？`Origin` 要和 `gateway.env` 里的地址一致（https 时用 https）。 |
| 登录后一刷新又要登录 | 走网页调试壳时，`GATEWAY_COOKIE_PATH` 要和前缀一致，并且全程用 https。直接用 Bearer 调 API 不依赖这张 cookie。 |
| Mac 一直不在线 | Mac 凭证里的钥匙和服务器「Mac 干活钥匙」是否一致；凭证文件权限是否 0600。 |
| Mac 报 bound to a different worker | Mac 名字和服务器里 `GATEWAY_WORKER_ID` 不一致，改成一样。 |
| Mac 在线但单子不动 | 看 status 里安卓 / root / 来客是否各自就绪；来客是否掉登录；开团单还要确认销帮已人工登录。 |
| 秒杀单说没有活动 | 正常保护：先在平台上有生效活动再下 `authorization`。 |

## 不要做的事

- 不要从别人的机器上拷 `gateway.env`、凭证、`queue.sqlite3`、`worker.sqlite3`、来客或销帮登录态来用——这些每套都**自己新生成**。酒店目录种子 `catalog.sqlite3` 按上面的表自备同结构文件。
- 不要两套环境共用一个 Mac 名字或同一把钥匙。
- 不要让程序自动登录来客或销帮。
- 不要把仓内静态页或现网皮拷去当交付物。
- 不要照抄文档附录里标着 `EXAMPLE_LIVE_ONLY` 的 IP、域名、Mac 名字——那是别人的现网环境样板。
