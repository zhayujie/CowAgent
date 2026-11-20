import {useEffect, useRef} from 'react';
import {Alert, type AlertButton} from 'react-native';
import {parsePairLink, type PairTarget} from '../api/pairing';
import {tr} from '../i18n';
import {cowNative as scanner} from '../media/cowNative';

/** Builds without the native module fall back to typing the code. */
export const qrScannerAvailable = scanner != null;

type Props = {
  visible: boolean;
  onClose: () => void;
  onScanned: (target: PairTarget) => void;
  onManual?: () => void;
};

/** Opens the system scanner (Scan Kit) whenever `visible` turns on; it draws its own UI. */
export function QrScanner(props: Props) {
  const latest = useRef(props);
  latest.current = props;

  useEffect(() => {
    const native = scanner;
    if (!props.visible || !native) {
      return;
    }
    let live = true;
    const run = () => {
      native.scan().then(
        value => {
          if (!live) {
            return;
          }
          const {onClose, onScanned, onManual} = latest.current;
          if (value == null) {
            onClose();
            return;
          }
          const target = parsePairLink(value);
          if (target) {
            onScanned(target);
            return;
          }
          const buttons: AlertButton[] = [{text: tr('common_cancel'), style: 'cancel', onPress: onClose}];
          if (onManual) {
            buttons.push({text: tr('connect_manual'), onPress: onManual});
          }
          buttons.push({text: tr('common_retry'), onPress: run});
          Alert.alert(tr('connect_scan_wrong_code'), tr('connect_scan_hint'), buttons, {
            cancelable: true,
            onDismiss: onClose,
          });
        },
        () => live && latest.current.onClose(),
      );
    };
    run();
    return () => {
      live = false;
    };
  }, [props.visible]);

  return null;
}
