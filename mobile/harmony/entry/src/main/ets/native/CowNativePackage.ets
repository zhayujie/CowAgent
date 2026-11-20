import { RNOHPackage } from '@rnoh/react-native-openharmony';
import { TurboModulesFactory } from '@rnoh/react-native-openharmony/ts';
import type { TurboModule, TurboModuleContext } from '@rnoh/react-native-openharmony/ts';
import { COW_NATIVE_MODULE, CowNativeModule } from './CowNativeModule';

class CowNativeModulesFactory extends TurboModulesFactory {
  createTurboModule(name: string): TurboModule | null {
    return name === COW_NATIVE_MODULE ? new CowNativeModule(this.ctx) : null;
  }

  hasTurboModule(name: string): boolean {
    return name === COW_NATIVE_MODULE;
  }
}

/** The C++ half lives in cpp/CowNativePackage.h. */
export class CowNativePackage extends RNOHPackage {
  createTurboModulesFactory(ctx: TurboModuleContext): TurboModulesFactory {
    return new CowNativeModulesFactory(ctx);
  }
}
