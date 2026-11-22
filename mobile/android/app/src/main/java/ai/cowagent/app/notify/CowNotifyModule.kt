package ai.cowagent.app.notify

import ai.cowagent.app.MainActivity
import ai.cowagent.app.R
import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.facebook.react.ReactPackage
import com.facebook.react.bridge.NativeModule
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import com.facebook.react.uimanager.ViewManager

/**
 * Announces a finished reply and carries a tap back to the conversation it belongs to.
 *
 * The tap only leaves a session id behind ([PendingSession]); the app reads it once its
 * navigation tree is ready, so a cold start and a warm resume take the same path.
 */
class CowNotifyModule(private val context: ReactApplicationContext) :
  ReactContextBaseJavaModule(context) {

  override fun getName() = "CowNotify"

  /** Resolves whether a notification was posted: permission and the user's switch both decide. */
  @ReactMethod
  fun notify(title: String, body: String, sessionId: String, promise: Promise) {
    promise.resolve(CowNotify.post(context, title, body, sessionId))
  }

  /** Drops the conversation's notice: it is on screen now, so the shade need not keep it. */
  @ReactMethod
  fun clear(sessionId: String, promise: Promise) {
    runCatching { NotificationManagerCompat.from(context).cancel(sessionId.hashCode()) }
    promise.resolve(null)
  }

  /** The conversation a notification opened, if any; cleared as it is read. */
  @ReactMethod
  fun consumeOpen(promise: Promise) {
    promise.resolve(PendingSession.take())
  }

  // Kept for modules that emit events; this one only answers calls.
  @ReactMethod
  fun addListener(name: String) = Unit

  @ReactMethod
  fun removeListeners(count: Int) = Unit
}

/** Where a notification tap parks the conversation until the app is ready to show it. */
object PendingSession {
  @Volatile
  private var sessionId: String? = null

  fun put(id: String?) {
    if (!id.isNullOrEmpty()) {
      sessionId = id
    }
  }

  fun take(): String? = sessionId.also { sessionId = null }
}

internal object CowNotify {
  private const val CHANNEL_ID = "replies"
  const val EXTRA_SESSION = "cow_session"

  fun post(context: Context, title: String, body: String, sessionId: String): Boolean {
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
      ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) !=
      PackageManager.PERMISSION_GRANTED
    ) {
      return false
    }
    val manager = NotificationManagerCompat.from(context)
    if (!manager.areNotificationsEnabled()) {
      return false
    }
    ensureChannel(context)
    val open = Intent(context, MainActivity::class.java).apply {
      // One task, one screen: a tap lands on the running app instead of stacking another copy.
      addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
      putExtra(EXTRA_SESSION, sessionId)
    }
    // One per conversation, so a later reply replaces the earlier notice instead of piling up.
    val pending = PendingIntent.getActivity(
      context,
      sessionId.hashCode(),
      open,
      PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
    )
    val notification = NotificationCompat.Builder(context, CHANNEL_ID)
      .setSmallIcon(R.drawable.ic_notification)
      .setContentTitle(title)
      .setContentText(body)
      .setStyle(NotificationCompat.BigTextStyle().bigText(body))
      .setContentIntent(pending)
      .setAutoCancel(true)
      .setPriority(NotificationCompat.PRIORITY_DEFAULT)
      .build()
    return runCatching { manager.notify(sessionId.hashCode(), notification) }.isSuccess
  }

  private fun ensureChannel(context: Context) {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
      return
    }
    val manager = context.getSystemService(NotificationManager::class.java) ?: return
    if (manager.getNotificationChannel(CHANNEL_ID) != null) {
      return
    }
    val name = context.getString(R.string.notify_channel_replies)
    manager.createNotificationChannel(
      NotificationChannel(CHANNEL_ID, name, NotificationManager.IMPORTANCE_DEFAULT).apply {
        description = context.getString(R.string.notify_channel_replies_desc)
        setShowBadge(true)
      },
    )
  }
}

class CowNotifyPackage : ReactPackage {
  override fun createNativeModules(reactContext: ReactApplicationContext): List<NativeModule> =
    listOf(CowNotifyModule(reactContext))

  override fun createViewManagers(reactContext: ReactApplicationContext): List<ViewManager<in Nothing, in Nothing>> =
    emptyList()
}
