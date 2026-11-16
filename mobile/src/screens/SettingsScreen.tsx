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
import {PERMISSION_META} from '../components/ComposerSheets';
import {Icon} from '../components/Icon';
import {ChoiceSheet, FieldSheet, Footnote, SettingRow} from '../components/settings';
import {showToast, ToastHost} from '../components/Toast';
import {GroupLabel, PageHeader} from '../components/ui';
import type {RootStackParamList} from '../navigation/types';
import type {PermissionMode} from '../protocol/resources';
import {useConfigStore} from '../store/configStore';
import {useOverviewStore} from '../store/overviewStore';
import {activeServer, changingPassword, describeConnectError, useServerStore} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, usePrefsStore, useTheme, type ThemeMode} from '../theme/theme';
import {PASSWORD_MIN_LENGTH, PASSWORD_STRENGTH_TEXT, passwordStrength} from '../utils/passwordStrength';

type Props = StackScreenProps<RootStackParamList, 'Settings'>;

const MODES: {key: ThemeMode; label: string; icon: typeof faSun}[] = [
  {key: 'system', label: '跟随系统', icon: faCircleHalfStroke},
  {key: 'light', label: '浅色', icon: faSun},
  {key: 'dark', label: '深色', icon: faMoon},
];

const REALTIME_LABEL = {
  idle: '未启用，使用 SSE',
  connecting: '连接中',
  open: '已连接',
  closed: '已断开，等待重连',
  revoked: '设备已被撤销',
} as const;

const PERMISSION_ORDER = Object.keys(PERMISSION_META) as PermissionMode[];

