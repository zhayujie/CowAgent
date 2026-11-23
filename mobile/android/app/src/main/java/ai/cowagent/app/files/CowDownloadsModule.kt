package ai.cowagent.app.files

import android.content.ContentValues
import android.content.ClipData
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.media.MediaScannerConnection
import android.os.Build
import android.os.Environment
import android.os.SystemClock
import android.provider.MediaStore
import android.provider.OpenableColumns
import android.util.Log
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
import java.util.UUID
import java.util.concurrent.Executors

/** Hands out the files the app shares, from its cache only. */
class ShareProvider : FileProvider()

/** What another app shared to this one, waiting for the chat to take it. */
object SharedIntake {
  @Volatile private var pending: Intent? = null
  @Volatile var onArrive: (() -> Unit)? = null

  fun receive(intent: Intent?) {
    val opened = intent?.action == Intent.ACTION_VIEW && intent.data?.scheme == "content"
    if (!opened && intent?.action != Intent.ACTION_SEND && intent?.action != Intent.ACTION_SEND_MULTIPLE) return
    // Opened again from recents, it carries the share it was first started with.
    if (intent.flags and Intent.FLAG_ACTIVITY_LAUNCHED_FROM_HISTORY != 0) return
    pending = intent
    onArrive?.invoke()
  }

  /** Only what another app hands over through a provider; a file: path could point into this app's own files. */
  fun readable(uri: Uri, context: Context): Boolean {
    if (uri.scheme != "content") return false
    // A "user@" prefix still reaches the provider it names, so compare without it.
    val authority = uri.authority?.substringAfterLast('@') ?: return false
    if (authority.startsWith("${context.packageName}.")) return false
    @Suppress("DEPRECATION")
    val owner = context.packageManager.resolveContentProvider(authority, 0)?.packageName
    return owner != context.packageName
  }

  fun take(): Intent? = pending.also { pending = null }
}

/**
 * Downloads in this process rather than through DownloadManager: the system downloader runs in
 * its own process, so it cannot use the app's certificate anchors (the self-hosted tunnel) or its
 * timeouts, and an unreachable address there leaves the request pending forever.
 *
 * Partial files live in the cache and survive a failed request or an app restart. A later call for
 * the same id resumes with Range and If-Range; the file is published only after the download is
 * complete. A finished file is reused only after the server confirms it is unchanged.
 */
class CowDownloadsModule(context: ReactApplicationContext) : ReactContextBaseJavaModule(context) {
  private val io: ExecutorService = Executors.newFixedThreadPool(2)
  private val fileLocks = ConcurrentHashMap<String, Any>()
  private val lastEmit = ConcurrentHashMap<String, Long>()

  init {
    SharedIntake.onArrive = {
      if (reactApplicationContext.hasActiveReactInstance()) {
        reactApplicationContext.getJSModule(DeviceEventManagerModule.RCTDeviceEventEmitter::class.java)
          .emit(SHARED_EVENT, null)
      }
    }
  }

