package ai.cowagent.app.files

import android.content.ContentValues
import android.content.Intent
import android.media.MediaScannerConnection
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.webkit.MimeTypeMap
import android.webkit.URLUtil
import androidx.core.content.FileProvider
import com.facebook.react.ReactPackage
import com.facebook.react.bridge.NativeModule
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import com.facebook.react.uimanager.ViewManager
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

/**
 * Downloads in this process rather than through DownloadManager: the system downloader runs in
 * its own process, so it cannot use the app's certificate anchors (the self-hosted tunnel) or its
 * timeouts, and an unreachable address there leaves the request pending forever.
 */
class CowDownloadsModule(context: ReactApplicationContext) : ReactContextBaseJavaModule(context) {
  private val io: ExecutorService = Executors.newFixedThreadPool(2)

  override fun getName() = "CowDownloads"

  /** Saves the file into Downloads; resolves with "downloads" once it is written. */
  @ReactMethod
  fun save(url: String, fileName: String, promise: Promise) {
    fetch(url, fileName, promise, openWith = false)
  }

  /**
   * Downloads the file and then opens the system "open with" chooser, so Word/WPS can take it.
   * Resolves with "opened" when the chooser was launched, or "downloads" when no app could be
   * started. Rejects as soon as the download fails, so the UI never keeps waiting.
   */
  @ReactMethod
  fun open(url: String, fileName: String, promise: Promise) {
    fetch(url, fileName, promise, openWith = true)
  }

  override fun invalidate() {
    io.shutdownNow()
    super.invalidate()
  }

  private fun fetch(url: String, fileName: String, promise: Promise, openWith: Boolean) {
    val name = safeName(fileName).ifEmpty { safeName(URLUtil.guessFileName(url, null, null)) }.ifEmpty { "download" }
    io.execute {
      try {
        openStream(url).use { input ->
          if (openWith) {
            val target = writeToCache(name, input)
            promise.resolve(if (launch(target, name)) "opened" else "downloads")
          } else {
            promise.resolve(if (saveToDownloads(name, input)) "downloads" else "files")
          }
        }
      } catch (e: Exception) {
        promise.reject("download_failed", e.message ?: "Download failed", e)
      }
    }
  }

  /** Opens a GET that respects the app network configuration, with timeouts so it cannot hang. */
  private fun openStream(url: String): InputStream {
    val conn = (URL(url).openConnection() as HttpURLConnection).apply {
      connectTimeout = 15_000
      readTimeout = 60_000
      instanceFollowRedirects = true
      requestMethod = "GET"
      setRequestProperty("Accept", "*/*")
    }
    val code = try {
      conn.responseCode
    } catch (e: IOException) {
      conn.disconnect()
      throw e
    }
    if (code !in 200..299) {
      conn.disconnect()
      throw IOException("HTTP $code")
    }
    return conn.inputStream
  }

  private fun writeToCache(name: String, input: InputStream): File {
    val dir = File(reactApplicationContext.cacheDir, "open").apply { mkdirs() }
    val target = File(dir, name)
    if (target.exists()) {
      target.delete()
    }
    target.outputStream().use { output -> input.copyTo(output) }
    return target
  }

  /** Downloads to the public Downloads folder; MediaStore is the only writable path on Android 10+. */
  private fun saveToDownloads(name: String, input: InputStream): Boolean {
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
      val resolver = reactApplicationContext.contentResolver
      val values = ContentValues().apply {
        put(MediaStore.Downloads.DISPLAY_NAME, name)
        put(MediaStore.Downloads.MIME_TYPE, mimeOf(name))
        put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
        put(MediaStore.Downloads.IS_PENDING, 1)
      }
      val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values) ?: return false
      try {
        resolver.openOutputStream(uri)?.use { output -> input.copyTo(output) } ?: return false
        values.clear()
        values.put(MediaStore.Downloads.IS_PENDING, 0)
        resolver.update(uri, values, null, null)
        return true
      } catch (e: Exception) {
        resolver.delete(uri, null, null)
        throw e
      }
    }
    val dir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
    if (!dir.exists() && !dir.mkdirs()) {
      return false
    }
    val target = File(dir, name)
    target.outputStream().use { output -> input.copyTo(output) }
    MediaScannerConnection.scanFile(reactApplicationContext, arrayOf(target.absolutePath), null, null)
    return true
  }

  /** Hands the file to another app through FileProvider, which can grant it to a third party. */
  private fun launch(file: File, name: String): Boolean {
    val uri = runCatching {
      FileProvider.getUriForFile(reactApplicationContext, "${reactApplicationContext.packageName}.files", file)
    }.getOrNull() ?: return false
    val view = Intent(Intent.ACTION_VIEW).apply {
      setDataAndType(uri, mimeOf(name))
      addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
    }
    return runCatching {
      reactApplicationContext.startActivity(Intent.createChooser(view, name).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
      true
    }.getOrDefault(false)
  }

  // Office extensions are missing from the platform map on some builds.
  private fun mimeOf(name: String): String {
    val ext = name.substringAfterLast('.', "").lowercase()
    return MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext)
      ?: OFFICE_MIME[ext]
      ?: "*/*"
  }

  private fun safeName(name: String): String =
    name.replace(Regex("[\\\\/:*?\"<>|\\p{Cntrl}]"), "_").trim().trimStart('.')

  private companion object {
    val OFFICE_MIME = mapOf(
      "doc" to "application/msword",
      "docx" to "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      "xls" to "application/vnd.ms-excel",
      "xlsx" to "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      "ppt" to "application/vnd.ms-powerpoint",
      "pptx" to "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )
  }
}

class CowDownloadsPackage : ReactPackage {
  override fun createNativeModules(reactContext: ReactApplicationContext): List<NativeModule> =
    listOf(CowDownloadsModule(reactContext))

  override fun createViewManagers(reactContext: ReactApplicationContext): List<ViewManager<in Nothing, in Nothing>> =
    emptyList()
}