export function SettingsScreen({navigation}: Props) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const mode = usePrefsStore(s => s.mode);
  const setMode = usePrefsStore(s => s.setMode);
  const realtimeStatus = useServerStore(s => s.realtimeStatus);
  const logout = useServerStore(s => s.logout);
  const relogin = useServerStore(s => s.relogin);
  const version = useOverviewStore(s => s.version);
  const config = useConfigStore(s => s.config);
  const externalApi = useConfigStore(s => s.externalApi);
  const loadConfig = useConfigStore(s => s.load);
  const updateConfig = useConfigStore(s => s.update);
  const server = activeServer();
  const [confirmLogout, setConfirmLogout] = useState(false);
  const [sheet, setSheet] = useState<'permission' | 'password' | null>(null);
  const [refreshing, setRefreshing] = useState(false);

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
      showToast(`新会话默认：${PERMISSION_META[next].name}`);
    } catch (e) {
      showToast(`保存失败：${describeConnectError(e)}`);
    }
  };

  const changePassword = async (value: string) => {
    if (passwordStrength(value) === 'short') {
      throw new Error(`密码至少 ${PASSWORD_MIN_LENGTH} 位`);
    }
    await changingPassword(
      (async () => {
        const res = await updateConfig({web_password: value});
        await relogin(value, res.auth_token);
      })(),
    );
    showToast('访问密码已更新，其他设备需要用新密码重新登录');
  };

  const loading = !config;
  return (
    <View style={styles.root}>
      <PageHeader title="设置" onBack={navigation.goBack} />
      <ScrollView
        contentContainerStyle={[styles.body, {paddingBottom: insets.bottom + 32}]}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={t.t3} colors={[t.green]} />}>
        <GroupLabel style={styles.firstGroup}>常用</GroupLabel>
        <SettingRow
          icon={faMicrochip}
          title="模型与接口"
          value={config?.model || (loading ? '…' : '未配置')}
          onPress={() => navigation.navigate('Models')}
        />
        <SettingRow
          icon={faGaugeHigh}
          title="Agent 运行"
          value={config ? `${config.agent_max_steps} 步 · ${config.agent_max_context_turns} 轮` : '…'}
          onPress={() => navigation.navigate('Runtime')}
        />
        <SettingRow icon={faPlug} title="MCP 服务" onPress={() => navigation.navigate('Mcp')} />
        <SettingRow icon={faBars} title="菜单" last onPress={() => navigation.navigate('MenuEditor')} />

        <GroupLabel style={styles.group}>对外访问</GroupLabel>
        <SettingRow icon={faGlobe} title="访问地址" onPress={() => navigation.navigate('Access')} />
        <SettingRow icon={faShareNodes} title="访客页面" onPress={() => navigation.navigate('GuestShares')} />
        <SettingRow
          icon={faCode}
          title="开放对话 API"
          value={externalApi ? (externalApi.enabled ? '已开启' : '未开启') : '…'}
          onPress={() => navigation.navigate('ExternalApi')}
          last
        />

        <GroupLabel style={styles.group}>外观</GroupLabel>
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
                <Text style={[styles.modeText, active && styles.modeTextActive]}>{m.label}</Text>
              </Pressable>
            );
          })}
        </View>

        <GroupLabel style={styles.group}>安全</GroupLabel>
        <SettingRow
          icon={faShieldHalved}
          title="默认权限"
          value={permission ? PERMISSION_META[permission]?.name ?? permission : '…'}
          onPress={config ? () => setSheet('permission') : undefined}
        />
        <SettingRow
          icon={faKey}
          title="访问密码"
          value={config ? (config.web_password_masked ? '已设置' : '未设置') : '…'}
          onPress={config ? () => setSheet('password') : undefined}
          last
        />
        <Footnote>新会话默认使用该权限，单个会话可在输入框下方单独调整。</Footnote>

        <GroupLabel style={styles.group}>系统</GroupLabel>
        <SettingRow icon={faTerminal} title="日志" onPress={() => navigation.navigate('Logs')} />
        <SettingRow
          icon={faArrowsRotate}
          title="版本更新"
          value={version ? `v${version}` : undefined}
          onPress={() => navigation.navigate('Version')}
          last
        />

        <GroupLabel style={styles.group}>服务器</GroupLabel>
        <SettingRow title="名称" value={server?.name ?? '-'} />
        <SettingRow title="地址" value={server?.baseUrl.replace(/^https?:\/\//, '') ?? '-'} />
        <SettingRow title="实时通道" value={REALTIME_LABEL[realtimeStatus]} last />

        <GroupLabel style={styles.group}>账号</GroupLabel>
        <Pressable
          accessibilityRole="button"
          onPress={() => (confirmLogout ? logout() : setConfirmLogout(true))}
          style={({pressed}) => [styles.logout, pressed && styles.logoutPressed]}>
          <Text style={styles.logoutText}>{confirmLogout ? '再点一次，退出登录' : '退出登录'}</Text>
        </Pressable>
        <Footnote>退出后这台设备不再保存访问凭证，下次需要重新输入访问密码。</Footnote>
      </ScrollView>

      <ChoiceSheet
        visible={sheet === 'permission'}
        title="新会话默认权限"
        options={PERMISSION_ORDER.filter(m => !config || config.permission_modes.includes(m)).map(m => ({
          key: m,
          label: PERMISSION_META[m].name,
          desc: PERMISSION_META[m].desc,
          icon: PERMISSION_META[m].icon,
        }))}
        selected={permission}
        note="已单独设置过权限的会话不受影响。"
        onSelect={pickPermission}
        onClose={() => setSheet(null)}
      />
      <FieldSheet
        visible={sheet === 'password'}
        title="修改访问密码"
        placeholder="输入新密码"
        secure
        allowEmpty={false}
        hint={`至少 ${PASSWORD_MIN_LENGTH} 位。改完后网页控制台和其他设备都需要用新密码重新登录，这台手机会自动保持登录。手机端连接要求服务端保留访问密码，这里不能清空。`}
        describe={v => {
          const s = passwordStrength(v);
          return {text: PASSWORD_STRENGTH_TEXT[s], tone: s === 'strong' ? 'ok' : s === 'medium' ? 'warn' : 'danger'};
        }}
        onSubmit={changePassword}
        onClose={() => setSheet(null)}
      />
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
