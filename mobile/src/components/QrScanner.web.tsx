import type {PairTarget} from '../api/pairing';

/** No camera in the browser preview; pairing falls back to typing the code. */
export const qrScannerAvailable = false;
export const qrScannerShowsBusy = false;

export function QrScanner(_props: {
  visible: boolean;
  onClose: () => void;
  onScanned: (target: PairTarget) => void;
  onManual?: () => void;
  busy?: boolean;
}) {
  return null;
}
