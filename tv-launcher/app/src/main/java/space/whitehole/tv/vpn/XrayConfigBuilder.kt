package space.whitehole.tv.vpn

import org.json.JSONArray
import org.json.JSONObject

/** Параметры сборки конфига ядра. */
class CoreOptions(
    /** geoip.dat (только RU) лежит на диске — тогда правила geoip:ru работают; иначе geoip-записи выкидываются. */
    val geoipRu: Boolean,
    val mtu: Int = 1500,
    val logLevel: String = "warning",
    /** Профиль маршрутизации Happ (assets/routing/happ-routing.json); по умолчанию — встроенный запасной. */
    val profile: RoutingProfile = RuRouting.DEFAULT,
)

/**
 * Упрощённый профиль маршрутизации v1 (по мотивам профиля Happ «WhiteHoleVPN» из infra/happ-routing.json):
 * всё через VPN, кроме локальной сети, российских доменов/сервисов и российских IP (geoip:ru).
 * YouTube/Google/Telegram — всегда через VPN (правило стоит раньше «напрямую», как RouteOrder block-proxy-direct).
 */
object RuRouting {
    const val DOMESTIC_DNS = "77.88.8.8"
    val REMOTE_DNS = listOf("1.1.1.1", "8.8.8.8")

    val PRIVATE_IP = listOf(
        "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16",
        "172.16.0.0/12", "192.168.0.0/16", "224.0.0.0/4", "255.255.255.255/32",
        "::1/128", "fc00::/7", "fe80::/10", "ff00::/8",
    )

    val PROXY_DOMAINS = listOf(
        "youtube.com", "youtu.be", "googlevideo.com", "ytimg.com", "ggpht.com", "youtube-nocookie.com",
        "youtubei.googleapis.com", "googleapis.com", "google.com", "google.ru", "gstatic.com", "googleusercontent.com",
        "telegram.org", "t.me", "telegram.me", "cdn-telegram.org", "telesco.pe",
    ).map { "domain:$it" }

    val DIRECT_DOMAINS = listOf(
        // национальные зоны
        "ru", "su", "xn--p1ai", "xn--d1acj3b",
        // Яндекс
        "yandex.net", "yandex.com", "yandex.by", "yandex.kz", "yandex.uz", "yandex.cloud", "yandex.st",
        "yastatic.net", "yastat.net", "yandexcloud.net", "yandexmetrica.com", "yandex-bank.net", "naydex.net",
        // VK / Mail / OK / Max
        "vk.com", "vk.me", "vk.cc", "vk.link", "vk.company", "vkontakte.com", "userapi.com", "vk-cdn.net", "vk-cdn.me",
        "vkuser.net", "vkuseraudio.net", "vkuservideo.net", "vkuserlive.net", "vkcache.com", "mycdn.me",
        // банки, госуслуги, магазины
        "sberbank.com", "tbank-online.com", "vtb.com", "alfabank.com", "alfa-bank.com", "gazprombank.tech",
        "ozon.st", "ozon.tech", "ozonusercontent.com", "wbcdn.net", "avito.st", "x5static.net", "lmru.tech",
        "megamarket.tech", "emias.info", "rzd.com", "pobeda.aero", "moex.com",
        // кино и ТВ
        "ivi.tv", "ivi.io", "okko.tv", "okko.sport", "more.tv", "premier.one", "kinescope.io", "kinescopecdn.net",
        "1internet.tv", "russia.tv", "vgtrk.com", "ren.tv", "rt.com",
        // карты, сервисы
        "2gis.com", "gismeteo.com", "kaspersky.com", "drweb.com", "timeweb.cloud", "tilda.cc",
        // игры (низкий пинг напрямую)
        "steamcontent.com", "steamserver.net", "steampowered.com", "steamstatic.com", "valve.net", "valvesoftware.com",
    ).map { "domain:$it" }

    /** Сети Valve (игровые серверы) — напрямую, как в профиле Happ. */
    val DIRECT_IP = listOf(
        "77.88.8.8/32", "77.88.8.1/32",
        "155.133.224.0/19", "162.254.192.0/21", "185.25.180.0/22", "146.66.152.0/21", "208.64.200.0/22",
        "208.78.164.0/22", "103.10.124.0/23", "103.28.54.0/23", "192.69.96.0/22", "190.217.32.0/22",
        "205.196.6.0/24", "45.121.184.0/22",
    )

    /** Запасной профиль, если assets/routing/happ-routing.json не прочитался. */
    val DEFAULT = RoutingProfile(
        name = "builtin", globalProxy = true,
        remoteDnsType = "DoH", remoteDnsDomain = "https://cloudflare-dns.com/dns-query", remoteDnsIp = "1.1.1.1",
        domesticDnsType = "DoU", domesticDnsDomain = "", domesticDnsIp = DOMESTIC_DNS,
        dnsHosts = emptyMap(),
        directSites = DIRECT_DOMAINS, directIp = listOf("geoip:ru") + DIRECT_IP,
        proxySites = PROXY_DOMAINS, proxyIp = emptyList(),
        blockSites = emptyList(), blockIp = emptyList(),
        domainStrategy = "IPIfNonMatch", routeOrder = listOf("block", "proxy", "direct"),
    )
}

