package space.whitehole.tv.vpn

import android.content.Context
import java.io.File
import java.util.UUID

/**
 * Маленькие файлы в filesDir/vpn. Не SharedPreferences: служба VPN живёт в отдельном процессе (:vpn),
 * а SharedPreferences кэшируются в каждом процессе и затирают друг друга. Файл читается всегда свежим.
 */
object VpnFiles {
    fun dir(ctx: Context): File = File(ctx.applicationContext.filesDir, "vpn").also { it.mkdirs() }

    fun read(ctx: Context, name: String): String? = try {
        val f = File(dir(ctx), name)
        if (f.isFile) f.readText(Charsets.UTF_8) else null
    } catch (e: Exception) {
        null
    }

    /** Атомарная запись: во временный файл и переименование. */
    fun write(ctx: Context, name: String, text: String?) {
        try {
            val f = File(dir(ctx), name)
            if (text == null) {
                f.delete()
                return
            }
            val tmp = File(dir(ctx), "$name.tmp")
            tmp.writeText(text, Charsets.UTF_8)
            if (!tmp.renameTo(f)) {
                f.delete()
                tmp.renameTo(f)
            }
        } catch (e: Exception) {
            // нет места — не критично
        }
    }

    // ---------- настройки ----------

    /** Пользователь хочет, чтобы VPN был включён (для автоподключения после перезагрузки). */
    fun wanted(ctx: Context): Boolean = read(ctx, "wanted") == "1"

    fun setWanted(ctx: Context, on: Boolean) = write(ctx, "wanted", if (on) "1" else "0")

    /** Тест: блокировать рекламу и трекеры (BlockSites из happ-routing-adblock.json). По умолчанию выключено. */
    fun adblock(ctx: Context): Boolean = read(ctx, "adblock") == "1"

    fun setAdblock(ctx: Context, on: Boolean) = write(ctx, "adblock", if (on) "1" else "0")

    /** Выбранный сервер: ключ ("" — Авто) и название для кнопки. */
    fun serverKey(ctx: Context): String = read(ctx, "server_key")?.trim() ?: ServerCatalog.AUTO_KEY

    fun serverName(ctx: Context): String =
        read(ctx, "server_name")?.trim()?.takeIf { it.isNotEmpty() } ?: ServerCatalog.AUTO_NAME

    fun setServer(ctx: Context, key: String, name: String) {
        write(ctx, "server_key", key)
        write(ctx, "server_name", name)
    }

    /**
     * Стабильный HWID устройства для лимита устройств Remnawave (заголовок x-hwid):
     * 32 hex-символа (формат ^[a-zA-Z0-9=-]{10,64}$), создаётся один раз.
     */
    @Synchronized
    fun hwid(ctx: Context): String {
        val cur = read(ctx, "hwid")?.trim()
        if (cur != null && cur.matches(Regex("^[a-zA-Z0-9=-]{10,64}$"))) return cur
        val id = UUID.randomUUID().toString().replace("-", "")
        write(ctx, "hwid", id)
        return id
    }
}
