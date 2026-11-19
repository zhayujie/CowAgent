import type { RNPackageContext, RNPackage } from '@rnoh/react-native-openharmony';
import { createRNOHPackages as createRNOHPackagesAutolinking } from "./RNOHPackagesFactory"
import GestureHandlerPackage from '@react-native-ohos/react-native-gesture-handler';
import { ReanimatedPackage } from '@react-native-ohos/react-native-reanimated';
import ScreensPackage from '@react-native-ohos/react-native-screens';
import { SvgPackage } from '@react-native-ohos/react-native-svg';
import { ReanimatedWorkletPackage } from '@react-native-ohos/react-native-worklets';
import { CowNativePackage } from './native/CowNativePackage';

// These libraries don't declare autolinking metadata, so they are linked by hand
// here and in cpp/PackageProvider.cpp + cpp/CMakeLists.txt.
export function getRNOHPackages(ctx: RNPackageContext): RNPackage[] {
  return [
    ...createRNOHPackagesAutolinking(ctx),
    new GestureHandlerPackage(ctx),
    new ReanimatedWorkletPackage(ctx),
    new ReanimatedPackage(ctx),
    new ScreensPackage(ctx),
    new SvgPackage(ctx),
    new CowNativePackage(ctx),
  ]
}