/** Собирает JSON-конфиг Xray: вход tun (fd от VpnService), выход VLESS из ссылки, DNS и правила. */
object XrayConfigBuilder {
    const val TAG_PROXY = "proxy"
    const val TAG_DIRECT = "direct"
    const val TAG_BLOCK = "block"
    const val TAG_DNS = "dns-out"
    const val TAG_TUN = "tun"

    fun build(link: VlessLink, opt: CoreOptions): String = buildJson(link, opt).toString()

    fun buildJson(link: VlessLink, opt: CoreOptions): JSONObject {
        val root = JSONObject()
        root.put("log", JSONObject().put("loglevel", opt.logLevel))
        root.put("dns", dns(link, opt))
        root.put("inbounds", JSONArray().put(tunInbound(opt)))
        root.put(
            "outbounds", JSONArray()
                .put(outbound(link))
                .put(
                    JSONObject().put("tag", TAG_DIRECT).put("protocol", "freedom")
                        .put(
                            "streamSettings",
                            JSONObject().put("sockopt", JSONObject().put("domainStrategy", "UseIPv4"))
                        )
                )
                .put(JSONObject().put("tag", TAG_BLOCK).put("protocol", "blackhole"))
                .put(JSONObject().put("tag", TAG_DNS).put("protocol", "dns"))
        )
        root.put("routing", routing(link, opt))
        root.put(
            "policy", JSONObject().put(
                "levels", JSONObject().put(
                    "8", JSONObject().put("handshake", 4).put("connIdle", 300).put("uplinkOnly", 1).put("downlinkOnly", 1)
                )
            )
        )
        return root
    }

    private fun tunInbound(opt: CoreOptions): JSONObject = JSONObject()
        .put("tag", TAG_TUN)
        .put("port", 0)
        .put("protocol", "tun")
        .put("settings", JSONObject().put("name", "xray0").put("mtu", opt.mtu).put("userLevel", 8))
        .put(
            "sniffing", JSONObject()
                .put("enabled", true)
                .put("destOverride", JSONArray().put("http").put("tls").put("quic"))
                .put("routeOnly", false)
        )

    /** Домены: без geosite:/ext: (своей geosite-базы с категориями нет). */
    fun sites(list: List<String>): List<String> =
        list.filter { e -> val l = e.lowercase(); !l.startsWith("geosite:") && !l.startsWith("ext:") }

    /** IP: geoip:ru — только если файл есть; другие geoip-коды в компактной базе отсутствуют. */
    fun ips(list: List<String>, geoipRu: Boolean): List<String> = list.filter { e ->
        val l = e.lowercase()
        when {
            l.startsWith("geoip:") -> geoipRu && l == "geoip:ru"
            l.startsWith("ext:") -> false
            else -> true
        }
    }

    private fun dns(link: VlessLink, opt: CoreOptions): JSONObject {
        val p = opt.profile
        val domestic = arr(sites(p.directSites).filter { it !in p.proxySites })
        // адрес сервера-доменом резолвим российским DNS напрямую (иначе — петля через сам VPN)
        if (!isIp(link.address)) domestic.put("full:" + link.address)
        val servers = JSONArray()
        servers.put(JSONObject().put("address", p.domesticDnsAddress()).put("domains", domestic).put("skipFallback", true))
        // удалённый DNS (DoH Cloudflare по IP) — через VPN; запасной — обычный 1.1.1.1
        servers.put(p.remoteDnsAddress())
        if (p.remoteDnsAddress() != "1.1.1.1") servers.put("1.1.1.1")
        val dns = JSONObject().put("servers", servers).put("queryStrategy", "UseIPv4")
        if (p.dnsHosts.isNotEmpty()) {
            val h = JSONObject()
            p.dnsHosts.forEach { (k, v) -> h.put(k, v) }
            dns.put("hosts", h)
        }
        return dns
    }

