package space.whitehole.tv

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RadialGradient
import android.graphics.RectF
import android.graphics.Shader
import android.graphics.SweepGradient
import android.os.SystemClock
import android.util.AttributeSet
import android.view.View
import android.view.animation.DecelerateInterpolator
import java.util.Random

/**
 * «Живая» чёрная дыра поверх статичного фона: медленно вращающееся мерцание аккреционного диска,
 * мягкое свечение кольца и мерцающие звёзды. Рисуется на аппаратном canvas не чаще 30 кадров/с
 * и останавливается, когда экран не виден (пауза, заставка, другой экран).
 *
 * Положение дыры задаётся долями от размера view (под фон hero_bg, обрезка centerCrop 16:9).
 */
class BlackHoleView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null
) : View(context, attrs) {

    /** Центр и радиус кольца в долях ширины/высоты. */
    var centerXFraction = 0.52f
    var centerYFraction = 0.51f
    var ringRadiusFraction = 0.19f   // от высоты

    private var running = false
    private var enabledAnim = true
    private val startTime = SystemClock.uptimeMillis()

    private val starCount: Int
    private val starX: FloatArray
    private val starY: FloatArray
    private val starR: FloatArray
    private val starPhase: FloatArray
    private val starSpeed: FloatArray
    private val starPaint = Paint(Paint.ANTI_ALIAS_FLAG)

    private val ringPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val diskPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val glowPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val connectPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val diskRect = RectF()

    private var ringShader: SweepGradient? = null
    private var diskShader: SweepGradient? = null
    private var glowShader: RadialGradient? = null
    private var shaderW = 0
    private var shaderH = 0

    // кольцо подключения (ConnectAnimator)
    private var connectProgress = -1f     // 0..1 — сжатие, -1 — нет
    private var connectColor = Color.WHITE
    private var connectAlpha = 0f
    private var connectAnimator: ValueAnimator? = null

    private val frame = Runnable { invalidate() }

    init {
        val low = Perf.isLowEnd(context)
        starCount = if (low) 50 else 110
        val rnd = Random(20261030L)
        starX = FloatArray(starCount)
        starY = FloatArray(starCount)
        starR = FloatArray(starCount)
        starPhase = FloatArray(starCount)
        starSpeed = FloatArray(starCount)
        for (i in 0 until starCount) {
            starX[i] = rnd.nextFloat()
            starY[i] = rnd.nextFloat() * 0.9f
            starR[i] = 0.6f + rnd.nextFloat() * 1.3f
            starPhase[i] = rnd.nextFloat() * 6.283f
            starSpeed[i] = 0.4f + rnd.nextFloat() * 1.4f
        }
        starPaint.color = Color.WHITE
        ringPaint.style = Paint.Style.STROKE
        diskPaint.style = Paint.Style.STROKE
        connectPaint.style = Paint.Style.STROKE
        setWillNotDraw(false)
        isFocusable = false
        importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_NO
    }

    /** Включить/выключить анимацию (настройка «Анимации» и слабые устройства). */
    fun setAnimationsEnabled(on: Boolean) {
        enabledAnim = on
        visibility = if (on) VISIBLE else GONE
        schedule()
    }

    /** Запуск/пауза отрисовки (onResume/onPause, смена экрана, заставка). */
    fun setRunning(on: Boolean) {
        running = on
        schedule()
    }

    private fun active(): Boolean =
        running && enabledAnim && visibility == VISIBLE && windowVisibility == VISIBLE && isShown

    private fun schedule() {
        removeCallbacks(frame)
        if (active()) postInvalidateOnAnimation()
    }

    override fun onWindowVisibilityChanged(visibility: Int) {
        super.onWindowVisibilityChanged(visibility)
        schedule()
    }

    override fun onVisibilityChanged(changedView: View, visibility: Int) {
        super.onVisibilityChanged(changedView, visibility)
        schedule()
    }

    override fun onDetachedFromWindow() {
        removeCallbacks(frame)
        connectAnimator?.cancel()
        super.onDetachedFromWindow()
    }

    private fun ensureShaders(w: Int, h: Int, cx: Float, cy: Float, r: Float) {
        if (w == shaderW && h == shaderH && ringShader != null) return
        shaderW = w
        shaderH = h
        ringShader = SweepGradient(
            cx, cy,
            intArrayOf(0x00FFFFFF, 0x55FFFFFF, 0x00FFFFFF, 0x33DDE6FF, 0x00FFFFFF, 0x44FFFFFF, 0x00FFFFFF),
            null
        )
        diskShader = SweepGradient(
            cx, cy,
            intArrayOf(0x00FFFFFF, 0x2EFFFFFF, 0x00FFFFFF, 0x22FFE9C8, 0x00FFFFFF),
            null
        )
        glowShader = RadialGradient(
            cx, cy, r * 1.7f,
            intArrayOf(0x00000000, 0x00000000, 0x1AFFFFFF, 0x00FFFFFF),
            floatArrayOf(0f, 0.55f, 0.62f, 1f),
            Shader.TileMode.CLAMP
        )
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val w = width
        val h = height
        if (w == 0 || h == 0) return
        val cx = w * centerXFraction
        val cy = h * centerYFraction
        val r = h * ringRadiusFraction
        ensureShaders(w, h, cx, cy, r)
        val t = (SystemClock.uptimeMillis() - startTime) / 1000f

        // звёзды
        for (i in 0 until starCount) {
            val a = 0.25f + 0.75f * (0.5f + 0.5f * Math.sin((t * starSpeed[i] + starPhase[i]).toDouble()).toFloat())
            starPaint.alpha = (a * 200).toInt()
            canvas.drawCircle(starX[i] * w, starY[i] * h, starR[i] * resources.displayMetrics.density * 0.6f, starPaint)
        }

        // мягкое свечение вокруг дыры (пульс очень медленный)
        val pulse = 0.85f + 0.15f * Math.sin(t * 0.5).toFloat()
        glowPaint.shader = glowShader
        glowPaint.alpha = (255 * pulse).toInt()
        canvas.drawCircle(cx, cy, r * 1.7f, glowPaint)

        // кольцо фотонов: вращающийся блик
        canvas.save()
        canvas.rotate((t * 9f) % 360f, cx, cy)
        ringPaint.shader = ringShader
        ringPaint.strokeWidth = r * 0.10f
        canvas.drawCircle(cx, cy, r * 1.02f, ringPaint)
        canvas.restore()

        // аккреционный диск: вытянутый эллипс, блик бежит в другую сторону
        diskPaint.shader = diskShader
        diskPaint.strokeWidth = r * 0.9f
        val dr = r * 2.3f
        diskRect.set(cx - dr, cy - dr, cx + dr, cy + dr)
        canvas.save()
        canvas.rotate(-4f, cx, cy)
        canvas.scale(1f, 0.16f, cx, cy)
        canvas.rotate(-(t * 6f) % 360f, cx, cy)
        canvas.drawOval(diskRect, diskPaint)
        canvas.restore()

        // кольцо подключения
        if (connectProgress >= 0f && connectAlpha > 0f) {
            val cr = r * (1.05f + 2.2f * (1f - connectProgress))
            connectPaint.color = connectColor
            connectPaint.alpha = (connectAlpha * 255).toInt().coerceIn(0, 255)
            connectPaint.strokeWidth = r * (0.03f + 0.07f * connectProgress)
            canvas.drawCircle(cx, cy, cr, connectPaint)
        }

        if (active()) postOnAnimationDelayed(frame, FRAME_MS)
    }

    // ---------- анимация подключения ----------

    /** Кольцо сжимается в дыру (повторяется, пока идёт подключение). */
    fun playContract(color: Int) {
        connectAnimator?.cancel()
        connectColor = color
        val a = ValueAnimator.ofFloat(0f, 1f)
        a.duration = 1400
        a.repeatCount = ValueAnimator.INFINITE
        a.interpolator = DecelerateInterpolator()
        a.addUpdateListener { va ->
            connectProgress = va.animatedValue as Float
            connectAlpha = 0.25f + 0.6f * connectProgress
            invalidate()
        }
        a.start()
        connectAnimator = a
    }

    /** Итог: кольцо вспыхивает цветом (зелёный/красный) и гаснет. */
    fun playResult(color: Int) {
        connectAnimator?.cancel()
        connectColor = color
        connectProgress = 1f
        val a = ValueAnimator.ofFloat(1f, 0f)
        a.duration = 1200
        a.addUpdateListener { va ->
            connectAlpha = va.animatedValue as Float
            invalidate()
        }
        a.start()
        connectAnimator = a
    }

    fun stopConnect() {
        connectAnimator?.cancel()
        connectAnimator = null
        connectProgress = -1f
        connectAlpha = 0f
        invalidate()
    }

    companion object {
        private const val FRAME_MS = 33L // ≤30 кадров/с
    }
}
