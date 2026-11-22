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
import java.util.concurrent.ConcurrentHashMap

class CowDownloadsModule(context: ReactApplicationContext) : ReactContextBaseJavaModule(context) {
  private val pending = ConcurrentHashMap<Long, Promise>()
  private val names = ConcurrentHashMap<Long, String>()
  // Downloads that should be handed to another app once they finish.
  private val openerIds = java.util.Collections.newSetFromMap(ConcurrentHashMap<Long, Boolean>())
  private var receiver: BroadcastReceiver? = null

  override fun getName() = "CowDownloads"

  /** Queues the file with the system downloader into Downloads; resolves with "downloads" once it is saved. */
  @ReactMethod
  fun save(url: String, fileName: String, promise: Promise) {
    enqueue(url, fileName, promise)
  }

  /**
   * Downloads the file and then opens the system "open with" chooser, so Word/WPS can take it.
   * Resolves with "opened" when the chooser was launched, or "downloads" when the file was saved
   * but no app could be started (the file is still in Downloads).
   */
  @ReactMethod
  fun open(url: String, fileName: String, promise: Promise) {
    enqueue(url, fileName, promise, openWith = true)
  }

  override fun invalidate() {
    receiver?.let { runCatching { reactApplicationContext.applicationContext.unregisterReceiver(it) } }
    receiver = null
    super.invalidate()
  }

  private fun manager() = reactApplicationContext.getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager

  /** Queues the download and returns its id, or null when it could not be started. */
  private fun enqueue(url: String, fileName: String, promise: Promise, openWith: Boolean = false): Long? {
    return try {
      val name = safeName(fileName).ifEmpty { safeName(URLUtil.guessFileName(url, null, null)) }.ifEmpty { "download" }
      val request = DownloadManager.Request(Uri.parse(url))
        .setTitle(name)
        .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
        .setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name)
      listen()
      val id = manager().enqueue(request)
      if (openWith) {
        openerIds.add(id)
      }
      names[id] = name
      pending[id] = promise
      // A small file can finish before it was registered above, and its broadcast found nothing.
      settle(id, finishedOnly = true)
      id
    } catch (e: Exception) {
      promise.reject("download_failed", e.message, e)
      null
    }
  }

  private fun settle(id: Long, finishedOnly: Boolean = false) {
    val status = manager().query(DownloadManager.Query().setFilterById(id))?.use { c ->
      if (c.moveToFirst()) c.getInt(c.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS)) else null
    }
    val done = status == DownloadManager.STATUS_SUCCESSFUL
    if (finishedOnly && !done && status != DownloadManager.STATUS_FAILED) {
      return
    }
    val promise = pending.remove(id) ?: return
    val name = names.remove(id)
    if (!done) {
      openerIds.remove(id)
      promise.reject("download_failed", "Download did not complete")
      return
    }
    if (openerIds.remove(id) && name != null && launch(id, name)) {
      promise.resolve("opened")
    } else {
      promise.resolve("downloads")
    }
  }

  /**
   * Hands the finished download to another app. The file is copied to the app cache and shared
   * through FileProvider, because the DownloadManager URI cannot be granted to a third party.
   */
  private fun launch(id: Long, name: String): Boolean {
    val downloaded = runCatching { manager().getUriForDownloadedFile(id) }.getOrNull() ?: return false
    val file = runCatching {
      val dir = java.io.File(reactApplicationContext.cacheDir, "open").apply { mkdirs() }
      val target = java.io.File(dir, name)
      reactApplicationContext.contentResolver.openInputStream(downloaded)?.use { input ->
        target.outputStream().use { output -> input.copyTo(output) }
      } ?: return false
      target
    }.getOrNull() ?: return false
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
