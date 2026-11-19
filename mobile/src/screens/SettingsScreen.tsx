import {
  faArrowsRotate,
  faBars,
  faChevronRight,
  faCode,
  faCommentDots,
  faGaugeHigh,
  faGlobe,
  faKey,
  faLaptop,
  faMicrochip,
  faMobileScreen,
  faServer,
  faShareNodes,
  faShieldHalved,
  faTerminal,
  faUserShield,
} from '@fortawesome/free-solid-svg-icons';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useEffect, useState} from 'react';
import {Pressable, RefreshControl, ScrollView, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {http} from '../api/http';
import {isDeviceToken} from '../api/pairing';
import {PERMISSION_META} from '../components/ComposerSheets';
import {Icon} from '../components/Icon';
import {ServerSheet} from '../components/ServerSheet';
import {tr, trf, useLangStore, type Lang, type MessageKey} from '../i18n';
import {ChoiceSheet, ConfirmSheet, FieldSheet, SettingCard, SettingRow} from '../components/settings';
import {showToast, ToastHost} from '../components/Toast';
import {PageHeader} from '../components/ui';
import {openWebPage} from '../navigation/openWeb';
import type {RootStackParamList} from '../navigation/types';
import type {PermissionMode} from '../protocol/resources';
import {useConfigStore} from '../store/configStore';
import {useOverviewStore} from '../store/overviewStore';
import {
  activeServer,
  changingPassword,
  describeConnectError,
  useLocalServer,
  useServerStore,
} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, usePrefsStore, useTheme, type ThemeMode} from '../theme/theme';
import {PASSWORD_MIN_LENGTH, PASSWORD_STRENGTH_TEXT, passwordStrength} from '../utils/passwordStrength';

type Props = StackScreenProps<RootStackParamList, 'Settings'>;

const MODES: {key: ThemeMode; label: MessageKey}[] = [
  {key: 'system', label: 'settings_theme_system'},
  {key: 'light', label: 'settings_theme_light'},
  {key: 'dark', label: 'settings_theme_dark'},
];

const REALTIME_LABEL = {
  idle: 'settings_realtime_idle',
  connecting: 'settings_realtime_connecting',
  open: 'settings_realtime_open',
  closed: 'settings_realtime_closed',
  revoked: 'settings_realtime_revoked',
} as const satisfies Record<string, MessageKey>;

/** Each language names itself, so a wrong pick can always be undone. */
const LANGS: {key: Lang; label: string}[] = [
  {key: 'zh', label: '简体中文'},
  {key: 'en', label: 'English'},
];

const PERMISSION_ORDER = Object.keys(PERMISSION_META) as PermissionMode[];

const REPO_URL = 'https://github.com/zhayujie/CowAgent';

