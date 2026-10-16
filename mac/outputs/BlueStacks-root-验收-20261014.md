# BlueStacks root：2026-10-14

用户明确要求先取得 root。当前 BlueStacks Air 5.21.720.7530 / Tiramisu64，Android 13，arm64-v8a；SELinux 本机读取为 Disabled。

## 已完成

- 原生 ADB TCP：127.0.0.1:5555。
- `adb root` 在修改前虽报告 restarting，但实际 id 仍 uid=2000，故未将其视为成功。
- 已停止 BlueStacks，并备份原始 Root.qcow2、当前实例 data.qcow2、initrd_hvf.img 和 bluestacks.conf。
- 使用 RobThePCGuy/BlueStacks-Root-GUI 的已审查 Mac 后端，在系统镜像中添加 `/system/xbin/su`，root 所有权、mode 6755；转换镜像后经过 e2fsck 检查再写回。
- 执行代码版本：b1eb994e1a35d6150adee0fea0f343c46642a700。
- e2fsprogs 来自该项目 v3.12.0 官方发布的 macOS 包，其 SHA-256 与 GitHub asset digest 一致：bb7bd30a55d7f6d09780eab78bd52ffa0f60ed406d04befb53b3088aaf8560b8。
- 重启后执行 `adb -s 127.0.0.1:5555 shell su -c id`，exit 0，实际返回 `uid=0(root) gid=0(root)`。

## 备份与恢复

备份位于 `work/bluestacks-root-20261014/backup/`，目录权限 0700，包含私有模拟器账号数据，不放入通用迁移包。原厂系统镜像另外有工具生成的 `Root.qcow2.prepatch.bak`。

恢复时先停止所有 BlueStacks 实例，再将原厂系统镜像原内容写回 `/Applications/BlueStacks.app/Contents/img/Root.qcow2`。不要在实例运行时替换磁盘；只有确实需要恢复用户数据时才恢复 data.qcow2，否则会丢弃备份之后的业务状态。

修改的是 BlueStacks 安装中的共享系统镜像，其他使用同一安装的实例也会获得 su。后续 BlueStacks 更新可能替换系统镜像，须以实际 `su -c id` 重新核验，而不是相信旧记录。

## 本轮业务代码状态

磁盘 v9 已增加纯 ADB BlueStacks 控制层、明确端点重连、按窗口尺寸计算导航手势、公司选择内部 URI 入口；375 项离线测试通过。原服务仍停用，未启动后台收单、未回放旧任务、未提交开团或秒杀。

下一步的接口分析与无坐标业务执行尚未验收。已验证的内部 URI：`snssdk299467://account/switch` 和 `snssdk299467://account/choose`；已有静态账号接口线索不等于已经实现直接按 ID 切换或确认计划。

方案来源：[BlueStacks-Root-GUI](https://github.com/RobThePCGuy/BlueStacks-Root-GUI)。
