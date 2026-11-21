package ai.cowagent.app

import ai.cowagent.app.files.CowDownloadsPackage
import ai.cowagent.app.kernel.CowKernelPackage
import ai.cowagent.app.scan.CowQrScannerPackage
import android.app.Application
import com.facebook.react.PackageList
import com.facebook.react.ReactApplication
import com.facebook.react.ReactHost
import com.facebook.react.ReactNativeApplicationEntryPoint.loadReactNative
import com.facebook.react.defaults.DefaultReactHost.getDefaultReactHost

class MainApplication : Application(), ReactApplication {

  override val reactHost: ReactHost by lazy {
    getDefaultReactHost(
      context = applicationContext,
      packageList =
        PackageList(this).packages.apply {
          add(CowKernelPackage())
          add(CowDownloadsPackage())
          add(CowQrScannerPackage())
          add(CowSystemBarsPackage())
        },
    )
  }

  override fun onCreate() {
    super.onCreate()
    loadReactNative(this)
  }
}
