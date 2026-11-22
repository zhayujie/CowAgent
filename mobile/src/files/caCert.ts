import {NativeModules, Platform} from 'react-native';
import {showToast} from '../components/Toast';
import {tr} from '../i18n';

const cowCert: {install(): Promise<'prompted' | 'cancelled'>} | undefined = NativeModules.CowCert;

/**
 * Android only: picks a .crt/.pem and hands it to the system KeyChain installer, which adds it
 * to the user certificate store. The app trusts user certificates, so a self-hosted HTTPS
 * endpoint with a private CA starts working without repackaging.
 */
export async function installCaCertificate() {
  if (Platform.OS !== 'android' || !cowCert) {
    showToast(tr('access_ca_cert_android_only'));
    return;
  }
  try {
    const result = await cowCert.install();
    if (result === 'prompted') {
      showToast(tr('access_ca_cert_prompted'));
    }
  } catch {
    showToast(tr('access_ca_cert_invalid'));
  }
}
