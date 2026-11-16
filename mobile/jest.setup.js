jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);

// Unit tests assert the Chinese copy regardless of the machine's locale.
require('./src/i18n').useLangStore.getState().setLang('zh');
