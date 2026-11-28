package com.mclite.android

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Android
import androidx.compose.material.icons.filled.Extension
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Memory
import androidx.compose.material.icons.filled.Wifi
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

// --------------------------------------------------------------------------- //
// 配色与入口
// --------------------------------------------------------------------------- //

private val Accent = Color(0xFF3DDC84)
private val BgColor = Color(0xFF12151B)
private val CardColor = Color(0xFF1A1E26)
private val TextColor = Color(0xFFE9EDF4)
private val SubColor = Color(0xFF8B93A3)

private val MCLiteColors = darkColorScheme(
    primary = Accent,
    onPrimary = Color(0xFF06170E),
    background = BgColor,
    onBackground = TextColor,
    surface = CardColor,
    onSurface = TextColor,
    surfaceVariant = Color(0xFF232935),
    onSurfaceVariant = SubColor,
)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { MaterialTheme(colorScheme = MCLiteColors) { MCLiteApp() } }
    }
}

// --------------------------------------------------------------------------- //
// 小工具
// --------------------------------------------------------------------------- //

private fun openUrl(ctx: Context, url: String) {
    try {
        ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
    } catch (_: Exception) {
    }
}

private fun copyText(ctx: Context, text: String, label: String = "MC Lite") {
    val cm = ctx.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    cm.setPrimaryClip(ClipData.newPlainText(label, text))
}

private fun shareText(ctx: Context, text: String) {
    val intent = Intent(Intent.ACTION_SEND).apply {
        type = "text/plain"
        putExtra(Intent.EXTRA_TEXT, text)
    }
    ctx.startActivity(Intent.createChooser(intent, "分享"))
}

private fun bedrockInstalled(ctx: Context): Boolean =
    try {
        ctx.packageManager.getLaunchIntentForPackage("com.mojang.minecraftpe") != null
    } catch (_: Exception) {
        false
    }

private fun launchBedrock(ctx: Context): Boolean {
    try {
        val intent = ctx.packageManager.getLaunchIntentForPackage("com.mojang.minecraftpe")
        if (intent != null) {
            ctx.startActivity(intent)
            return true
        }
    } catch (_: Exception) {
    }
    return try {
        ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("minecraft://")))
        true
    } catch (_: Exception) {
        false
    }
}

// Java 版在安卓上要真跑起来，需要一个自带 JVM 与图形转译层的运行环境。
// 下面几个都是免费开源、不用登录也不用实名的，装上任意一个就能跑。
private val RunnerPackages = listOf(
    "net.kdt.pojavlaunch" to "PojavLauncher",
    "com.movtery.pojavzh" to "PojavLauncher 中文版",
    "com.angelaura.amethyst" to "Amethyst",
    "io.github.angelauramc.amethyst" to "Amethyst",
)

private fun findRunner(ctx: Context): Pair<String, String>? {
    for ((pkg, label) in RunnerPackages) {
        try {
            if (ctx.packageManager.getLaunchIntentForPackage(pkg) != null) return pkg to label
        } catch (_: Exception) {
        }
    }
    return null
}

private fun runnerInstalled(ctx: Context): Boolean = findRunner(ctx) != null

/** 拉起运行环境，尽量把版本名带过去；对方不认识这个参数时会退化成打开它的主界面。 */
private fun launchRunner(ctx: Context, version: String? = null): Boolean {
    val hit = findRunner(ctx) ?: return false
    return try {
        val intent = ctx.packageManager.getLaunchIntentForPackage(hit.first) ?: return false
        if (!version.isNullOrBlank()) {
            intent.putExtra("version", version)
            intent.putExtra("mcversion", version)
            intent.putExtra("versionName", version)
        }
        ctx.startActivity(intent)
        true
    } catch (_: Exception) {
        false
    }
}

private const val POJAV_RELEASES = "https://github.com/PojavLauncherTeam/PojavLauncher/releases"
private const val AMETHYST_RELEASES = "https://github.com/AngelAuraMC/Amethyst-Android/releases"

