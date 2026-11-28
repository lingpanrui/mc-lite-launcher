# MC Lite 启动器 · 正式版 v1.0

**Windows + Android** 的 Minecraft 启动器：Java 版与基岩版统一管理，能装模组光影、开联机房间。
桌面端 `MCLite-v2.exe` 是单文件，**不需要装 Python / Java / 任何运行库**就能启动
（Java 版游戏本身需要的 JDK 由启动器自动检测并下载 Temurin）。

> 纯 Python 标准库实现，源码无第三方依赖；MIT 协议开源。

## 下载

到 [Releases](../../releases/latest) 下载：

| 文件 | 说明 |
| --- | --- |
| `MC-Lite-v1.0.exe` | Windows 桌面端，正式版 v1.0，已自签名 |
| `MCLite-android-1.2.0.apk` | Android 端，含 Java 版运行环境接入 |
| `MC-Lite-v1.0-src.zip` | 桌面端完整源码 |
| `MCLite-selfsigned.cer` / `trust-mclite-cert.bat` | 自签名证书与本机信任脚本 |
| `SHA256SUMS.txt` | 全部资产的 SHA-256 |

### Windows 版（三步）

1. 把 `MC-Lite-v1.0.exe`、`MCLite-selfsigned.cer`、`trust-mclite-cert.bat` 放在**同一个目录**
2. 双击 `trust-mclite-cert.bat`（当前用户级别，不需要管理员），把发布者证书装进本机
3. 双击 `MC-Lite-v1.0.exe` 运行，绿色免安装，不写注册表，数据都在 `%APPDATA%\MCLite`

> 不想导入证书也能跑，只是首次启动会提示"未知发布者"，点「更多信息 → 仍要运行」即可。

### Android 版

直接安装 APK（`versionName 1.2.0` / `versionCode 3` / minSdk 24）。

**注意：1.2.0 换了签名证书**（旧 1.1.0 的 CI 私钥未保留），签名指纹现在是
`84b0cc3a2244ea006ad73102d27d1d3c2ab6493f12e44c2c6569b334ec55ffc7`，
所以装过 1.1.0 的机器**必须先卸载旧版**，再装 1.2.0，之后版本沿用这把 key 可直接覆盖升级。

## 桌面端 v1.0 的功能

### 界面
- 深色主题全自绘组件（自定义按钮 / 滚动区 / 进度条 / 下拉框 / 侧边导航），无第三方 UI 库
- **中英双语实时切换**，语言写入配置持久化
- 首页：已装版本数、社区票数、我的投票、Modrinth 入口 + 三张快速开始卡

### 版本与启动
- **安装新版本**（版本页右上角按钮）：选游戏版本 + 加载器，带进度条与状态行；
  原版走 Mojang 官方源，Fabric 自动选最新 loader 并先装好依赖的原版。
  Forge / NeoForge 仍需在仓库 `mclite/ui.py` 的旧界面里安装，新版界面后续接入。
- 扫描已安装版本（原版 / Fabric / Quilt / Forge / NeoForge），识别加载器与版本目录
- 启动时按版本自动匹配 Java 8/16/17/21/25，缺哪个下载哪个
- 内存分配、自定义 JVM 参数、Java 路径、数据目录

### 内容下载（照 PCL2 的布局）
- 左侧资源类型栏（模组 / 光影 / 资源包）+ 筛选卡 + **带真实图标的资源行**
- 数据来自 Modrinth（官方 API 走 `mod.mcimirror.top` 镜像，图标仍用 CDN）
- 进详情页看项目页地址、每个版本的文件名与直链，可一键下载到对应版本目录
- 图标本地缓存（`%APPDATA%\MCLite\cache\icons`）

### 功能投票
- 13 项**真实存在的功能**（版本管理、加载器、启动、内存分配、整合包、模组、光影、
  数据包、资源包、一键联机、账号切换、中英切换、下载详情页），一功能一票，按票数排序

