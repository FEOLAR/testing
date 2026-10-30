package space.whitehole.tv.vpn

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.URLEncoder
import java.util.Base64

/** Все UUID/ключи здесь выдуманные — только формат как у Remnawave. */
class ShareLinkParserTest {

    private val uuid = "11111111-2222-3333-4444-555555555555"

    private fun enc(s: String) = URLEncoder.encode(s, "UTF-8").replace("+", "%20")

    private val tcp = "vless://$uuid@203.0.113.10:443?security=reality&type=tcp&headerType=none" +
        "&flow=xtls-rprx-vision&sni=originfi.example.org&fp=firefox&pbk=AbCdEf-GhIj_KlMn0123456789abcdefABCDEFghij" +
        "&sid=0a1b2c3d&spx=%2F#" + enc("⚡ Авто — 📱 для телефона")
    private val xhttp = "vless://$uuid@203.0.113.10:8443?security=reality&type=xhttp&path=%2Fapi%2Fv2%2Fstream" +
        "&mode=auto&sni=originfi.example.org&fp=firefox&pbk=AbCdEf&sid=0a1b&extra=" +
        enc("{\"xmux\":{\"maxConcurrency\":\"16-32\"}}") + "#" + enc("⚡ Авто — 💻 для ПК")
    private val grpc = "vless://$uuid@[2001:db8::1]:2053?security=reality&type=grpc&serviceName=grpcsvc&mode=gun" +
        "&sni=originfi.example.org&fp=firefox&pbk=AbCdEf&sid=0a1b#" + enc("🇫🇷 Франция — gRPC")

    @Test
    fun parsesRealityTcpVision() {
        val l = ShareLinkParser.parseVless(tcp)
        assertNotNull(l)
        l!!
        assertEquals(uuid, l.uuid)
        assertEquals("203.0.113.10", l.address)
        assertEquals(443, l.port)
        assertEquals("tcp", l.network)
        assertEquals("reality", l.security)
        assertEquals("xtls-rprx-vision", l.flow)
        assertEquals("originfi.example.org", l.sni)
        assertEquals("firefox", l.param("fp"))
        assertEquals("AbCdEf-GhIj_KlMn0123456789abcdefABCDEFghij", l.param("pbk"))
        assertEquals("0a1b2c3d", l.param("sid"))
        assertEquals("/", l.param("spx"))
        assertEquals("⚡ Авто — 📱 для телефона", l.remark)
    }

    @Test
    fun parsesXhttpWithExtraAndPath() {
        val l = ShareLinkParser.parseVless(xhttp)!!
        assertEquals("xhttp", l.network)
        assertEquals(8443, l.port)
        assertEquals("/api/v2/stream", l.param("path"))
        assertEquals("{\"xmux\":{\"maxConcurrency\":\"16-32\"}}", l.param("extra"))
    }

    @Test
    fun parsesIpv6AndGrpc() {
        val l = ShareLinkParser.parseVless(grpc)!!
        assertEquals("2001:db8::1", l.address)
        assertEquals(2053, l.port)
        assertEquals("grpc", l.network)
        assertEquals("grpcsvc", l.param("serviceName"))
    }

    @Test
    fun commaSeparatedAddressTakesFirst() {
        val l = ShareLinkParser.parseVless("vless://$uuid@198.51.100.1,198.51.100.2:443?type=tcp&security=none#x")!!
        assertEquals("198.51.100.1", l.address)
    }

    @Test
    fun rejectsGarbage() {
        assertNull(ShareLinkParser.parseVless("vmess://abc"))
        assertNull(ShareLinkParser.parseVless("vless://nohost"))
        assertNull(ShareLinkParser.parseVless("vless://$uuid@1.2.3.4:99999?type=tcp"))
        assertNull(ShareLinkParser.parseVless("vless://$uuid@1.2.3.4?type=tcp"))
    }

    @Test
    fun decodesBase64Subscription() {
        val body = listOf(tcp, xhttp, "trojan://pw@1.2.3.4:443#t", grpc).joinToString("\n")
        val b64 = Base64.getEncoder().encodeToString(body.toByteArray())
        val links = ShareLinkParser.parseSubscription(b64)
        assertEquals(3, links.size)
        // URL-safe и без паддинга тоже
        val urlSafe = Base64.getUrlEncoder().withoutPadding().encodeToString(body.toByteArray())
        assertEquals(3, ShareLinkParser.parseSubscription(urlSafe).size)
        // уже расшифрованный текст
        assertEquals(3, ShareLinkParser.parseSubscription(body).size)
    }

    @Test
    fun base64RoundTrip() {
        for (s in listOf("a", "ab", "abc", "abcd", "Привет, мир! ⚡")) {
            val e = Base64.getEncoder().encodeToString(s.toByteArray())
            assertEquals(s, String(ShareLinkParser.base64Decode(e)!!))
        }
        assertNull(ShareLinkParser.base64Decode("not base64 at all!"))
    }

    @Test
    fun percentDecodeKeepsPlus() {
        assertEquals("a+b c", ShareLinkParser.percentDecode("a+b%20c"))
        assertEquals("Франция", ShareLinkParser.percentDecode(enc("Франция")))
        assertEquals("100%", ShareLinkParser.percentDecode("100%"))
    }

    @Test
    fun parsesXrayJsonFallback() {
        val json = """
            [{"remarks":"🇩🇪 Германия","outbounds":[{"tag":"proxy","protocol":"vless",
              "settings":{"vnext":[{"address":"198.51.100.7","port":443,"users":[{"id":"$uuid","flow":"xtls-rprx-vision","encryption":"none"}]}]},
              "streamSettings":{"network":"tcp","security":"reality",
                "realitySettings":{"serverName":"sni.example.org","fingerprint":"firefox","publicKey":"PBK","shortId":"ab"}}},
              {"tag":"direct","protocol":"freedom"}]}]
        """.trimIndent()
        val links = ShareLinkParser.parseSubscription(json)
        assertEquals(1, links.size)
        val l = links[0]
        assertEquals("198.51.100.7", l.address)
        assertEquals("xtls-rprx-vision", l.flow)
        assertEquals("PBK", l.param("pbk"))
        assertEquals("sni.example.org", l.sni)
        assertTrue(l.remark.contains("Германия"))
    }
}
