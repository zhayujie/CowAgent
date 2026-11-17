import {faMoon, faSun} from '@fortawesome/free-regular-svg-icons';
import {
  faArrowsRotate,
  faBars,
  faCircleHalfStroke,
  faCode,
  faGaugeHigh,
  faGlobe,
  faKey,
  faMicrochip,
  faPlug,
  faShareNodes,
  faShieldHalved,
  faTerminal,
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
import {ChoiceSheet, FieldSheet, Footnote, SettingRow} from '../components/settings';
import {showToast, ToastHost} from '../components/Toast';
import {GroupLabel, PageHeader} from '../components/ui';
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

const MODES: {key: ThemeMode; label: MessageKey; icon: typeof faSun}[] = [
  {key: 'system', label: 'settings_theme_system', icon: faCircleHalfStroke},
  {key: 'light', label: 'settings_theme_light', icon: faSun},
  {key: 'dark', label: 'settings_theme_dark', icon: faMoon},
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

  const loading = !config;
  return (
    <View style={styles.root}>
      <PageHeader title={tr('settings_title')} onBack={navigation.goBack} />
      <ScrollView
        contentContainerStyle={[styles.body, {paddingBottom: insets.bottom + 32}]}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={t.t3} colors={[t.green]} />}>
        <GroupLabel style={styles.firstGroup}>{tr('settings_group_common')}</GroupLabel>
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
        <SettingRow icon={faPlug} title={tr('settings_mcp')} onPress={() => navigation.navigate('Mcp')} />
        <SettingRow icon={faBars} title={tr('settings_menu')} last onPress={() => navigation.navigate('MenuEditor')} />

        {/* The built-in agent listens on loopback only, so nothing outside this phone can reach it. */}
        {!local && (
          <>
            <GroupLabel style={styles.group}>{tr('settings_group_access')}</GroupLabel>
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
              last
            />
          </>
        )}

        <GroupLabel style={styles.group}>{tr('settings_group_appearance')}</GroupLabel>
        <View style={styles.modes}>
          {MODES.map(m => {
            const active = mode === m.key;
            return (
              <Pressable
                key={m.key}
                accessibilityRole="radio"
                accessibilityState={{selected: active}}
                onPress={() => setMode(m.key)}
                style={[styles.mode, active && styles.modeActive]}>
                <Icon icon={m.icon} size={15} color={active ? t.accent : t.t3} />
                <Text style={[styles.modeText, active && styles.modeTextActive]}>{tr(m.label)}</Text>
              </Pressable>
            );
          })}
        </View>

        <GroupLabel style={styles.group}>{tr('settings_language')}</GroupLabel>
        <View style={styles.modes}>
          {LANGS.map(l => {
            const active = lang === l.key;
            return (
              <Pressable
                key={l.key}
                accessibilityRole="radio"
                accessibilityState={{selected: active}}
                onPress={() => changeLanguage(l.key)}
                style={[styles.mode, active && styles.modeActive]}>
                <Text style={[styles.modeText, active && styles.modeTextActive]}>{l.label}</Text>
              </Pressable>
            );
          })}
        </View>

        <GroupLabel style={styles.group}>{tr('settings_group_security')}</GroupLabel>
        <SettingRow
          icon={faShieldHalved}
          title={tr('settings_default_permission')}
          value={permission ? PERMISSION_META[permission]?.name ?? permission : '…'}
          onPress={config ? () => setSheet('permission') : undefined}
          last={local}
        />
        {/* The app keeps the built-in agent's password itself and sets it on every start. */}
        {!local && (
          <SettingRow
            icon={faKey}
            title={tr('settings_access_password')}
            value={config ? (config.web_password_masked ? tr('common_configured') : tr('common_not_set')) : '…'}
            onPress={config ? () => setSheet('password') : undefined}
            last
          />
        )}
        <Footnote>{tr('settings_permission_note')}</Footnote>

        <GroupLabel style={styles.group}>{tr('settings_group_system')}</GroupLabel>
        <SettingRow icon={faTerminal} title={tr('settings_logs')} onPress={() => navigation.navigate('Logs')} />
        <SettingRow
          icon={faArrowsRotate}
          title={tr('settings_version')}
          value={version ? `v${version}` : undefined}
          onPress={() => navigation.navigate('Version')}
          last
        />

        <GroupLabel style={styles.group}>{tr('settings_group_server')}</GroupLabel>
        <SettingRow title={tr('common_name')} value={local ? tr('server_local') : server?.name ?? '-'} />
        <SettingRow
          title={tr('settings_server_address')}
          value={local ? tr('server_local_meta') : server?.baseUrl.replace(/^https?:\/\//, '') ?? '-'}
        />
        <SettingRow
          title={tr('connect_method')}
          value={
            local
              ? tr('connect_method_local')
              : (server?.via ?? (isDeviceToken(http.getToken()) ? 'pairing' : 'password')) === 'pairing'
                ? tr('connect_method_device')
                : tr('connect_method_password')
          }
        />
        <SettingRow title={tr('settings_realtime')} value={tr(REALTIME_LABEL[realtimeStatus])} />
        <SettingRow title={tr('server_switch')} onPress={() => setServerSheet(true)} last />

        <GroupLabel style={styles.group}>{tr('settings_group_account')}</GroupLabel>
        <Pressable
          accessibilityRole="button"
          onPress={() => (confirmLogout ? logout() : setConfirmLogout(true))}
          style={({pressed}) => [styles.logout, pressed && styles.logoutPressed]}>
          <Text style={styles.logoutText}>{confirmLogout ? tr('settings_logout_confirm') : tr('settings_logout')}</Text>
        </Pressable>
        <Footnote>{tr('settings_logout_note')}</Footnote>
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
      <ServerSheet visible={serverSheet} onClose={() => setServerSheet(false)} />
      <ToastHost bottom={insets.bottom + 28} />
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  body: {paddingTop: 4},
  firstGroup: {marginTop: 8},
  group: {marginTop: 26},
  modes: {flexDirection: 'row', gap: 8, paddingHorizontal: 18},
  mode: {
    flex: 1,
    alignItems: 'center',
    gap: 8,
    paddingVertical: 14,
    borderRadius: radius.md,
    backgroundColor: t.bg1,
    borderWidth: 1,
    borderColor: t.line1,
  },
  modeActive: {backgroundColor: t.accentSoft, borderColor: t.accentLine},
  modeText: {fontSize: 13, color: t.t2},
  modeTextActive: {color: t.t1, fontWeight: '600'},
  logout: {
    marginHorizontal: 18,
    paddingVertical: 14,
    alignItems: 'center',
    borderRadius: radius.md,
    backgroundColor: t.dangerSoft,
  },
  logoutPressed: {opacity: 0.7},
  logoutText: {fontSize: 15, fontWeight: '500', color: t.danger},
}));