  override fun getName() = "CowDownloads"
  /**
   * The system share sheet with the file itself, under its own name: a link is fetched
   * first, a path on the phone copied. Resolves once the sheet is up.
   */
  @ReactMethod
  fun share(source: String, fileName: String, mime: String, promise: Promise) {
    io.execute {
      try {
        val name = safeName(fileName).ifEmpty { safeName(URLUtil.guessFileName(source, null, null)) }.ifEmpty { "file" }
        val root = File(reactApplicationContext.cacheDir, "share").also(::sweep)
        val file = File(File(root, UUID.randomUUID().toString()).apply { mkdirs() }, name)
        if (source.startsWith("http://") || source.startsWith("https://")) {
          fetchInto(source, file)
        } else {
          File(if (source.startsWith("file:")) Uri.parse(source).path ?: source else source).copyTo(file, overwrite = true)
        }
        val context = reactApplicationContext
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.share", file)
        val send = Intent(Intent.ACTION_SEND)
          .setType(mime.ifEmpty { context.contentResolver.getType(uri) ?: "application/octet-stream" })
          .putExtra(Intent.EXTRA_STREAM, uri)
          .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        send.clipData = ClipData.newRawUri(name, uri)
        val chooser = Intent.createChooser(send, null)
        val activity = reactApplicationContext.currentActivity
        if (activity != null) {
          activity.runOnUiThread { activity.startActivity(chooser) }
        } else {
          context.startActivity(chooser.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        }
        promise.resolve(true)
      } catch (e: Exception) {
        promise.reject("share_failed", e.message, e)
      }
    }
  }

  /**
   * What another app last shared here, copied into the cache: `{files: [{uri, name, type, size}], text}`,
   * or null when nothing is waiting.
   */
  @ReactMethod
  fun takeShared(promise: Promise) {
    val intent = SharedIntake.take() ?: return promise.resolve(null)
    io.execute {
      try {
        @Suppress("DEPRECATION")
        val uris: List<Uri> = when (intent.action) {
          Intent.ACTION_VIEW -> listOfNotNull(intent.data)
          Intent.ACTION_SEND_MULTIPLE -> intent.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM).orEmpty()
          else -> listOfNotNull(intent.getParcelableExtra(Intent.EXTRA_STREAM))
        }
        val root = File(reactApplicationContext.cacheDir, "shared-in").also(::sweep)
        val folder = File(root, UUID.randomUUID().toString()).apply { mkdirs() }
        val files = Arguments.createArray()
        val resolver = reactApplicationContext.contentResolver
        uris.filter { SharedIntake.readable(it, reactApplicationContext) }.take(MAX_SHARED).forEachIndexed { i, uri ->
          // One the sender no longer lets this app read is left out, not the whole share.
          runCatching {
            val name = safeName(displayName(uri) ?: uri.lastPathSegment.orEmpty()).ifEmpty { "file" }
            val file = File(File(folder, i.toString()).apply { mkdirs() }, name)
            resolver.openInputStream(uri)?.use { input -> file.outputStream().use { input.copyTo(it) } } ?: return@runCatching
            files.pushMap(Arguments.createMap().apply {
              putString("uri", Uri.fromFile(file).toString())
              putString("name", name)
              putString("type", resolver.getType(uri) ?: intent.type ?: "application/octet-stream")
              putDouble("size", file.length().toDouble())
            })
          }
        }
        val result = Arguments.createMap()
        result.putArray("files", files)
        intent.getStringExtra(Intent.EXTRA_TEXT)?.let { result.putString("text", it) }
        promise.resolve(result)
      } catch (e: Exception) {
        promise.reject("failed", e.message, e)
      }
    }
  }

  private fun displayName(uri: Uri): String? =
    runCatching {
      reactApplicationContext.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use {
        if (it.moveToFirst()) it.getString(0) else null
      }
    }.getOrNull()

  private fun fetchInto(url: String, to: File) {
    val connection = URL(url).openConnection() as HttpURLConnection
    connection.connectTimeout = 15_000
    connection.readTimeout = 60_000
    try {
      if (connection.responseCode >= 400) throw IllegalStateException("HTTP ${connection.responseCode}")
      connection.inputStream.use { input -> to.outputStream().use { input.copyTo(it) } }
    } finally {
      connection.disconnect()
    }
  }

