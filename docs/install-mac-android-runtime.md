# Mac 安卓执行运行时 · 自助安装清单

> 上级文档：[docs/AI-INSTALL.md](AI-INSTALL.md) §7（Mac 安装）。本文只讲安卓运行时绿场；网关、登录、队列、酒店目录种子以该文 §5.8 / §7 为准。

日期：2026-10-16  
对象：任意新环境从零装一套，能力与产品设计一致。  
范围：BlueStacks（Tiramisu64）/ ADB / root / Frida / 来客人工登录与身份核验。  
不在本文：搭 gateway、改服务器、发密码；网关地址与 worker token **安装时填自己的**。

仓库：`https://github.com/a192289394-oss/kaituan-seckill`，工作根 `mac/`  
本文路径：`docs/install-mac-android-runtime.md`（安卓绿场权威副本）。

---

## 0. 产品化原则（先读再动手）

- [ ] **一套部署 = 1 个 gateway + 1 台 Mac 上的一个 worker**。不要让两台机器抢同一个 worker 身份。需要另一套互不影响的环境时，按上级文档再装一套，不在本绿场清单里加第二个 worker。
- [ ] 本清单只装 **模拟器运行时绿场**。网关 / 网页 / 队列在服务器侧另装；本机只做出站领取任务。
- [ ] **网关 base URL、worker token 安装时自填**（见附录样板）。本文不写死某一台生产机。
- [ ] 来客登录、商家账号 **只人工完成**；禁止脚本自动登录、自动点「同意」、清数据刷登录。
- [ ] BlueStacks 大版本更新可能冲掉 root / 系统镜像；更新后必须重新跑本文验收，不能信旧勾选。
- [ ] 绿场阶段只做探活与身份只读；**不要**在未完成配置与风控验收前对生产商家做开团/秒杀写入。

建议总顺序：

1. 装 BlueStacks 实例 → 开 ADB → 做 root → 对齐 Frida → 装来客并人工登录  
2. 拉 `mac/` 代码、建 venv、填自己的网关 URL 与 token（另册可补 worker/LaunchAgent）  
3. 启动 worker 后，在**你的**网页工作台看探活再放业务  

---

## 1. BlueStacks（实例名必须是 Tiramisu64）

目标：本机有 Android 13 arm64 实例 `Tiramisu64`，能长期开着。

- [ ] 安装 BlueStacks（需能创建 **Tiramisu64 / Android 13 / arm64**；历史环境用过 Air `5.21.x`，以你本机可创建的实例为准）。
- [ ] 安装路径期望：`/Applications/BlueStacks.app`（代码拉起用  
  `/Applications/BlueStacks.app/Contents/MacOS/BlueStacks --instance Tiramisu64`）。
- [ ] 创建并使用实例名 **`Tiramisu64`**（与 `trigger-worker.json` 里 `android_device.instance` 一致）。
- [ ] 关掉会卡死初始化的「有可用更新」之类弹窗（只点「稍后 / 关闭」，不要点「立即更新」挡着桌面）。
- [ ] 能正常进 Android 桌面。

**验收**

- [ ] 启动：`/Applications/BlueStacks.app/Contents/MacOS/BlueStacks --instance Tiramisu64`
- [ ] 桌面可见，不再停在 Initializing。

---

## 2. ADB：固定本机环回 `127.0.0.1:5555`

目标：本机 adb 只连这一台模拟器；serial 必须是环回地址（不要混 USB 真机）。

- [ ] 准备 platform-tools（推荐放在 `mac/work/android-sdk/platform-tools/adb`；LaunchAgent 的 PATH 通常指这里）。
- [ ] 打开 BlueStacks 的 ADB 访问；端口落到 **5555**（配置键名常见：`bst.enable_adb_access=1`、`status.adb_port=5555`，以本机 `bluestacks.conf` 为准）。
- [ ] 连接：

```sh
adb connect 127.0.0.1:5555
adb -s 127.0.0.1:5555 get-state
adb -s 127.0.0.1:5555 shell getprop sys.boot_completed
```

**验收（必须全过）**

- [ ] `get-state` 输出正好是 `device`
- [ ] `sys.boot_completed` 输出正好是 `1`
- [ ] `adb devices` 里本部署只认 `127.0.0.1:5555`

本地配置对齐（装 worker 时写入；不要抄别人的 token）：

```json
"android_device": {
  "backend": "bluestacks",
  "execution_backend": "native_api",
  "adb_endpoint": "127.0.0.1:5555",
  "instance": "Tiramisu64",
  "autostart": true
}
```

`serial` 必须与 `adb_endpoint` 同为 `127.0.0.1:5555`。

---

## 3. Root：安装 + 验收 `uid=0`

目标：模拟器里有可用的 `su`，`su -c id` 能看到 root。  
**业务代码不会替你改镜像**；root 必须在绿场阶段人工做好。

推荐做法（先停实例再改盘）：

