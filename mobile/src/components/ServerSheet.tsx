import {faCheck, faKeyboard, faMobileScreen, faQrcode, faServer} from '@fortawesome/free-solid-svg-icons';
import type {IconDefinition} from '@fortawesome/fontawesome-svg-core';
import React, {useEffect, useState} from 'react';
import {ActivityIndicator, Pressable, Text, View} from 'react-native';
import type {PairTarget} from '../api/pairing';
import {tr} from '../i18n';
import {isLocalKernelAvailable, LOCAL_SERVER_ID} from '../kernel/localKernel';
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
 * Pick where the agent runs: the kernel on this phone or one of the saved
 * computers and servers, or pair a new one by scanning its code.
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

  return (
    <>
      <Sheet visible={visible} onClose={onClose} title={tr('server_sheet_title')}>
        {local && (
          <>
            <Text style={styles.group}>{tr('connect_group_local')}</Text>
            {row(LOCAL_SERVER_ID, faMobileScreen, tr('server_local'), tr('server_local_meta'), false)}
          </>
        )}
        {remotes.length > 0 && (
          <>
            <Text style={[styles.group, local && styles.groupSpaced]}>{tr('connect_group_remote')}</Text>
            {remotes.map(s => row(s.id, faServer, s.name, hostOf(s.baseUrl), true))}
          </>
        )}
        <View style={styles.actions}>
          {qrScannerAvailable && (
            <Pressable
              accessibilityRole="button"
              onPress={scan}
              style={({pressed}) => [styles.action, styles.actionPrimary, pressed && styles.pressed]}>
              <Icon icon={faQrcode} size={14} color={t.accent} />
              <Text style={[styles.actionText, styles.actionTextPrimary]}>{tr('connect_scan')}</Text>
            </Pressable>
          )}
          <Pressable
            accessibilityRole="button"
            onPress={addManually}
            style={({pressed}) => [styles.action, pressed && styles.pressed]}>
            <Icon icon={faKeyboard} size={14} color={t.t2} />
            <Text style={styles.actionText}>{tr('connect_add_manual')}</Text>
          </Pressable>
        </View>
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
  group: {fontSize: 11, fontWeight: '600', letterSpacing: 1.2, color: t.t4, paddingHorizontal: 12, marginBottom: 4},
  groupSpaced: {marginTop: 14},
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
  meta: {fontSize: 12, color: t.t3, marginTop: 3},
  remove: {fontSize: 13, color: t.t4},
  removeConfirm: {color: t.danger},
  actions: {flexDirection: 'row', gap: 10, marginTop: 16, paddingHorizontal: 4},
  action: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    height: 46,
    borderRadius: radius.md,
    backgroundColor: t.bg2,
  },
  actionPrimary: {backgroundColor: t.accentSoft, borderWidth: 1, borderColor: t.accentLine},
  actionText: {fontSize: 15, fontWeight: '500', color: t.t1},
  actionTextPrimary: {color: t.accent, fontWeight: '600'},
  busy: {flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 10, paddingVertical: 20},
  busyText: {fontSize: 15, color: t.t2},
}));
