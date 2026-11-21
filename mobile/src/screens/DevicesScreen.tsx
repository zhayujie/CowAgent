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
  faXmark,
} from '@fortawesome/free-solid-svg-icons';
import type {IconDefinition} from '@fortawesome/fontawesome-svg-core';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useEffect, useRef, useState} from 'react';
import {ActivityIndicator, Image, Pressable, RefreshControl, ScrollView, Text, View} from 'react-native';
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
import {hostOf, useLinkColor, useServerPicker} from '../components/ServerPicker';
import {
  ActionButton,
  CardLabel,
  ChoiceSheet,
  ConfirmSheet,
  FieldSheet,
  MONO,
  Notice,
  SettingCard,
  SettingRow,
  StatusTag,
  TileButtons,
} from '../components/settings';
import {SHEET_DISMISS_MS, Sheet} from '../components/Sheet';
import {showToast, ToastHost} from '../components/Toast';
import {PageHeader} from '../components/ui';
import {tr, trf} from '../i18n';
import {setLocalDeviceName, systemDeviceName, useLocalDeviceName} from '../kernel/localKernel';
import type {RootStackParamList} from '../navigation/types';
import type {DeviceList, PairedDevice, PairingCode} from '../protocol/resources';
import {activeServer, describeConnectError, noteServerName, useLocalServer, useServerStore} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {copyText} from '../utils/clipboard';
import {countdown, deviceMeta, seenLabel, sortDevices} from '../utils/devices';

type Props = StackScreenProps<RootStackParamList, 'Devices'>;

type Pairing = PairingCode & {expiresAt: number; expired?: boolean};
type MenuKey = 'rename' | 'remove' | 'signout';
type Confirm = {kind: 'remove' | 'signout'; device: PairedDevice} | {kind: 'forget'; id: string; name: string};
type Renaming = PairedDevice | 'current';

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

/**
 * The device the app is on now, the ones it can switch to, and, for a
 * remote one, everything else connected to it.
 */
