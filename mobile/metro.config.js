const {mergeConfig, getDefaultConfig} = require('@react-native/metro-config');
const {
  createHarmonyMetroConfig,
} = require('@react-native-oh/react-native-harmony/metro.config');

const defaultConfig = getDefaultConfig(__dirname);
const harmonyConfig = createHarmonyMetroConfig({
  reactNativeHarmonyPackageName: '@react-native-oh/react-native-harmony',
});

// The harmony serializer returns no pre-main modules for non-harmony
// platforms, which would skip InitializeCore on Android and iOS.
const harmonyRunBeforeMain = harmonyConfig.serializer.getModulesRunBeforeMainModule;
harmonyConfig.serializer.getModulesRunBeforeMainModule = entryFilePath => {
  const modules = harmonyRunBeforeMain(entryFilePath);
  return modules.length > 0
    ? modules
    : defaultConfig.serializer.getModulesRunBeforeMainModule(entryFilePath);
};

/**
 * @type {import("metro-config").MetroConfig}
 */
const config = {
  transformer: {
    getTransformOptions: async () => ({
      transform: {
        experimentalImportSupport: false,
        inlineRequires: true,
      },
    }),
  },
};

module.exports = mergeConfig(defaultConfig, harmonyConfig, config);