### 联机
- 游戏内「对局域网开放」后从 `logs/latest.log` 自动识别端口
- 一键拉起开源隧道 [bore](https://github.com/ekzhang/bore) 的免费公共服务（`bore.pub`，无需注册付费）

### 账号
- 离线登录 / 外置登录（authlib-injector）/ 微软正版（设备码流程，需自备 Azure 公开客户端 Client ID）

### 基岩版
- 检测本机 Minecraft 客户端，正式版 / 预览版分别启动
- 服务端（BDS）：官方正式版 / 预览版列表，按版本号取历史版本

## Android 端 1.2.0

`android/` 是 Kotlin + Jetpack Compose 的配套端，定位是**管理 + 一键拉起**：

- **Java 版运行环境**：自动识别 PojavLauncher / PojavLauncher 中文版 / Amethyst，
  一键拉起并可携带版本名；未安装时给出免费开源下载入口，装好后回来自动识别
- 版本清单浏览（900+ 版本）、BDS 服务端版本、Modrinth 热门前置预取、燃烧式筛选
- 基岩版客户端检测与启动

> 说明：安卓上真正运行 Java 版需要 JVM + OpenGL 转译层（内置 ARM JRE、LWJGL 转 GL4ES），
> 那是 PojavLauncher / Amethyst 级别的工程。本 App 不重造这一层，而是负责版本、资源、
> 联机管理，并把已装的运行环境一键拉起来 —— 这样手机上也真的能玩 Java 版。

## 签名与校验

**Windows exe** 使用自签名代码签名证书（`CN=MCLite Self-Signed`，证书 SHA-1
`A382880EE6D964E45D8410303303C373415060B3`），时间戳走 DigiCert。
文件属性里能看到签名者并检测篡改，但根证书不在公共信任库，**别人电脑上仍显示"未知发布者"**，
除非导入随包 `.cer`。

**Android APK** 固定 release keystore 自签名（`CN=MCLite, OU=Launcher, O=MCLite, C=CN`），
SHA-256 `84b0cc3a2244ea006ad73102d27d1d3c2ab6493f12e44c2c6569b334ec55ffc7`。
keystore 与私钥**不进仓库**。

下载后请核对 SHA-256（见 Release 里的 `SHA256SUMS.txt`）：

```powershell
Get-FileHash .\MC-Lite-v1.0.exe -Algorithm SHA256
Get-FileHash .\MCLite-android-1.2.0.apk -Algorithm SHA256
```

> [!WARNING]
> 哈希对不上说明文件被改动过（篡改、二次打包、下载被替换），**不要运行**。
> 官方构建只从 [Releases](../../releases) 产出，不通过网盘、群文件、第三方站点分发。

## 已知限制（诚实版）

- **Forge / NeoForge 安装还没搬进新界面**：新版界面的「安装新版本」支持原版与 Fabric；
  Forge / NeoForge 的安装仍在仓库 `mclite/ui.py` 那套旧界面里可用。
- **NeoForge** 官方 maven 在部分国内网络被污染，可能卡在依赖下载。
- **基岩版客户端**由 Microsoft Store 分发，启动器不绕过商店，只检测并启动已安装版本；
  可免安装下载的是**服务端**（BDS）。
- **微软正版登录** 需自备 Azure Client ID（免费注册但要额外几步）。
- **安卓端跑 Java 版依赖 PojavLauncher / Amethyst**，本 App 不自带 JVM。
- **bore** 是共享公共隧道，延迟看线路，适合临时联机。

## 从源码跑

```powershell
启动.bat
# 需要 Python 3.10+，仅标准库
```

打包：

```powershell
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --windowed `
  --name MCLite-v2 --version-file version_info_v2.txt main.py
# 产物：dist\MCLite-v2.exe
```

安卓端：

```powershell
cd android
# 需要 JDK 17 + Android SDK 34 + Gradle 8.7
gradle assembleRelease
```

## 代码结构

```
main.py              入口（DPI 适配、全局异常兜底，指向 ui_v2）
mclite/ui_v2.py      正式版界面（深色自绘组件、页面路由、下载页、投票页、设置）
mclite/i18n.py       中英文案表与语言切换
mclite/poll.py       功能投票的 13 项功能定义与票数
mclite/imgcache.py   模组图标本地缓存
mclite/modrinth.py   Modrinth 搜索/版本/依赖（官方 + 镜像）
mclite/mojang.py     版本清单、原版安装、inheritsFrom 合并、启动命令
mclite/forge.py      Forge / NeoForge 安装器调度
mclite/auth.py       authlib-injector 外置登录、微软设备码登录
mclite/java.py       Java 检测与 Temurin 自动下载
mclite/bedrock.py    基岩客户端检测、BDS 多版本下载与启动
mclite/tunnel.py     局域网端口识别 + bore 隧道
mclite/util.py       配置、HTTP、校验、解压
mclite/ui.py         v1 界面（保留：完整安装流程在这里）
android/             Kotlin + Jetpack Compose 安卓端
```

## 版权

**MIT License**，著作权人 `lingpanrui`（见 [LICENSE](LICENSE)）。

`MCLite-v2.exe` 版本资源（文件属性 → 详细信息）：

| 字段 | 值 |
| --- | --- |
| CompanyName | MCLite 项目 |
| FileDescription | MC Lite 启动器 正式版 v1.0 |
| ProductName / ProductVersion | MC Lite / 1.0.0.0 |
| LegalCopyright | Copyright © 2026 lingpanrui，MIT License |

## 参与开发

见 [CONTRIBUTING.md](CONTRIBUTING.md)。Issue / PR 都欢迎。
