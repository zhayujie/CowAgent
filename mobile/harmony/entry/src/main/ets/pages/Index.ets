import {
  AnyJSBundleProvider,
  ComponentBuilderContext,
  MetroJSBundleProvider,
  RNApp,
  RNOHErrorDialog,
  ResourceJSBundleProvider,
  RNOHCoreContext
} from '@rnoh/react-native-openharmony';
import { KeyboardAvoidMode } from '@kit.ArkUI';
import { componentBuilder as screensComponentBuilder } from '@react-native-ohos/react-native-screens';
import { getRNOHPackages } from '../PackageProvider';

// RNOHScreensPackage doesn't register every ArkTS component it ships (e.g.
// RNSScreenContentWrapper, which hosts each screen's content); without this
// fallback those render nothing and every screen is blank.
@Builder
function buildCustomRNComponent(ctx: ComponentBuilderContext) {
  screensComponentBuilder(ctx)
}

const wrappedCustomRNComponentBuilder = wrapBuilder(buildCustomRNComponent)

@Entry
@Component
struct Index {
  @StorageLink('RNOHCoreContext') private rnohCoreContext: RNOHCoreContext | undefined = undefined

  // The screens leave room for the keyboard only on iOS and expect the window itself to
  // shrink elsewhere, as adjustResize does on Android. HarmonyOS lifts or covers instead.
  aboutToAppear(): void {
    this.getUIContext().setKeyboardAvoidMode(KeyboardAvoidMode.RESIZE)
  }

  // The system back gesture has to reach React Navigation; whatever RN leaves
  // unhandled falls through to RNAbility's default, which closes the app.
  onBackPress(): boolean | undefined {
    this.rnohCoreContext?.dispatchBackPress()
    return true
  }

  build() {
    Column() {
      if (this.rnohCoreContext) {
        if (this.rnohCoreContext?.isDebugModeEnabled) {
          RNOHErrorDialog({ ctx: this.rnohCoreContext })
        }
        RNApp({
          rnInstanceConfig: {
            name: "CowAgentMobile",
            createRNPackages: getRNOHPackages,
            fontResourceByFontFamily: {},
            enableDebugger: this.rnohCoreContext?.isDebugModeEnabled,
          },
          appKey: "CowAgentMobile",
          wrappedCustomRNComponentBuilder: wrappedCustomRNComponentBuilder,
          jsBundleProvider: this.rnohCoreContext?.isDebugModeEnabled ?
            new AnyJSBundleProvider([
              new MetroJSBundleProvider(),
              new ResourceJSBundleProvider(this.rnohCoreContext.uiAbilityContext.resourceManager, 'hermes_bundle.hbc'),
            ]) :
            /**
             * NOTE: The HBC format is recommended for Hermes in a production environment. HBC provides better performance and loading times.
             */
            new ResourceJSBundleProvider(this.rnohCoreContext.uiAbilityContext.resourceManager, 'hermes_bundle.hbc'),
        })
      }
    }
    .height('100%')
    .width('100%')
  }
}
