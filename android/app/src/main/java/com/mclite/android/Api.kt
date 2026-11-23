package com.mclite.android

import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.io.OutputStream
import java.net.HttpURLConnection
import java.net.InetSocketAddress
import java.net.Socket
import java.net.URL
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

// --------------------------------------------------------------------------- //
// 网络与数据：只用系统自带的 HttpURLConnection / org.json，零第三方依赖
// --------------------------------------------------------------------------- //

object Api {
    private const val UA = "MCLite-Android/1.0 (+https://github.com/lingpanrui)"
    private const val MOJANG_MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
    private const val MODRINTH = "https://api.modrinth.com/v2"
    private const val BDS_LINKS = "https://net-secondary.web.minecraft-services.net/api/v1.0/download/links"

    private fun httpText(url: String, timeout: Int = 20000): String {
        val conn = URL(url).openConnection() as HttpURLConnection
        conn.connectTimeout = timeout
        conn.readTimeout = timeout
        conn.requestMethod = "GET"
        conn.setRequestProperty("User-Agent", UA)
        try {
            val code = conn.responseCode
            if (code !in 200..299) throw IllegalStateException("HTTP $code: $url")
            return conn.inputStream.bufferedReader(StandardCharsets.UTF_8).use { it.readText() }
        } finally {
            conn.disconnect()
        }
    }

    // ------------------------------ Mojang --------------------------------- //

    data class McVersion(
        val id: String,
        val type: String,
        val released: String,
        val jsonUrl: String,
    )

    data class Manifest(val latestRelease: String, val latestSnapshot: String, val versions: List<McVersion>)

    fun mojangManifest(): Manifest {
        val root = JSONObject(httpText(MOJANG_MANIFEST))
        val latest = root.optJSONObject("latest") ?: JSONObject()
        val arr = root.optJSONArray("versions") ?: JSONArray()
        val list = ArrayList<McVersion>(arr.length())
        for (i in 0 until arr.length()) {
            val o = arr.getJSONObject(i)
            list.add(
                McVersion(
                    id = o.optString("id"),
                    type = o.optString("type"),
                    released = o.optString("releaseTime").take(10),
                    jsonUrl = o.optString("url"),
                )
            )
        }
        return Manifest(latest.optString("release"), latest.optString("snapshot"), list)
    }

    // ------------------------------ 基岩 BDS -------------------------------- //

    data class BdsLink(val version: String, val kind: String, val url: String)

    fun bdsLinks(): List<BdsLink> {
        val root = JSONObject(httpText(BDS_LINKS, 30000))
        val result = root.optJSONObject("result") ?: JSONObject()
        val links = result.optJSONArray("links") ?: JSONArray()
        val out = ArrayList<BdsLink>()
        for (i in 0 until links.length()) {
            val o = links.getJSONObject(i)
            val type = o.optString("downloadType")
            val kind = when (type) {
                "serverBedrockWindows" -> "正式版"
                "serverBedrockPreviewWindows" -> "预览版"
                else -> continue
            }
            val url = o.optString("downloadUrl")
            if (url.isEmpty()) continue
            val file = url.substringAfterLast('/')
            val ver = Regex("bedrock-server-([0-9][0-9.]*)\\.zip").find(file)?.groupValues?.get(1) ?: file
            out.add(BdsLink(ver, kind, url))
        }
        return out
    }

    // ------------------------------ Modrinth ------------------------------- //

    data class ModHit(
        val id: String,
        val slug: String,
        val title: String,
        val description: String,
        val downloads: Long,
        val iconUrl: String,
        val projectType: String,
    )

    fun searchMods(query: String, projectType: String, limit: Int = 25, index: String = "relevance"): List<ModHit> {
        val q = URLEncoder.encode(query, "UTF-8")
        val facets = URLEncoder.encode("[[\"project_type:$projectType\"]]", "UTF-8")
        val url = "$MODRINTH/search?query=$q&limit=$limit&facets=$facets&index=$index"
        val root = JSONObject(httpText(url))
        val hits = root.optJSONArray("hits") ?: JSONArray()
        val out = ArrayList<ModHit>()
        for (i in 0 until hits.length()) {
            val o = hits.getJSONObject(i)
            out.add(
                ModHit(
                    id = o.optString("project_id"),
                    slug = o.optString("slug"),
                    title = o.optString("title"),
                    description = o.optString("description"),
                    downloads = o.optLong("downloads"),
                    iconUrl = o.optString("icon_url"),
                    projectType = projectType,
                )
            )
        }
        return out
    }

    fun modrinthUrl(hit: ModHit): String {
        val kind = when (hit.projectType) {
            "mod" -> "mod"
            "shader" -> "shader"
            "resourcepack" -> "resourcepack"
            else -> "project"
        }
        return "https://modrinth.com/$kind/${hit.slug}"
    }

    // -------------------- 项目版本 / 真实下载直链 --------------------------- //

    data class ModFile(
        val name: String,
        val url: String,
        val size: Long,
        val primary: Boolean,
    )

    data class ModVersion(
        val versionNumber: String,
        val gameVersions: List<String>,
        val loaders: List<String>,
        val files: List<ModFile>,
    )

