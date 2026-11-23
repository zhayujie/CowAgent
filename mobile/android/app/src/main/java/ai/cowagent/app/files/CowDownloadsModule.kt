package ai.cowagent.app.files

import android.annotation.SuppressLint
import android.app.DownloadManager
import android.content.BroadcastReceiver
import android.content.ClipData
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.OpenableColumns
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
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
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
  fun readable(uri: Uri, context: Context): Boolean =
    uri.scheme == "content" && uri.authority != "${context.packageName}.share"

  fun take(): Intent? = pending.also { pending = null }
}

class CowDownloadsModule(context: ReactApplicationContext) : ReactContextBaseJavaModule(context) {
  private val pending = ConcurrentHashMap<Long, Promise>()
  private var receiver: BroadcastReceiver? = null
  private val worker = Executors.newSingleThreadExecutor()

  init {
    SharedIntake.onArrive = {
      if (reactApplicationContext.hasActiveReactInstance()) {
        reactApplicationContext.getJSModule(DeviceEventManagerModule.RCTDeviceEventEmitter::class.java).emit(SHARED_EVENT, null)
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
    worker.execute {
      try {
        val name = safeName(fileName).ifEmpty { safeName(URLUtil.guessFileName(source, null, null)) }.ifEmpty { "file" }
        val root = File(reactApplicationContext.cacheDir, "share").also(::sweep)
        val file = File(File(root, UUID.randomUUID().toString()).apply { mkdirs() }, name)
        if (source.startsWith("http://") || source.startsWith("https://")) {
          fetch(source, file)
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
    worker.execute {
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

  private fun fetch(url: String, to: File) {
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

  /** Queues the file with the system downloader into Downloads; resolves with "downloads" once it is saved. */
  @ReactMethod
  fun save(url: String, fileName: String, promise: Promise) {
    try {
      val name = safeName(fileName).ifEmpty { safeName(URLUtil.guessFileName(url, null, null)) }.ifEmpty { "download" }
      val request = DownloadManager.Request(Uri.parse(url))
        .setTitle(name)
        .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
        .setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name)
      listen()
      val id = manager().enqueue(request)
      pending[id] = promise
      // A small file can finish before it was registered above, and its broadcast found nothing.
      settle(id, finishedOnly = true)
    } catch (e: Exception) {
      promise.reject("download_failed", e.message, e)
    }
  }

  override fun invalidate() {
    SharedIntake.onArrive = null
    worker.shutdown()
    receiver?.let { runCatching { reactApplicationContext.applicationContext.unregisterReceiver(it) } }
    receiver = null
    super.invalidate()
  }

  private fun manager() = reactApplicationContext.getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager

  private fun settle(id: Long, finishedOnly: Boolean = false) {
    val status = manager().query(DownloadManager.Query().setFilterById(id))?.use { c ->
      if (c.moveToFirst()) c.getInt(c.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS)) else null
    }
    val done = status == DownloadManager.STATUS_SUCCESSFUL
    if (finishedOnly && !done && status != DownloadManager.STATUS_FAILED) {
      return
    }
    val promise = pending.remove(id) ?: return
    if (done) {
      promise.resolve("downloads")
    } else {
      promise.reject("download_failed", "Download did not complete")
    }
  }

  // The broadcast comes from the system download provider, another app, so the receiver is exported.
  @SuppressLint("UnspecifiedRegisterReceiverFlag")
  @Synchronized
  private fun listen() {
    if (receiver != null) {
      return
    }
    val r = object : BroadcastReceiver() {
      override fun onReceive(context: Context, intent: Intent) {
        val id = intent.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID, -1)
        if (pending.containsKey(id)) {
          settle(id)
        }
      }
    }
    val filter = IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE)
    val app = reactApplicationContext.applicationContext
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
      app.registerReceiver(r, filter, Context.RECEIVER_EXPORTED)
    } else {
      app.registerReceiver(r, filter)
    }
    receiver = r
  }

  private fun safeName(name: String): String =
    name.replace(Regex("[\\\\/:*?\"<>|\\p{Cntrl}]"), "_").trim().trimStart('.')

  companion object {
    const val SHARED_EVENT = "cowShared"
    private const val MAX_SHARED = 9
    private const val KEEP_MS = 24 * 60 * 60 * 1000L
  }
}

class CowDownloadsPackage : ReactPackage {
  override fun createNativeModules(reactContext: ReactApplicationContext): List<NativeModule> =
    listOf(CowDownloadsModule(reactContext))

  override fun createViewManagers(reactContext: ReactApplicationContext): List<ViewManager<in Nothing, in Nothing>> =
    emptyList()
}