// --------------------------------------------------------------------------- //
// 通用小组件
// --------------------------------------------------------------------------- //

@Composable
private fun SectionCard(
    title: String,
    subtitle: String? = null,
    content: @Composable () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = CardColor),
    ) {
        Column(Modifier.padding(16.dp)) {
            Text(title, color = TextColor, fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
            if (subtitle != null) {
                Spacer(Modifier.height(4.dp))
                Text(subtitle, color = SubColor, fontSize = 12.sp)
            }
            Spacer(Modifier.height(12.dp))
            content()
        }
    }
}

@Composable
private fun PageTitle(title: String, subtitle: String) {
    Column(Modifier.padding(top = 20.dp, bottom = 8.dp)) {
        Text(title, color = TextColor, fontSize = 24.sp, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(4.dp))
        Text(subtitle, color = SubColor, fontSize = 12.sp)
    }
}

@Composable
private fun EmptyHint(text: String) {
    Text(text, color = SubColor, fontSize = 13.sp, modifier = Modifier.padding(vertical = 16.dp))
}

// --------------------------------------------------------------------------- //
// 主界面
// --------------------------------------------------------------------------- //

private data class TabItem(val label: String, val icon: ImageVector)

/** 应用一启动就在后台预取的缓存：用户点进模组页时立刻有数据 */
private object Cache {
    var mods: List<Api.ModHit>? = null
    val versions = HashMap<String, List<Api.ModVersion>>()
}

private val Tabs = listOf(
    TabItem("首页", Icons.Filled.Home),
    TabItem("Java", Icons.Filled.Memory),
    TabItem("基岩", Icons.Filled.Android),
    TabItem("模组", Icons.Filled.Extension),
    TabItem("联机", Icons.Filled.Wifi),
)

@Composable
fun MCLiteApp() {
    var tab by rememberSaveable { mutableStateOf(0) }

    Scaffold(
        containerColor = BgColor,
        bottomBar = {
            NavigationBar(containerColor = CardColor) {
                Tabs.forEachIndexed { index, item ->
                    NavigationBarItem(
                        selected = tab == index,
                        onClick = { tab = index },
                        icon = { Icon(item.icon, contentDescription = item.label) },
                        label = { Text(item.label, fontSize = 11.sp) },
                        colors = NavigationBarItemDefaults.colors(
                            selectedIconColor = Accent,
                            selectedTextColor = Accent,
                            unselectedIconColor = SubColor,
                            unselectedTextColor = SubColor,
                            indicatorColor = Color(0xFF1F3A2B),
                        ),
                    )
                }
            }
        },
    ) { padding ->
        Box(Modifier.padding(padding).fillMaxSize()) {
            when (tab) {
                0 -> HomeScreen(onNavigate = { tab = it })
                1 -> JavaScreen()
                2 -> BedrockScreen()
                3 -> ContentScreen()
                4 -> OnlineScreen()
            }
        }
    }
}

// --------------------------------------------------------------------------- //
// 首页
// --------------------------------------------------------------------------- //

