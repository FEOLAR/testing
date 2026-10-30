package space.whitehole.tv.vpn

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class XrayConfigBuilderTest {

    private val uuid = "11111111-2222-3333-4444-555555555555"

    private fun parse(link: String) = ShareLinkParser.parseVless(link)!!

    private val tcp = parse(
        "vless://$uuid@203.0.113.10:443?security=reality&type=tcp&flow=xtls-rprx-vision&sni=sni.example.org" +
            "&fp=firefox&pbk=PBK_key-1&sid=0a1b&spx=%2F#Auto"
    )

    private fun cfg(link: VlessLink, geo: Boolean = true) = JSONObject(XrayConfigBuilder.build(link, CoreOptions(geoipRu = geo)))

    private fun JSONArray.objects() = (0 until length()).map { getJSONObject(it) }
    private fun JSONArray.strings() = (0 until length()).map { getString(it) }

    @Test
    fun realityTcpVisionOutbound() {
        val ob = cfg(tcp).getJSONArray("outbounds").getJSONObject(0)
        assertEquals("proxy", ob.getString("tag"))
        assertEquals("vless", ob.getString("protocol"))
        val s = ob.getJSONObject("settings")
        assertEquals("203.0.113.10", s.getString("address"))
        assertEquals(443, s.getInt("port"))
        assertEquals(uuid, s.getString("id"))
        assertEquals("none", s.getString("encryption"))
        assertEquals("xtls-rprx-vision", s.getString("flow"))
        val ss = ob.getJSONObject("streamSettings")
        assertEquals("tcp", ss.getString("network"))
        assertEquals("reality", ss.getString("security"))
        val r = ss.getJSONObject("realitySettings")
        assertEquals("sni.example.org", r.getString("serverName"))
        assertEquals("firefox", r.getString("fingerprint"))
        assertEquals("PBK_key-1", r.getString("publicKey"))
        assertEquals("0a1b", r.getString("shortId"))
        assertEquals("/", r.getString("spiderX"))
    }

    @Test
    fun xhttpOutbound() {
        val l = parse(
            "vless://$uuid@203.0.113.10:8443?security=reality&type=xhttp&path=%2Fapi%2Fv2%2Fstream&mode=auto" +
                "&sni=s.example.org&fp=firefox&pbk=P&sid=1&extra=%7B%22xmux%22%3A%7B%22maxConcurrency%22%3A%2216-32%22%7D%7D#x"
        )
        val ss = cfg(l).getJSONArray("outbounds").getJSONObject(0).getJSONObject("streamSettings")
        assertEquals("xhttp", ss.getString("network"))
        val x = ss.getJSONObject("xhttpSettings")
        assertEquals("/api/v2/stream", x.getString("path"))
        assertEquals("auto", x.getString("mode"))
        assertEquals("16-32", x.getJSONObject("extra").getJSONObject("xmux").getString("maxConcurrency"))
        assertFalse(cfg(l).getJSONArray("outbounds").getJSONObject(0).getJSONObject("settings").has("flow"))
    }

    @Test
    fun grpcOutbound() {
        val l = parse("vless://$uuid@203.0.113.10:2053?security=reality&type=grpc&serviceName=svc&mode=multi&sni=s&pbk=P&sid=1#g")
        val g = cfg(l).getJSONArray("outbounds").getJSONObject(0).getJSONObject("streamSettings").getJSONObject("grpcSettings")
        assertEquals("svc", g.getString("serviceName"))
        assertTrue(g.getBoolean("multiMode"))
    }

    @Test
    fun tunInboundAndDnsHijack() {
        val c = cfg(tcp)
        val inb = c.getJSONArray("inbounds").getJSONObject(0)
        assertEquals("tun", inb.getString("protocol"))
        assertTrue(inb.getJSONObject("sniffing").getBoolean("enabled"))
        val first = c.getJSONObject("routing").getJSONArray("rules").getJSONObject(0)
        assertEquals("53", first.getString("port"))
        assertEquals("dns-out", first.getString("outboundTag"))
        assertTrue(c.getJSONArray("outbounds").objects().any { it.getString("protocol") == "dns" })
        assertEquals("UseIPv4", c.getJSONObject("dns").getString("queryStrategy"))
    }

    @Test
    fun routingOrderProxyBeforeDirect() {
        val rules = cfg(tcp).getJSONObject("routing").getJSONArray("rules").objects()
        val proxyIdx = rules.indexOfFirst { it.optJSONArray("domain")?.strings()?.contains("domain:youtube.com") == true }
        val directIdx = rules.indexOfFirst { it.optJSONArray("domain")?.strings()?.contains("domain:ru") == true }
        assertTrue(proxyIdx in 0 until directIdx)
        assertEquals("proxy", rules[proxyIdx].getString("outboundTag"))
        assertEquals("direct", rules[directIdx].getString("outboundTag"))
        assertTrue(rules[directIdx].getJSONArray("domain").strings().containsAll(listOf("domain:su", "domain:xn--p1ai", "domain:yandex.net", "domain:vk.com")))
        val last = rules.last()
        assertEquals("proxy", last.getString("outboundTag"))
        // локальная сеть — напрямую, раньше прокси-правил
        val privIdx = rules.indexOfFirst { it.optJSONArray("ip")?.strings()?.contains("192.168.0.0/16") == true }
        assertTrue(privIdx in 0 until proxyIdx)
    }

    @Test
    fun geoipRuOnlyWhenAvailable() {
        fun hasGeo(c: JSONObject) = c.getJSONObject("routing").getJSONArray("rules").objects()
            .any { it.optJSONArray("ip")?.strings()?.contains("geoip:ru") == true }
        assertTrue(hasGeo(cfg(tcp, geo = true)))
        assertFalse(hasGeo(cfg(tcp, geo = false)))
        // geoip:private в компактной базе нет — не используем никогда
        assertFalse(XrayConfigBuilder.build(tcp, CoreOptions(true)).contains("geoip:private"))
    }

    @Test
    fun domainServerResolvedDirectly() {
        val l = parse("vless://$uuid@node.example.org:443?security=reality&type=tcp&sni=s&pbk=P&sid=1#d")
        val c = cfg(l)
        val dom = c.getJSONObject("dns").getJSONArray("servers").getJSONObject(0).getJSONArray("domains").strings()
        assertTrue(dom.contains("full:node.example.org"))
        assertTrue(XrayConfigBuilder.isIp("203.0.113.10"))
        assertFalse(XrayConfigBuilder.isIp("node.example.org"))
    }
}
