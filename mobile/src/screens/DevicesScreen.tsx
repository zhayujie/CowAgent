import {
  faCheck,
  faClock,
  faDesktop,
  faGlobe,
  faLaptop,
  faLink,
  faMobileScreen,
  faPen,
  faQrcode,
  faRightFromBracket,
  faServer,
  faTrashCan,
} from '@fortawesome/free-solid-svg-icons';
import type {IconDefinition} from '@fortawesome/fontawesome-svg-core';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useEffect, useRef, useState} from 'react';
import {ActivityIndicator, Image, RefreshControl, ScrollView, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {
  createPairing,
  getPairing,
  listDevices,
  removeDevice,
  renameDevice,
  renameInstance,
} from '../api/cowApi';
import {ApiError, http} from '../api/http';
import {Icon} from '../components/Icon';
import {
  ActionButton,
  ChoiceSheet,
  ConfirmSheet,
  FieldSheet,
  MONO,
  Notice,
  SettingRow,
  StatusTag,
} from '../components/settings';
import {SHEET_DISMISS_MS, Sheet} from '../components/Sheet';
import {showToast, ToastHost} from '../components/Toast';
import {EmptyState, GroupLabel, PageHeader} from '../components/ui';
import {tr, trf} from '../i18n';
import type {RootStackParamList} from '../navigation/types';
import type {DeviceList, PairedDevice, PairingCode} from '../protocol/resources';
import {describeConnectError, noteServerName, useServerStore} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {copyText} from '../utils/clipboard';
import {countdown, deviceMeta, seenLabel, sortDevices} from '../utils/devices';

type Props = StackScreenProps<RootStackParamList, 'Devices'>;

type Pairing = PairingCode & {expiresAt: number; expired?: boolean};
type MenuKey = 'rename' | 'remove' | 'signout';
type Confirm = {kind: 'remove' | 'signout'; device: PairedDevice};

const REFRESH_MS = 30_000;
const PAIR_POLL_MS = 2_000;
const QR_SIZE = 180;

function platformIcon(platform: string): IconDefinition {
  if (platform === 'ios' || platform === 'android' || platform === 'harmony') {
    return faMobileScreen;
  }
  if (platform === 'desktop') {
    return faLaptop;
  }
  return platform === 'web' ? faGlobe : faDesktop;
}

/** The last non-null value, so a closing sheet keeps its text while it slides away. */
function useLingering<T>(value: T | null): T | null {
  const last = useRef(value);
  if (value !== null) {
    last.current = value;
  }
  return last.current;
}

export function DevicesScreen({navigation}: Props) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const logout = useServerStore(s => s.logout);
  const [list, setList] = useState<DeviceList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [pairOpen, setPairOpen] = useState(false);
  // Kept after the sheet closes so its content stays put while it slides away.
  const [pairing, setPairing] = useState<Pairing | null>(null);
  const [pairBusy, setPairBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const pairReq = useRef(0);
  const [localOnly, setLocalOnly] = useState(false);
  const [, setTick] = useState(0);
  const [menu, setMenu] = useState<PairedDevice | null>(null);
  const [renaming, setRenaming] = useState<PairedDevice | 'server' | null>(null);
  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const menuShown = useLingering(menu);
  const renamingShown = useLingering(renaming);
  const confirmShown = useLingering(confirm);

  const load = useCallback(async () => {
    try {
      const data = await listDevices();
      setList(data);
      setError(null);
      noteServerName(data.instance?.name);
    } catch (e) {
      setError(describeConnectError(e));
    }
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  const refresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const startPairing = async () => {
    const req = ++pairReq.current;
    setPairBusy(true);
    setCopied(false);
    try {
      const data = await createPairing(http.getBaseUrl());
      if (req !== pairReq.current) {
        return;
      }
      setLocalOnly(false);
      setPairing({...data, expiresAt: Date.now() + data.expires_in * 1000});
    } catch (e) {
      if (req !== pairReq.current) {
        return;
      }
      // Toasts sit under the sheet's modal, so it closes first.
      setPairOpen(false);
      const reason = e instanceof ApiError ? e.body?.reason : undefined;
      if (reason === 'local_only') {
        setLocalOnly(true);
      } else {
        showToast(trf('devices_pair_failed', {error: describeConnectError(e)}));
      }
    } finally {
      if (req === pairReq.current) {
        setPairBusy(false);
      }
    }
  };

  const openPairing = () => {
    setPairing(null);
    setPairOpen(true);
    startPairing();
  };

  const closePairing = () => {
    pairReq.current++;
    setPairBusy(false);
    setPairOpen(false);
  };

  const pairingId = pairOpen && pairing && !pairing.expired ? pairing.pairing_id : '';
  useEffect(() => {
    if (!pairingId) {
      return;
    }
    let alive = true;
    let polling = false;
    let lastPoll = Date.now();
    // Ticks every second for the countdown; asks the server every PAIR_POLL_MS.
    const timer = setInterval(async () => {
      setTick(n => n + 1);
      if (polling || Date.now() - lastPoll < PAIR_POLL_MS) {
        return;
      }
      polling = true;
      lastPoll = Date.now();
      try {
        const res = await getPairing(pairingId);
        // A sheet closed or reopened meanwhile no longer shows this code.
        if (!alive) {
          return;
        }
        if (res.state === 'paired') {
          setPairOpen(false);
          showToast(trf('devices_paired', {name: res.device?.name ?? ''}));
          load();
        } else if (res.state === 'expired') {
          setPairing(p => (p && p.pairing_id === pairingId ? {...p, expired: true} : p));
        }
      } catch {
        // Tried again on the next round.
      } finally {
        polling = false;
      }
    }, 1000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [pairingId, load]);

  const left = pairing ? pairing.expiresAt - Date.now() : 0;
  useEffect(() => {
    if (pairing && !pairing.expired && left <= 0) {
      setPairing({...pairing, expired: true});
    }
  }, [pairing, left]);

  useEffect(() => {
    if (!copied) {
      return;
    }
    const timer = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(timer);
  }, [copied]);

  const copyLink = async () => {
    if (pairing && !pairing.expired && (await copyText(pairing.link))) {
      setCopied(true);
    }
  };

  const current = list?.current ?? '';
  const devices = list ? sortDevices(list.devices, current) : [];

  const onMenu = (key: MenuKey) => {
    const device = menu;
    setMenu(null);
    if (!device) {
      return;
    }
    setTimeout(
      () => (key === 'rename' ? setRenaming(device) : setConfirm({kind: key, device})),
      SHEET_DISMISS_MS,
    );
  };

  const submitRename = async (value: string) => {
    const target = renamingShown;
    if (target === 'server') {
      if (value === list?.instance.name) {
        return;
      }
      const res = await renameInstance(value);
      setList(l => l && {...l, instance: res.instance});
      noteServerName(res.instance.name);
      return;
    }
    if (!target || value === target.name) {
      return;
    }
    const res = await renameDevice(target.id, value);
    setList(l => l && {...l, devices: l.devices.map(d => (d.id === target.id ? {...d, ...res.device} : d))});
  };

  const runConfirm = async () => {
    const c = confirmShown;
    if (!c) {
      return;
    }
    try {
      if (c.kind === 'signout') {
        await logout();
        return;
      }
      await removeDevice(c.device.id);
      setList(l => l && {...l, devices: l.devices.filter(d => d.id !== c.device.id)});
    } catch (e) {
      showToast(trf('devices_remove_failed', {error: describeConnectError(e)}));
    } finally {
      setConfirm(null);
    }
  };

  const confirmCopy = (() => {
    const c = confirmShown;
    if (!c) {
      return {title: '', message: '', ok: ''};
    }
    if (c.kind === 'signout') {
      return {
        title: tr('devices_sign_out_here'),
        message: tr('devices_sign_out_here_confirm'),
        ok: tr('devices_sign_out_here'),
      };
    }
    return {
      title: tr('devices_remove'),
      message: trf('devices_remove_confirm', {name: c.device.name}),
      ok: tr('devices_remove'),
    };
  })();

  if (!list) {
    return (
      <View style={styles.root}>
        <PageHeader title={tr('devices_title')} onBack={navigation.goBack} />
        <EmptyState loading={!error} title={tr('devices_load_failed')} hint={error ?? undefined} />
      </View>
    );
  }

  // A managed instance is named and reached the way whoever runs it set up.
  const managed = !!list.instance.managed;
  const menuIsCurrent = !!menuShown && menuShown.id === current;

  return (
    <View style={styles.root}>
      <PageHeader title={tr('devices_title')} onBack={navigation.goBack} />
      <ScrollView
        contentContainerStyle={[styles.body, {paddingBottom: insets.bottom + 32}]}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={t.t3} colors={[t.green]} />}>
        <GroupLabel style={styles.firstGroup}>{tr('devices_server')}</GroupLabel>
        <SettingRow
          icon={faServer}
          title={list.instance.name}
          detail={list.instance.version ? `CowAgent v${list.instance.version}` : undefined}
          onPress={managed ? undefined : () => setRenaming('server')}
          last
        />

        <GroupLabel style={styles.group}>
          {devices.length ? `${tr('devices_connected')} (${devices.length})` : tr('devices_connected')}
        </GroupLabel>
        {!managed && localOnly && <Notice>{tr('devices_local_only')}</Notice>}
        {!managed && !list.password_set && <Notice>{tr('devices_no_password')}</Notice>}

        <SettingRow icon={faQrcode} title={tr('devices_let_connect')} onPress={openPairing} />

        {!devices.length ? (
          <View style={styles.empty}>
            <Icon icon={faMobileScreen} size={18} color={t.t4} />
            <Text style={styles.emptyText}>{tr('devices_empty')}</Text>
          </View>
        ) : (
          devices.map((d, i) => {
            const isCurrent = d.id === current;
            return (
              <SettingRow
                key={d.id}
                icon={platformIcon(d.platform)}
                title={d.name}
                detail={deviceMeta(d)}
                value={isCurrent || d.online ? undefined : seenLabel(d)}
                right={
                  isCurrent ? (
                    <StatusTag label={tr('devices_this')} on />
                  ) : d.online ? (
                    <StatusTag label={tr('devices_online')} on />
                  ) : undefined
                }
                onPress={() => setMenu(d)}
                last={i === devices.length - 1}
              />
            );
          })
        )}
      </ScrollView>

      <Sheet visible={pairOpen} onClose={closePairing} title={tr('devices_let_connect')}>
        <ScrollView style={styles.sheetScroll} bounces={false}>
          {pairing ? (
            <PairingCard
              pairing={pairing}
              left={left}
              busy={pairBusy}
              copied={copied}
              onRegenerate={startPairing}
              onCopyLink={copyLink}
              onClose={closePairing}
            />
          ) : (
            <View style={styles.pairLoading}>
              <ActivityIndicator color={t.t3} />
            </View>
          )}
        </ScrollView>
      </Sheet>
      <ChoiceSheet<MenuKey>
        visible={!!menu}
        title={menuShown?.name ?? ''}
        options={[
          {key: 'rename', label: tr('devices_rename_device'), icon: faPen},
          menuIsCurrent
            ? {key: 'signout', label: tr('devices_sign_out_here'), icon: faRightFromBracket}
            : {key: 'remove', label: tr('devices_remove'), icon: faTrashCan},
        ]}
        onSelect={onMenu}
        onClose={() => setMenu(null)}
      />
      <FieldSheet
        visible={!!renaming}
        title={renamingShown === 'server' ? tr('devices_rename_server') : tr('devices_rename_device')}
        initial={renamingShown === 'server' ? list.instance.name : renamingShown?.name ?? ''}
        hint={renamingShown === 'server' ? tr('devices_rename_server_hint') : undefined}
        allowEmpty={renamingShown === 'server'}
        onSubmit={submitRename}
        onClose={() => setRenaming(null)}
      />
      <ConfirmSheet
        visible={!!confirm}
        title={confirmCopy.title}
        message={confirmCopy.message}
        confirmLabel={confirmCopy.ok}
        danger
        onConfirm={runConfirm}
        onClose={() => setConfirm(null)}
      />
      <ToastHost bottom={insets.bottom + 28} />
    </View>
  );
}

function PairingCard({
  pairing,
  left,
  busy,
  copied,
  onRegenerate,
  onCopyLink,
  onClose,
}: {
  pairing: Pairing;
  left: number;
  busy: boolean;
  copied: boolean;
  onRegenerate: () => void;
  onCopyLink: () => void;
  onClose: () => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  const {expired} = pairing;
  return (
    <View style={styles.pairBody}>
      <View style={styles.qrFrame}>
        {pairing.qr_image ? (
          <Image
            source={{uri: pairing.qr_image}}
            accessibilityLabel={tr('devices_code')}
            style={[styles.qr, expired && styles.faded]}
            resizeMode="contain"
          />
        ) : (
          <View style={[styles.qr, styles.noQr]}>
            <Text style={styles.noQrText}>{tr('devices_no_qr')}</Text>
          </View>
        )}
      </View>
      <View style={styles.status}>
        <Icon icon={faClock} size={11} color={expired ? t.danger : t.t3} />
        <Text style={[styles.statusText, expired && styles.danger]}>
          {expired ? tr('devices_expired') : trf('devices_expires_in', {t: countdown(left)})}
        </Text>
        {!expired && (
          <>
            <ActivityIndicator size="small" color={t.t4} style={styles.spinner} />
            <Text style={styles.statusText}>{tr('devices_waiting')}</Text>
          </>
        )}
      </View>

      <Text style={styles.label}>{tr('devices_code')}</Text>
      <Text style={[styles.code, expired && styles.codeExpired]} selectable>
        {pairing.code}
      </Text>
      <Text style={styles.label}>{tr('devices_address')}</Text>
      {pairing.urls.map(u => (
        <Text key={u} style={styles.url} selectable>
          {u}
        </Text>
      ))}

      <View style={styles.steps}>
        {[tr('devices_step_app'), tr('devices_step_other')].map((text, i) => (
          <View key={text} style={styles.step}>
            <Text style={styles.stepNo}>{i + 1}</Text>
            <Text style={styles.stepText}>{text}</Text>
          </View>
        ))}
      </View>

      <View style={styles.actions}>
        <ActionButton label={tr('common_close')} onPress={onClose} style={styles.flex} />
        {expired ? (
          <ActionButton
            label={tr('devices_regenerate')}
            tone="primary"
            loading={busy}
            onPress={onRegenerate}
            style={styles.flex}
          />
        ) : (
          <ActionButton
            label={copied ? tr('common_copied') : tr('devices_copy_link')}
            icon={copied ? faCheck : faLink}
            onPress={onCopyLink}
            style={styles.flex}
          />
        )}
      </View>
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  body: {paddingTop: 4},
  firstGroup: {marginTop: 8},
  group: {marginTop: 26},
  empty: {alignItems: 'center', gap: 10, paddingVertical: 28},
  emptyText: {fontSize: 13, color: t.t3},
  sheetScroll: {flexGrow: 0, flexShrink: 1},
  pairLoading: {alignItems: 'center', justifyContent: 'center', paddingVertical: 48},
  pairBody: {paddingHorizontal: 12, paddingTop: 4, paddingBottom: 4},
  qrFrame: {
    alignSelf: 'center',
    padding: 10,
    borderRadius: radius.md,
    backgroundColor: '#FFFFFF',
    borderWidth: t.isDark ? 0 : 1,
    borderColor: t.line1,
  },
  qr: {width: QR_SIZE, height: QR_SIZE},
  faded: {opacity: 0.15},
  noQr: {alignItems: 'center', justifyContent: 'center'},
  noQrText: {fontSize: 12, color: '#888888'},
  status: {flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, marginTop: 12},
  statusText: {fontSize: 12, color: t.t3},
  danger: {color: t.danger},
  spinner: {marginLeft: 8, transform: [{scale: 0.7}]},
  label: {fontSize: 12, color: t.t4, marginTop: 14, marginBottom: 4},
  code: {fontFamily: MONO, fontSize: 26, fontWeight: '600', letterSpacing: 4, color: t.t1},
  codeExpired: {opacity: 0.4, textDecorationLine: 'line-through'},
  url: {fontFamily: MONO, fontSize: 12, lineHeight: 18, color: t.t2},
  steps: {gap: 8, marginTop: 16},
  step: {flexDirection: 'row', gap: 10},
  stepNo: {
    width: 20,
    height: 20,
    borderRadius: 10,
    overflow: 'hidden',
    textAlign: 'center',
    lineHeight: 20,
    fontSize: 11,
    fontWeight: '600',
    color: t.accent,
    backgroundColor: t.accentSoft,
  },
  stepText: {flex: 1, fontSize: 13, lineHeight: 20, color: t.t2},
  actions: {flexDirection: 'row', gap: 10, marginTop: 16},
  flex: {flex: 1},
}));
