package space.whitehole.tv

import android.content.ContentProvider
import android.content.ContentValues
import android.database.Cursor
import android.database.MatrixCursor
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.provider.OpenableColumns
import java.io.File
import java.io.FileNotFoundException

/**
 * Отдаёт установщику Android скачанный APK (Happ) из cacheDir/apk/ — без androidx FileProvider.
 * Адрес: content://space.whitehole.tv.apk/<имя файла>. Доступ только по выданному разрешению (grantUriPermissions).
 */
class ApkProvider : ContentProvider() {

    override fun onCreate(): Boolean = true

    private fun fileFor(uri: Uri): File {
        val ctx = context ?: throw FileNotFoundException("no context")
        val name = uri.lastPathSegment ?: throw FileNotFoundException("no name")
        if (name.contains("/") || name.contains("..")) throw FileNotFoundException(name)
        val f = File(File(ctx.cacheDir, DIR), name)
        if (!f.isFile) throw FileNotFoundException(name)
        return f
    }

    override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor =
        ParcelFileDescriptor.open(fileFor(uri), ParcelFileDescriptor.MODE_READ_ONLY)

    override fun getType(uri: Uri): String = MIME

    override fun query(
        uri: Uri,
        projection: Array<out String>?,
        selection: String?,
        selectionArgs: Array<out String>?,
        sortOrder: String?
    ): Cursor {
        val f = fileFor(uri)
        val cursor = MatrixCursor(arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE))
        cursor.addRow(arrayOf<Any>(f.name, f.length()))
        return cursor
    }

    override fun insert(uri: Uri, values: ContentValues?): Uri? = null

    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int = 0

    override fun update(uri: Uri, values: ContentValues?, selection: String?, selectionArgs: Array<out String>?): Int = 0

    companion object {
        const val AUTHORITY = "space.whitehole.tv.apk"
        const val DIR = "apk"
        const val MIME = "application/vnd.android.package-archive"

        fun uriFor(name: String): Uri = Uri.parse("content://$AUTHORITY/$name")
    }
}