export function SettingsScreen({navigation}: Props) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const mode = usePrefsStore(s => s.mode);
  const setMode = usePrefsStore(s => s.setMode);
  const lang = useLangStore(s => s.lang);
  const setLang = useLangStore(s => s.setLang);
  const realtimeStatus = useServerStore(s => s.realtimeStatus);
  const logout = useServerStore(s => s.logout);
  const relogin = useServerStore(s => s.relogin);
  const version = useOverviewStore(s => s.version);
  const config = useConfigStore(s => s.config);
  const externalApi = useConfigStore(s => s.externalApi);
  const loadConfig = useConfigStore(s => s.load);
  const updateConfig = useConfigStore(s => s.update);
  const server = activeServer();
  const local = useLocalServer();
  const [confirmLogout, setConfirmLogout] = useState(false);
  const [sheet, setSheet] = useState<'permission' | 'password' | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [serverSheet, setServerSheet] = useState(false);

  useEffect(() => {
    loadConfig().catch(() => undefined);
  }, [loadConfig]);

  const refresh = async () => {
    setRefreshing(true);
    await loadConfig().catch(() => undefined);
    setRefreshing(false);
  };

  const permission = config?.agent_permission_mode;
  const pickPermission = async (next: PermissionMode) => {
    setSheet(null);
    if (next === permission) {
      return;
    }
    try {
      await updateConfig({agent_permission_mode: next});
      showToast(trf('settings_permission_default_toast', {name: PERMISSION_META[next].name}));
    } catch (e) {
      showToast(trf('common_save_failed_detail', {error: describeConnectError(e)}));
    }
  };

  const changePassword = async (value: string) => {
    if (passwordStrength(value) === 'short') {
      throw new Error(trf('settings_pwd_min', {min: PASSWORD_MIN_LENGTH}));
    }
    await changingPassword(
      (async () => {
        const res = await updateConfig({web_password: value});
        await relogin(value, res.auth_token);
      })(),
    );
    showToast(tr('settings_pwd_updated'));
  };

  const changeLanguage = (next: Lang) => {
    if (next === lang) {
      return;
    }
    setLang(next);
    // Agent replies, logs and the CLI follow the server's cow_lang; best effort like the desktop client.
    updateConfig({cow_lang: next}).catch(() => undefined);
  };

  const serverName = local ? tr('server_local') : server?.name ?? '-';
  const serverMeta = local
    ? tr('server_local_meta')
    : `${server?.baseUrl.replace(/^https?:\/\//, '') ?? '-'} · ${
        (server?.via ?? (isDeviceToken(http.getToken()) ? 'pairing' : 'password')) === 'pairing'
          ? tr('connect_method_device')
          : tr('connect_method_password')
      }`;
  const realtimeLabel = tr(REALTIME_LABEL[realtimeStatus]);
  const realtimeColor = {
    idle: t.t4,
    connecting: t.kind.image[1],
    open: t.green,
    closed: t.danger,
    revoked: t.danger,
  }[realtimeStatus];

  const loading = !config;
  return (
    <View style={styles.root}>
      <PageHeader title={tr('settings_title')} onBack={navigation.goBack} />
      <ScrollView
        contentContainerStyle={[styles.body, {paddingBottom: insets.bottom + 32}]}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={t.t3} colors={[t.green]} />}>
        <SettingCard>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={trf('settings_connection_a11y', {name: serverName, meta: serverMeta, status: realtimeLabel})}
            onPress={() => setServerSheet(true)}
            style={({pressed}) => [styles.server, pressed && styles.pressed]}>
            <View style={styles.serverIcon}>
              <Icon icon={local ? faMobileScreen : faServer} size={16} color={t.accent} />
            </View>
            <View style={styles.serverText}>
              <Text style={styles.serverName} numberOfLines={1}>
                {serverName}
              </Text>
              <Text style={styles.serverMeta} numberOfLines={1}>
                {serverMeta}
              </Text>
              <View style={styles.realtime}>
                <View style={[styles.dot, {backgroundColor: realtimeColor}]} />
                <Text style={styles.realtimeText} numberOfLines={1}>
                  {realtimeLabel}
                </Text>
              </View>
            </View>
            <Icon icon={faChevronRight} size={10} color={t.t4} />
          </Pressable>
        </SettingCard>

        <SettingCard style={styles.group}>
          <SettingRow
            icon={faMicrochip}
            title={tr('settings_models')}
            value={config?.model || (loading ? '…' : tr('common_not_configured'))}
            onPress={() => navigation.navigate('Models')}
          />
          <SettingRow
            icon={faGaugeHigh}
            title={tr('settings_runtime')}
            value={
              config
                ? trf('settings_runtime_value', {steps: config.agent_max_steps, turns: config.agent_max_context_turns})
                : '…'
            }
            onPress={() => navigation.navigate('Runtime')}
          />
          <SettingRow
            icon={faShieldHalved}
            title={tr('settings_default_permission')}
            value={permission ? PERMISSION_META[permission]?.name ?? permission : '…'}
            onPress={config ? () => setSheet('permission') : undefined}
            last
          />
        </SettingCard>

        {/* The built-in agent listens on loopback only and keeps its own password, so none of this applies. */}
        {!local && (
          <SettingCard style={styles.group}>
            <SettingRow icon={faGlobe} title={tr('settings_access_url')} onPress={() => navigation.navigate('Access')} />
            <SettingRow
              icon={faShareNodes}
              title={tr('settings_guest_pages')}
              onPress={() => navigation.navigate('GuestShares')}
            />
            <SettingRow
              icon={faCode}
              title={tr('settings_external_api')}
              value={externalApi ? (externalApi.enabled ? tr('common_enabled') : tr('common_disabled')) : '…'}
              onPress={() => navigation.navigate('ExternalApi')}
            />
            <SettingRow icon={faLaptop} title={tr('devices_title')} onPress={() => navigation.navigate('Devices')} />
            <SettingRow
              icon={faKey}
              title={tr('settings_access_password')}
              value={config ? (config.web_password_masked ? tr('common_configured') : tr('common_not_set')) : '…'}
              onPress={config ? () => setSheet('password') : undefined}
              last
            />
          </SettingCard>
        )}

        <SettingCard style={styles.group}>
          <Segmented
            title={tr('settings_theme')}
            options={MODES.map(m => ({key: m.key, label: tr(m.label)}))}
            value={mode}
            onChange={setMode}
          />
          <Segmented title={tr('settings_language')} options={LANGS} value={lang} onChange={changeLanguage} />
          <SettingRow icon={faBars} title={tr('settings_menu')} onPress={() => navigation.navigate('MenuEditor')} last />
        </SettingCard>

        <SettingCard style={styles.group}>
          <SettingRow icon={faUserShield} title={tr('perm_title')} onPress={() => navigation.navigate('Permissions')} />
          <SettingRow icon={faTerminal} title={tr('settings_logs')} onPress={() => navigation.navigate('Logs')} />
          <SettingRow
            icon={faArrowsRotate}
            title={tr('settings_version')}
            value={version ? `v${version}` : undefined}
            onPress={() => navigation.navigate('Version')}
          />
          <SettingRow
            icon={faCommentDots}
            title={tr('settings_feedback')}
            onPress={() => openWebPage(`${REPO_URL}/issues`)}
            last
          />
        </SettingCard>

        <Pressable
          accessibilityRole="button"
          onPress={() => setConfirmLogout(true)}
          style={({pressed}) => [styles.logout, pressed && styles.pressed]}>
          <Text style={styles.logoutText}>{tr('settings_logout')}</Text>
        </Pressable>
      </ScrollView>

      <ChoiceSheet
        visible={sheet === 'permission'}
        title={tr('settings_permission_sheet_title')}
        options={PERMISSION_ORDER.filter(m => !config || config.permission_modes.includes(m)).map(m => ({
          key: m,
          label: PERMISSION_META[m].name,
          desc: PERMISSION_META[m].desc,
          icon: PERMISSION_META[m].icon,
        }))}
        selected={permission}
        note={tr('settings_permission_sheet_note')}
        onSelect={pickPermission}
        onClose={() => setSheet(null)}
      />
      <FieldSheet
        visible={sheet === 'password'}
        title={tr('settings_change_password')}
        placeholder={tr('settings_new_password_ph')}
        secure
        allowEmpty={false}
        hint={trf('settings_password_hint', {min: PASSWORD_MIN_LENGTH})}
        describe={v => {
          const s = passwordStrength(v);
          return {text: PASSWORD_STRENGTH_TEXT[s], tone: s === 'strong' ? 'ok' : s === 'medium' ? 'warn' : 'danger'};
        }}
        onSubmit={changePassword}
        onClose={() => setSheet(null)}
      />
      <ConfirmSheet
        visible={confirmLogout}
        title={tr('settings_logout')}
        message={tr('settings_logout_note')}
        confirmLabel={tr('settings_logout')}
        danger
        onConfirm={logout}
        onClose={() => setConfirmLogout(false)}
      />
      <ServerSheet visible={serverSheet} onClose={() => setServerSheet(false)} />
      <ToastHost bottom={insets.bottom + 28} />
    </View>
  );
}

