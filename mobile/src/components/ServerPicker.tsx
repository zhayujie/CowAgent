import {faKeyboard, faQrcode} from '@fortawesome/free-solid-svg-icons';
import React, {useEffect, useState} from 'react';
import {ActivityIndicator, Text, View} from 'react-native';
import type {PairTarget} from '../api/pairing';
import {tr} from '../i18n';
import {isLocalKernelAvailable, LOCAL_SERVER_ID, useLocalDeviceName} from '../kernel/localKernel';
import {describeConnectError, useServerStore} from '../store/serverStore';
import {makeStyles, useTheme} from '../theme/theme';
import {usePairAction} from './PairFlow';
import {QrScanner, qrScannerAvailable} from './QrScanner';
import {SHEET_DISMISS_MS, Sheet} from './Sheet';
import {showToast} from './Toast';

export const hostOf = (baseUrl: string) => baseUrl.replace(/^https?:\/\//, '');

/** The status dot beside the current device: green while it answers, amber on the way, red once cut off. */
export function useLinkColor(): string {
  const t = useTheme();
  const status = useServerStore(s => s.realtimeStatus);
  return {
    idle: t.green,
    open: t.green,
    connecting: t.kind.image[1],
    closed: t.danger,
    revoked: t.danger,
  }[status];
}

export interface ServerEntry {
  id: string;
  name: string;
  meta: string;
  local: boolean;
}

/**
 * Where the agent can run: this phone first, then the computers and servers
 * paired before, with the ways to pair another one. Shared by the switcher
 * sheet and the devices page; `overlays` must be rendered outside any sheet.
 */
export function useServerPicker() {
  const t = useTheme();
  const styles = useStyles();
  const servers = useServerStore(s => s.servers);
  const activeId = useServerStore(s => s.activeId);
  const localName = useLocalDeviceName();
  const [pending, setPending] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const pairing = usePairAction();

  useEffect(() => {
    if (pairing.error) {
      showToast(pairing.error);
    }
  }, [pairing.error]);

  const entries: ServerEntry[] = [
    ...(isLocalKernelAvailable()
      ? [{id: LOCAL_SERVER_ID, name: localName, meta: tr('server_local_meta'), local: true}]
      : []),
    ...servers.filter(s => !s.local).map(s => ({id: s.id, name: s.name, meta: hostOf(s.baseUrl), local: false})),
  ];

  const select = async (id: string) => {
    if (pending || id === activeId) {
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

  const remove = (id: string) => useServerStore.getState().removeServer(id);

  /** `fromSheet`: iOS can't present the camera while a sheet's modal is still closing. */
  const scan = (fromSheet = false) => {
    setTimeout(() => setScanning(true), fromSheet ? SHEET_DISMISS_MS : 0);
  };

  const addManually = () => useServerStore.getState().addServer(true);

  /** `closeSheet`: the picker sits in a sheet that has to get out of the way first. */
  const connectActions = (closeSheet?: () => void) => [
    ...(qrScannerAvailable
      ? [
          {
            icon: faQrcode,
            label: tr('connect_scan'),
            onPress: () => {
              closeSheet?.();
              scan(!!closeSheet);
            },
          },
        ]
      : []),
    {
      icon: faKeyboard,
      label: tr('connect_manual_short'),
      onPress: () => {
        closeSheet?.();
        addManually();
      },
    },
  ];

  const onScanned = (target: PairTarget) => {
    setScanning(false);
    pairing.run(target);
  };

  const overlays = (
    <>
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

  return {entries, activeId, pending, select, remove, connectActions, overlays};
}

const useStyles = makeStyles(t => ({
  busy: {flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 10, paddingVertical: 20},
  busyText: {fontSize: 15, color: t.t2},
}));
