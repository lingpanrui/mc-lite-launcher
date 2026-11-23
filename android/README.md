# MC Lite · 安卓端

和桌面版同一个仓库的安卓版本，Kotlin + Jetpack Compose 实现，MIT 开源。

## 它是什么

安卓上要**真的运行 Java 版**，需要 ARM 架构的 JVM、LWJGL 的 OpenGL 转译和输入映射
（这正是 PojavLauncher 做的事，工程量以年计）。所以这一版把定位说清楚：

**MC Lite 安卓端 = 版本 / 内容 / 联机的配套管理端**，而不是内置 JVM 的启动器。

它能做：

- **Java 版**：读 Mojang 官方清单（900+ 版本），按正式版 / 快照筛选，看版本详情、
  复制版本 JSON 地址（可直接交给 PojavLauncher 之类工具）
- **基岩版**：检测本机是否安装，一键拉起；服务端（BDS）正式版/预览版列表，点开即下载
- **模组 / 光影 / 资源包**：Modrinth 搜索，按类型筛选，跳转项目页下载
- **联机**：输入 `bore.pub:端口` 或任意 `host:port`，真实实现 Minecraft
  Server List Ping 协议，显示在线人数、MOTD、延迟；一键复制/分享地址
- **PojavLauncher**：本机装了就直接拉起

## 构建

要求：JDK 17、Android SDK（compileSdk 34）。仓库里没有提交 Gradle Wrapper，
CI 用 `gradle/actions/setup-gradle` 提供 Gradle，本地构建同样：

```bash
# 本地
gradle -p android assembleDebug
# 产物：android/app/build/outputs/apk/debug/app-debug.apk
```

或者直接推 GitHub，让 `.github/workflows/android.yml` 构建，从 Actions 的
artifact 里下 APK。

## 结构

```
android/
├─ settings.gradle.kts
├─ build.gradle.kts
└─ app/
   ├─ build.gradle.kts           # AGP 8.5 / Kotlin 1.9 / Compose BOM
   └─ src/main/
      ├─ AndroidManifest.xml
      └─ java/com/mclite/android/
         ├─ MainActivity.kt      # Compose 界面：首页 / Java / 基岩 / 模组 / 联机
         └─ Api.kt               # Mojang、Modrinth、BDS、Server List Ping（零第三方依赖）
```

## 说明

- 网络库只用系统自带的 `HttpURLConnection` + `org.json`，不引 OkHttp/Retrofit，
  减小体积也少踩版本坑。
- Server List Ping 是手写的 VarInt + 握手包，任何 Java 版服务端都适用。
- 基岩版通过 `com.mojang.minecraftpe` 的启动 Intent 拉起，没有安装则跳下载页。
- 应用不包含任何账号密码存储；联机地址只在本机内存里。