@Composable
private fun HomeScreen(onNavigate: (Int) -> Unit) {
    val ctx = LocalContext.current
    var manifest by remember { mutableStateOf<Api.Manifest?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var bedrock by remember { mutableStateOf(false) }
    var runner by remember { mutableStateOf<Pair<String, String>?>(null) }

    LaunchedEffect(Unit) {
        bedrock = bedrockInstalled(ctx)
        runner = findRunner(ctx)
        withContext(Dispatchers.IO) {
            runCatching { Api.mojangManifest() }
                .onSuccess { manifest = it }
                .onFailure { error = it.message }
            // 一联网就先把模组首页抓下来，点进“模组”页立刻有数据
            Cache.mods = runCatching { Api.searchMods("", "mod", 25, "downloads") }.getOrNull()
        }
    }

    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp)
    ) {
        PageTitle("MC Lite", "Java 版 + 基岩版 · 模组光影 · 免注册联机")

        SectionCard(
            title = "Java 版",
            subtitle = if (manifest != null) {
                "最新正式版 ${manifest!!.latestRelease} · 共 ${manifest!!.versions.size} 个版本"
            } else if (error != null) {
                "清单加载失败：$error"
            } else {
                "正在读取 Mojang 版本清单…"
            },
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { onNavigate(1) }) { Text("版本列表") }
                TextButton(onClick = { onNavigate(3) }) { Text("找模组 / 光影") }
            }
        }

        Spacer(Modifier.height(12.dp))

        SectionCard(
            title = "Java 版运行环境",
            subtitle = if (runner != null) {
                "已就绪：${runner!!.second} 负责 JVM 与图形转译"
            } else {
                "未检测到运行环境 · 装一个就能在手机上真正跑 Java 版"
            },
        ) {
            Column {
                if (runner != null) {
                    Text(
                        "版本、模组光影、联机由 MC Lite 管；点启动时会把版本名交给 ${runner!!.second}，由它把游戏跑起来。",
                        color = SubColor, fontSize = 12.sp
                    )
                    Spacer(Modifier.height(8.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(onClick = {
                            if (!launchRunner(ctx)) runner = findRunner(ctx)
                        }) { Text("打开 ${runner!!.second}") }
                        TextButton(onClick = { onNavigate(1) }) { Text("选版本启动") }
                    }
                } else {
                    Text(
                        "安卓本身没有 JVM 和 OpenGL 转译层，光有启动器跑不起来。PojavLauncher / Amethyst 是免费开源的运行环境，不用登录、不用实名、也不用花钱，装上之后这里会自动识别。",
                        color = SubColor, fontSize = 12.sp
                    )
                    Spacer(Modifier.height(8.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(onClick = { openUrl(ctx, POJAV_RELEASES) }) { Text("下载 PojavLauncher") }
                        TextButton(onClick = { openUrl(ctx, AMETHYST_RELEASES) }) { Text("Amethyst") }
                    }
                    Spacer(Modifier.height(4.dp))
                    TextButton(onClick = { runner = findRunner(ctx) }) { Text("装好了，重新检测") }
                }
            }
        }

        Spacer(Modifier.height(12.dp))

        SectionCard(
            title = "基岩版",
            subtitle = if (bedrock) "已检测到本机安装的 Minecraft（Windows/安卓版）" else "未检测到已安装的基岩版",
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = {
                    if (!launchBedrock(ctx)) {
                        openUrl(ctx, "https://play.google.com/store/apps/details?id=com.mojang.minecraftpe")
                    }
                }) { Text(if (bedrock) "启动基岩版" else "打开下载页") }
                TextButton(onClick = { onNavigate(2) }) { Text("服务端版本") }
            }
        }

        Spacer(Modifier.height(12.dp))

        SectionCard(
            title = "联机",
            subtitle = "桌面版开房后给出 bore.pub 地址，这里可以直接检测服务器状态、复制和分享地址",
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { onNavigate(4) }) { Text("联机工具") }
            }
        }

        Spacer(Modifier.height(12.dp))

        SectionCard(
            title = "关于",
            subtitle = "开源 · MIT · 桌面版与安卓版同一仓库",
        ) {
            Column {
                Text(
                    if (runner != null) "运行环境已就绪：${runner!!.second} 负责把 Java 版真正跑起来，这里的版本与资源直接对着它用。"
                    else "本应用负责版本、模组光影与联机管理；安卓上跑 Java 版还需要一个免费开源的运行环境（PojavLauncher / Amethyst），装好后这里会自动识别。",
                    color = SubColor, fontSize = 12.sp
                )
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    TextButton(onClick = { openUrl(ctx, "https://github.com/lingpanrui/mc-lite-launcher") }) {
                        Text("GitHub 仓库")
                    }
                    if (runner != null) {
                        TextButton(onClick = { launchRunner(ctx) }) { Text("打开 ${runner!!.second}") }
                    } else {
                        TextButton(onClick = { openUrl(ctx, POJAV_RELEASES) }) { Text("去装运行环境") }
                    }
                }
            }
        }

        Spacer(Modifier.height(24.dp))
    }
}

