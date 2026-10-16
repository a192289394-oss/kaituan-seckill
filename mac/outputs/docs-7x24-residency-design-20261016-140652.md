# 7×24 常驻总设计（第①步：看得见 + 能停写；第②③步后补）

目标：Mac+BlueStacks+来客能常驻；坏了**立刻标红停写**；可安全项自愈；不可安全则停手等人。  
不改：只提交一次、gate/commit、秒杀人工确认、开团提交即执行。

## 0. 现状锚点（已有，复用）

| 能力 | 现状 |
|---|---|
| Worker 心跳 | `POST /api/worker/heartbeat`，`HEARTBEAT_SECONDS=30`，网关 `LEASE_SECONDS=90` 判 online |
| 运行时探测 | `_observe_runtime_health`：`android_device` / `root` / `business_app` / `native_interface`，`HEALTH_PROBE_SECONDS=60` |
| 健康落库 | 网关 meta：`worker_heartbeat` + `worker_health`（JSON） |
| 写入闸（执行） | claim 时 `allow_write`；Android 未就绪 → `waiting_device` / `NativeAccountUnavailable`；gate preflight/commit 不变 |
| 写入闸（网页） | `writeEnvironmentReady`：android+root 必须 available；来客 running；native `unknown` 仅当 `processes_present_attach_not_probed` 放行 |
| 任务心跳 | 执行中 `beating()` 每 30s；`STALL_SECONDS=600` 则 `os._exit(75)` 交 launchd 重启 worker（不杀 App） |
| 启动探测 | `android_runtime.probe(allow_launch=True)` 可按配置 autostart BlueStacks |

缺口：探测红了只在折叠详情；无「执行端未就绪」顶栏人话；无结构化 `write_ready`；无巡检自愈白名单；无连续失败/频率停手。

---

## 1. 巡检项（worker 侧，只读优先）

周期：沿用 60s 探测；心跳 30s 捎带缓存结果（与现逻辑一致）。

| 项 | 判定 available/ready | 失败 reason（稳定英文码，给人话映射） |
|---|---|---|
| A. adb 设备 | `get-state` == `device` | `adb_not_device` / `adb_timeout` |
| B. boot | `sys.boot_completed==1`（**新增**，今日 offline 窗口需要） | `boot_incomplete` |
| C. root | `su -c id` 含 `uid=0(root)` | `uid_0_not_confirmed` |
| D. 来客进程 | `pidof com.bytedance.ls.merchant` 恰好 1 个 | `process_absent` / `process_not_unique` |
| E. frida helper | `pidof kaituan-frida-server` 恰好 1 个 | `helper_process_absent_or_ambiguous` |
| F. 来客前台（软） | 可选：`dumpsys` 前台包==来客；**不**因后台 alone 停写，只告警 | `app_not_foreground` |
| G. 登录态（软，第②步） | 业务只读轻探或缓存标记；失败→停写+告警，**禁止**自动重新登录刷接口 | `session_unconfirmed` |

**硬就绪（write_ready）**：A∧B∧C∧D∧E。  
**native_interface**：保持「进程在 ≠ attach 探测」；心跳仍 `unknown` + `processes_present_attach_not_probed`；真正 attach 只在任务路径。

---

## 2. 心跳 / 标红字段（网关 + 前端契约）

### 2.1 Worker → Gateway `health` 扩展（向后兼容）

在现有 `health.runtime` 旁增加汇总（旧字段保留）：

```json
{
  "build": "...",
  "runtime": { "...现有四段..." },
  "residency": {
    "write_ready": true,
    "degraded": false,
    "human_reason": "执行环境正常",
    "blocking": [],
    "warnings": [],
    "heal_last": null,
    "fail_streak": 0,
    "checked_at": 1730000000.0
  }
}
```

- `blocking[]`：导致 `write_ready=false` 的 reason 码  
- `warnings[]`：不停写的软问题（如仅未前台）  
- `human_reason`：一句中文，给顶栏直接用（worker 生成，前端不拼技术词）

### 2.2 Gateway

- 继续写入 `worker_health`；`/api/status`（或现 status）原样吐出  
- **新增派生**（可算可不落库）：`execution.write_ready` = residency.write_ready ∧ worker.online  
- Worker 心跳超过 `LEASE_SECONDS`：`online=false` → 强制 `write_ready=false`，`human_reason=「Mac 收单离线」`

### 2.3 前端（第①步必做）

- 顶栏一句：用 `residency.human_reason`（或 online 假时的离线句）  
- **默认不展开** Android/root/来客/原生四格（已有折叠可留「给技术看」）  
- `writeEnvironmentReady` 改为认 `residency.write_ready`（缺字段时回退旧四段逻辑，兼容未升级 worker）  
- 标红：`write_ready=false` → 徽章坏色 + 禁止勾选自动执行 / 提交写入

