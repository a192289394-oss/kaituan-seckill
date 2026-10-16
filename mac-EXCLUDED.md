# Mac 拉取排除说明（瘦身）

已排除（体积过大 / 非源码）：
- .venv (~124M)
- __pycache__
- work/bluestacks-root-20261014/ (~8.5G 镜像与 Root GUI)
- work/apk-analysis/ (~974M apk/jre/jadx)
- work/pc-profile/ (~911M 浏览器配置缓存)
- work/android-sdk/ (~37M)
- work/platform-tools-darwin.zip (~16M)
- work/frida-20261014/frida-server 与 frida-server.xz（大二进制，保留同目录其它脚本）

已包含：全部 .py/.js/.html/.css/.md、配置、outputs（含 trigger-ui 及 bak）、work 业务脚本、backups、official-assets、trigger-worker、uiautomator2-source 等。
