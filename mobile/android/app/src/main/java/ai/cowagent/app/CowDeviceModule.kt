package ai.cowagent.app

import ai.cowagent.app.reminders.Notices
import ai.cowagent.app.reminders.NotificationTaps
import ai.cowagent.app.reminders.TaskReminders
import android.content.ActivityNotFoundException
import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.media.AudioManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.BatteryManager
import android.os.Environment
import android.os.PowerManager
import android.os.StatFs
import android.location.Address
import android.location.Geocoder
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.net.Uri
import android.os.Build
import android.os.CancellationSignal
import android.os.Handler
import android.os.Looper
import android.provider.CalendarContract.Calendars
import android.provider.CalendarContract.Events
import android.provider.CalendarContract.Instances
import android.provider.CalendarContract.Reminders
import android.provider.ContactsContract.CommonDataKinds.Email
import android.provider.ContactsContract.CommonDataKinds.Organization
import android.provider.ContactsContract.CommonDataKinds.Phone
import android.provider.ContactsContract.Contacts
import android.provider.ContactsContract.Data
import androidx.core.location.LocationManagerCompat
import com.facebook.react.ReactPackage
import com.facebook.react.bridge.Arguments
import com.facebook.react.bridge.NativeModule
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import com.facebook.react.bridge.ReadableArray
import com.facebook.react.bridge.ReadableMap
import com.facebook.react.uimanager.ViewManager
import java.util.Calendar
import java.util.Locale
import java.util.TimeZone
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import org.json.JSONArray
import org.json.JSONObject

/**
 * What the phone tools read from and add to the phone itself. The app has asked for the
 * permission before calling in; a missing one rejects with permission_denied.
 */
class CowDeviceModule(context: ReactApplicationContext) : ReactContextBaseJavaModule(context) {
  override fun getName() = "CowDevice"

