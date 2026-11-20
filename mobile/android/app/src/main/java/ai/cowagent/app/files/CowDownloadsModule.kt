package ai.cowagent.app.files

import android.annotation.SuppressLint
import android.app.DownloadManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.webkit.URLUtil
import com.facebook.react.ReactPackage
import com.facebook.react.bridge.NativeModule
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import com.facebook.react.uimanager.ViewManager
import java.util.concurrent.ConcurrentHashMap

class CowDownloadsModule(context: ReactApplicationContext) : ReactContextBaseJavaModule(context) {
  private val pending = ConcurrentHashMap<Long, Promise>()
  private var receiver: BroadcastReceiver? = null

  override fun getName() = "CowDownloads"

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
}

class CowDownloadsPackage : ReactPackage {
  override fun createNativeModules(reactContext: ReactApplicationContext): List<NativeModule> =
    listOf(CowDownloadsModule(reactContext))

  override fun createViewManagers(reactContext: ReactApplicationContext): List<ViewManager<in Nothing, in Nothing>> =
    emptyList()
}
