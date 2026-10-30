package space.whitehole.tv

import android.content.Context
import android.content.res.Configuration

/**
 * Единый масштаб интерфейса на любом телевизоре и приставке.
 *
 * Интерфейс рассчитан на экран 960×540 dp. На большинстве ТВ так и есть (1920×1080 @ 320 dpi,
 * 3840×2160 @ 640 dpi, 1280×720 @ 213 dpi), но встречаются 1280×720 @ 240 dpi (853×480 dp),
 * 1366×768, «телефонные» приставки и т. п. Подбираем densityDpi так, чтобы экран был ровно
 * 960×540 dp (по меньшей стороне), и ограничиваем системный размер шрифта, чтобы надписи не вылезали.
 */
object UiScale {
    private const val DESIGN_W = 960f
    private const val DESIGN_H = 540f
    private const val MAX_FONT_SCALE = 1.15f

    /** Конфигурация-переопределение или null, если менять ничего не нужно. */
    fun overrideFor(base: Context): Configuration? {
        return try {
            val res = base.resources
            val dm = res.displayMetrics
            val cur = res.configuration
            val w = maxOf(dm.widthPixels, dm.heightPixels)
            val h = minOf(dm.widthPixels, dm.heightPixels)
            if (w <= 0 || h <= 0) return null
            val target = (minOf(w / DESIGN_W, h / DESIGN_H) * 160f).toInt()
            val curDpi = if (cur.densityDpi > 0) cur.densityDpi else dm.densityDpi
            val needDensity = target >= 80 && curDpi > 0 && Math.abs(target - curDpi) * 50 > curDpi // >2%
            val needFont = cur.fontScale > MAX_FONT_SCALE
            if (!needDensity && !needFont) return null
            val o = Configuration()
            if (needDensity) o.densityDpi = target
            if (needFont) o.fontScale = MAX_FONT_SCALE
            o
        } catch (e: Exception) {
            null
        }
    }
}
