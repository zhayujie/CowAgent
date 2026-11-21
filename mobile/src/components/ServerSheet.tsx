import {faCheck, faChevronRight, faKeyboard, faMobileScreen, faQrcode, faServer} from '@fortawesome/free-solid-svg-icons';
import type {IconDefinition} from '@fortawesome/fontawesome-svg-core';
import React, {useEffect, useState} from 'react';
import {ActivityIndicator, Pressable, Text, View} from 'react-native';
import type {PairTarget} from '../api/pairing';
import {tr} from '../i18n';
import {isLocalKernelAvailable, LOCAL_SERVER_ID, localDeviceName} from '../kernel/localKernel';
import {describeConnectError, useServerStore} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {Icon} from './Icon';
import {usePairAction} from './PairFlow';
import {QrScanner, qrScannerAvailable} from './QrScanner';
import {SHEET_DISMISS_MS, Sheet} from './Sheet';
import {showToast} from './Toast';

function hostOf(baseUrl: string): string {
  return baseUrl.replace(/^https?:\/\//, '');
}

/**
 * Pick where the agent runs: this phone first, then the computers and servers
 * paired before, then the ways to pair another one.
 */
export function ServerSheet({visible, onClose}: {visible: boolean; onClose: () => void}) {
  const t = useTheme();
  const styles = useStyles();
  const servers = useServerStore(s => s.servers);
  const activeId = useServerStore(s => s.activeId);
  const [pending, setPending] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const pairing = usePairAction();
  const remotes = servers.filter(s => !s.local);
  const local = isLocalKernelAvailable();

  useEffect(() => {
    if (!visible) {
      setConfirmRemove(null);
    }
  }, [visible]);

  useEffect(() => {
    if (pairing.error) {
      showToast(pairing.error);
    }
  }, [pairing.error]);

  const select = async (id: string) => {
    if (pending) {
      return;
    }
    if (id === activeId) {
      onClose();
      return;
    }
    setPending(id);
    try {
      await useServerStore.getState().switchTo(id);
    } catch (e) {
      showToast(describeConnectError(e));
    } finally {
      setPending(null);
    }
  };

  const remove = (id: string) => {
    if (confirmRemove !== id) {
      setConfirmRemove(id);
      return;
    }
    setConfirmRemove(null);
    useServerStore.getState().removeServer(id);
  };

  const scan = () => {
    onClose();
    // iOS can't present the camera while the sheet's modal is still closing.
    setTimeout(() => setScanning(true), SHEET_DISMISS_MS);
  };

  const addManually = () => {
    onClose();
    useServerStore.getState().addServer(true);
  };

  const onScanned = (target: PairTarget) => {
    setScanning(false);
    pairing.run(target);
  };

  const row = (id: string, icon: IconDefinition, name: string, meta: string, removable: boolean) => {
    const selected = id === activeId;
    const busy = pending === id;
    // Two sibling buttons: on the web a button inside a button is invalid HTML.
    return (
      <View key={id} style={[styles.row, selected && styles.rowActive]}>
        <Pressable
          accessibilityRole="button"
          accessibilityState={{selected, busy}}
          onPress={() => select(id)}
          style={({pressed}) => [styles.rowMain, pressed && styles.pressed]}>
          <View style={[styles.badge, selected && styles.badgeActive]}>
            <Icon icon={icon} size={14} color={selected ? t.accent : t.t3} />
          </View>
          <View style={styles.text}>
            <Text style={styles.name} numberOfLines={1}>
              {name}
            </Text>
            <Text style={styles.meta} numberOfLines={1}>
              {meta}
            </Text>
          </View>
          {busy ? (
            <ActivityIndicator size="small" color={t.t3} />
          ) : (
            selected && <Icon icon={faCheck} size={13} color={t.accent} />
          )}
        </Pressable>
        {removable && !selected && !busy && (
          <Pressable accessibilityRole="button" hitSlop={8} onPress={() => remove(id)} style={styles.removeButton}>
            <Text style={[styles.remove, confirmRemove === id && styles.removeConfirm]}>
              {confirmRemove === id ? tr('server_remove_confirm') : tr('server_remove')}
            </Text>
          </Pressable>
        )}
      </View>
    );
  };

  const action = (icon: IconDefinition, title: string, desc: string, onPress: () => void) => (
    <Pressable
      key={title}
      accessibilityRole="button"
      onPress={onPress}
      style={({pressed}) => [styles.action, pressed && styles.pressed]}>
      <View style={styles.badge}>
        <Icon icon={icon} size={14} color={t.t1} />
      </View>
      <View style={styles.text}>
        <Text style={styles.name} numberOfLines={1}>
          {title}
        </Text>
        <Text style={styles.meta} numberOfLines={1}>
          {desc}
        </Text>
      </View>
      <Icon icon={faChevronRight} size={11} color={t.t4} />
    </Pressable>
  );

  return (
    <>
      <Sheet visible={visible} onClose={onClose} title={tr('server_sheet_title')}>
        {local && row(LOCAL_SERVER_ID, faMobileScreen, localDeviceName(), tr('server_local_meta'), false)}
        {remotes.map(s => row(s.id, faServer, s.name, hostOf(s.baseUrl), true))}
        <Text style={[styles.group, (local || remotes.length > 0) && styles.groupSpaced]}>
          {tr('connect_group_other')}
        </Text>
        {qrScannerAvailable && action(faQrcode, tr('connect_scan'), tr('connect_scan_desc'), scan)}
        {action(faKeyboard, tr('connect_manual'), tr('connect_manual_desc'), addManually)}
      </Sheet>
      <QrScanner
        visible={scanning}
        onClose={() => setScanning(false)}
        onScanned={onScanned}
        onManual={() => {
          setScanning(false);
          setTimeout(addManually, SHEET_DISMISS_MS);
        }}
      />
      {pairing.busy && (
        <Sheet visible onClose={() => undefined}>
          <View style={styles.busy}>
            <ActivityIndicator color={t.t3} />
            <Text style={styles.busyText}>{tr('connect_connecting')}</Text>
          </View>
        </Sheet>
      )}
    </>
  );
}

const useStyles = makeStyles(t => ({
  group: {fontSize: 12, fontWeight: '600', letterSpacing: 0.4, color: t.t3, paddingHorizontal: 12, marginBottom: 4},
  groupSpaced: {marginTop: 18},
  row: {flexDirection: 'row', alignItems: 'center', borderRadius: radius.md},
  rowActive: {backgroundColor: t.bg2},
  rowMain: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 12,
    paddingVertical: 11,
  },
  removeButton: {paddingRight: 12},
  action: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 12,
    paddingVertical: 11,
    borderRadius: radius.md,
  },
  pressed: {opacity: 0.7},
  badge: {
    width: 34,
    height: 34,
    borderRadius: 17,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: t.bg2,
  },
  badgeActive: {backgroundColor: t.accentSoft},
  text: {flex: 1},
  name: {fontSize: 16, fontWeight: '500', color: t.t1, letterSpacing: -0.2},
  meta: {fontSize: 13, color: t.t3, marginTop: 3},
  remove: {fontSize: 13, color: t.t3},
  removeConfirm: {color: t.danger},
  busy: {flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 10, paddingVertical: 20},
  busyText: {fontSize: 15, color: t.t2},
}));
