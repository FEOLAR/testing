package space.whitehole.tv.vpn

import org.json.JSONArray
import org.json.JSONObject

/**
 * Одна ссылка vless://uuid@host:port?параметры#название из подписки Remnawave.
 * Параметры — как в стандарте share-ссылок Xray (type, security, sni, fp, pbk, sid, spx, flow, path, mode, …).
 */
data class VlessLink(
    val uuid: String,
    val address: String,
    val port: Int,
    val remark: String,
    val params: Map<String, String>,
) {
    fun param(name: String): String? = params[name]?.takeIf { it.isNotEmpty() }

    /** tcp / xhttp / grpc / ws / httpupgrade (raw → tcp, splithttp → xhttp). */
    val network: String
        get() = when (val t = (param("type") ?: "tcp").lowercase()) {
            "raw" -> "tcp"
            "splithttp" -> "xhttp"
            else -> t
        }

    val security: String get() = (param("security") ?: "none").lowercase()
    val flow: String get() = param("flow") ?: ""
    val sni: String get() = param("sni") ?: param("serverName") ?: ""

    override fun toString(): String = "vless[$remark $network/$security port=$port]" // без uuid и ключей — для логов
}

object ShareLinkParser {

    /** Тело подписки: base64 со ссылками, просто ссылки построчно или JSON (Xray JSON от Remnawave). */
    fun parseSubscription(body: String): List<VlessLink> {
        val text = body.trim().removePrefix("﻿")
        if (text.isEmpty()) return emptyList()
        if (text.startsWith("[") || text.startsWith("{")) {
            val fromJson = parseXrayJson(text)
            if (fromJson.isNotEmpty()) return fromJson
        }
        return decodeSubscriptionText(text).lineSequence()
            .map { it.trim() }
            .filter { it.isNotEmpty() }
            .mapNotNull { parseVless(it) }
            .toList()
    }

    /** Если тело — base64, вернуть расшифрованный текст, иначе как есть. */
    fun decodeSubscriptionText(body: String): String {
        val t = body.trim()
        if (t.contains("://")) return t
        val bytes = base64Decode(t) ?: return t
        return String(bytes, Charsets.UTF_8)
    }

    fun parseVless(line: String): VlessLink? {
        val s = line.trim()
        if (!s.regionMatches(0, "vless://", 0, 8, ignoreCase = true)) return null
        var rest = s.substring(8)
        var remark = ""
        val hash = rest.indexOf('#')
        if (hash >= 0) {
            remark = percentDecode(rest.substring(hash + 1)).trim()
            rest = rest.substring(0, hash)
        }
        var query = ""
        val q = rest.indexOf('?')
        if (q >= 0) {
            query = rest.substring(q + 1)
            rest = rest.substring(0, q)
        }
        rest = rest.trimEnd('/')
        val at = rest.lastIndexOf('@')
        if (at <= 0) return null
        val uuid = percentDecode(rest.substring(0, at)).trim()
        val hostPort = rest.substring(at + 1)
        val host: String
        val portStr: String
        if (hostPort.startsWith("[")) {
            val end = hostPort.indexOf(']')
            if (end < 0) return null
            host = hostPort.substring(1, end)
            portStr = hostPort.substring(end + 1).removePrefix(":")
        } else {
            val colon = hostPort.lastIndexOf(':')
            if (colon <= 0) return null
            host = hostPort.substring(0, colon)
            portStr = hostPort.substring(colon + 1)
        }
        val port = portStr.toIntOrNull() ?: return null
        if (port !in 1..65535) return null
        // Remnawave сам выбирает один адрес из «a,b,c», но на всякий случай берём первый
        val address = percentDecode(host).split(',').map { it.trim() }.firstOrNull { it.isNotEmpty() } ?: return null
        if (uuid.isEmpty()) return null
        val params = LinkedHashMap<String, String>()
        if (query.isNotEmpty()) {
            for (pair in query.split('&')) {
                if (pair.isEmpty()) continue
                val eq = pair.indexOf('=')
                val k = percentDecode(if (eq >= 0) pair.substring(0, eq) else pair)
                val v = if (eq >= 0) percentDecode(pair.substring(eq + 1)) else ""
                if (k.isNotEmpty() && !params.containsKey(k)) params[k] = v
            }
        }
        return VlessLink(uuid, address, port, remark, params)
    }

    /** %XX → байты UTF-8. «+» не трогаем (в pbk/extra он значимый). */
    fun percentDecode(s: String): String {
        if (s.indexOf('%') < 0) return s
        val out = java.io.ByteArrayOutputStream(s.length)
        var i = 0
        while (i < s.length) {
            val c = s[i]
            if (c == '%' && i + 2 < s.length) {
                val hi = Character.digit(s[i + 1], 16)
                val lo = Character.digit(s[i + 2], 16)
                if (hi >= 0 && lo >= 0) {
                    out.write(hi * 16 + lo)
                    i += 3
                    continue
                }
            }
            val len = if (Character.isHighSurrogate(c) && i + 1 < s.length) 2 else 1
            out.write(s.substring(i, i + len).toByteArray(Charsets.UTF_8))
            i += len
        }
        return String(out.toByteArray(), Charsets.UTF_8)
    }