// --------------------------------------------------------------------------- //
// Java 版本
// --------------------------------------------------------------------------- //

@Composable
private fun JavaScreen() {
    val ctx = LocalContext.current
    var versions by remember { mutableStateOf<List<Api.McVersion>>(emptyList()) }
    var filter by rememberSaveable { mutableStateOf("release") }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var selected by remember { mutableStateOf<Api.McVersion?>(null) }
    var runner by remember { mutableStateOf<Pair<String, String>?>(null) }

    LaunchedEffect(Unit) {
        runner = findRunner(ctx)
        withContext(Dispatchers.IO) {
            runCatching { Api.mojangManifest().versions }
                .onSuccess { versions = it }
                .onFailure { error = it.message }
        }
        loading = false
    }

    val shown = remember(versions, filter) {
        when (filter) {
            "release" -> versions.filter { it.type == "release" }
            "snapshot" -> versions.filter { it.type == "snapshot" }
            else -> versions
        }
    }

    Column(Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
        PageTitle("Java 版版本", "官方清单 · 点击版本查看下载信息")

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            FilterChip(selected = filter == "release", onClick = { filter = "release" }, label = { Text("正式版") })
            FilterChip(selected = filter == "snapshot", onClick = { filter = "snapshot" }, label = { Text("快照") })
            FilterChip(selected = filter == "all", onClick = { filter = "all" }, label = { Text("全部") })
        }

        Spacer(Modifier.height(8.dp))

        when {
            loading -> Box(Modifier.fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = Accent)
            }
            error != null -> EmptyHint("加载失败：$error")
            else -> LazyColumn(Modifier.fillMaxSize()) {
                items(shown, key = { it.id }) { v ->
                    Column(
                        Modifier
                            .fillMaxWidth()
                            .padding(vertical = 10.dp)
                    ) {
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text(v.id, color = TextColor, fontSize = 15.sp, fontWeight = FontWeight.Medium)
                            Text(
                                when (v.type) {
                                    "release" -> "正式版"
                                    "snapshot" -> "快照"
                                    else -> v.type
                                },
                                color = SubColor, fontSize = 12.sp
                            )
                        }
                        Spacer(Modifier.height(2.dp))
                        Text(v.released, color = SubColor, fontSize = 11.sp)
                        Spacer(Modifier.height(6.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                            TextButton(onClick = { selected = v }) { Text("详情", fontSize = 12.sp) }
                            TextButton(onClick = { copyText(ctx, v.jsonUrl, "版本 JSON") }) {
                                Text("复制 JSON 地址", fontSize = 12.sp)
                            }
                        }
                    }
                    HorizontalDivider(color = Color(0xFF232935))
                }
            }
        }
    }

    val pick = selected
    if (pick != null) {
        androidx.compose.material3.AlertDialog(
            onDismissRequest = { selected = null },
            title = { Text(pick.id) },
            text = {
                Column {
                    Text("类型：${pick.type}", color = SubColor, fontSize = 13.sp)
                    Text("发布时间：${pick.released}", color = SubColor, fontSize = 13.sp)
                    Spacer(Modifier.height(8.dp))
                    Text(
                        if (runner != null) "点“用它启动”会把 ${pick.id} 交给 ${runner!!.second} 直接跑起来；也可以在它的版本列表里手动选。"
                        else "手机上要跑这个版本，得先装一个免费开源的运行环境（PojavLauncher / Amethyst），装好后回到这里就能一键启动。",
                        color = SubColor, fontSize = 12.sp
                    )
                }
            },
            confirmButton = {
                Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    if (runner != null) {
                        TextButton(onClick = {
                            if (!launchRunner(ctx, pick.id)) {
                                copyText(ctx, pick.id, "版本名")
                            }
                            selected = null
                        }) { Text("用它启动") }
                    }
                    TextButton(onClick = {
                        copyText(ctx, pick.jsonUrl, "版本 JSON")
                        selected = null
                    }) { Text("复制地址") }
                }
            },
            dismissButton = {
                TextButton(onClick = { openUrl(ctx, pick.jsonUrl); selected = null }) { Text("浏览器打开") }
            },
        )
    }
}

