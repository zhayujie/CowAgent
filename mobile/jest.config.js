module.exports = {
  preset: 'react-native',
  roots: ['<rootDir>/__tests__'],
  setupFiles: ['<rootDir>/jest.setup.js'],
  // The preset's list, plus marked, which ships only as an ES module.
  transformIgnorePatterns: ['node_modules/(?!((jest-)?react-native|@react-native(-community)?|marked)/)'],
};
