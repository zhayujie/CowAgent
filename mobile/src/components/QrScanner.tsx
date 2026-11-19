import {faBolt, faKeyboard, faXmark} from '@fortawesome/free-solid-svg-icons';
import React, {useEffect, useRef, useState} from 'react';
import {
  Linking,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  TurboModuleRegistry,
  View,
  type TurboModule,
} from 'react-native';
import {Camera, CameraType} from 'react-native-camera-kit';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {parsePairLink, type PairTarget} from '../api/pairing';
import {tr} from '../i18n';
import {useTheme} from '../theme/theme';
import {Icon} from './Icon';

export const qrScannerAvailable = true;

type Access = 'checking' | 'granted' | 'denied';

// Android has QrScanner.android.tsx.
async function requestCamera(): Promise<boolean> {
  const mod = TurboModuleRegistry.get<CameraKitModule>('RNCameraKitModule');
  return mod ? !!(await mod.requestDeviceCameraAuthorization()) : true;
}

interface CameraKitModule extends TurboModule {
  requestDeviceCameraAuthorization(): Promise<boolean>;
}

const FRAME = 240;
const CORNER = 28;

/** Full-screen camera that reads a CowAgent pairing QR code. */
export function QrScanner({
  visible,
  onClose,
  onScanned,
  onManual,
}: {
  visible: boolean;
  onClose: () => void;
  onScanned: (target: PairTarget) => void;
  /** Offered for codes that can't be scanned; omitted hides the button. */
  onManual?: () => void;
}) {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const [access, setAccess] = useState<Access>('checking');
  const [torch, setTorch] = useState(false);
  const [wrongCode, setWrongCode] = useState(false);
  const done = useRef(false);
  const wrongTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!visible) {
      return;
    }
    done.current = false;
    setTorch(false);
    setWrongCode(false);
    setAccess('checking');
    let live = true;
    requestCamera().then(
      ok => live && setAccess(ok ? 'granted' : 'denied'),
      () => live && setAccess('denied'),
    );
    return () => {
      live = false;
    };
  }, [visible]);

  useEffect(() => () => {
    if (wrongTimer.current) {
      clearTimeout(wrongTimer.current);
    }
  }, []);

  const onRead = (value: string) => {
    if (done.current) {
      return;
    }
    const target = parsePairLink(value);
    if (!target) {
      setWrongCode(true);
      if (wrongTimer.current) {
        clearTimeout(wrongTimer.current);
      }
      wrongTimer.current = setTimeout(() => setWrongCode(false), 2500);
      return;
    }
    done.current = true;
    onScanned(target);
  };

  const corner = (pos: object) => <View style={[styles.corner, {borderColor: t.accent}, pos]} />;

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose} statusBarTranslucent>
      <View style={styles.root}>
        {access === 'granted' && (
          <Camera
            style={StyleSheet.absoluteFill}
            cameraType={CameraType.Back}
            scanBarcode
            allowedBarcodeTypes={['qr']}
            scanThrottleDelay={800}
            torchMode={torch ? 'on' : 'off'}
            onReadCode={(e: {nativeEvent: {codeStringValue: string}}) => onRead(e.nativeEvent.codeStringValue)}
          />
        )}

        <View style={[styles.top, {paddingTop: insets.top + 8}]}>
          <Pressable accessibilityRole="button" accessibilityLabel={tr('common_close')} hitSlop={10} onPress={onClose} style={styles.round}>
            <Icon icon={faXmark} size={18} color="#fff" />
          </Pressable>
          <Text style={styles.title}>{tr('connect_scan_title')}</Text>
          <View style={styles.round} />
        </View>

        <View style={styles.center} pointerEvents="none">
          <View style={styles.frame}>
            {corner({top: 0, left: 0, borderTopWidth: 3, borderLeftWidth: 3, borderTopLeftRadius: 16})}
            {corner({top: 0, right: 0, borderTopWidth: 3, borderRightWidth: 3, borderTopRightRadius: 16})}
            {corner({bottom: 0, left: 0, borderBottomWidth: 3, borderLeftWidth: 3, borderBottomLeftRadius: 16})}
            {corner({bottom: 0, right: 0, borderBottomWidth: 3, borderRightWidth: 3, borderBottomRightRadius: 16})}
          </View>
          {access === 'denied' ? (
            <Text style={styles.hint}>{tr('connect_scan_no_camera')}</Text>
          ) : (
            <Text style={[styles.hint, wrongCode && {color: t.danger}]}>
              {wrongCode ? tr('connect_scan_wrong_code') : tr('connect_scan_hint')}
            </Text>
          )}
        </View>

        <View style={[styles.bottom, {paddingBottom: insets.bottom + 28}]}>
          {access === 'denied' ? (
            <Pressable accessibilityRole="button" onPress={() => Linking.openSettings().catch(() => undefined)} style={styles.pill}>
              <Text style={styles.pillText}>{tr('connect_scan_open_settings')}</Text>
            </Pressable>
          ) : (
            access === 'granted' && (
              <Pressable
                accessibilityRole="button"
                accessibilityState={{selected: torch}}
                accessibilityLabel={tr('connect_scan_torch')}
                onPress={() => setTorch(v => !v)}
                style={[styles.roundLarge, torch && styles.roundLargeOn]}>
                <Icon icon={faBolt} size={18} color={torch ? '#111' : '#fff'} />
              </Pressable>
            )
          )}
          {onManual && (
            <Pressable accessibilityRole="button" onPress={onManual} style={styles.manual} hitSlop={8}>
              <Icon icon={faKeyboard} size={13} color="rgba(255,255,255,0.8)" />
              <Text style={styles.manualText}>{tr('connect_manual')}</Text>
            </Pressable>
          )}
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: {flex: 1, backgroundColor: '#000'},
  top: {
    position: 'absolute',
    left: 0,
    right: 0,
    top: 0,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
  },
  title: {fontSize: 17, fontWeight: '600', color: '#fff'},
  round: {
    width: 38,
    height: 38,
    borderRadius: 19,
    alignItems: 'center',
    justifyContent: 'center',
  },
  center: {...StyleSheet.absoluteFillObject, alignItems: 'center', justifyContent: 'center'},
  frame: {width: FRAME, height: FRAME},
  corner: {position: 'absolute', width: CORNER, height: CORNER},
  hint: {
    marginTop: 28,
    paddingHorizontal: 40,
    fontSize: 14,
    lineHeight: 21,
    color: 'rgba(255,255,255,0.85)',
    textAlign: 'center',
  },
  bottom: {position: 'absolute', left: 0, right: 0, bottom: 0, alignItems: 'center', gap: 22},
  roundLarge: {
    width: 52,
    height: 52,
    borderRadius: 26,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(255,255,255,0.16)',
  },
  roundLargeOn: {backgroundColor: '#fff'},
  pill: {paddingHorizontal: 20, paddingVertical: 11, borderRadius: 22, backgroundColor: 'rgba(255,255,255,0.16)'},
  pillText: {fontSize: 15, color: '#fff', fontWeight: '500'},
  manual: {flexDirection: 'row', alignItems: 'center', gap: 7},
  manualText: {fontSize: 14, color: 'rgba(255,255,255,0.8)'},
});