// --------------------------------------------------------------------------- //
// 基岩版
// --------------------------------------------------------------------------- //

@Composable
private fun BedrockScreen() {
    val ctx = LocalContext.current
    var installed by remember { mutableStateOf(false) }
    var links by remember { mutableStateOf<List<Api.BdsLink>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(Unit) {
        installed = bedrockInstalled(ctx)
        withContext(Dispatchers.IO) {
            runCatching { Api.bdsLinks() }
                .onSuccess { links = it }
                .onFailure { error = it.message }
        }
        loading = false
    }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
        PageTitle("基岩版", "客户端检测 · 服务端多版本下载")

        SectionCard(
            title = "客户端",
            subtitle = if (installed) "已检测到 Minecraft 基岩版" else "未检测到已安装的基岩版客户端",
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = {
                    if (!launchBedrock(ctx)) openUrl(ctx, "https://play.google.com/store/apps/details?id=com.mojang.minecraftpe")
                }) { Text(if (installed) "启动游戏" else "打开下载页") }
                TextButton(onClick = { openUrl(ctx, "https://www.minecraft.net/en-us/download/server/bedrock") }) {
                    Text("官方页面")
                }
            }
        }

        Spacer(Modifier.height(12.dp))

        SectionCard(
            title = "服务端（BDS）",
            subtitle = "官方下载 API 的当前正式版 / 预览版，点开在浏览器下载",
        ) {
            when {
                loading -> CircularProgressIndicator(color = Accent, modifier = Modifier.size(24.dp))
                error != null -> Text("获取失败：$error", color = SubColor, fontSize = 12.sp)
                links.isEmpty() -> EmptyHint("官方接口暂时没有返回版本")
                else -> Column {
                    links.forEach { link ->
                        Row(
                            Modifier.fillMaxWidth().padding(vertical = 8.dp),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Column(Modifier.weight(1f)) {
                                Text(link.version, color = TextColor, fontSize = 14.sp)
                                Text(link.kind, color = SubColor, fontSize = 11.sp)
                            }
                            TextButton(onClick = { openUrl(ctx, link.url) }) { Text("下载") }
                        }
                        HorizontalDivider(color = Color(0xFF232935))
                    }
                }
            }
        }

        Spacer(Modifier.height(24.dp))
    }
}

// --------------------------------------------------------------------------- //
// 模组 / 光影 / 资源包
// --------------------------------------------------------------------------- //

