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
import android.net.Uri
import android.media.AudioAttributes
import android.media.RingtoneManager
import android.os.Build
import android.provider.Settings
import android.util.Log
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
  /**
   * A channel's sound is frozen once it exists, so a build that created it silent would stay
   * silent forever. A new id is how a channel is changed; the old one is removed on first use.
   */
  private const val CHANNEL_ID = "replies3"
  /** Ids this channel had before it carried a sound; a channel's sound can never be edited. */
  private val CHANNEL_ID_LEGACY = arrayOf("replies", "replies2")
  private val VIBRATION = longArrayOf(0, 250, 150, 250)
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
    Log.i("CowNotify", stateOf(context))
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
      // A reply is a message: saying so is what keeps chat-shaped apps out of a ROM's
      // "unimportant notifications" bucket, where sound and vibration are dropped.
      .setCategory(NotificationCompat.CATEGORY_MESSAGE)
      .setPriority(NotificationCompat.PRIORITY_DEFAULT)
      // Ignored from Android 8 on, where the channel owns the sound; Android 7 has no channel.
      .setDefaults(NotificationCompat.DEFAULT_ALL)
      .setSound(soundUri())
      .setVibrate(VIBRATION)
      .build()
    return runCatching { manager.notify(sessionId.hashCode(), notification) }.isSuccess
  }

  /**
   * The phone's own notification tone. RingtoneManager is the source the settings screen edits;
   * it also covers the devices where the settings URI is stored but resolves to nothing.
   */
  private fun soundUri(): Uri? =
    RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION)
      ?: Settings.System.DEFAULT_NOTIFICATION_URI

  private fun notificationAudio(): AudioAttributes =
    AudioAttributes.Builder()
      .setUsage(AudioAttributes.USAGE_NOTIFICATION)
      .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
      .build()

  /** A one-line summary of why a notification may or may not make a sound; it goes to logcat. */
  private fun stateOf(context: Context): String {
    val manager = NotificationManagerCompat.from(context)
    val channel =
      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
        manager.getNotificationChannel(CHANNEL_ID)
      } else {
        null
      }
    val dnd =
      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
        (context.getSystemService(NotificationManager::class.java))?.currentInterruptionFilter ?: -1
      } else {
        -1
      }
    return buildString {
      append("enabled=").append(manager.areNotificationsEnabled())
      append(", channel=").append(CHANNEL_ID)
      append(", importance=").append(channel?.importance ?: -1)
      append(", sound=").append(channel?.sound ?: "none")
      append(", vibrate=").append(channel?.shouldVibrate() ?: false)
      append(", dnd=").append(dnd)
    }
  }

  private fun ensureChannel(context: Context) {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
      return
    }
    val manager = context.getSystemService(NotificationManager::class.java) ?: return
    // Earlier versions of this channel had no sound and cannot be edited.
    CHANNEL_ID_LEGACY.forEach(manager::deleteNotificationChannel)
    if (manager.getNotificationChannel(CHANNEL_ID) != null) {
      return
    }
    val name = context.getString(R.string.notify_channel_replies)
    manager.createNotificationChannel(
      // HIGH rather than DEFAULT: it is the importance that reliably carries a sound and a
      // heads-up, and some ROMs quietly mute their own default channels.
      NotificationChannel(CHANNEL_ID, name, NotificationManager.IMPORTANCE_HIGH).apply {
        description = context.getString(R.string.notify_channel_replies_desc)
        setShowBadge(true)
        // The system's own notification sound, at notification volume, with vibration: an
        // announcement the user hears without the app inventing a tone.
        soundUri()?.let { setSound(it, notificationAudio()) }
        enableVibration(true)
        vibrationPattern = VIBRATION
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
