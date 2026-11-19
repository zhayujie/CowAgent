module.exports = {
  dependencies: {
    // Android scans with ZXing (CowQrScannerModule): this library's Android
    // side pulls in Google's ML Kit, which reports usage to Google.
    'react-native-camera-kit': {
      platforms: {android: null},
    },
  },
};