    private const val B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"

    /** base64 (обычный и URL-safe, с паддингом и без, с переносами строк). null — не base64. */
    fun base64Decode(input: String): ByteArray? {
        val clean = StringBuilder(input.length)
        for (c in input) {
            when {
                c == '-' -> clean.append('+')
                c == '_' -> clean.append('/')
                c == '=' || c.isWhitespace() -> {}
                B64.indexOf(c) >= 0 -> clean.append(c)
                else -> return null
            }
        }
        if (clean.isEmpty() || clean.length % 4 == 1) return null
        val out = java.io.ByteArrayOutputStream(clean.length * 3 / 4)
        var buf = 0
        var bits = 0
        for (c in clean) {
            buf = (buf shl 6) or B64.indexOf(c)
            bits += 6
            if (bits >= 8) {
                bits -= 8
                out.write((buf shr bits) and 0xFF)
            }
        }
        return out.toByteArray()
    }

    // ---------- запасной формат: Xray JSON (если панель отдаст JSON вместо base64) ----------

    fun parseXrayJson(text: String): List<VlessLink> {
        val result = ArrayList<VlessLink>()
        try {
            val configs: JSONArray = if (text.trim().startsWith("[")) JSONArray(text) else JSONArray().put(JSONObject(text))
            for (i in 0 until configs.length()) {
                val cfg = configs.optJSONObject(i) ?: continue
                val remark = cfg.optString("remarks", "")
                val outbounds = cfg.optJSONArray("outbounds") ?: continue
                for (j in 0 until outbounds.length()) {
                    val ob = outbounds.optJSONObject(j) ?: continue
                    if (ob.optString("protocol") != "vless") continue
                    outboundToLink(ob, remark)?.let { result.add(it) }
                    break
                }
            }
        } catch (e: Exception) {
            return emptyList()
        }
        return result
    }

    private fun outboundToLink(ob: JSONObject, remark: String): VlessLink? {
        val settings = ob.optJSONObject("settings") ?: return null
        var address = settings.optString("address", "")
        var port = settings.optInt("port", 0)
        var user: JSONObject? = settings
        val vnext = settings.optJSONArray("vnext")
        if (vnext != null && vnext.length() > 0) {
            val v = vnext.optJSONObject(0) ?: return null
            address = v.optString("address", "")
            port = v.optInt("port", 0)
            user = v.optJSONArray("users")?.optJSONObject(0)
        }
        val id = user?.optString("id", "") ?: ""
        if (address.isEmpty() || port <= 0 || id.isEmpty()) return null
        val p = LinkedHashMap<String, String>()
        user?.optString("flow", "")?.takeIf { it.isNotEmpty() }?.let { p["flow"] = it }
        user?.optString("encryption", "")?.takeIf { it.isNotEmpty() }?.let { p["encryption"] = it }
        val ss = ob.optJSONObject("streamSettings") ?: JSONObject()
        p["type"] = ss.optString("network", "tcp").ifEmpty { "tcp" }
        val sec = ss.optString("security", "none").ifEmpty { "none" }
        p["security"] = sec
        val sec2 = if (sec == "reality") ss.optJSONObject("realitySettings") else ss.optJSONObject("tlsSettings")
        if (sec2 != null) {
            sec2.optString("serverName").takeIf { it.isNotEmpty() }?.let { p["sni"] = it }
            sec2.optString("fingerprint").takeIf { it.isNotEmpty() }?.let { p["fp"] = it }
            (sec2.optString("publicKey").ifEmpty { sec2.optString("password") }).takeIf { it.isNotEmpty() }?.let { p["pbk"] = it }
            sec2.optString("shortId").takeIf { it.isNotEmpty() }?.let { p["sid"] = it }
            sec2.optString("spiderX").takeIf { it.isNotEmpty() }?.let { p["spx"] = it }
            sec2.optString("mldsa65Verify").takeIf { it.isNotEmpty() }?.let { p["pqv"] = it }
        }
        when (p["type"]) {
            "xhttp", "splithttp" -> ss.optJSONObject("xhttpSettings")?.let { x ->
                x.optString("path").takeIf { it.isNotEmpty() }?.let { p["path"] = it }
                x.optString("host").takeIf { it.isNotEmpty() }?.let { p["host"] = it }
                x.optString("mode").takeIf { it.isNotEmpty() }?.let { p["mode"] = it }
                x.optJSONObject("extra")?.let { p["extra"] = it.toString() }
            }
            "grpc" -> ss.optJSONObject("grpcSettings")?.let { g ->
                g.optString("serviceName").takeIf { it.isNotEmpty() }?.let { p["serviceName"] = it }
                g.optString("authority").takeIf { it.isNotEmpty() }?.let { p["authority"] = it }
                if (g.optBoolean("multiMode", false)) p["mode"] = "multi"
            }
            "ws" -> ss.optJSONObject("wsSettings")?.let { w ->
                w.optString("path").takeIf { it.isNotEmpty() }?.let { p["path"] = it }
                w.optString("host").takeIf { it.isNotEmpty() }?.let { p["host"] = it }
            }
        }
        return VlessLink(id, address, port, remark, p)
    }
}
