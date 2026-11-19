import {PermissionsAndroid, Platform} from 'react-native';

/** Writing to the shared Downloads folder needs this permission before Android 10. */
export async function canWriteDownloads(): Promise<boolean> {
  if (Platform.OS !== 'android' || typeof Platform.Version !== 'number' || Platform.Version >= 29) {
    return true;
  }
  const result = await PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.WRITE_EXTERNAL_STORAGE);
  return result === PermissionsAndroid.RESULTS.GRANTED;
}