1. **完全退出** BlueStacks（不要在实例运行时换系统盘）。
2. 备份：至少备份  
   `/Applications/BlueStacks.app/Contents/img/Root.qcow2`、  
   当前实例 `data.qcow2`、相关 `initrd_hvf.img`、`bluestacks.conf`。  
   备份目录权限建议 `0700`；含账号数据时不要打进公开安装包。
3. 用已审查工具给系统镜像打上 `/system/xbin/su`（产品内验证过  
   [BlueStacks-Root-GUI](https://github.com/RobThePCGuy/BlueStacks-Root-GUI) 的 Mac 后端；  
   e2fsprogs 用该项目发布包并核对 checksum）。
4. 改完再启动 `Tiramisu64`。

**验收（一票否决）**

```sh
adb -s 127.0.0.1:5555 shell su -c id
```

- [ ] 退出码 0
- [ ] 输出含 `uid=0(root)`（常见还有 `gid=0(root)`）
- [ ] **不要**只看 `adb root` 报 restarting 就当成功（可能仍是 `uid=2000`）

注意：

- [ ] 改的是安装包里的**共享系统镜像**，同安装下其他实例也会带 su。
- [ ] BlueStacks 日后更新可能覆盖 `Root.qcow2` → 必须重新跑上面这条验收。

---

## 4. Frida：本机 Python `16.7.19` ↔ 设备端同名 helper

目标：

| 侧 | 要求 |
|---|---|
| Mac Python | `frida==16.7.19`（见 `mac/outputs/requirements.lock.txt`） |
| 模拟器里 | 二进制固定路径 `/data/local/tmp/kaituan-frida-server` |
| 监听 | `127.0.0.1:27042`（只本机环回） |
| 版本 | 设备端 `--version` **必须等于** `16.7.19`（与 `frida.__version__` 对齐） |

运行时自愈**只会启动已安装的二进制，不会自动 push/替换**。首次必须人工装好。

### 4.1 Mac 侧 Python

在 `mac/` 虚拟环境里：

```sh
pip install 'frida==16.7.19'
python -c "import frida; print(frida.__version__)"
```

- [ ] 打印正好是 `16.7.19`

### 4.2 设备端二进制（arm64）

- [ ] 下载与 **16.7.19** 匹配的 **android-arm64** `frida-server`（官方 Frida release；架构必须对 Tiramisu64 的 arm64-v8a）。
- [ ] 推入并命名为 **`kaituan-frida-server`**（名字不要改）：

```sh
adb -s 127.0.0.1:5555 push ./frida-server-16.7.19-android-arm64 /data/local/tmp/kaituan-frida-server
adb -s 127.0.0.1:5555 shell su -c 'chmod 755 /data/local/tmp/kaituan-frida-server'
adb -s 127.0.0.1:5555 shell su -c '/data/local/tmp/kaituan-frida-server --version'
```

- [ ] `--version` 输出正好是 `16.7.19`（不一致就停，不要硬启动）

### 4.3 首次拉起

`su -c` 后面整串命令要包在一起（参数被拆开会起不来）：

```sh
adb -s 127.0.0.1:5555 shell "su -c '/data/local/tmp/kaituan-frida-server -D -l 127.0.0.1:27042'"
adb -s 127.0.0.1:5555 shell "su -c 'pidof kaituan-frida-server'"
```

**验收**

- [ ] `pidof` 正好 **一个** 数字 PID（多个 = 不健康）
- [ ] 监听口是 `127.0.0.1:27042`（不要改成 `0.0.0.0`）

---

## 5. 来客：安装 + 人工登录 + 身份核验

包名：`com.bytedance.ls.merchant`（抖音来客）

### 5.1 安装

- [ ] 在模拟器里安装来客（官方渠道 APK / 商店；版本以能正常商家登录为准）。
- [ ] 确认包可用：

```sh
adb -s 127.0.0.1:5555 shell cmd package resolve-activity --brief com.bytedance.ls.merchant
adb -s 127.0.0.1:5555 shell pidof com.bytedance.ls.merchant
```

- [ ] 可冷启动（示例）：

```sh
adb -s 127.0.0.1:5555 shell monkey -p com.bytedance.ls.merchant -c android.intent.category.LAUNCHER 1
```

### 5.2 人工登录（禁止自动）

- [ ] **人**在模拟器里完成来客登录（扫码/验证码均可）。
- [ ] 登录后能看到商家工作台（公司/门店切换正常）。
- [ ] **禁止**脚本自动登录、自动点「同意」、清数据重装。
- [ ] 提醒：平台对自动化敏感；绿场只探活，本步不要提交开团/秒杀。

### 5.3 身份核验（登录真可用）

进程在 ≠ 已登录。产品路径用 Frida attach 后读 `NativeAccount.identity()`：

- 读到身份 → 会话可视为 confirmed（可写闸才放行）  
- 读失败 → unconfirmed，停写，等人再登（不要自动重登）

`mac/` 代码与 venv 就绪后，做一次**只读**核验（路径按本机调整）：

```sh
cd /path/to/kaituan-seckill/mac
.venv/bin/python - <<'PY'
from native_account import NativeAccount
adb = "work/android-sdk/platform-tools/adb"  # 或 PATH 里的 adb
with NativeAccount(adb, "127.0.0.1:5555", autostart=True) as acc:
    ident = acc.identity()
    print("ok", bool(ident), "keys", sorted((ident or {}).keys())[:12])
PY
```

**验收**

- [ ] 来客进程 `pidof` 正好 1 个
- [ ] identity **能读通**（不抛 `NativeAccountUnavailable`）
- [ ] 当前公司/门店是本部署要用的商家主体（酒店目录种子见 §8，口径与上级文档 §5.8 相同）

---

## 6. 一页总验收（绿场全绿）

```sh
ADB=adb   # 或 work/android-sdk/platform-tools/adb
S=127.0.0.1:5555

$ADB connect $S
$ADB -s $S get-state                          # → device
$ADB -s $S shell getprop sys.boot_completed   # → 1
$ADB -s $S shell su -c id                     # → 含 uid=0(root)
$ADB -s $S shell su -c '/data/local/tmp/kaituan-frida-server --version'  # → 16.7.19
$ADB -s $S shell "su -c 'pidof kaituan-frida-server'"   # → 单个 PID
$ADB -s $S shell pidof com.bytedance.ls.merchant        # → 单个 PID
python -c "import frida; assert frida.__version__=='16.7.19'"
```

- [ ] 以上全绿  
- [ ] 来客人工登录完成 + identity 只读通过  
- [ ] 本部署的网关 URL / worker 身份已按「自己的环境」填好（见附录），未误连别人的队列  

---

## 7. 本文明确不做

| 不做 | 原因 |
|---|---|
| 在本文改服务器 gateway / nginx | 绿场只管执行机运行时 |
| 在文档里写死生产 IP / 泄露 token | 安装时自填；样板只放附录 |
| 自动登录来客、清数据刷登录 | 风控 + 丢态 |
| 日常自愈自动 push/覆盖 frida 二进制 | 只启动已装好的；版本错了要人工重装 |
| 绿场未完成就对生产商家实弹写入 | 先探活与风控清单 |

绿场之后才做（可另出产品化安装册）：clone `mac/`、venv、`trigger-worker.json`、权限 0600 的 `credentials.json`、LaunchAgent、kickstart、网页探活。

---

## 8. 安装时需自备（产品化缺口）

- [ ] 来客 APK：官方渠道，版本以能登录为准（仓库不锁死安装包）。
- [ ] 商家账号：谁登、登哪个主体，由业务方定；执行侧只验收 identity 可读。
- [ ] Frida server：从官方 release 拉 **16.7.19 / android-arm64**（仓库通常不打包二进制）。
- [ ] Root GUI 操作以工具当前 UI 为准；原则是停实例 → 备份 → 打 su → `su -c id`。
- [ ] **你的**网关 HTTPS 地址、worker token、worker_id：安装时自填，写入本机配置（权限 0600），不要提交进 git。
- [ ] **酒店目录种子 `catalog.sqlite3`**（上级文档 [AI-INSTALL.md](AI-INSTALL.md) §5.8）：它是酒店目录种子库，表 `merchant_catalog`。worker 启动时只读拷进 `worker.sqlite3` 一次；缺文件则目录为空、不崩溃。仓库内没有从 `merchant-*.json` 生成该 sqlite 的脚本。新装自备同结构的 sqlite（业务导出，或从已有环境拷贝这份种子），放到 `mac/work/trigger-worker/catalog.sqlite3`。**本轮不做** catalog 导入功能。

---

## 附录 A · 配置样板（非默认值）

以下仅为「长什么样」的样板，**安装时改成自己的**。不要把样板 IP/token 当成所有环境的默认。

网关 base（worker `--server` / 配置里的 server 根）：

```text
https://<你的网关主机>/<你的路径前缀>
```

历史某套环境曾用过的网关地址（`EXAMPLE_LIVE_ONLY`，禁止当默认值，禁止抄进新环境）：

```text
https://1.12.208.101/kaituan
```

`android_device` 段（运行时固定项，一般不用改）：

```json
{
  "backend": "bluestacks",
  "execution_backend": "native_api",
  "adb_endpoint": "127.0.0.1:5555",
  "instance": "Tiramisu64",
  "autostart": true
}
```

worker token：放本机 `credentials.json`（或环境变量约定字段），权限 `0600`，**本文永不填写真实值**。

---

## 附录 B · 一句话

任意新 Mac 绿场 = **Tiramisu64 + adb `127.0.0.1:5555` + `su -c id` 见 uid=0 + 本机/设备 Frida 钉死 16.7.19（路径 `/data/local/tmp/kaituan-frida-server`，监听 `127.0.0.1:27042`）+ 来客人工登录并能读 identity**；网关与 token 安装时填自己的；一套部署一个 worker。
