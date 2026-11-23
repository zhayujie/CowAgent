import {
  faArrowsRotate,
  faBars,
  faChevronRight,
  faCircleHalfStroke,
  faCode,
  faCommentDots,
  faGaugeHigh,
  faGlobe,
  faKey,
  faLanguage,
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
import {PERMISSION_META} from '../components/ComposerSheets';
import {Icon} from '../components/Icon';
import {hostOf, useLinkColor} from '../components/ServerPicker';
import {tr, trf, useLangStore, type Lang, type MessageKey} from '../i18n';
import {useLocalDeviceName} from '../kernel/localKernel';
import {CardLabel, ChoiceSheet, FieldSheet, SettingCard, SettingRow} from '../components/settings';
import {showToast, ToastHost} from '../components/Toast';
import {PageHeader} from '../components/ui';
import {openWebPage} from '../navigation/openWeb';
import type {RootStackParamList} from '../navigation/types';
import type {PermissionMode} from '../protocol/resources';
import {useConfigStore} from '../store/configStore';
import {
  activeServer,
  changingPassword,
  describeConnectError,
  useLocalServer,
  useServerStore,
} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, usePrefsStore, useTheme, type ThemeMode} from '../theme/theme';
import {useAgentVersion} from '../update/useAgentVersion';
import {PASSWORD_MIN_LENGTH, PASSWORD_STRENGTH_TEXT, passwordStrength} from '../utils/passwordStrength';

type Props = StackScreenProps<RootStackParamList, 'Settings'>;

const MODES: {key: ThemeMode; label: MessageKey}[] = [
  {key: 'system', label: 'settings_theme_system'},
  {key: 'light', label: 'settings_theme_light'},
  {key: 'dark', label: 'settings_theme_dark'},
];

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
  const relogin = useServerStore(s => s.relogin);
  const version = useAgentVersion();
  const config = useConfigStore(s => s.config);
  const externalApi = useConfigStore(s => s.externalApi);
  const loadConfig = useConfigStore(s => s.load);
  const updateConfig = useConfigStore(s => s.update);
  const server = activeServer();
  const local = useLocalServer();
  const [sheet, setSheet] = useState<'permission' | 'password' | 'theme' | 'lang' | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const localName = useLocalDeviceName();
  const linkColor = useLinkColor();

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
    setSheet(null);
    if (next === lang) {
      return;
    }
    setLang(next);
    // Agent replies, logs and the CLI follow the server's cow_lang; best effort like the desktop client.
    updateConfig({cow_lang: next}).catch(() => undefined);
  };

  const serverName = local ? localName : server?.name ?? '-';
  const serverMeta = local ? tr('server_local_meta') : server ? hostOf(server.baseUrl) : '-';

  const loading = !config;
  return (
    <View style={styles.root}>
      <PageHeader title={tr('settings_title')} onBack={navigation.goBack} background={t.grouped} />
      <ScrollView
        contentContainerStyle={[styles.body, {paddingBottom: insets.bottom + 32}]}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={t.t3} colors={[t.green]} />}>
        <SettingCard>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={trf('settings_connection_a11y', {name: serverName, meta: serverMeta})}
            onPress={() => navigation.navigate('Devices')}
            style={({pressed}) => [styles.server, pressed && styles.pressed]}>
            <View style={styles.serverIcon}>
              <Icon icon={local ? faMobileScreen : faServer} size={16} color={t.accent} />
            </View>
            <View style={styles.serverText}>
              <Text style={styles.serverName} numberOfLines={1}>
                {serverName}
              </Text>
              <View style={styles.serverMetaRow}>
                <View style={[styles.dot, {backgroundColor: linkColor}]} />
                <Text style={styles.serverMeta} numberOfLines={1}>
                  {serverMeta}
                </Text>
              </View>
            </View>
            <Icon icon={faChevronRight} size={10} color={t.t4} />
          </Pressable>
        </SettingCard>

        <CardLabel>{tr('settings_group_agent')}</CardLabel>
        <SettingCard>
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
          <>
            <CardLabel>{tr('settings_group_access')}</CardLabel>
            <SettingCard>
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
              <SettingRow
                icon={faKey}
                title={tr('settings_access_password')}
                value={config ? (config.web_password_masked ? tr('common_configured') : tr('common_not_set')) : '…'}
                onPress={config ? () => setSheet('password') : undefined}
                last
              />
            </SettingCard>
          </>
        )}

        <CardLabel>{tr('settings_group_display')}</CardLabel>
        <SettingCard>
          <SettingRow
            icon={faCircleHalfStroke}
            title={tr('settings_theme')}
            value={tr(MODES.find(m => m.key === mode)?.label ?? 'settings_theme_system')}
            onPress={() => setSheet('theme')}
          />
          <SettingRow
            icon={faLanguage}
            title={tr('settings_language')}
            value={LANGS.find(l => l.key === lang)?.label}
            onPress={() => setSheet('lang')}
          />
          <SettingRow icon={faBars} title={tr('settings_menu')} onPress={() => navigation.navigate('MenuEditor')} last />
        </SettingCard>

        <CardLabel>{tr('settings_group_other')}</CardLabel>
        <SettingCard>
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
      <ChoiceSheet
        visible={sheet === 'theme'}
        title={tr('settings_theme')}
        options={MODES.map(m => ({key: m.key, label: tr(m.label)}))}
        selected={mode}
        onSelect={next => {
          setSheet(null);
          setMode(next);
        }}
        onClose={() => setSheet(null)}
      />
      <ChoiceSheet
        visible={sheet === 'lang'}
        title={tr('settings_language')}
        options={LANGS.map(l => ({key: l.key, label: l.label}))}
        selected={lang}
        onSelect={changeLanguage}
        onClose={() => setSheet(null)}
      />
      <ToastHost bottom={insets.bottom + 28} />
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.grouped},
  body: {paddingTop: 8},
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
  serverName: {fontSize: 17, fontWeight: '600', color: t.t1, letterSpacing: -0.3},
  serverMetaRow: {flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 5},
  serverMeta: {flexShrink: 1, fontSize: 13, color: t.t3},
  dot: {width: 7, height: 7, borderRadius: 4},
}));
