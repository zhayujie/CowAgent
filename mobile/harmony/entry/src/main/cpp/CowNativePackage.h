#pragma once

#include "RNOH/ArkTSTurboModule.h"
#include "RNOH/Package.h"

namespace rnoh {

// Registers `method` as forwarded to the ArkTS module of the same name: `callAsync`
// for an ArkTS method that returns a promise, `call` for one that returns at once
// (a JS promise on a method returning nothing would never settle).
#define COW_ARKTS_METHOD(kind, method, argc)                                   \
  methodMap_[#method] = MethodMetadata{                                         \
      argc,                                                                     \
      [](facebook::jsi::Runtime& rt,                                            \
         facebook::react::TurboModule& turboModule,                             \
         const facebook::jsi::Value* args,                                      \
         size_t count) {                                                        \
        return static_cast<ArkTSTurboModule&>(turboModule)                      \
            .kind(rt, #method, args, count);                                    \
      }}

// ets/native/CowNativeModule.ets
class JSI_EXPORT CowNativeTurboModule : public ArkTSTurboModule {
 public:
  CowNativeTurboModule(const ArkTSTurboModule::Context ctx, const std::string name)
      : ArkTSTurboModule(ctx, name) {
    COW_ARKTS_METHOD(callAsync, scan, 0);
    COW_ARKTS_METHOD(callAsync, takePhoto, 0);
    COW_ARKTS_METHOD(callAsync, pickPhotos, 1);
    COW_ARKTS_METHOD(callAsync, saveDownload, 3);
    COW_ARKTS_METHOD(callAsync, share, 3);
    COW_ARKTS_METHOD(callAsync, takeShared, 0);
  }
};

// ets/native/CowDeviceModule.ets
class JSI_EXPORT CowDeviceTurboModule : public ArkTSTurboModule {
 public:
  CowDeviceTurboModule(const ArkTSTurboModule::Context ctx, const std::string name)
      : ArkTSTurboModule(ctx, name) {
    COW_ARKTS_METHOD(callAsync, currentLocation, 0);
    COW_ARKTS_METHOD(callAsync, calendarEvents, 2);
    COW_ARKTS_METHOD(callAsync, createCalendarEvent, 1);
    COW_ARKTS_METHOD(callAsync, searchContacts, 2);
    COW_ARKTS_METHOD(callAsync, deviceStatus, 0);
    COW_ARKTS_METHOD(callAsync, notice, 5);
    COW_ARKTS_METHOD(callAsync, takeNotificationTap, 0);
    COW_ARKTS_METHOD(call, holdBackground, 0);
    COW_ARKTS_METHOD(call, releaseBackground, 0);
    COW_ARKTS_METHOD(callAsync, scheduleReminders, 1);
  }
};

// ets/native/CowKernelModule.ets
class JSI_EXPORT CowKernelTurboModule : public ArkTSTurboModule {
 public:
  CowKernelTurboModule(const ArkTSTurboModule::Context ctx, const std::string name)
      : ArkTSTurboModule(ctx, name) {
    COW_ARKTS_METHOD(callAsync, start, 0);
    COW_ARKTS_METHOD(call, deviceName, 0);
  }
};

#undef COW_ARKTS_METHOD

class CowNativeFactoryDelegate : public TurboModuleFactoryDelegate {
 public:
  SharedTurboModule createTurboModule(Context ctx, const std::string& name)
      const override {
    if (name == "CowNative") {
      return std::make_shared<CowNativeTurboModule>(ctx, name);
    }
    if (name == "CowDevice") {
      return std::make_shared<CowDeviceTurboModule>(ctx, name);
    }
    // The ArkTS side only offers the kernel when this build embeds Python;
    // claiming it without that would be a fatal error.
    if (name == "CowKernel" && ctx.arkTSTurboModuleInstanceRef) {
      return std::make_shared<CowKernelTurboModule>(ctx, name);
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