    /** 拉取某个 Modrinth 项目的版本列表，里面的 files[].url 就是可直接下载的直链 */
    fun projectVersions(projectId: String, limit: Int = 6): List<ModVersion> {
        val url = "$MODRINTH/project/$projectId/version"
        val arr = JSONArray(httpText(url))
        val out = ArrayList<ModVersion>()
        for (i in 0 until minOf(arr.length(), limit)) {
            val o = arr.getJSONObject(i)
            val gv = o.optJSONArray("game_versions") ?: JSONArray()
            val ld = o.optJSONArray("loaders") ?: JSONArray()
            val files = o.optJSONArray("files") ?: JSONArray()
            val fileList = ArrayList<ModFile>()
            for (j in 0 until files.length()) {
                val f = files.getJSONObject(j)
                fileList.add(
                    ModFile(
                        name = f.optString("filename"),
                        url = f.optString("url"),
                        size = f.optLong("size"),
                        primary = f.optBoolean("primary"),
                    )
                )
            }
            out.add(
                ModVersion(
                    versionNumber = o.optString("version_number").ifEmpty { o.optString("name") },
                    gameVersions = (0 until gv.length()).map { gv.optString(it) },
                    loaders = (0 until ld.length()).map { ld.optString(it) },
                    files = fileList,
                )
            )
        }
        return out
    }

    // --------------------------- Java 服务器状态 ---------------------------- //

    data class ServerStatus(
        val version: String,
        val online: Int,
        val max: Int,
        val motd: String,
        val latencyMs: Long,
    )

    fun pingServer(host: String, port: Int, timeout: Int = 6000): ServerStatus {
        val started = System.currentTimeMillis()
        Socket().use { socket ->
            socket.connect(InetSocketAddress(host, port), timeout)
            socket.soTimeout = timeout

            val hs = ByteArrayOutputStream()
            writeVarInt(hs, 0x00)
            writeVarInt(hs, 47)          // 1.8 协议，任何现代服务端都接受
            writeString(hs, host)
            writeVarInt(hs, port)
            writeVarInt(hs, 1)           // status

            val out: OutputStream = socket.getOutputStream()
            writeVarInt(out, hs.size())
            out.write(hs.toByteArray())
            val req = ByteArrayOutputStream().apply { writeVarInt(this, 0x00) }
            writeVarInt(out, req.size())
            out.write(req.toByteArray())
            out.flush()

            val input: InputStream = socket.getInputStream()
            val length = readVarInt(input)
            if (length <= 0) throw IllegalStateException("服务端没有返回状态数据")
            val data = ByteArray(length)
            var read = 0
            while (read < length) {
                val n = input.read(data, read, length - read)
                if (n <= 0) throw IllegalStateException("连接被服务端关闭")
                read += n
            }

            val bis = ByteArrayInputStream(data)
            readVarInt(bis)                       // packet id
            val json = JSONObject(readString(bis))
            val players = json.optJSONObject("players") ?: JSONObject()
            val ver = json.optJSONObject("version") ?: JSONObject()
            val motd = flattenDescription(json.opt("description"))
            return ServerStatus(
                version = ver.optString("name"),
                online = players.optInt("online"),
                max = players.optInt("max"),
                motd = motd.ifEmpty { "（无描述）" },
                latencyMs = System.currentTimeMillis() - started,
            )
        }
    }

    private fun flattenDescription(node: Any?): String {
        return when (node) {
            null -> ""
            is String -> node
            is JSONObject -> {
                val sb = StringBuilder(node.optString("text"))
                val extra = node.optJSONArray("extra")
                if (extra != null) {
                    for (i in 0 until extra.length()) {
                        sb.append(flattenDescription(extra.get(i)))
                    }
                }
                sb.toString()
            }
            is JSONArray -> {
                val sb = StringBuilder()
                for (i in 0 until node.length()) sb.append(flattenDescription(node.get(i)))
                sb.toString()
            }
            else -> node.toString()
        }
    }

    // ------------------------------ varint --------------------------------- //

    private fun writeVarInt(out: OutputStream, value: Int) {
        var v = value
        while (true) {
            if (v and 0x7F.inv() == 0) {
                out.write(v)
                return
            }
            out.write((v and 0x7F) or 0x80)
            v = v ushr 7
        }
    }

    private fun writeVarInt(out: ByteArrayOutputStream, value: Int) {
        var v = value
        while (true) {
            if (v and 0x7F.inv() == 0) {
                out.write(v)
                return
            }
            out.write((v and 0x7F) or 0x80)
            v = v ushr 7
        }
    }

    private fun readVarInt(input: InputStream): Int {
        var result = 0
        var shift = 0
        while (true) {
            val b = input.read()
            if (b < 0) throw IllegalStateException("数据不完整")
            result = result or ((b and 0x7F) shl shift)
            if (b and 0x80 == 0) return result
            shift += 7
            if (shift > 35) throw IllegalStateException("varint 过长")
        }
    }

    private fun writeString(out: ByteArrayOutputStream, text: String) {
        val bytes = text.toByteArray(StandardCharsets.UTF_8)
        writeVarInt(out, bytes.size)
        out.write(bytes)
    }

    private fun readString(input: InputStream): String {
        val len = readVarInt(input)
        if (len <= 0 || len > 32767 * 4) return ""
        val bytes = ByteArray(len)
        var read = 0
        while (read < len) {
            val n = input.read(bytes, read, len - read)
            if (n <= 0) throw IllegalStateException("字符串读取失败")
            read += n
        }
        return String(bytes, StandardCharsets.UTF_8)
    }
}
