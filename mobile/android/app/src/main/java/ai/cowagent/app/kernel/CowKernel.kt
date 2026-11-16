package ai.cowagent.app.kernel

import android.content.Context
import android.content.SharedPreferences
import android.content.res.AssetManager
import android.util.Log
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.File
import java.io.IOException
import java.net.InetAddress
import java.net.ServerSocket
import java.security.SecureRandom
import java.util.Locale

/**
 * The agent kernel running inside this app: the CowAgent Python backend in
 * its `mobile` deployment, serving the usual web console API on loopback.
 *
 * Process-wide rather than per React context, so a JS reload finds the kernel
 * that is already running instead of starting a second one on the same data.
 */
object CowKernel {
  data class Endpoint(val port: Int, val password: String)

  private const val TAG = "CowKernel"
  private const val PREFS = "cow_kernel"
  private const val ASSET_ROOT = "cow-kernel"

  private var endpoint: Endpoint? = null
  private var thread: Thread? = null

  @Synchronized
  fun start(context: Context): Endpoint {
    endpoint?.let { if (thread?.isAlive == true) return it }

    val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    // The console password guards the port against other apps on this device,
    // which can reach loopback too. It never leaves the app.
    val password = prefs.getString("password", null) ?: newSecret().also {
      prefs.edit().putString("password", it).apply()
    }
    val port = pickPort(prefs.getInt("port", 0))
    prefs.edit().putInt("port", port).apply()
    val sources = installSources(context, prefs)

    if (!Python.isStarted()) {
      Python.start(AndroidPlatform(context))
    }
    val py = Python.getInstance()
    val os = py.getModule("os")
    val environ = os["environ"]!!
    val home = context.filesDir
    val env = mutableMapOf(
      // The kernel keeps its workspace under ~/cow, like on a desktop.
      "HOME" to home.path,
      "TMPDIR" to context.cacheDir.path,
      "COW_DEPLOYMENT" to "mobile",
      "COW_DATA_DIR" to File(home, ".cow").path,
      "COW_WEB_PORT" to port.toString(),
      "WEB_PASSWORD" to password,
    )
    // First launch only: later the app's Settings owns cow_lang via the API.
    // Blank (ignored by the kernel) otherwise, as a restart keeps os.environ.
    val firstRun = !File(home, ".cow/config.json").isFile
    val lang = Locale.getDefault().language.lowercase(Locale.ROOT)
    env["COW_LANG"] = if (!firstRun) "" else if (lang.startsWith("zh")) "zh" else "en"
    env.forEach { (key, value) -> environ.callAttr("__setitem__", key, value) }
    py.getModule("sys")["path"]!!.callAttr("insert", 0, sources.path)
    os.callAttr("chdir", context.filesDir.path)

    thread = Thread({
      try {
        py.getModule("app").callAttr("run")
      } catch (e: Throwable) {
        Log.e(TAG, "kernel stopped", e)
      }
    }, "cow-kernel").apply {
      isDaemon = true
      start()
    }
    return Endpoint(port, password).also { endpoint = it }
  }

  /**
   * Copy the kernel sources out of the APK once per install or update: the
   * kernel reads its bundled files (skills, templates, prompts) from disk.
   */
  private fun installSources(context: Context, prefs: SharedPreferences): File {
    val dest = File(context.filesDir, ASSET_ROOT)
    @Suppress("DEPRECATION")
    val stamp = context.packageManager.getPackageInfo(context.packageName, 0).lastUpdateTime
    if (dest.isDirectory && prefs.getLong("sources_stamp", -1L) == stamp) {
      return dest
    }
    val staging = File(context.filesDir, "$ASSET_ROOT.tmp")
    staging.deleteRecursively()
    copyAssets(context.assets, ASSET_ROOT, staging)
    dest.deleteRecursively()
    if (!staging.renameTo(dest)) {
      throw IOException("Could not install the kernel sources")
    }
    prefs.edit().putLong("sources_stamp", stamp).apply()
    return dest
  }

  private fun copyAssets(assets: AssetManager, path: String, target: File) {
    val children = assets.list(path).orEmpty()
    if (children.isEmpty()) {
      target.parentFile?.mkdirs()
      assets.open(path).use { input -> target.outputStream().use { input.copyTo(it) } }
      return
    }
    target.mkdirs()
    children.forEach { copyAssets(assets, "$path/$it", File(target, it)) }
  }

  /** The last port if it is still free, so the saved server address keeps working. */
  private fun pickPort(preferred: Int): Int {
    val loopback = InetAddress.getByName("127.0.0.1")
    if (preferred > 0) {
      try {
        ServerSocket(preferred, 1, loopback).close()
        return preferred
      } catch (_: IOException) {
      }
    }
    ServerSocket(0, 1, loopback).use { return it.localPort }
  }

  private fun newSecret(): String {
    val bytes = ByteArray(24)
    SecureRandom().nextBytes(bytes)
    return bytes.joinToString("") { "%02x".format(it) }
  }
}
