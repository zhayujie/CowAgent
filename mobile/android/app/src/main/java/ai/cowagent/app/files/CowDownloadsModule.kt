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
import com.facebook.react.bridge.Arguments
import com.facebook.react.bridge.NativeModule
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import com.facebook.react.modules.core.DeviceEventManagerModule
import com.facebook.react.uimanager.ViewManager
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

/**
 * Downloads in this process rather than through DownloadManager: the system downloader runs in
 * its own process, so it cannot use the app's certificate anchors (the self-hosted tunnel) or its
 * timeouts, and an unreachable address there leaves the request pending forever.
 *
 * Partial files live in the cache and survive a failed request or an app restart. A later call for
 * the same id resumes with Range; the file is published only after the download is complete.
 */
class CowDownloadsModule(context: ReactApplicationContext) : ReactContextBaseJavaModule(context) {
  private val io: ExecutorService = Executors.newFixedThreadPool(2)
  private val fileLocks = ConcurrentHashMap<String, Any>()

  override fun getName() = "CowDownloads"

  @ReactMethod
  fun save(url: String, fileName: String, id: String, promise: Promise) {
    fetch(url, fileName, id, promise, openWith = false)
  }

  @ReactMethod
  fun open(url: String, fileName: String, id: String, promise: Promise) {
    fetch(url, fileName, id, promise, openWith = true)
  }

  // NativeModules event emitters expect these two methods on Android.
  @ReactMethod
  fun addListener(name: String) = Unit

  @ReactMethod
  fun removeListeners(count: Int) = Unit

  override fun invalidate() {
    io.shutdownNow()
    super.invalidate()
  }

  private fun fetch(url: String, fileName: String, id: String, promise: Promise, openWith: Boolean) {
    val name = safeName(fileName).ifEmpty { safeName(URLUtil.guessFileName(url, null, null)) }.ifEmpty { "download" }
    io.execute {
      // Download and "open with" for the same file queue up; two writers on one .part corrupt it.
      val lock = fileLocks.getOrPut(id) { Any() }
      synchronized(lock) {
        try {
        val target = cachedFile(id, name)
        if (!target.exists()) {
          download(url, id, target, resume = true)
        }
        if (openWith) {
          if (launch(target, name)) {
            promise.resolve("opened")
          } else {
            // A file left in the private cache is not a completed public download.
            promise.resolve(if (saveToDownloads(name, target)) "downloads" else "files")
          }
        } else {
          promise.resolve(if (saveToDownloads(name, target)) "downloads" else "files")
        }
        } catch (e: Exception) {
          promise.reject("download_failed", e.message ?: "Download failed", e)
        }
      }
    }
  }

  /** Downloads into a partial cache file, then atomically makes it the completed cache file. */
  private fun download(url: String, id: String, target: File, resume: Boolean) {
    val partial = partialFile(id)
    val offset = if (resume) partial.length() else 0L
    if (!resume) {
      partial.delete()
    }
    val conn = (URL(url).openConnection() as HttpURLConnection).apply {
      connectTimeout = 15_000
      readTimeout = 60_000
      instanceFollowRedirects = true
      requestMethod = "GET"
      setRequestProperty("Accept", "*/*")
      if (offset > 0) {
        setRequestProperty("Range", "bytes=$offset-")
      }
    }
    try {
      when (val code = conn.responseCode) {
        416 -> {
          val total = contentRangeTotal(conn.getHeaderField("Content-Range"))
          if (total != null && total == offset) {
            publish(partial, target)
            return
          }
          // The remote file changed or the cached range is invalid. Start cleanly once.
          partial.delete()
          if (resume) {
            download(url, id, target, resume = false)
            return
          }
          throw IOException("HTTP $code")
        }
        !in 200..299 -> throw IOException("HTTP $code")
      }

      val append = conn.responseCode == 206 && offset > 0
      val start = if (append) offset else 0L
      if (!append) {
        // A server that ignores Range returns the whole file, never append it to the old part.
        partial.delete()
      }
      val total = contentRangeTotal(conn.getHeaderField("Content-Range"))
        ?: conn.contentLengthLong.takeIf { it >= 0 }?.let { it + start }
        ?: -1L
      emitProgress(id, start, total)
      conn.inputStream.use { input ->
        FileOutputStream(partial, append).use { output ->
          val buffer = ByteArray(64 * 1024)
          var loaded = start
          while (true) {
            val count = input.read(buffer)
            if (count < 0) break
            output.write(buffer, 0, count)
            loaded += count
            emitProgress(id, loaded, total)
          }
        }
      }
      if (total >= 0 && partial.length() != total) {
        throw IOException("Incomplete download")
      }
      publish(partial, target)
    } finally {
      // Do not delete the part on failure: the next tap resumes from this byte.
      conn.disconnect()
    }
  }

  private fun publish(partial: File, target: File) {
    target.parentFile?.mkdirs()
    if (target.exists()) {
      target.delete()
    }
    if (partial.renameTo(target)) {
      return
    }
    try {
      partial.inputStream().use { input -> target.outputStream().use { output -> input.copyTo(output) } }
      partial.delete()
    } catch (e: Exception) {
      target.delete()
      throw e
    }
  }

  private fun emitProgress(id: String, loaded: Long, total: Long) {
    if (!reactApplicationContext.hasActiveReactInstance()) {
      return
    }
    val event = Arguments.createMap().apply {
      putString("id", id)
      putDouble("loaded", loaded.toDouble())
      putDouble("total", total.toDouble())
    }
    runCatching {
      reactApplicationContext
        .getJSModule(DeviceEventManagerModule.RCTDeviceEventEmitter::class.java)
        .emit("cowDownloadProgress", event)
    }
  }

  /** Downloads to the public Downloads folder; MediaStore is the only writable path on Android 10+. */
  private fun saveToDownloads(name: String, source: File): Boolean {
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
        val output = resolver.openOutputStream(uri) ?: throw IOException("Cannot open download destination")
        source.inputStream().use { input -> output.use { input.copyTo(it) } }
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
    val target = availableFile(dir, name)
    try {
      source.inputStream().use { input -> target.outputStream().use { output -> input.copyTo(output) } }
      MediaScannerConnection.scanFile(reactApplicationContext, arrayOf(target.absolutePath), null, null)
      return true
    } catch (e: Exception) {
      target.delete()
      throw e
    }
  }

  private fun availableFile(dir: File, name: String): File {
    val first = File(dir, name)
    if (!first.exists()) return first
    val extension = name.substringAfterLast('.', "")
    val stem = name.removeSuffix(if (extension.isEmpty()) "" else ".$extension")
    var index = 2
    while (true) {
      val suffix = if (extension.isEmpty()) "" else ".$extension"
      val candidate = File(dir, "$stem ($index)$suffix")
      if (!candidate.exists()) return candidate
      index += 1
    }
  }

  private fun partialFile(id: String): File =
    File(File(reactApplicationContext.cacheDir, "downloads").apply { mkdirs() }, "${hash(id)}.part")

  private fun cachedFile(id: String, name: String): File =
    File(File(reactApplicationContext.cacheDir, "downloads").apply { mkdirs() }, "${hash(id)}-$name")

  private fun hash(value: String): String =
    MessageDigest.getInstance("SHA-256").digest(value.toByteArray()).joinToString("") { "%02x".format(it) }

  private fun contentRangeTotal(header: String?): Long? =
    header?.let { Regex("""/(\\d+)$""").find(it)?.groupValues?.get(1)?.toLongOrNull() }

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