---

## 3. 自愈白名单（仅安卓执行；其它禁自动）

原则：**可逆、不触达业务提交、不自动登录、不点同意协议。**

| 允许自动（最多 N 次/小时，建议 3） | 动作 | 成功条件 |
|---|---|---|
| BlueStacks 未起 / adb 拒连 | `android_runtime.probe(allow_launch=True)` 已有路径 | `get-state=device` 且 boot_completed |
| 升级/阻塞弹窗挡 adb（已知类） | 仅点「关闭/稍后」白名单控件；点不到→停 | adb 恢复 |
| frida helper 掉进程 | 按现应急脚本拉起 `kaituan-frida-server` | pidof 唯一 |
| 来客进程不在 | 冷启动 App（不清数据、不切账号） | pidof 唯一 |
| 来客在但未前台 | `am start` 拉到前台 | 前台包匹配 |

| 禁止自动 | 原因 |
|---|---|
| 重新登录 / 验证码 / 扫码 | 风控+账号安全 |
| 任意业务 API 写入、重放 gate | 只提交一次 |
| 杀来客清缓存、重装 | 丢登录态 |
| 无限重启模拟器 | 振荡；达上限停写告警 |

自愈结果写入 `residency.heal_last={at,action,ok,reason}`，并打 worker 日志一行（不进操作员默认 UI）。

---

## 4. 停写条件（硬闸，与现 gate 叠加）

任一成立 → `write_ready=false`，新任务只接核验；进行中未 commit 的写入不得开新 commit（已有 fence/read_only 回收逻辑保持）：

1. Mac worker offline（心跳 > 90s）  
2. `android_device` ≠ available 或 boot 未完成  
3. `root` ≠ available  
4. 来客进程非唯一 running  
5. frida helper 非唯一 running  
6. **连续失败停手**：同 worker 在窗口 T（建议 15min）内业务结果 `failed`/`AppRead` 耗尽/`NativeAccountUnavailable` 累计 ≥ K（建议 3）→ `degraded=true`，需人工或冷却后清零  
7. **频率上限**（风控）：写入类 commit 全局限流（建议：每账号每小时 ≤ N 次原生提交；超限 → 排队不提交，人话「已限流，稍后自动继续或明天再试」）  
8. 自愈白名单动作连续失败 ≥ 2 → 停写，人话点明「模拟器/来客需要人工看一眼」

**不清零自动恢复写入**除非：巡检硬就绪连续 2 轮通过，且 fail_streak 冷却结束。

---

## 5. 与现有 gate / heartbeat 怎么接

```
[巡检循环 ≤60s] → 更新 residency → heartbeat 上传
                         ↓
              网关 meta.worker_health
                         ↓
         网页 status → 顶栏 + write_ready 闸
                         ↓
    操作员提交 allow_write=true ──否──→ 只核验
                         ↓是
    claim → 任务前 android_runtime.probe
                         ↓未就绪
              waiting_device（已有）+ 可触发白名单自愈
                         ↓就绪
         业务只读 →（确认）→ gate preflight → 唯一 commit → 回读
```

- **Heartbeat**：继续 30s；residency 挂在 health 里，不新开端口  
- **Gate**：不改语义；停写发生在「claim 前网页闸 + claim/执行前 probe」，不在 commit 成功后补刀  
- **waiting_device**：保留；自愈成功后下一轮 claim 自然恢复  
- **LaunchAgent**：worker 崩了仍靠 launchd；自愈只管模拟器/frida/App，不管替 launchd 抢活

---

## 6. 第①步落地分工（可并行，改前备份）

| 角色 | 交付 | 验收 |
|---|---|---|
| **架构** | 本设计；定字段名；改 worker `residency` 汇总 + boot 检查；网关若需透出字段则备份后改 | heartbeat JSON 含 write_ready/human_reason；缺字段前端可回退 |
| **安卓** | 白名单自愈钩子（先接 adb/BS 拉起 + frida + 来客冷启）；失败计数 | 人为杀 frida 后 ≤2min 内恢复或标红停写 |
| **前端** | 顶栏人话；write 闸认 residency；技术详情默认藏 | 红时无法勾选自动执行；绿时恢复 |
| **风控** | 验收：停写条件 1–5；连续失败 K；限流不盲打；自愈不碰提交 | 清单过关才关单 |
| **产品** | 人话文案表（offline / android / 来客 / 限流 / 要人工） | 无英文码上顶栏 |

第②步：登录态巡检 + 主动推送（微信/邮件任选，另开需求）。  
第③步：第二台执行机。  

---

## 7. 明确不做（本轮）

- 改只提交一次 / fingerprint / 秒杀确认规则  
- 心跳里 Frida attach 探活  
- 自动过验证码、自动重新登录  
- 为「好看」重做业务状态机
