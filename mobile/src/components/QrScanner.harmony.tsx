import type {PairTarget} from '../api/pairing';

/** The camera library has no HarmonyOS build yet; pairing falls back to typing the code. */
export const qrScannerAvailable = false;

export function QrScanner(_props: {
  visible: boolean;
  onClose: () => void;
  onScanned: (target: PairTarget) => void;
  onManual?: () => void;
}) {
  return null;
}