  /** Earlier copies are only needed while the other app reads them. */
  private fun sweep(root: File) {
    val cutoff = System.currentTimeMillis() - KEEP_MS
    root.listFiles()?.filter { it.lastModified() < cutoff }?.forEach { it.deleteRecursively() }
  }

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
        download(url, id, target, resume = true)
        if (openWith) {
          if (launch(target, name)) {
            promise.resolve("opened")
          } else {
            // A file left in the private cache is not a completed public download.
            promise.resolve(keepInDownloads(id, name, target))
          }
        } else {
          promise.resolve(keepInDownloads(id, name, target))
        }
        } catch (e: Exception) {
          // The status is what makes a failed retry actionable; keep it in the message.
          Log.w(TAG, "Download of $name failed: ${e.message}", e)
          promise.reject("download_failed", e.message ?: "Download failed", e)
        }
      }
    }
  }

  /** Downloads into a partial cache file, then atomically makes it the completed cache file. */
  private fun download(url: String, id: String, target: File, resume: Boolean) {
    val partial = partialFile(id)
    val known = if (resume) readValidators(id) else null
    val revalidate = target.exists() && known != null
    val ifRange = known?.ifRange?.takeUnless { revalidate }
    val offset = if (ifRange != null) partial.length() else 0L
    if (offset == 0L) {
      partial.delete()
    }
    // No TLS setup here: CowTls puts the imported anchors on java.net's defaults.
    val conn = (URL(url).openConnection() as HttpURLConnection).apply {
      connectTimeout = 15_000
      readTimeout = 60_000
      instanceFollowRedirects = true
      requestMethod = "GET"
      setRequestProperty("Accept", "*/*")
      if (revalidate) {
        known?.etag?.let { setRequestProperty("If-None-Match", it) }
        known?.lastModified?.let { setRequestProperty("If-Modified-Since", it) }
      } else if (ifRange != null && offset > 0) {
        setRequestProperty("Range", "bytes=$offset-")
        setRequestProperty("If-Range", ifRange)
      }
    }
    try {
      when (val code = conn.responseCode) {
        304 -> {
          if (revalidate) return
          throw IOException("HTTP $code")
        }
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
        // A server that ignores Range, or a file that changed since the part was written, sends it
        // whole: never append it to the old part, and never let the old copy pass revalidation.
        partial.delete()
        target.delete()
        writeValidators(id, conn)
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
      emitProgress(id, partial.length(), total, force = true)
      lastEmit.remove(id)
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

  /**
   * Progress crosses the JS bridge, and every event costs a render there. An 80 MB file arrives
   * in ~1300 chunks: sending each one saturates the JS thread, so the bar keeps replaying a
   * backlog long after the bytes are on disk and the rest of the screen stutters. One update per
   * [EMIT_INTERVAL_MS] is far more than an eye can take in, and the last one is always sent.
   */
  private fun emitProgress(id: String, loaded: Long, total: Long, force: Boolean = false) {
    val now = SystemClock.elapsedRealtime()
    if (!force && now - (lastEmit[id] ?: 0L) < EMIT_INTERVAL_MS) {
      return
    }
    lastEmit[id] = now
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

  /**
   * Copies into Downloads unless this file is already there. A second tap on download must not
   * leave a duplicate next to the first one, so the copy is remembered and checked by size.
   */
  private fun keepInDownloads(id: String, name: String, source: File): String {
    val known = remembered(id)
    if (known != null && stillThere(known)) {
      return "present"
    }
    val uri = saveToDownloads(name, source) ?: return "files"
    remember(id, uri, source.length())
    return "downloads"
  }

  private data class Saved(val uri: Uri, val size: Long)

  private fun remembered(id: String): Saved? {
    val raw = prefs().getString(SAVED_PREFIX + hash(id), null) ?: return null
    val uri = runCatching { Uri.parse(raw.substringBefore('|')) }.getOrNull() ?: return null
    return Saved(uri, raw.substringAfter('|', "").toLongOrNull() ?: return null)
  }

  /** A row outlives the file itself: the user may have deleted it from Files. */
  private fun stillThere(saved: Saved): Boolean {
    val resolver = reactApplicationContext.contentResolver
    return runCatching {
      resolver.openAssetFileDescriptor(saved.uri, "r")?.use { it.length == saved.size }
        ?: resolver.query(saved.uri, arrayOf(OpenableColumns.SIZE), null, null, null)?.use { c ->
          c.moveToFirst() && c.getLong(0) == saved.size
        }
        ?: false
    }.getOrDefault(false)
  }

  private fun remember(id: String, uri: Uri, size: Long) {
    val prefs = prefs()
    if (prefs.all.size >= MAX_REMEMBERED) {
      // Cheap ceiling: the table only saves a duplicate copy, so losing it costs little.
      prefs.edit().clear().apply()
    }
    prefs.edit().putString(SAVED_PREFIX + hash(id), "$uri|$size").apply()
  }

  private fun prefs() = reactApplicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

  /** Downloads to the public Downloads folder; MediaStore is the only writable path on Android 10+. */
  private fun saveToDownloads(name: String, source: File): Uri? {
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
      val resolver = reactApplicationContext.contentResolver
      val values = ContentValues().apply {
        put(MediaStore.Downloads.DISPLAY_NAME, name)
        put(MediaStore.Downloads.MIME_TYPE, mimeOf(name))
        put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
        put(MediaStore.Downloads.IS_PENDING, 1)
      }
      val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values) ?: return null
      try {
        val output = resolver.openOutputStream(uri) ?: throw IOException("Cannot open download destination")
        source.inputStream().use { input -> output.use { input.copyTo(it) } }
        values.clear()
        values.put(MediaStore.Downloads.IS_PENDING, 0)
        resolver.update(uri, values, null, null)
        return uri
      } catch (e: Exception) {
        resolver.delete(uri, null, null)
        throw e
      }
    }
    val dir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
    if (!dir.exists() && !dir.mkdirs()) {
      return null
    }
    val target = availableFile(dir, name)
    try {
      source.inputStream().use { input -> target.outputStream().use { output -> input.copyTo(output) } }
      MediaScannerConnection.scanFile(reactApplicationContext, arrayOf(target.absolutePath), null, null)
      return Uri.fromFile(target)
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

  private fun downloadsDir(): File = File(reactApplicationContext.cacheDir, "downloads").apply { mkdirs() }

  private fun partialFile(id: String): File = File(downloadsDir(), "${hash(id)}.part")

  /** File systems cap a name at 255 bytes, which a long CJK name reaches quickly. */
  private fun cachedFile(id: String, name: String): File {
    val prefix = "${hash(id)}-"
    return File(downloadsDir(), prefix + fitBytes(name, MAX_NAME_BYTES - prefix.length))
  }

  /** Shortens the stem by whole characters until the UTF-8 name fits, keeping the extension. */
  private fun fitBytes(name: String, max: Int): String {
    if (name.toByteArray().size <= max) return name
    val dot = name.lastIndexOf('.')
    val ext = if (dot > 0 && name.length - dot <= MAX_EXT_CHARS) name.substring(dot) else ""
    val stem = name.substring(0, name.length - ext.length)
    val budget = max - ext.toByteArray().size
    val out = StringBuilder()
    var used = 0
    var i = 0
    while (i < stem.length) {
      val end = i + Character.charCount(stem.codePointAt(i))
      val size = stem.substring(i, end).toByteArray().size
      if (used + size > budget) break
      out.append(stem, i, end)
      used += size
      i = end
    }
    return out.toString() + ext
  }

  /** What the server said identifies this version of the file; kept next to its part and cache. */
  private class Validators(val etag: String?, val lastModified: String?) {
    /** If-Range only takes a strong ETag or a date. */
    val ifRange: String? get() = etag?.takeUnless { it.startsWith("W/") } ?: lastModified
  }

  private fun validatorFile(id: String): File = File(downloadsDir(), "${hash(id)}.validators")

  private fun readValidators(id: String): Validators? = runCatching {
    val lines = validatorFile(id).readLines()
    Validators(lines.getOrNull(0)?.ifEmpty { null }, lines.getOrNull(1)?.ifEmpty { null })
  }.getOrNull()?.takeIf { it.etag != null || it.lastModified != null }

  private fun writeValidators(id: String, conn: HttpURLConnection) {
    val etag = conn.getHeaderField("ETag")
    val modified = conn.getHeaderField("Last-Modified")
    val file = validatorFile(id)
    if (etag == null && modified == null) {
      file.delete()
    } else {
      file.writeText("${etag.orEmpty()}\n${modified.orEmpty()}\n")
    }
  }

  private fun hash(value: String): String =
    MessageDigest.getInstance("SHA-256").digest(value.toByteArray()).joinToString("") { "%02x".format(it) }

  private fun contentRangeTotal(header: String?): Long? =
    header?.let { Regex("""/(\d+)$""").find(it)?.groupValues?.get(1)?.toLongOrNull() }

  /** Hands the file to another app through FileProvider, which can grant it to a third party. */
  private fun launch(file: File, name: String): Boolean {
    val uri = runCatching {
      FileProvider.getUriForFile(reactApplicationContext, "${reactApplicationContext.packageName}.files", file)
    }.onFailure {
      // Usually a file outside the roots in res/xml/file_paths.xml.
      Log.w(TAG, "Cannot share $name: ${it.message}")
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
    const val SHARED_EVENT = "cowShared"
    private const val MAX_SHARED = 9
    private const val KEEP_MS = 24 * 60 * 60 * 1000L
    const val TAG = "CowDownloads"
    const val PREFS = "cow-downloads"
    const val SAVED_PREFIX = "saved-"
    const val MAX_REMEMBERED = 500
    const val EMIT_INTERVAL_MS = 100L
    const val MAX_NAME_BYTES = 255
    const val MAX_EXT_CHARS = 16

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
