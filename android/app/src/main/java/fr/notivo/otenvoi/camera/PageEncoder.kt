package fr.notivo.otenvoi.camera

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import java.io.ByteArrayOutputStream
import kotlin.math.max
import kotlin.math.min

/**
 * Transforme la photo brute de l'appareil en une page JPEG redressée et allégée, ENTIÈREMENT EN MÉMOIRE
 * (octets -> bitmap -> octets). Rien n'est écrit sur le téléphone.
 */
object PageEncoder {
    /** Plus grand côté de la page envoyée : assez pour lire les petits chiffres, sans e-mail géant. */
    const val MAX_SIDE = 3000
    const val QUALITY = 88

    fun encode(rawJpeg: ByteArray, rotationDegrees: Int): ByteArray {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(rawJpeg, 0, rawJpeg.size, bounds)
        var sample = 1
        while (max(bounds.outWidth, bounds.outHeight) / (sample * 2) >= MAX_SIDE) sample *= 2
        val options = BitmapFactory.Options().apply { inSampleSize = sample }
        val decoded = BitmapFactory.decodeByteArray(rawJpeg, 0, rawJpeg.size, options)
            ?: throw IllegalStateException("Photo illisible.")

        val scale = min(1f, MAX_SIDE.toFloat() / max(decoded.width, decoded.height))
        val matrix = Matrix().apply {
            postRotate(rotationDegrees.toFloat())
            if (scale < 1f) postScale(scale, scale)
        }
        val page = Bitmap.createBitmap(decoded, 0, 0, decoded.width, decoded.height, matrix, true)
        val out = ByteArrayOutputStream(512 * 1024)
        page.compress(Bitmap.CompressFormat.JPEG, QUALITY, out)
        if (page !== decoded) decoded.recycle()
        page.recycle()
        return out.toByteArray()
    }

    /**
     * Rotation à appliquer à une photo déjà prise (galerie), d'après son orientation EXIF. Lue dans les octets
     * en mémoire : rien n'est copié ni écrit.
     */
    fun exifRotation(jpeg: ByteArray): Int = try {
        val orientation = android.media.ExifInterface(java.io.ByteArrayInputStream(jpeg)).getAttributeInt(
            android.media.ExifInterface.TAG_ORIENTATION, android.media.ExifInterface.ORIENTATION_NORMAL,
        )
        when (orientation) {
            android.media.ExifInterface.ORIENTATION_ROTATE_90, android.media.ExifInterface.ORIENTATION_TRANSPOSE -> 90
            android.media.ExifInterface.ORIENTATION_ROTATE_180, android.media.ExifInterface.ORIENTATION_FLIP_VERTICAL -> 180
            android.media.ExifInterface.ORIENTATION_ROTATE_270, android.media.ExifInterface.ORIENTATION_TRANSVERSE -> 270
            else -> 0
        }
    } catch (e: Exception) {
        0
    }

    /** Miniature pour l'aperçu à l'écran (décodée directement en petit). */
    fun thumbnail(jpeg: ByteArray, maxSide: Int = 320): Bitmap? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size, bounds)
        var sample = 1
        while (max(bounds.outWidth, bounds.outHeight) / (sample * 2) >= maxSide) sample *= 2
        return BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size, BitmapFactory.Options().apply { inSampleSize = sample })
    }
}
