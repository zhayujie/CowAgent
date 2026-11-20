import {useEffect, useRef} from 'react';
import {NativeModules, PermissionsAndroid} from 'react-native';
import {parsePairLink, type PairTarget} from '../api/pairing';
import {tr} from '../i18n';
import {showToast} from './Toast';

interface CowQrScanner {
  /** The text read, or null when the user backs out. */
  scan(prompt: string): Promise<string | null>;
}

const scanner: CowQrScanner | undefined = NativeModules.CowQrScanner;

export const qrScannerAvailable = !!scanner;

/** ZXing's full-screen scanner, reading a CowAgent pairing QR code. */
export function QrScanner({
  visible,
  onClose,
  onScanned,
}: {
  visible: boolean;
  onClose: () => void;
  onScanned: (target: PairTarget) => void;
  onManual?: () => void;
}) {
  const handlers = useRef({onClose, onScanned});
  handlers.current = {onClose, onScanned};

  useEffect(() => {
    if (!visible || !scanner) {
      return;
    }
    let live = true;
    (async () => {
      const res = await PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.CAMERA).catch(() => null);
      if (!live) {
        return;
      }
      if (res !== PermissionsAndroid.RESULTS.GRANTED) {
        showToast(tr('connect_scan_no_camera'));
        handlers.current.onClose();
        return;
      }
      let prompt = tr('connect_scan_hint');
      while (live) {
        const value = await scanner.scan(prompt).catch(() => null);
        if (!live) {
          return;
        }
        if (value == null) {
          handlers.current.onClose();
          return;
        }
        const target = parsePairLink(value);
        if (target) {
          handlers.current.onScanned(target);
          return;
        }
        prompt = tr('connect_scan_wrong_code');
      }
    })();
    return () => {
      live = false;
    };
  }, [visible]);

  return null;
}