@Composable
private fun ContentScreen() {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var query by remember { mutableStateOf("") }
    var kind by rememberSaveable { mutableStateOf("mod") }
    var hits by remember { mutableStateOf<List<Api.ModHit>>(emptyList()) }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var searched by remember { mutableStateOf(false) }
    var detail by remember { mutableStateOf<Api.ModHit?>(null) }

    fun doSearch(q: String = query, idx: String = "relevance") {
        loading = true
        error = null
        searched = true
        scope.launch {
            withContext(Dispatchers.IO) {
                runCatching { Api.searchMods(q, kind, 25, idx) }
                    .onSuccess {
                        hits = it
                        if (q.isEmpty()) Cache.mods = it
                    }
                    .onFailure { error = it.message; hits = emptyList() }
            }
            loading = false
        }
    }

    LaunchedEffect(Unit) {
        if (hits.isEmpty()) {
            val cached = Cache.mods
            if (cached != null) {
                hits = cached
                searched = true
            } else {
                doSearch("", "downloads")
            }
        }
    }

    Column(Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
        PageTitle("内容下载", "数据来自 Modrinth · 搜索后跳转项目页")

        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = query,
                onValueChange = { query = it },
                modifier = Modifier.weight(1f),
                singleLine = true,
                label = { Text("搜索") },
            )
            Spacer(Modifier.width(8.dp))
            Button(onClick = { doSearch() }, enabled = !loading) { Text("搜索") }
        }

        Spacer(Modifier.height(8.dp))

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            FilterChip(selected = kind == "mod", onClick = { kind = "mod" }, label = { Text("模组") })
            FilterChip(selected = kind == "shader", onClick = { kind = "shader" }, label = { Text("光影") })
            FilterChip(selected = kind == "resourcepack", onClick = { kind = "resourcepack" }, label = { Text("资源包") })
        }

        Spacer(Modifier.height(4.dp))

        when {
            loading -> Box(Modifier.fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = Accent)
            }
            !searched -> EmptyHint("输入关键词后点搜索，比如 sodium、iris、faithful")
            error != null -> EmptyHint("搜索失败：$error")
            hits.isEmpty() -> EmptyHint("没有结果")
            else -> LazyColumn(Modifier.fillMaxSize()) {
                items(hits, key = { it.id }) { hit ->
                    Column(
                        Modifier
                            .fillMaxWidth()
                            .clickable { detail = hit }
                            .padding(vertical = 10.dp)
                    ) {
                        Text(hit.title, color = TextColor, fontSize = 15.sp, fontWeight = FontWeight.Medium)
                        Spacer(Modifier.height(2.dp))
                        Text(
                            hit.description,
                            color = SubColor, fontSize = 12.sp,
                            maxLines = 2, overflow = TextOverflow.Ellipsis,
                        )
                        Spacer(Modifier.height(4.dp))
                        Text("下载 ${hit.downloads}", color = SubColor, fontSize = 11.sp)
                        Text(
                            Api.modrinthUrl(hit),
                            color = Accent, fontSize = 10.sp,
                            maxLines = 1, overflow = TextOverflow.Ellipsis,
                        )
                        Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                            TextButton(onClick = { detail = hit }) { Text("解析下载直链", fontSize = 12.sp) }
                            TextButton(onClick = { openUrl(ctx, Api.modrinthUrl(hit)) }) {
                                Text("打开项目页", fontSize = 12.sp)
                            }
                        }
                    }
                    HorizontalDivider(color = Color(0xFF232935))
                }
            }
        }
    }

    val pick = detail
    if (pick != null) {
        ModDetailDialog(pick) { detail = null }
    }
}

@Composable
private fun ModDetailDialog(hit: Api.ModHit, onDismiss: () -> Unit) {
    val ctx = LocalContext.current
    val cache = Cache.versions[hit.id]
    var versions by remember { mutableStateOf(cache ?: emptyList()) }
    var loading by remember { mutableStateOf(cache == null) }
    var error by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(hit.id) {
        if (versions.isNotEmpty()) {
            loading = false
            return@LaunchedEffect
        }
        withContext(Dispatchers.IO) {
            runCatching { Api.projectVersions(hit.id, 5) }
                .onSuccess {
                    versions = it
                    Cache.versions[hit.id] = it
                }
                .onFailure { error = it.message }
        }
        loading = false
    }

    androidx.compose.material3.AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(hit.title, fontSize = 16.sp) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                Text(Api.modrinthUrl(hit), color = Accent, fontSize = 11.sp)
                Spacer(Modifier.height(8.dp))
                when {
                    loading -> Row(verticalAlignment = Alignment.CenterVertically) {
                        CircularProgressIndicator(color = Accent, modifier = Modifier.size(20.dp))
                        Spacer(Modifier.width(8.dp))
                        Text("正在解析下载地址…", color = SubColor, fontSize = 12.sp)
                    }
                    error != null -> Text("解析失败：$error", color = SubColor, fontSize = 12.sp)
                    versions.isEmpty() -> Text("这个项目还没有可下载的文件", color = SubColor, fontSize = 12.sp)
                    else -> versions.forEach { v ->
                        val file = v.files.firstOrNull { it.primary } ?: v.files.firstOrNull()
                        Column(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
                            Text(v.versionNumber, color = TextColor, fontSize = 13.sp)
                            Text(
                                "${v.gameVersions.take(3).joinToString(" / ")} · ${v.loaders.joinToString("/")}",
                                color = SubColor, fontSize = 10.sp,
                            )
                            if (file != null) {
                                Text(
                                    "${file.name} · ${(file.size / 1024 / 1024)} MB",
                                    color = SubColor, fontSize = 10.sp,
                                    maxLines = 1, overflow = TextOverflow.Ellipsis,
                                )
                                Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                                    TextButton(onClick = { copyText(ctx, file.url, "下载直链") }) {
                                        Text("复制直链", fontSize = 11.sp)
                                    }
                                    TextButton(onClick = { openUrl(ctx, file.url) }) {
                                        Text("下载", fontSize = 11.sp)
                                    }
                                }
                            }
                        }
                        HorizontalDivider(color = Color(0xFF232935))
                    }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = { copyText(ctx, Api.modrinthUrl(hit), "项目页") }) { Text("复制项目页") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("关闭") } },
    )
}

