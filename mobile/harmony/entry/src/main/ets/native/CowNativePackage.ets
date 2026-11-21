import { RNOHPackage } from '@rnoh/react-native-openharmony';
import { TurboModulesFactory } from '@rnoh/react-native-openharmony/ts';
import type { TurboModule, TurboModuleContext } from '@rnoh/react-native-openharmony/ts';
import { COW_KERNEL_MODULE, CowKernelModule } from './CowKernelModule';
import { COW_NATIVE_MODULE, CowNativeModule } from './CowNativeModule';

class CowNativeModulesFactory extends TurboModulesFactory {
  createTurboModule(name: string): TurboModule | null {
    if (name === COW_NATIVE_MODULE) {
      return new CowNativeModule(this.ctx);
    }
    if (name === COW_KERNEL_MODULE && CowKernelModule.isAvailable()) {
      return new CowKernelModule(this.ctx);
    }
    return null;
  }

  hasTurboModule(name: string): boolean {
    return name === COW_NATIVE_MODULE || (name === COW_KERNEL_MODULE && CowKernelModule.isAvailable());
  }
}

/** The C++ half lives in cpp/CowNativePackage.h. */
export class CowNativePackage extends RNOHPackage {
  createTurboModulesFactory(ctx: TurboModuleContext): TurboModulesFactory {
    return new CowNativeModulesFactory(ctx);
  }
}
