package ai.cowagent.app.reminders

import ai.cowagent.app.MainActivity
import ai.cowagent.app.R
import ai.cowagent.app.kernel.CowKernel
import android.app.AlarmManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import org.json.JSONArray
import org.json.JSONObject
import kotlin.concurrent.thread

/**
 * Reminders of scheduled tasks, kept by the system: the kernel stops with the app, so the
 * alarms stand in for it while the app is in the background or gone. Kept on disk so a
 * restart of the phone can set them again.
 */
object TaskReminders {
  private const val PREFS = "cow_reminders"
  private const val KEY = "items"
  private const val ACTION = "ai.cowagent.app.REMINDER"
  const val CHANNEL = "reminders"
  const val MAX = 50

  /**
   * What a task the agent itself carries out adds: its `task` id, and the texts for how its run
   * went: `done`, `failed` (with `{error}`) and `running`, when it has not ended in time.
   */
  val AGENT_KEYS = listOf("task", "done", "failed", "running")

  /** The chat a task delivers to, opened by tapping its reminder. */
  const val SESSION = "session"

  /** Replaces every reminder set before with these: `{at (epoch ms), title, body, session}` and [AGENT_KEYS]. */
  fun replace(context: Context, items: JSONArray) {
    val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    val before = runCatching { JSONArray(prefs.getString(KEY, "[]")) }.getOrDefault(JSONArray())
    val alarms = alarms(context)
    for (i in 0 until before.length()) {
      pending(context, i, null, PendingIntent.FLAG_NO_CREATE)?.let(alarms::cancel)
    }
    prefs.edit().putString(KEY, items.toString()).apply()
    arm(context, items)
  }

  /** After a restart of the phone, which forgets every alarm. */
  fun restore(context: Context) {
    val stored = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY, null) ?: return
    runCatching { arm(context, JSONArray(stored)) }
  }

  private fun arm(context: Context, items: JSONArray): Int {
    val alarms = alarms(context)
    val now = System.currentTimeMillis()
    // Without the exact-alarm grant (off by default from Android 14) the system may run it a few minutes late.
    val exact = Build.VERSION.SDK_INT < Build.VERSION_CODES.S || alarms.canScheduleExactAlarms()
    var armed = 0
    for (i in 0 until minOf(items.length(), MAX)) {
      val item = items.optJSONObject(i) ?: continue
      val at = item.optLong("at")
      if (at <= now) continue
      val intent = pending(context, i, item, PendingIntent.FLAG_UPDATE_CURRENT) ?: continue
      if (exact) {
        alarms.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, intent)
      } else {
        alarms.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, intent)
      }
      armed++
    }
    return armed
  }

  /** Alarms are told apart by request code alone; the extras ride along for the receiver. */
  private fun pending(context: Context, index: Int, item: JSONObject?, flags: Int): PendingIntent? {
    val intent = Intent(context, ReminderReceiver::class.java).setAction(ACTION)
    if (item != null) {
      intent.putExtra("title", item.optString("title")).putExtra("body", item.optString("body")).putExtra("at", item.optLong("at"))
        .putExtra(SESSION, item.optString(SESSION))
      AGENT_KEYS.forEach { intent.putExtra(it, item.optString(it)) }
    }
    return PendingIntent.getBroadcast(context, index, intent, flags or PendingIntent.FLAG_IMMUTABLE)
  }

  private fun alarms(context: Context) = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager

  /** Each reminder its own notification, so two coming due together both stay. */
  fun show(context: Context, at: Long, title: String, body: String, session: String): Thread? =
    Notices.post(context, CHANNEL, R.string.reminder_channel, NotificationCompat.CATEGORY_REMINDER,
      ((at / 1000) xor title.hashCode().toLong()).toInt(), title, body, session)
}

/** The chat a tapped notification is about, kept until the app asks for it. */
object NotificationTaps {
  private const val EXTRA = "ai.cowagent.app.SESSION"
  @Volatile private var session: String? = null

  fun open(intent: Intent, session: String): Intent = intent.putExtra(EXTRA, session)

  fun receive(intent: Intent?) {
    val tapped = intent?.getStringExtra(EXTRA)?.takeIf { it.isNotEmpty() } ?: return
    session = tapped
    // The activity keeps its intent, which must not open the chat again once recreated.
    intent.removeExtra(EXTRA)
  }

  fun take(): String? = session.also { session = null }
}

object Notices {
  private const val REPLY_CHANNEL = "replies"

  /** A reply that finished while the app was away; a newer one in the same chat takes its place. */
  fun reply(context: Context, key: String, title: String, body: String, session: String): Thread? =
    post(context, REPLY_CHANNEL, R.string.reply_channel, NotificationCompat.CATEGORY_MESSAGE, key.hashCode(), title, body, session)

  /** What a scheduled task came up with, once it has run. */
  fun task(context: Context, key: String, title: String, body: String, session: String): Thread? =
    post(context, TaskReminders.CHANNEL, R.string.reminder_channel, NotificationCompat.CATEGORY_REMINDER, key.hashCode(), title, body, session)

