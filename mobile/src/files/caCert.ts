import {NativeModules, Platform} from 'react-native';
import {showToast} from '../components/Toast';
import {tr} from '../i18n';

export interface CaCert {
  name: string;
  subject: string;
  expires: string | null;
  expired: boolean;
}

interface CowCertModule {
  pick(): Promise<CaCert | null>;
  list(): Promise<CaCert[]>;
  remove(name: string): Promise<boolean>;
}

const cowCert: CowCertModule | undefined = NativeModules.CowCert;

/**
 * Android only: the app keeps its own list of trusted CA certificates (in its private directory)
 * instead of installing into the system store, because Android 11+ only lets an app install
 * credentials that carry a private key, and a bare CA certificate does not have one.
 */
export const caCertSupported = Platform.OS === 'android' && !!cowCert;

/** Picks a .crt/.pem and stores it inside the app; resolves the entry, or null when cancelled. */
export async function importCaCertificate(): Promise<CaCert | null> {
  if (!caCertSupported || !cowCert) {
    showToast(tr('access_ca_cert_android_only'));
    return null;
  }
  try {
    const entry = await cowCert.pick();
    if (entry) {
      showToast(tr('access_ca_cert_added'));
    }
    return entry;
  } catch {
    showToast(tr('access_ca_cert_invalid'));
    return null;
  }
}

export async function listCaCertificates(): Promise<CaCert[]> {
  if (!caCertSupported || !cowCert) {
    return [];
  }
  try {
    return await cowCert.list();
  } catch {
    return [];
  }
}

export async function removeCaCertificate(name: string): Promise<boolean> {
  if (!caCertSupported || !cowCert) {
    return false;
  }
  try {
    return await cowCert.remove(name);
  } catch {
    return false;
  }
}
