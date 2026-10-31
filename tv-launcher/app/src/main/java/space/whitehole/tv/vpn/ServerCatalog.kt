package space.whitehole.tv.vpn

/**
 * Сервер в списке «Сервер»: одна страна/«Авто»/резерв. Варианты «📱 для телефона» и «💻 для ПК»
 * одного хоста склеиваются в одну строку; внутри — ссылки по приоритету транспорта для ТВ
 * (TCP+Vision → XHTTP → gRPC → прочее).
 */
class ServerEntry(
    val key: String,
    val name: String,
    val isAuto: Boolean,
    val isReserve: Boolean,
    val links: List<VlessLink>,
)

/** Одна попытка подключения: сервер + конкретная ссылка (транспорт). */
class Attempt(val entry: ServerEntry, val link: VlessLink)

object ServerCatalog {
    /** Ключ «по умолчанию» = Авто. */
    const val AUTO_KEY = ""
    const val AUTO_NAME = "Авто"

    private val RESERVE_RE = Regex("резерв|мост|запас|белы[йе]|bridge|reserve|backup|white", RegexOption.IGNORE_CASE)
    private val AUTO_RE = Regex("(^|[^\\p{L}])(авто|auto)([^\\p{L}]|$)", RegexOption.IGNORE_CASE)

    /** Хосты «белого списка» (маскировка под российский CDN) — только как резерв. */
    private val WHITELIST_SNI = setOf("yastatic.net")

    private val VARIANT_PHRASES = listOf(
        "для телефона", "для смартфона", "для пк", "для компьютера", "для тв", "для телевизора",
        "если не работает", "phone", "pc",
    )

    private val ZERO_UUID = Regex("^0{8}-0{4}-0{4}-0{4}-0{12}$")

    fun build(links: List<VlessLink>): List<ServerEntry> {
        val groups = LinkedHashMap<String, MutableList<VlessLink>>()
        val names = HashMap<String, String>()
        val reserve = HashMap<String, Boolean>()
        val auto = HashMap<String, Boolean>()
        for (l in links) {
            if (!isUsable(l)) continue
            val isAuto = AUTO_RE.containsMatchIn(l.remark)
            val name = if (isAuto) AUTO_NAME else cleanName(l.remark)
            val key = name.lowercase()
            groups.getOrPut(key) { ArrayList() }.add(l)
            names.putIfAbsent(key, name)
            val res = RESERVE_RE.containsMatchIn(l.remark) || l.sni.lowercase() in WHITELIST_SNI
            reserve[key] = (reserve[key] ?: false) || res
            auto[key] = (auto[key] ?: false) || isAuto
        }
        val entries = groups.map { (key, list) ->
            val sorted = list.sortedWith(compareBy({ transportRank(it) }, { list.indexOf(it) }))
                .distinctBy { "${it.address}|${it.port}|${it.network}|${it.security}" }
            val isAuto = auto[key] == true
            ServerEntry(key, names[key] ?: key, isAuto, isReserve = !isAuto && reserve[key] == true, links = sorted)
        }
        // Авто — первым, резервы — в конце, остальное — в порядке подписки
        return entries.filter { it.isAuto } + entries.filter { !it.isAuto && !it.isReserve } + entries.filter { it.isReserve }
    }

    /** Ссылка годится для подключения (Remnawave подкладывает «пустые» ссылки-подсказки с 0.0.0.0). */
    fun isUsable(l: VlessLink): Boolean {
        if (l.uuid.isEmpty() || ZERO_UUID.matches(l.uuid)) return false
        val a = l.address.lowercase()
        if (a.isEmpty() || a == "0.0.0.0" || a == "localhost" || a.startsWith("127.") || a == "::" || a == "::1") return false
        if (l.security == "reality" && l.param("pbk") == null) return false
        return l.network in SUPPORTED_NETWORKS
    }

    private val SUPPORTED_NETWORKS = setOf("tcp", "xhttp", "grpc", "ws", "httpupgrade")

    fun transportRank(l: VlessLink): Int = when (l.network) {
        "tcp" -> if (l.flow.startsWith("xtls-rprx-vision")) 0 else 1
        "xhttp" -> 2
        "grpc" -> 3
        else -> 4
    }

    /** «🇫🇷 Франция — 📱 для телефона ^~2~^» → «Франция». */
    fun cleanName(remark: String): String {
        var s = remark.replace(Regex("\\s*\\^~\\d+~\\^\\s*$"), "")
        // всё после длинного тире/дефиса с пробелами — вариант («— 📱 для телефона»)
        s = s.split(Regex("\\s+[—–-]\\s+|\\s*\\|\\s*"))[0]
        val sb = StringBuilder()
        var i = 0
        while (i < s.length) {
            val cp = s.codePointAt(i)
            val keep = Character.isLetterOrDigit(cp) || Character.isSpaceChar(cp) || cp == '.'.code ||
                cp == ','.code || cp == '('.code || cp == ')'.code || cp == '+'.code || cp == '-'.code || cp == '#'.code
            sb.append(if (keep) String(Character.toChars(cp)) else " ")
            i += Character.charCount(cp)
        }
        var out = sb.toString()
        for (p in VARIANT_PHRASES) {
            out = out.replace(Regex("(^|\\s)" + Regex.escape(p) + "(?=\\s|$)", RegexOption.IGNORE_CASE), " ")
        }
        out = out.replace(Regex("\\s+"), " ").trim().trim('-', ',', '.', ' ')
        // «( )» от вырезанных эмодзи
        out = out.replace(Regex("\\(\\s*\\)"), "").replace(Regex("\\s+"), " ").trim()
        return out.ifEmpty { remark.trim().ifEmpty { "Сервер" } }
    }

    fun find(entries: List<ServerEntry>, key: String?): ServerEntry? {
        if (key.isNullOrEmpty()) return entries.firstOrNull { it.isAuto }
        return entries.firstOrNull { it.key == key.lowercase() }
    }

    /**
     * План подключения: выбранный сервер (или Авто, или первый обычный) — по одной попытке на транспорт
     * (TCP → XHTTP → gRPC), затем один раз первый резерв. Не больше [max] попыток.
     */
    fun attemptPlan(entries: List<ServerEntry>, key: String?, max: Int = 4): List<Attempt> {
        val sel = find(entries, key)
            ?: entries.firstOrNull { it.isAuto }
            ?: entries.firstOrNull { !it.isReserve }
            ?: entries.firstOrNull()
            ?: return emptyList()
        val plan = ArrayList<Attempt>()
        sel.links.take(3).forEach { plan.add(Attempt(sel, it)) }
        if (!sel.isReserve) {
            // Авто выбран, но не работает — пробуем ещё первую страну; потом резерв
            if (sel.isAuto && plan.size < max - 1) {
                entries.firstOrNull { !it.isAuto && !it.isReserve }?.let { plan.add(Attempt(it, it.links.first())) }
            }
            entries.firstOrNull { it.isReserve }?.let { plan.add(Attempt(it, it.links.first())) }
        }
        return plan.take(max)
    }
}