    private fun routing(link: VlessLink, opt: CoreOptions): JSONObject {
        val p = opt.profile
        val rules = JSONArray()
        // DNS-запросы телевизора — в DNS-модуль Xray
        rules.put(rule().put("inboundTag", JSONArray().put(TAG_TUN)).put("port", "53").put("outboundTag", TAG_DNS))
        rules.put(rule().put("ip", arr(RuRouting.PRIVATE_IP)).put("outboundTag", TAG_DIRECT))
        if (!isIp(link.address)) {
            rules.put(rule().put("domain", JSONArray().put("full:" + link.address)).put("outboundTag", TAG_DIRECT))
        }
        // российский DNS всегда напрямую
        val domesticIp = p.domesticDnsIp.takeIf { isIp(it) }
        if (domesticIp != null) rules.put(rule().put("ip", JSONArray().put("$domesticIp/32")).put("outboundTag", TAG_DIRECT))
        // RouteOrder профиля (по умолчанию block-proxy-direct)
        for (group in p.routeOrder) {
            val (domains, ipList, tag) = when (group) {
                "block" -> Triple(p.blockSites, p.blockIp, TAG_BLOCK)
                "proxy" -> Triple(p.proxySites, p.proxyIp, TAG_PROXY)
                else -> Triple(p.directSites, p.directIp, TAG_DIRECT)
            }
            val d = sites(domains)
            if (d.isNotEmpty()) rules.put(rule().put("domain", arr(d)).put("outboundTag", tag))
            val i = ips(ipList, opt.geoipRu)
            if (i.isNotEmpty()) rules.put(rule().put("ip", arr(i)).put("outboundTag", tag))
        }
        // QUIC через VPN не нужен (Vision его не пропускает) — сразу отказ, приложения перейдут на TCP
        rules.put(rule().put("network", "udp").put("port", "443").put("outboundTag", TAG_BLOCK))
        rules.put(rule().put("network", "tcp,udp").put("outboundTag", if (p.globalProxy) TAG_PROXY else TAG_DIRECT))
        return JSONObject().put("domainStrategy", p.domainStrategy).put("rules", rules)
    }

    fun outbound(link: VlessLink): JSONObject {
        val settings = JSONObject()
            .put("address", link.address)
            .put("port", link.port)
            .put("id", link.uuid)
            .put("encryption", link.param("encryption") ?: "none")
            .put("level", 8)
        if (link.flow.isNotEmpty()) settings.put("flow", link.flow)

        val stream = JSONObject().put("network", link.network)
        when (link.network) {
            "xhttp" -> {
                val x = JSONObject()
                link.param("path")?.let { x.put("path", it) }
                link.param("host")?.let { x.put("host", it) }
                x.put("mode", link.param("mode") ?: "auto")
                link.param("extra")?.let { e ->
                    try {
                        x.put("extra", JSONObject(e))
                    } catch (ex: Exception) {
                        // битый extra — без него
                    }
                }
                stream.put("xhttpSettings", x)
            }
            "grpc" -> {
                val g = JSONObject()
                g.put("serviceName", link.param("serviceName") ?: "")
                g.put("multiMode", link.param("mode") == "multi")
                link.param("authority")?.let { g.put("authority", it) }
                stream.put("grpcSettings", g)
            }
            "ws" -> {
                val w = JSONObject().put("path", link.param("path") ?: "/")
                link.param("host")?.let { w.put("host", it) }
                stream.put("wsSettings", w)
            }
            "httpupgrade" -> {
                val h = JSONObject().put("path", link.param("path") ?: "/")
                link.param("host")?.let { h.put("host", it) }
                stream.put("httpupgradeSettings", h)
            }
        }

        when (link.security) {
            "reality" -> {
                stream.put("security", "reality")
                val r = JSONObject()
                    .put("serverName", link.sni)
                    .put("fingerprint", link.param("fp") ?: "chrome")
                    .put("publicKey", link.param("pbk") ?: "")
                    .put("shortId", link.param("sid") ?: "")
                link.param("spx")?.let { r.put("spiderX", it) }
                link.param("pqv")?.let { r.put("mldsa65Verify", it) }
                stream.put("realitySettings", r)
            }
            "tls" -> {
                stream.put("security", "tls")
                val t = JSONObject().put("fingerprint", link.param("fp") ?: "chrome")
                if (link.sni.isNotEmpty()) t.put("serverName", link.sni)
                link.param("alpn")?.let { a -> t.put("alpn", arr(a.split(',').map { it.trim() }.filter { it.isNotEmpty() })) }
                link.param("pcs")?.let { t.put("pinnedPeerCertSha256", it) }
                stream.put("tlsSettings", t)
            }
            else -> stream.put("security", "none")
        }

        return JSONObject()
            .put("tag", TAG_PROXY)
            .put("protocol", "vless")
            .put("settings", settings)
            .put("streamSettings", stream)
            .put("mux", JSONObject().put("enabled", false))
    }

    private fun rule(): JSONObject = JSONObject().put("type", "field")

    private fun arr(items: List<String>): JSONArray {
        val a = JSONArray()
        items.forEach { a.put(it) }
        return a
    }

    fun isIp(s: String): Boolean {
        if (s.contains(':')) return true // IPv6
        val parts = s.split('.')
        return parts.size == 4 && parts.all { p -> p.isNotEmpty() && p.length <= 3 && p.all { it.isDigit() } && p.toInt() <= 255 }
    }
}