/** A card row whose value is picked in place from a few short options. */
function Segmented<K extends string>({
  title,
  options,
  value,
  onChange,
}: {
  title: string;
  options: {key: K; label: string}[];
  value: K;
  onChange: (key: K) => void;
}) {
  const styles = useStyles();
  return (
    <View style={styles.segRow}>
      <Text style={styles.segTitle} numberOfLines={1}>
        {title}
      </Text>
      <View style={styles.seg} accessibilityRole="radiogroup" accessibilityLabel={title}>
        {options.map(o => {
          const active = o.key === value;
          return (
            <Pressable
              key={o.key}
              accessibilityRole="radio"
              accessibilityState={{selected: active}}
              onPress={() => onChange(o.key)}
              style={[styles.segItem, active && styles.segItemActive]}>
              <Text style={[styles.segText, active && styles.segTextActive]} numberOfLines={1}>
                {o.label}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  body: {paddingTop: 8},
  group: {marginTop: 14},
  pressed: {opacity: 0.6},
  server: {flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 14, paddingVertical: 14},
  serverIcon: {
    width: 40,
    height: 40,
    borderRadius: radius.sm,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: t.accentSoft,
  },
  serverText: {flex: 1, minWidth: 0},
  serverName: {fontSize: 16, fontWeight: '600', color: t.t1, letterSpacing: -0.2},
  serverMeta: {fontSize: 12, color: t.t3, marginTop: 3},
  realtime: {flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 6},
  dot: {width: 6, height: 6, borderRadius: 3},
  realtimeText: {fontSize: 12, color: t.t3},
  segRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    minHeight: 52,
    marginHorizontal: 14,
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: t.line1,
  },
  segTitle: {flex: 1, fontSize: 15, color: t.t1, letterSpacing: -0.1},
  seg: {flexBasis: 228, flexShrink: 1, flexDirection: 'row', padding: 3, borderRadius: radius.sm, backgroundColor: t.bg2},
  segItem: {flex: 1, alignItems: 'center', paddingVertical: 6, borderRadius: radius.xs},
  segItemActive: {backgroundColor: t.accentSoft},
  segText: {fontSize: 13, color: t.t3},
  segTextActive: {color: t.accent, fontWeight: '600'},
  logout: {
    marginTop: 14,
    marginHorizontal: 16,
    paddingVertical: 14,
    alignItems: 'center',
    borderRadius: radius.md,
    backgroundColor: t.dangerSoft,
  },
  logoutText: {fontSize: 15, fontWeight: '500', color: t.danger},
}));
