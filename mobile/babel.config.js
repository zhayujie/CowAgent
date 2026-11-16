module.exports = {
  presets: ['module:@react-native/babel-preset'],
  // Must stay last: transforms worklets used by react-native-reanimated.
  plugins: ['react-native-worklets/plugin'],
};