// --------------------------------------------------------------------------- //
// 联机
// --------------------------------------------------------------------------- //

@Composable
private fun OnlineScreen() {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var address by remember { mutableStateOf("") }
    var loading by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf<Api.ServerStatus?>(null) }
    var error by remember { mutableStateOf<String?>(null) }

    fun ping() {
        val text = address.trim()
        if (text.isEmpty()) return
        val host = if (text.contains(":")) text.substringBeforeLast(":") else text
        val port = if (text.contains(":")) text.substringAfterLast(":").toIntOrNull() ?: 25565 else 25565
        loading = true
        error = null
        status = null
        scope.launch {
            withContext(Dispatchers.IO) {
                runCatching { Api.pingServer(host, port) }
                    .onSuccess { status = it }
                    .onFailure { error = it.message ?: "连接失败" }
            }
            loading = false
        }
    }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
        PageTitle("联机", "检测服务器 · 复制地址 · 分享给朋友")

        SectionCard(
            title = "服务器 / 房间地址",
            subtitle = "桌面版开房后会给类似 bore.pub:57163 的地址，粘到这里即可检测",
        ) {
            Column {
                OutlinedTextField(
                    value = address,
                    onValueChange = { address = it },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    label = { Text("host:port，例如 bore.pub:57163") },
                )
                Spacer(Modifier.height(10.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { ping() }, enabled = !loading && address.isNotBlank()) { Text("检测状态") }
                    TextButton(onClick = {
                        if (address.isNotBlank()) copyText(ctx, address, "服务器地址")
                    }) { Text("复制地址") }
                    TextButton(onClick = {
                        if (address.isNotBlank()) shareText(ctx, address)
                    }) { Text("分享") }
                }
            }
        }

        Spacer(Modifier.height(12.dp))

        when {
            loading -> Box(Modifier.fillMaxWidth().padding(24.dp), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = Accent)
            }
            error != null -> SectionCard(title = "连接失败", subtitle = error) {
                Text("检查地址是否正确、服务器是否已开房、网络是否能直连。", color = SubColor, fontSize = 12.sp)
            }
            status != null -> {
                val s = status!!
                SectionCard(title = "在线", subtitle = "${s.latencyMs} ms · ${s.version}") {
                    Column {
                        Text("玩家：${s.online} / ${s.max}", color = TextColor, fontSize = 14.sp)
                        Spacer(Modifier.height(6.dp))
                        Text(s.motd, color = SubColor, fontSize = 13.sp)
                    }
                }
            }
        }

        Spacer(Modifier.height(12.dp))

        SectionCard(
            title = "怎么开房",
            subtitle = "安卓端只做客户端侧；开房需要桌面版 MC Lite 或自建服务器",
        ) {
            Text(
                "1. 在电脑上打开 MC Lite（桌面版），进游戏后「对局域网开放」\n" +
                    "2. 启动器识别端口后点「公网联机」，会得到 bore.pub:端口\n" +
                    "3. 把这个地址发给朋友，在「多人游戏 → 直接连接」里填入\n\n" +
                    "bore 是免费公共隧道，不需要注册；地址在启动器关闭后失效。",
                color = SubColor, fontSize = 12.sp
            )
        }

        Spacer(Modifier.height(24.dp))
    }
}
