package space.whitehole.tv

import android.content.res.Resources
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.drawable.BitmapDrawable
import android.os.Handler
import android.os.Looper
import android.service.dreams.DreamService
import android.view.View
import android.view.animation.AccelerateDecelerateInterpolator
import android.widget.ImageView
import android.widget.TextView
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.Random

/**
 * Заставка: чёрная дыра + крупные часы и дата. Блок с часами раз в минуту плавно переезжает
 * в другое место (защита от выгорания), фон тоже чуть смещается. Используется и системной
 * заставкой (DreamService), и заставкой при простое внутри лаунчера.
 */
class ScreensaverController(private val root: View, private val animations: Boolean) {

    private val handler = Handler(Looper.getMainLooper())
    private val bg: ImageView = root.findViewById(R.id.ss_bg)
    private val hole: BlackHoleView = root.findViewById(R.id.ss_hole)
    private val box: View = root.findViewById(R.id.ss_box)
    private val time: TextView = root.findViewById(R.id.ss_time)
    private val date: TextView = root.findViewById(R.id.ss_date)
    private val rnd = Random()
    private var running = false
    private var timeFmt = SimpleDateFormat("HH:mm", Locale.getDefault())
    private var dateFmt = SimpleDateFormat("EEEE, d MMMM", Locale("ru"))

    private val tick = object : Runnable {
        override fun run() {
            updateClock()
            val now = System.currentTimeMillis()
            handler.postDelayed(this, 60_000L - (now % 60_000L) + 50L)
        }
    }

    private val drift = object : Runnable {
        override fun run() {
            moveBox(true)
            handler.postDelayed(this, 60_000L)
        }
    }

    fun start() {
        if (running) return
        running = true
        timeFmt = SimpleDateFormat("HH:mm", Locale.getDefault())
        dateFmt = SimpleDateFormat("EEEE, d MMMM", Locale("ru"))
        hole.setAnimationsEnabled(animations)
        hole.setRunning(true)
        if (bg.drawable == null) loadBackground()
        handler.removeCallbacks(tick)
        handler.removeCallbacks(drift)
        tick.run()
        box.post { moveBox(false) }
        handler.postDelayed(drift, 60_000L)
    }

    fun stop() {
        running = false
        handler.removeCallbacks(tick)
        handler.removeCallbacks(drift)
        hole.setRunning(false)
        box.animate().cancel()
    }

    private fun updateClock() {
        val now = Date()
        time.text = timeFmt.format(now)
        val d = dateFmt.format(now)
        date.text = if (d.isEmpty()) d else d.substring(0, 1).uppercase(Locale("ru")) + d.substring(1)
    }

    /** Случайное место для блока часов в пределах экрана (с отступом 6%). */
    private fun moveBox(animate: Boolean) {
        val w = root.width
        val h = root.height
        if (w <= 0 || h <= 0 || box.width <= 0) return
        val padX = (w * 0.06f).toInt()
        val padY = (h * 0.08f).toInt()
        val maxX = maxOf(padX, w - box.width - padX)
        val maxY = maxOf(padY, h - box.height - padY)
        val x = (padX + rnd.nextInt(maxOf(1, maxX - padX + 1))).toFloat()
        val y = (padY + rnd.nextInt(maxOf(1, maxY - padY + 1))).toFloat()
        val shift = root.resources.displayMetrics.density * 10f
        val bx = (rnd.nextFloat() * 2f - 1f) * shift
        val by = (rnd.nextFloat() * 2f - 1f) * shift
        if (animate && animations) {
            box.animate().translationX(x).translationY(y).setDuration(4000)
                .setInterpolator(AccelerateDecelerateInterpolator()).start()
            bg.animate().translationX(bx).translationY(by).setDuration(8000).start()
            hole.animate().translationX(bx).translationY(by).setDuration(8000).start()
        } else {
            box.translationX = x
            box.translationY = y
            bg.translationX = bx
            bg.translationY = by
            hole.translationX = bx
            hole.translationY = by
        }
    }

    private fun loadBackground() {
        val res = root.resources
        val dm = res.displayMetrics
        val low = Perf.isLowEnd(root.context)
        val sw = if (low) minOf(dm.widthPixels, 1280) else dm.widthPixels
        val sh = if (low) minOf(dm.heightPixels, 720) else dm.heightPixels
        Thread {
            val bmp = decodeHero(res, sw, sh)
            if (bmp != null) {
                handler.post {
                    // чуть больше экрана, чтобы сдвиг фона не открывал края
                    bg.scaleX = 1.03f
                    bg.scaleY = 1.03f
                    bg.setImageDrawable(BitmapDrawable(res, bmp))
                }
            }
        }.start()
    }

    companion object {
        /** Фон hero_bg под размер экрана: только уменьшение (inSampleSize), без увеличения. */
        fun decodeHero(res: Resources, screenW: Int, screenH: Int): Bitmap? {
            return try {
                val sw = if (screenW > 0) screenW else 1920
                val sh = if (screenH > 0) screenH else 1080
                val bounds = BitmapFactory.Options()
                bounds.inJustDecodeBounds = true
                bounds.inScaled = false
                BitmapFactory.decodeResource(res, R.drawable.hero_bg, bounds)
                var sample = 1
                while (bounds.outWidth / (sample * 2) >= sw && bounds.outHeight / (sample * 2) >= sh) sample *= 2
                val opts = BitmapFactory.Options()
                opts.inScaled = false
                opts.inSampleSize = sample
                BitmapFactory.decodeResource(res, R.drawable.hero_bg, opts)
            } catch (e: Throwable) {
                null
            }
        }
    }
}

/** Системная заставка «WhiteHole — заставка» (выбирается в настройках ТВ или через adb). */
class ScreensaverService : DreamService() {
    private var controller: ScreensaverController? = null

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        isInteractive = false
        isFullscreen = true
        setContentView(R.layout.screensaver)
        val root = findViewById<View>(R.id.ss_root)
        controller = ScreensaverController(root, Prefs(this).animations)
    }

    override fun onDreamingStarted() {
        super.onDreamingStarted()
        controller?.start()
    }

    override fun onDreamingStopped() {
        controller?.stop()
        super.onDreamingStopped()
    }

    override fun onDetachedFromWindow() {
        controller?.stop()
        controller = null
        super.onDetachedFromWindow()
    }
}