  override fun getConstants(): Map<String, Any> {
    val context = reactApplicationContext
    val packages = context.packageManager
    val version = runCatching { packages.getPackageInfo(context.packageName, 0).versionName }.getOrNull()
    // The app market it came from, which then also delivers its updates; empty when sideloaded via adb.
    val installer = runCatching {
      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
        packages.getInstallSourceInfo(context.packageName).installingPackageName
      } else {
        @Suppress("DEPRECATION")
        packages.getInstallerPackageName(context.packageName)
      }
    }.getOrNull()
    return mapOf("appVersion" to (version ?: ""), "installer" to (installer ?: ""))
  }

  private val main = Handler(Looper.getMainLooper())
  private val worker = Executors.newSingleThreadExecutor()

  /** One location fix, with a street address when the phone's geocoder can give one. */
  @ReactMethod
  fun currentLocation(promise: Promise) {
    val lm = reactApplicationContext.getSystemService(Context.LOCATION_SERVICE) as LocationManager
    if (!LocationManagerCompat.isLocationEnabled(lm)) {
      promise.reject("location_off", "Location is turned off")
      return
    }
    val providers = PROVIDERS.filter { it in lm.allProviders && lm.isProviderEnabled(it) }
    val recent = try {
      providers.mapNotNull { lm.getLastKnownLocation(it) }.maxByOrNull { it.time }
    } catch (e: SecurityException) {
      promise.reject("permission_denied", e.message, e)
      return
    }
    if (recent != null && System.currentTimeMillis() - recent.time < RECENT_MS) {
      resolve(recent, promise)
      return
    }
    tryProviders(lm, providers, 0, recent, promise)
  }

  /** Each provider in turn until one gives a fix; a stale fix beats none. */
  private fun tryProviders(lm: LocationManager, providers: List<String>, index: Int, stale: Location?, promise: Promise) {
    if (index >= providers.size) {
      if (stale != null) resolve(stale, promise) else promise.reject("no_fix", "No location fix")
      return
    }
    fixFrom(lm, providers[index]) { location, error ->
      when {
        error != null -> promise.reject("permission_denied", error.message, error)
        location != null -> resolve(location, promise)
        else -> tryProviders(lm, providers, index + 1, stale, promise)
      }
    }
  }

  private fun fixFrom(lm: LocationManager, provider: String, done: (Location?, SecurityException?) -> Unit) {
    val finished = AtomicBoolean(false)
    val finish = { location: Location?, error: SecurityException? ->
      if (finished.compareAndSet(false, true)) done(location, error)
    }
    main.post {
      try {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
          val cancel = CancellationSignal()
          lm.getCurrentLocation(provider, cancel, worker) { finish(it, null) }
          main.postDelayed({
            cancel.cancel()
            finish(null, null)
          }, FIX_TIMEOUT_MS)
        } else {
          val listener = LocationListener { finish(it, null) }
          @Suppress("DEPRECATION")
          lm.requestSingleUpdate(provider, listener, Looper.getMainLooper())
          main.postDelayed({
            lm.removeUpdates(listener)
            finish(null, null)
          }, FIX_TIMEOUT_MS)
        }
      } catch (e: SecurityException) {
        finish(null, e)
      } catch (e: IllegalArgumentException) {
        finish(null, null)
      }
    }
  }

  private fun resolve(location: Location, promise: Promise) {
    worker.execute {
      val map = Arguments.createMap()
      map.putDouble("latitude", location.latitude)
      map.putDouble("longitude", location.longitude)
      if (location.hasAccuracy()) map.putDouble("accuracy", location.accuracy.toDouble())
      if (location.hasAltitude()) map.putDouble("altitude", location.altitude)
      map.putDouble("time", location.time.toDouble())
      address(location)?.let { map.putString("address", it) }
      promise.resolve(map)
    }
  }

  /** Blocks the worker for a few seconds at most; phones without a geocoder answer null at once. */
  private fun address(location: Location): String? {
    if (!Geocoder.isPresent()) return null
    val geocoder = Geocoder(reactApplicationContext, Locale.getDefault())
    return try {
      val found: List<Address>? = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
        var result: List<Address>? = null
        val latch = CountDownLatch(1)
        geocoder.getFromLocation(location.latitude, location.longitude, 1, object : Geocoder.GeocodeListener {
          override fun onGeocode(addresses: MutableList<Address>) {
            result = addresses
            latch.countDown()
          }

          override fun onError(errorMessage: String?) {
            latch.countDown()
          }
        })
        latch.await(GEOCODE_TIMEOUT_MS, TimeUnit.MILLISECONDS)
        result
      } else {
        @Suppress("DEPRECATION")
        geocoder.getFromLocation(location.latitude, location.longitude, 1)
      }
      found?.firstOrNull()?.let(::describe)
    } catch (e: Exception) {
      null
    }
  }

  private fun describe(a: Address): String? {
    a.getAddressLine(0)?.takeIf { it.isNotBlank() }?.let { return it }
    val parts = listOf(a.countryName, a.adminArea, a.locality, a.subLocality, a.thoroughfare, a.featureName)
    return parts.filterNotNull().filter { it.isNotBlank() }.distinct().joinToString(" ").ifBlank { null }
  }

  /**
   * Events in the visible calendars around [start, end), recurring ones expanded. All-day
   * events are stored at UTC midnight and come back at local midnight, like the rest.
   */
  @ReactMethod
  fun calendarEvents(start: Double, end: Double, promise: Promise) {
    worker.execute {
      try {
        val uri = Instances.CONTENT_URI.buildUpon().also {
          // A day either side catches all-day events, whose UTC day straddles the local one.
          ContentUris.appendId(it, start.toLong() - DAY_MS)
          ContentUris.appendId(it, end.toLong() + DAY_MS)
        }.build()
        val columns = arrayOf(
          Instances.TITLE, Instances.BEGIN, Instances.END, Instances.ALL_DAY,
          Instances.EVENT_LOCATION, Instances.DESCRIPTION, Instances.CALENDAR_DISPLAY_NAME,
        )
        val list = Arguments.createArray()
        resolver().query(uri, columns, "${Instances.VISIBLE} = 1", null, "${Instances.BEGIN} ASC")?.use { c ->
          while (c.moveToNext() && list.size() < MAX_EVENTS) {
            val allDay = c.getInt(3) == 1
            val map = Arguments.createMap()
            map.putString("title", c.getString(0).orEmpty())
            map.putDouble("start", (if (allDay) utcDayToLocal(c.getLong(1)) else c.getLong(1)).toDouble())
            map.putDouble("end", (if (allDay) utcDayToLocal(c.getLong(2)) else c.getLong(2)).toDouble())
            map.putBoolean("allDay", allDay)
            map.putString("location", c.getString(4).orEmpty())
            map.putString("notes", c.getString(5).orEmpty())
            map.putString("calendar", c.getString(6).orEmpty())
            list.pushMap(map)
          }
        }
        promise.resolve(list)
      } catch (e: SecurityException) {
        promise.reject("permission_denied", e.message, e)
      } catch (e: Exception) {
        promise.reject("failed", e.message, e)
      }
    }
  }

  /** Adds an event to the primary writable calendar. All-day events take local-midnight bounds. */
  @ReactMethod
  fun createCalendarEvent(event: ReadableMap, promise: Promise) {
    worker.execute {
      try {
        val (calendarId, calendarName) = writableCalendar()
          ?: return@execute promise.reject("no_calendar", "No calendar events can be added to")
        val allDay = event.hasKey("allDay") && event.getBoolean("allDay")
        val start = event.getDouble("start").toLong()
        val end = event.getDouble("end").toLong()
        val values = ContentValues().apply {
          put(Events.CALENDAR_ID, calendarId)
          put(Events.TITLE, event.getString("title"))
          put(Events.DTSTART, if (allDay) localDayToUtc(start) else start)
          put(Events.DTEND, if (allDay) localDayToUtc(end) else end)
          put(Events.ALL_DAY, if (allDay) 1 else 0)
          put(Events.EVENT_TIMEZONE, if (allDay) "UTC" else TimeZone.getDefault().id)
          if (event.hasKey("location")) put(Events.EVENT_LOCATION, event.getString("location"))
          if (event.hasKey("notes")) put(Events.DESCRIPTION, event.getString("notes"))
        }
        val inserted = resolver().insert(Events.CONTENT_URI, values)
          ?: return@execute promise.reject("failed", "The calendar did not take the event")
        val id = ContentUris.parseId(inserted)
        if (event.hasKey("reminderMinutes")) {
          resolver().insert(Reminders.CONTENT_URI, ContentValues().apply {
            put(Reminders.EVENT_ID, id)
            put(Reminders.MINUTES, event.getInt("reminderMinutes"))
            put(Reminders.METHOD, Reminders.METHOD_ALERT)
          })
        }
        val result = Arguments.createMap()
        result.putString("id", id.toString())
        result.putString("calendar", calendarName)
        promise.resolve(result)
      } catch (e: SecurityException) {
        promise.reject("permission_denied", e.message, e)
      } catch (e: Exception) {
        promise.reject("failed", e.message, e)
      }
    }
  }

  private fun writableCalendar(): Pair<Long, String>? {
    val selection = "${Calendars.VISIBLE} = 1 AND ${Calendars.CALENDAR_ACCESS_LEVEL} >= ${Calendars.CAL_ACCESS_CONTRIBUTOR}"
    val columns = arrayOf(Calendars._ID, Calendars.CALENDAR_DISPLAY_NAME)
    resolver().query(Calendars.CONTENT_URI, columns, selection, null, "${Calendars.IS_PRIMARY} DESC, ${Calendars._ID} ASC")
      ?.use { c -> if (c.moveToFirst()) return c.getLong(0) to c.getString(1).orEmpty() }
    return null
  }

  /** Contacts whose name matches, with their numbers, addresses and organization. */
  @ReactMethod
  fun searchContacts(query: String, limit: Double, promise: Promise) {
    worker.execute {
      try {
        class Person(val name: String) {
          val phones = mutableListOf<Pair<String, String>>()
          val emails = mutableListOf<Pair<String, String>>()
          var organization = ""
        }
        val people = LinkedHashMap<Long, Person>()
        val filter = Uri.withAppendedPath(Contacts.CONTENT_FILTER_URI, Uri.encode(query))
        resolver().query(filter, arrayOf(Contacts._ID, Contacts.DISPLAY_NAME_PRIMARY), null, null, null)?.use { c ->
          while (c.moveToNext() && people.size < limit.toInt()) people[c.getLong(0)] = Person(c.getString(1).orEmpty())
        }
        if (people.isNotEmpty()) {
          val selection = "${Data.CONTACT_ID} IN (${people.keys.joinToString(",")}) AND ${Data.MIMETYPE} IN (?, ?, ?)"
          val kinds = arrayOf(Phone.CONTENT_ITEM_TYPE, Email.CONTENT_ITEM_TYPE, Organization.CONTENT_ITEM_TYPE)
          val columns = arrayOf(Data.CONTACT_ID, Data.MIMETYPE, Data.DATA1, Data.DATA2, Data.DATA3)
          val res = reactApplicationContext.resources
          resolver().query(Data.CONTENT_URI, columns, selection, kinds, null)?.use { c ->
            while (c.moveToNext()) {
              val person = people[c.getLong(0)] ?: continue
              val value = c.getString(2)?.trim().orEmpty()
              if (value.isEmpty()) continue
              val type = if (c.isNull(3)) 0 else c.getInt(3)
              when (c.getString(1)) {
                Phone.CONTENT_ITEM_TYPE -> person.phones += value to Phone.getTypeLabel(res, type, c.getString(4)).toString()
                Email.CONTENT_ITEM_TYPE -> person.emails += value to Email.getTypeLabel(res, type, c.getString(4)).toString()
                else -> if (person.organization.isEmpty()) person.organization = value
              }
            }
          }
        }
        val list = Arguments.createArray()
        for (person in people.values) {
          val map = Arguments.createMap()
          map.putString("name", person.name)
          map.putArray("phones", labelled(person.phones))
          map.putArray("emails", labelled(person.emails))
          map.putString("organization", person.organization)
          list.pushMap(map)
        }
        promise.resolve(list)
      } catch (e: SecurityException) {
        promise.reject("permission_denied", e.message, e)
      } catch (e: Exception) {
        promise.reject("failed", e.message, e)
      }
    }
  }

  private fun labelled(values: List<Pair<String, String>>) = Arguments.createArray().also { list ->
    for ((value, label) in values) {
      list.pushMap(Arguments.createMap().also {
        it.putString("value", value)
        it.putString("label", label)
      })
    }
  }

  /** Battery, power saving, network, storage, ringer and model; none of it needs a permission. */
  @ReactMethod
  fun deviceStatus(promise: Promise) {
    try {
      val context = reactApplicationContext
      val map = Arguments.createMap()
      val battery = context.getSystemService(Context.BATTERY_SERVICE) as BatteryManager
      battery.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY).takeIf { it in 0..100 }?.let { map.putInt("battery", it) }
      map.putBoolean("charging", battery.isCharging)
      map.putBoolean("powerSaving", (context.getSystemService(Context.POWER_SERVICE) as PowerManager).isPowerSaveMode)
      val connectivity = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
      val caps = connectivity.getNetworkCapabilities(connectivity.activeNetwork)
      map.putString("network", when {
        caps == null -> "none"
        caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
        caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "cellular"
        caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "ethernet"
        caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN) -> "vpn"
        else -> "other"
      })
      if (caps != null) map.putBoolean("metered", connectivity.isActiveNetworkMetered)
      val storage = StatFs(Environment.getDataDirectory().path)
      map.putDouble("storageFree", storage.availableBytes.toDouble())
      map.putDouble("storageTotal", storage.totalBytes.toDouble())
      map.putString("ringer", when ((context.getSystemService(Context.AUDIO_SERVICE) as AudioManager).ringerMode) {
        AudioManager.RINGER_MODE_SILENT -> "silent"
        AudioManager.RINGER_MODE_VIBRATE -> "vibrate"
        else -> "normal"
      })
      map.putString("model", "${Build.MANUFACTURER} ${Build.MODEL}")
      map.putString("system", "Android ${Build.VERSION.RELEASE}")
      promise.resolve(map)
    } catch (e: Exception) {
      promise.reject("failed", e.message, e)
    }
  }

  /** Replaces the reminders of scheduled tasks: `[{at (epoch ms), title, body, session}]`, soonest first. */
  @ReactMethod
  fun scheduleReminders(items: ReadableArray, promise: Promise) {
    try {
      val list = JSONArray()
      for (i in 0 until minOf(items.size(), TaskReminders.MAX)) {
        val item = items.getMap(i) ?: continue
        list.put(JSONObject().apply {
          put("at", item.getDouble("at").toLong())
          put("title", item.getString("title").orEmpty())
          put("body", item.getString("body").orEmpty())
          for (key in TaskReminders.AGENT_KEYS + TaskReminders.SESSION) {
            if (item.hasKey(key)) put(key, item.getString(key).orEmpty())
          }
        })
      }
      TaskReminders.replace(reactApplicationContext, list)
      promise.resolve(list.length())
    } catch (e: Exception) {
      promise.reject("failed", e.message, e)
    }
  }

  /**
   * The messaging app with the text filled in. Some leave the body of an sms: link percent-encoded,
   * while the extra is read as is by all of them.
   */
  @ReactMethod
  fun composeSms(number: String, body: String, promise: Promise) {
    val intent = Intent(Intent.ACTION_SENDTO, Uri.fromParts("smsto", number, null)).putExtra("sms_body", body)
    val activity = reactApplicationContext.currentActivity
    try {
      if (activity != null) activity.startActivity(intent)
      else reactApplicationContext.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
      promise.resolve(null)
    } catch (e: ActivityNotFoundException) {
      promise.reject("no_app", e.message, e)
    }
  }

  /**
   * A reply or a scheduled task's result that came while the app was out of sight; on screen the
   * chat shows it. Tapping it opens [session].
   */
  @ReactMethod
  fun notice(kind: String, key: String, title: String, body: String, session: String, promise: Promise) {
    if (!MainActivity.visible) {
      if (kind == "task") Notices.task(reactApplicationContext, key, title, body, session)
      else Notices.reply(reactApplicationContext, key, title, body, session)
    }
    promise.resolve(null)
  }

  /** The chat of the notification the app was last opened from, once. */
  @ReactMethod
  fun takeNotificationTap(promise: Promise) {
    promise.resolve(NotificationTaps.take())
  }

  /** Whether the system dropped or turned down one of the app's notifications since last asked. */
  @ReactMethod
  fun takeDroppedNotice(promise: Promise) {
    promise.resolve(Notices.takeDropped(reactApplicationContext))
  }

  private fun resolver() = reactApplicationContext.contentResolver

  override fun invalidate() {
    worker.shutdown()
    super.invalidate()
  }

  companion object {
    private const val MAX_EVENTS = 200
    private const val DAY_MS = 24 * 60 * 60 * 1000L

    private fun utcDayToLocal(ms: Long): Long {
      val utc = Calendar.getInstance(TimeZone.getTimeZone("UTC")).apply { timeInMillis = ms }
      return Calendar.getInstance().apply {
        clear()
        set(utc.get(Calendar.YEAR), utc.get(Calendar.MONTH), utc.get(Calendar.DAY_OF_MONTH))
      }.timeInMillis
    }

    private fun localDayToUtc(ms: Long): Long {
      val local = Calendar.getInstance().apply { timeInMillis = ms }
      return Calendar.getInstance(TimeZone.getTimeZone("UTC")).apply {
        clear()
        set(local.get(Calendar.YEAR), local.get(Calendar.MONTH), local.get(Calendar.DAY_OF_MONTH))
      }.timeInMillis
    }

    private const val RECENT_MS = 2 * 60 * 1000L
    private const val FIX_TIMEOUT_MS = 10_000L
    private const val GEOCODE_TIMEOUT_MS = 5_000L

    // Fused and network answer in a second or two indoors, where GPS may never.
    private val PROVIDERS = listOfNotNull(
      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) LocationManager.FUSED_PROVIDER else null,
      LocationManager.NETWORK_PROVIDER,
      LocationManager.GPS_PROVIDER,
    )
  }
}

class CowDevicePackage : ReactPackage {
  override fun createNativeModules(context: ReactApplicationContext): List<NativeModule> =
    listOf(CowDeviceModule(context))

  override fun createViewManagers(context: ReactApplicationContext): List<ViewManager<in Nothing, in Nothing>> =
    emptyList()
}