  private const val PREFS = "cow_notices"
  private const val DROPPED = "dropped"
  private const val SETTLE_MS = 1500L

  /**
   * Ids are per channel, which is the tag. Tapping opens the app on [session], if any. Then checks,
   * off this thread, that the system kept it; join the returned thread to have that done before going on.
   */
  fun post(context: Context, channelId: String, channelName: Int, category: String, id: Int, title: String, body: String, session: String): Thread? {
    val manager = NotificationManagerCompat.from(context)
    if (!manager.areNotificationsEnabled()) return null
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
      val channel = NotificationChannel(channelId, context.getString(channelName), NotificationManager.IMPORTANCE_HIGH)
      context.getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }
    // Told apart by request code, so each notification keeps its own chat.
    val open = context.packageManager.getLaunchIntentForPackage(context.packageName)?.let {
      PendingIntent.getActivity(context, "$channelId:$id".hashCode(), NotificationTaps.open(it, session),
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }
    val notification = NotificationCompat.Builder(context, channelId)
      .setSmallIcon(R.drawable.ic_notification)
      .setContentTitle(title.ifBlank { context.getString(R.string.app_name) })
      .setContentText(body)
      .setStyle(NotificationCompat.BigTextStyle().bigText(body))
      .setPriority(NotificationCompat.PRIORITY_HIGH)
      .setCategory(category)
      .setAutoCancel(true)
      .setContentIntent(open)
      .build()
    try {
      manager.notify(channelId, id, notification)
    } catch (e: SecurityException) {
      // Notifications were turned off between the check and now.
      return null
    }
    return thread(name = "cow-notice") {
      Thread.sleep(SETTLE_MS)
      if (!kept(context, channelId, id)) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putBoolean(DROPPED, true).apply()
      }
    }
  }

  /**
   * Some systems' notification assistants drop an app's notifications on arrival or file them as
   * unimportant, and none says so. What shows is that it is gone, too soon to have been swiped
   * away, or that its channel was turned down below making a sound.
   */
  private fun kept(context: Context, channelId: String, id: Int): Boolean {
    val manager = context.getSystemService(NotificationManager::class.java) ?: return true
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
      val channel = manager.getNotificationChannel(channelId)
      if (channel != null && channel.importance < NotificationManager.IMPORTANCE_DEFAULT) return false
    }
    return manager.activeNotifications.any { it.id == id && it.tag == channelId }
  }

  /** Whether one was dropped since the last asking. */
  fun takeDropped(context: Context): Boolean {
    val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    val dropped = prefs.getBoolean(DROPPED, false)
    if (dropped) prefs.edit().remove(DROPPED).apply()
    return dropped
  }
}

/**
 * One reminder coming due. While the app is on screen the chat shows the delivery itself. A task
 * for the agent, with the kernel still in this process, is run now and told with its result.
 */
class ReminderReceiver : BroadcastReceiver() {
  override fun onReceive(context: Context, intent: Intent) {
    if (MainActivity.visible) return
    val at = intent.getLongExtra("at", System.currentTimeMillis())
    val title = intent.getStringExtra("title").orEmpty()
    val body = intent.getStringExtra("body").orEmpty()
    val task = intent.getStringExtra("task").orEmpty()
    val session = intent.getStringExtra(TaskReminders.SESSION).orEmpty()
    // In the background the system freezes the app, kernel and all, except while a broadcast
    // like this one is being handled, which may take up to a minute.
    val pending = goAsync()
    thread(name = "cow-reminder") {
      try {
        tell(context, intent, at, title, body, task, session)?.join()
      } catch (e: Throwable) {
        TaskReminders.show(context, at, title, body, session)?.join()
      } finally {
        pending.finish()
      }
    }
  }

  private fun tell(context: Context, intent: Intent, at: Long, title: String, body: String, task: String, session: String): Thread? {
    if (task.isEmpty() || !CowKernel.running) return TaskReminders.show(context, at, title, body, session)
    // A run starts once its time has come, so an earlier one of the same task never counts.
    val run = CowKernel.awaitRun(task, at / 1000 - 1, WAIT_S)
      ?: return TaskReminders.show(context, at, title, intent.getStringExtra("running").orEmpty().ifEmpty { body }, session)
    val text = if (run.status in DONE) {
      clip(run.output).ifEmpty { intent.getStringExtra("done").orEmpty() }
    } else {
      intent.getStringExtra("failed").orEmpty().replace("{error}", run.error)
    }
    return Notices.task(context, run.id, title, text, session)
  }

  private fun clip(text: String): String {
    val flat = text.replace(Regex("\\s+"), " ").trim()
    return if (flat.length > NOTICE_MAX) flat.take(NOTICE_MAX) + "…" else flat
  }

  private companion object {
    /** Within the time a broadcast may take. */
    const val WAIT_S = 45
    const val NOTICE_MAX = 200
    val DONE = setOf("done", "success")
  }
}

class RestartReceiver : BroadcastReceiver() {
  override fun onReceive(context: Context, intent: Intent) {
    if (intent.action == Intent.ACTION_BOOT_COMPLETED) TaskReminders.restore(context)
  }
}
