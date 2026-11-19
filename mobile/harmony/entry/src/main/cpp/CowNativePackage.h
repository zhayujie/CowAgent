#pragma once

#include "RNOH/ArkTSTurboModule.h"
#include "RNOH/Package.h"

namespace rnoh {

// Forwards JS calls to the ArkTS module in ets/native/CowNativeModule.ets.
class JSI_EXPORT CowNativeTurboModule : public ArkTSTurboModule {
 public:
  CowNativeTurboModule(const ArkTSTurboModule::Context ctx, const std::string name)
      : ArkTSTurboModule(ctx, name) {
    methodMap_["scan"] = MethodMetadata{0, scan};
    methodMap_["takePhoto"] = MethodMetadata{0, takePhoto};
    methodMap_["pickPhotos"] = MethodMetadata{1, pickPhotos};
    methodMap_["saveDownload"] = MethodMetadata{2, saveDownload};
  }

 private:
  static facebook::jsi::Value scan(
      facebook::jsi::Runtime& rt,
      facebook::react::TurboModule& turboModule,
      const facebook::jsi::Value* args,
      size_t count) {
    return static_cast<ArkTSTurboModule&>(turboModule)
        .callAsync(rt, "scan", args, count);
  }

  static facebook::jsi::Value takePhoto(
      facebook::jsi::Runtime& rt,
      facebook::react::TurboModule& turboModule,
      const facebook::jsi::Value* args,
      size_t count) {
    return static_cast<ArkTSTurboModule&>(turboModule)
        .callAsync(rt, "takePhoto", args, count);
  }

  static facebook::jsi::Value pickPhotos(
      facebook::jsi::Runtime& rt,
      facebook::react::TurboModule& turboModule,
      const facebook::jsi::Value* args,
      size_t count) {
    return static_cast<ArkTSTurboModule&>(turboModule)
        .callAsync(rt, "pickPhotos", args, count);
  }

  static facebook::jsi::Value saveDownload(
      facebook::jsi::Runtime& rt,
      facebook::react::TurboModule& turboModule,
      const facebook::jsi::Value* args,
      size_t count) {
    return static_cast<ArkTSTurboModule&>(turboModule)
        .callAsync(rt, "saveDownload", args, count);
  }
};

class CowNativeFactoryDelegate : public TurboModuleFactoryDelegate {
 public:
  SharedTurboModule createTurboModule(Context ctx, const std::string& name)
      const override {
    if (name == "CowNative") {
      return std::make_shared<CowNativeTurboModule>(ctx, name);
    }
    return nullptr;
  }
};

class CowNativePackage : public Package {
 public:
  CowNativePackage(Package::Context ctx) : Package(ctx) {}

  std::unique_ptr<TurboModuleFactoryDelegate> createTurboModuleFactoryDelegate()
      override {
    return std::make_unique<CowNativeFactoryDelegate>();
  }
};

} // namespace rnoh