export function DevicesScreen({navigation}: Props) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const local = useLocalServer();
  const server = activeServer();
  const localName = useLocalDeviceName();
  const linkColor = useLinkColor();
  const picker = useServerPicker();
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
  const [renaming, setRenaming] = useState<Renaming | null>(null);
  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const menuShown = useLingering(menu);
  const renamingShown = useLingering(renaming);
  const confirmShown = useLingering(confirm);

  // The agent on this phone listens on loopback only: nothing else can connect to it.
  const load = useCallback(async () => {
    if (local) {
      return;
    }
    try {
      const data = await listDevices();
      setList(data);
      setError(null);
      noteServerName(data.instance?.name);
    } catch (e) {
      setError(describeConnectError(e));
    }
  }, [local]);

  useEffect(() => {
    if (local) {
      return;
    }
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, [load, local]);

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
  // A managed instance is named and reached the way whoever runs it set up.
  const managed = !!list?.instance.managed;
  const currentName = local ? localName : server?.name || list?.instance.name || '-';
  const canRename = local || (!!list && !managed);

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
    if (target === 'current') {
      if (local) {
        setLocalDeviceName(value);
        return;
      }
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
      if (c.kind === 'forget') {
        picker.remove(c.id);
      } else if (c.kind === 'signout') {
        await logout();
      } else {
        await removeDevice(c.device.id);
        setList(l => l && {...l, devices: l.devices.filter(d => d.id !== c.device.id)});
      }
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
    if (c.kind === 'forget') {
      return {
        title: tr('devices_forget'),
        message: trf('devices_forget_confirm', {name: c.name}),
        ok: tr('devices_forget'),
      };
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

  const renameCopy =
    renamingShown === 'current'
      ? local
        ? {
            title: tr('devices_rename_local'),
            initial: localName,
            hint: trf('devices_rename_local_hint', {name: systemDeviceName()}),
          }
        : {title: tr('devices_rename_server'), initial: list?.instance.name ?? '', hint: tr('devices_rename_server_hint')}
      : {title: tr('devices_rename_device'), initial: renamingShown?.name ?? '', hint: undefined};

  const menuIsCurrent = !!menuShown && menuShown.id === current;
  const others = picker.entries;
  const address = local ? tr('server_local_meta') : server ? hostOf(server.baseUrl) : '-';
  const version = !local && list?.instance.version ? ` · v${list.instance.version}` : '';

  const connectedList = () => {
    if (!list) {
      return error ? (
        <SettingRow icon={faXmark} title={tr('devices_load_failed')} detail={error} onPress={refresh} last />
      ) : (
        <View style={styles.loading}>
          <ActivityIndicator color={t.t3} />
        </View>
      );
    }
    if (!devices.length) {
      return (
        <View style={styles.empty}>
          <Text style={styles.emptyText}>{tr('devices_empty')}</Text>
        </View>
      );
    }
    return devices.map((d, i) => {
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
    });
  };

  return (
    <View style={styles.root}>
      <PageHeader title={tr('devices_title')} onBack={navigation.goBack} background={t.grouped} />
      <ScrollView
        contentContainerStyle={[styles.body, {paddingBottom: insets.bottom + 32}]}
        refreshControl={
          local ? undefined : (
            <RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={t.t3} colors={[t.green]} />
          )
        }>
        <SettingCard>
          <View style={styles.hero}>
            <View style={styles.heroIcon}>
              <Icon icon={local ? faMobileScreen : faServer} size={17} color={t.accent} />
            </View>
            <View style={styles.heroText}>
              <Text style={styles.heroName} numberOfLines={1}>
                {currentName}
              </Text>
              <View style={styles.heroMetaRow}>
                <View style={[styles.dot, {backgroundColor: linkColor}]} />
                <Text style={styles.heroMeta} numberOfLines={1}>
                  {address}
                  {version}
                </Text>
              </View>
            </View>
            {canRename && (
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={tr('devices_rename_device')}
                hitSlop={8}
                onPress={() => setRenaming('current')}
                style={({pressed}) => [styles.heroEdit, pressed && styles.pressed]}>
                <Icon icon={faPen} size={13} color={t.t2} />
              </Pressable>
            )}
          </View>
        </SettingCard>

        <CardLabel desc={tr('devices_mine_note')}>{tr('devices_mine')}</CardLabel>
        <SettingCard>
          {others.map(s => {
            const active = s.id === picker.activeId;
            const busy = picker.pending === s.id;
            return (
              <SettingRow
                key={s.id}
                icon={s.local ? faMobileScreen : faServer}
                title={s.name}
                detail={s.meta}
                chevron={false}
                right={
                  busy ? (
                    <ActivityIndicator size="small" color={t.t3} />
                  ) : active ? (
                    <Icon icon={faCheck} size={14} color={t.accent} />
                  ) : undefined
                }
                onPress={active ? undefined : () => picker.select(s.id)}
                action={
                  !s.local && !active && !busy ? (
                    <Pressable
                      accessibilityRole="button"
                      accessibilityLabel={tr('devices_forget')}
                      hitSlop={8}
                      onPress={() => setConfirm({kind: 'forget', id: s.id, name: s.name})}
                      style={({pressed}) => [styles.forget, pressed && styles.pressed]}>
                      <Icon icon={faTrashCan} size={13} color={t.t4} />
                    </Pressable>
                  ) : undefined
                }
              />
            );
          })}
        </SettingCard>
        <TileButtons items={picker.connectActions()} style={styles.tiles} />

        {!local && (
          <>
            <CardLabel desc={tr('devices_connected_note')}>
              {trf('devices_connected', {name: currentName}) + (devices.length ? ` (${devices.length})` : '')}
            </CardLabel>
            {!managed && localOnly && <Notice>{tr('devices_local_only')}</Notice>}
            {!!list && !managed && !list.password_set && <Notice>{tr('devices_no_password')}</Notice>}
            <SettingCard>{connectedList()}</SettingCard>
            <TileButtons
              items={[{icon: faQrcode, label: tr('devices_let_connect'), onPress: openPairing}]}
              style={styles.tiles}
            />
          </>
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
        title={renameCopy.title}
        initial={renameCopy.initial}
        hint={renameCopy.hint}
        allowEmpty={renamingShown === 'current'}
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
      {picker.overlays}
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
  root: {flex: 1, backgroundColor: t.grouped},
  body: {paddingTop: 8},
  pressed: {opacity: 0.6},
  hero: {flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 14, paddingVertical: 16},
  heroIcon: {
    width: 44,
    height: 44,
    borderRadius: radius.sm,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: t.accentSoft,
  },
  heroText: {flex: 1, minWidth: 0},
  heroName: {fontSize: 18, fontWeight: '600', color: t.t1, letterSpacing: -0.3},
  heroMetaRow: {flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 5},
  heroMeta: {flexShrink: 1, fontSize: 13, color: t.t3},
  heroEdit: {
    width: 34,
    height: 34,
    borderRadius: 17,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: t.isDark ? t.bg3 : t.bg2,
  },
  dot: {width: 7, height: 7, borderRadius: 4},
  forget: {alignSelf: 'stretch', justifyContent: 'center', paddingLeft: 10},
  tiles: {marginHorizontal: 16, marginTop: 10},
  loading: {alignItems: 'center', paddingVertical: 24},
  empty: {alignItems: 'center', paddingVertical: 22},
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
