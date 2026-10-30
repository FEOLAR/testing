package space.whitehole.tv

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.drawable.Drawable

/** Быстрый «доминирующий» цвет картинки приложения (вместо androidx.palette). */
object ColorUtil {

    /** Средний цвет насыщенных пикселей уменьшенной до 24×24 картинки; null — если цвет не определить. */
    fun dominant(d: Drawable): Int? {
        return try {
            val size = 24
            val bmp = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888)
            val c = Canvas(bmp)
            val copy = d.constantState?.newDrawable()?.mutate() ?: d
            copy.setBounds(0, 0, size, size)
            copy.draw(c)
            val px = IntArray(size * size)
            bmp.getPixels(px, 0, size, 0, 0, size, size)
            bmp.recycle()
            var r = 0.0
            var g = 0.0
            var b = 0.0
            var wsum = 0.0
            val hsv = FloatArray(3)
            for (p in px) {
                if (Color.alpha(p) < 128) continue
                Color.colorToHSV(p, hsv)
                // насыщенные и не слишком тёмные пиксели весят больше
                val w = (hsv[1] * hsv[1] * hsv[2]).toDouble() + 0.02
                r += Color.red(p) * w
                g += Color.green(p) * w
                b += Color.blue(p) * w
                wsum += w
            }
            if (wsum <= 0.0) return null
            val col = Color.rgb((r / wsum).toInt(), (g / wsum).toInt(), (b / wsum).toInt())
            Color.colorToHSV(col, hsv)
            // приглушаем: фон должен остаться тёмным
            hsv[2] = minOf(hsv[2], 0.55f)
            Color.HSVToColor(hsv)
        } catch (e: Throwable) {
            null
        }
    }
}
