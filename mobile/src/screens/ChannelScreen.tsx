import {faChevronRight, faEye, faEyeSlash, faQrcode} from '@fortawesome/free-solid-svg-icons';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useEffect, useMemo, useRef, useState} from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {bindChannelInstance, channelAction, renameChannelInstance} from '../api/cowApi';
import {ChannelAgentsSheet} from '../components/ChannelAgentsSheet';
import {ChannelIcon} from '../components/ChannelIcon';
import {Icon} from '../components/Icon';
import {QrLoginPanel, type QrConnected} from '../components/QrLoginPanel';
import {ActionButton, ConfirmSheet, FieldSheet, MONO, Toggle} from '../components/settings';
import {showToast, ToastHost} from '../components/Toast';
import {EmptyState, PageHeader, Segmented} from '../components/ui';
import type {RootStackParamList} from '../navigation/types';
import type {ChannelField, ChannelInfo, ChannelsResponse} from '../protocol/resources';
import {useAgentStore} from '../store/agentStore';
import {useChannelStore} from '../store/channelStore';
import {describeConnectError} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {
  bindingSummary,
  blankChannel,
  buildChannelConfig,
  CHANNEL_BLURB,
  CHANNEL_HELP,
  changedFields,
  channelLabel,
  channelPending,
  channelStatusLabel,
  channelTitle,
  initialValues,
  isMaskedSecret,
  isMultiInstance,
  localized,
  missingFields,
} from '../utils/channels';

type Props = StackScreenProps<RootStackParamList, 'Channel'>;
type Params = RootStackParamList['Channel'];
type OpenSheet = 'rename' | 'agents' | 'disconnect' | null;

const SETTLE_POLL_MS = 3000;

/** The card this page is about. Adding a bot of a multi-instance type always starts blank. */
function resolve(data: ChannelsResponse, {name, instanceId, add}: Params): ChannelInfo | undefined {
  const base = data.channels.find(c => c.name === name);
  if (add && base && isMultiInstance(data, name)) {
    return blankChannel(base);
  }
  if (instanceId) {
    return data.instances?.find(c => c.instance_id === instanceId);
  }
  return base;
}

export function ChannelScreen({navigation, route}: Props) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const params = route.params;
  const data = useChannelStore(s => s.data);
  const error = useChannelStore(s => s.error);
  const load = useChannelStore(s => s.load);
  const agents = useAgentStore(s => s.agents);

  const target = useMemo(() => (data ? resolve(data, params) : undefined), [data, params]);
  const multiAgent = !!data?.multi_agent;
  const multiType = !!data && isMultiInstance(data, params.name);
  const creating = !!target && (!target.active || (!!params.add && multiType));
  const fields = useMemo(() => target?.fields ?? [], [target]);
  const isInstance = multiAgent && !!target?.instance_id;
  const pending = target ? channelPending(target) : 'none';
  const label = target ? channelLabel(target) : '';

  // Empty creates a new bot, a real id edits that one, undefined takes the per-type path.
  const instanceArg = !multiAgent ? undefined : creating && multiType ? '' : target?.instance_id || undefined;
  const newInstance = multiAgent && (creating && multiType ? true : !target?.instance_id);

  const [values, setValues] = useState<Record<string, string>>({});
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});
  const [mode, setMode] = useState<'scan' | 'manual'>('scan');
  const [feishuScanning, setFeishuScanning] = useState(false);
  const [busy, setBusy] = useState<'connect' | 'save' | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [sheet, setSheet] = useState<OpenSheet>(null);
  const seeded = useRef<string | null>(null);

  useEffect(() => {
    if (!data) {
      load();
    }
  }, [data, load]);

  // Seed the form once per card, so a background refresh never wipes what is being typed.
  useEffect(() => {
    const key = target ? `${target.instance_id ?? target.name}:${creating}` : null;
    if (!target || seeded.current === key) {
      return;
    }
    seeded.current = key;
    setValues(initialValues(target.fields ?? []));
    setMode((target.fields ?? []).some(f => f.type !== 'bool' && !!f.value) ? 'manual' : 'scan');
  }, [target, creating]);

  useEffect(() => {
    if (pending === 'none') {
      return;
    }
    const timer = setInterval(load, SETTLE_POLL_MS);
    return () => clearInterval(timer);
  }, [pending, load]);

  if (!data || !target) {
    return (
      <View style={styles.root}>
        <PageHeader title="通道" onBack={navigation.goBack} />
        <EmptyState
          loading={!data && !error}
          title={data ? '这个通道已经断开' : '加载失败'}
          hint={data ? '回到通道列表重新接入' : error ?? undefined}
        />
      </View>
    );
  }

  const nameOf = (id: string) => agents.find(a => a.id === id)?.name;
  const isWeixin = params.name === 'weixin';
  const isFeishu = params.name === 'feishu';
  const missing = missingFields(fields, values);
  const dirty = changedFields(fields, values);
  const hasMasked = fields.some(isMaskedSecret);
  const help = CHANNEL_HELP[params.name];

  const connected = async ({instanceId, downloading}: QrConnected) => {
    await load();
    showToast(downloading ? '已接入，首次启用要下载飞书组件，连上可能稍慢' : `${label}已接入`);
    navigation.replace('Channel', {name: params.name, instanceId: multiAgent && multiType ? instanceId : undefined});
  };

  const submit = async (action: 'connect' | 'save') => {
    if (action === 'connect' && missing.length) {
      setFormError(`还没填 ${missing.map(f => localized(f.label, f.key)).join('、')}`);
      return;
    }
    setBusy(action);
    setFormError(null);
    try {
      const res = await channelAction(action, params.name, buildChannelConfig(fields, values), instanceArg);
      if (action === 'connect') {
        await connected({instanceId: res.instance_id, downloading: res.downloading});
        return;
      }
      await load();
      const fresh = useChannelStore.getState().data;
      const updated = fresh ? resolve(fresh, params) : undefined;
      setValues(initialValues(updated?.fields ?? fields));
      showToast('已保存，通道会用新配置重新连接');
    } catch (e) {
      setFormError(`${action === 'connect' ? '连接' : '保存'}失败：${describeConnectError(e)}`);
    } finally {
      setBusy(null);
    }
  };

  const disconnect = async () => {
    try {
      await channelAction('disconnect', params.name, undefined, multiAgent ? target.instance_id || undefined : undefined);
      setSheet(null);
      await load();
      showToast(`已断开${channelTitle(target)}`);
      navigation.goBack();
    } catch (e) {
      setSheet(null);
      showToast(`断开失败：${describeConnectError(e)}`);
    }
  };

  const rename = async (name: string) => {
    if (!target.instance_id || name === (target.instance_name ?? '')) {
      return;
    }
    try {
      await renameChannelInstance(params.name, target.instance_id, name);
    } catch (e) {
      throw new Error(describeConnectError(e));
    }
    await load();
  };

  const bind = async (ids: string[]) => {
    try {
      await bindChannelInstance(target.channel_type || params.name, target.instance_id ?? '', ids[0] ?? '', ids.slice(1));
    } catch (e) {
      throw new Error(describeConnectError(e));
    }
    setSheet(null);
    await Promise.all([load(), useAgentStore.getState().load().catch(() => undefined)]);
    showToast('已更新，下一条消息起生效');
  };

  const form = (
    <>
      <View style={styles.group}>
        {fields.map((f, i) => (
          <FieldRow
            key={f.key}
            field={f}
            first={i === 0}
            value={values[f.key] ?? ''}
            revealed={!!revealed[f.key]}
            onReveal={() => setRevealed(r => ({...r, [f.key]: !r[f.key]}))}
            onChange={v => {
              setValues(prev => ({...prev, [f.key]: v}));
              setFormError(null);
            }}
          />
        ))}
      </View>
      {(hasMasked && !creating) || help ? (
        <Text style={styles.help}>
          {[hasMasked && !creating ? '密钥留空表示不修改。' : '', help ?? ''].filter(Boolean).join('')}
        </Text>
      ) : null}
      {!!formError && <Text style={styles.formError}>{formError}</Text>}
      <ActionButton
        label={creating ? '连接' : '保存'}
        tone="primary"
        loading={!!busy}
        disabled={creating ? false : !dirty}
        onPress={() => submit(creating ? 'connect' : 'save')}
        style={styles.submit}
      />
    </>
  );

  const feishuScan = feishuScanning ? (
    <View style={styles.qrWrap}>
      <QrLoginPanel provider="feishu" instanceId={target.instance_id} newInstance={newInstance} onConnected={connected} />
    </View>
  ) : (
    <View style={styles.scanIntro}>
      <View style={styles.scanIcon}>
        <Icon icon={faQrcode} size={22} color={t.accent} />
      </View>
      <Text style={styles.scanTitle}>{creating ? '扫码就能创建好机器人' : '扫码换一个新机器人'}</Text>
      <Text style={styles.scanText}>
        {creating
          ? '用飞书 App 扫码授权，自动创建应用，权限和事件订阅都会配好，不用去开放平台手动设置。'
          : '扫码会创建一个新的飞书机器人，并替换当前的 App ID 和 App Secret。'}
      </Text>
      <ActionButton label="一键创建飞书应用" tone="primary" onPress={() => setFeishuScanning(true)} style={styles.scanButton} />
    </View>
  );

  return (
    <View style={styles.root}>
      <PageHeader title={creating ? `接入${label}` : channelTitle(target)} onBack={navigation.goBack} />
      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView
          contentContainerStyle={[styles.body, {paddingBottom: insets.bottom + 32}]}
          keyboardShouldPersistTaps="handled">
          <View style={styles.identity}>
            <ChannelIcon name={params.name} size={46} />
            <View style={styles.flex}>
              <Text style={styles.identityName} numberOfLines={1}>
                {label}
              </Text>
              {creating ? (
                <Text style={styles.identityMeta} numberOfLines={2}>
                  {CHANNEL_BLURB[params.name] ?? '填写凭证后连接'}
                </Text>
              ) : (
                <View style={styles.statusLine}>
                  <View style={[styles.dot, pending === 'none' ? styles.dotOn : styles.dotPending]} />
                  <Text style={[styles.statusText, pending !== 'none' && styles.pendingText]}>{channelStatusLabel(target)}</Text>
                </View>
              )}
            </View>
          </View>

          {isInstance && !creating && (
            <View style={[styles.group, styles.section]}>
              <InfoRow first title="名称" value={target.instance_name || '未命名'} onPress={() => setSheet('rename')} />
              <InfoRow title="谁来回复" value={bindingSummary(target, nameOf)} onPress={() => setSheet('agents')} />
              <InfoRow title="通道 ID" value={target.instance_id ?? ''} mono />
            </View>
          )}

          {isWeixin && (creating || pending === 'scanning') && (
            <View style={[styles.section, styles.qrWrap]}>
              <QrLoginPanel provider="weixin" instanceId={target.instance_id} newInstance={newInstance} onConnected={connected} />
            </View>
          )}
          {isWeixin && !creating && pending === 'starting' && (
            <View style={[styles.group, styles.section, styles.starting]}>
              <ActivityIndicator size="small" color={t.t3} />
              <Text style={styles.startingText}>正在启动，通常几秒就好</Text>
            </View>
          )}
          {isWeixin && !creating && pending === 'none' && (
            <Text style={styles.help}>微信已登录。退出登录或换号，先断开再重新接入。</Text>
          )}

          {isFeishu ? (
            <View style={styles.section}>
              <View style={styles.segmentWrap}>
                <Segmented
                  value={mode}
                  onChange={m => {
                    setMode(m);
                    if (m === 'manual') {
                      setFeishuScanning(false);
                    }
                  }}
                  options={[
                    {key: 'scan', label: '扫码创建'},
                    {key: 'manual', label: '手动填写'},
                  ]}
                />
              </View>
              {mode === 'scan' ? feishuScan : form}
            </View>
          ) : (
            !!fields.length && (
              <View style={styles.section}>
                {!creating && <Text style={styles.sectionTitle}>连接配置</Text>}
                {form}
              </View>
            )
          )}

          {!creating && (
            <ActionButton label="断开连接" tone="danger" onPress={() => setSheet('disconnect')} style={styles.disconnect} />
          )}
        </ScrollView>
      </KeyboardAvoidingView>

      <FieldSheet
        visible={sheet === 'rename'}
        title="通道名称"
        initial={target.instance_name ?? ''}
        placeholder={`如「${label}2」`}
        hint="只用于区分同类型的多个机器人，不影响连接"
        onSubmit={rename}
        onClose={() => setSheet(null)}
      />
      <ChannelAgentsSheet
        visible={sheet === 'agents'}
        initial={[target.agent_id, ...(target.members ?? [])].filter((id): id is string => !!id)}
        onSave={bind}
        onClose={() => setSheet(null)}
      />
      <ConfirmSheet
        visible={sheet === 'disconnect'}
        title={`断开${channelTitle(target)}`}
        message={
          isInstance
            ? '这个机器人会停止接收消息，它的配置也会一起移除，之后要用需重新接入。'
            : '通道会停止接收消息。凭证会保留，之后可以随时重新连接。'
        }
        confirmLabel="断开"
        danger
        onConfirm={disconnect}
        onClose={() => setSheet(null)}
      />
      <ToastHost bottom={insets.bottom + 28} />
    </View>
  );
}

function FieldRow({
  field,
  first,
  value,
  revealed,
  onReveal,
  onChange,
}: {
  field: ChannelField;
  first: boolean;
  value: string;
  revealed: boolean;
  onReveal: () => void;
  onChange: (value: string) => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  const label = localized(field.label, field.key);
  if (field.type === 'bool') {
    return (
      <View style={[styles.fieldRow, styles.boolRow, !first && styles.divider]}>
        <Text style={[styles.fieldLabel, styles.flex]}>{label}</Text>
        <Toggle value={value === 'true'} onValueChange={v => onChange(String(v))} label={label} />
      </View>
    );
  }
  const secret = field.type === 'secret';
  const placeholder = isMaskedSecret(field)
    ? String(field.value)
    : field.default !== undefined && field.default !== ''
      ? String(field.default)
      : `填写 ${label}`;
  return (
    <View style={[styles.fieldRow, !first && styles.divider]}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <View style={styles.inputLine}>
        <TextInput
          value={value}
          onChangeText={onChange}
          placeholder={placeholder}
          placeholderTextColor={t.t4}
          selectionColor={t.accent}
          cursorColor={t.accent}
          secureTextEntry={secret && !revealed}
          keyboardType={field.type === 'number' ? 'number-pad' : 'default'}
          autoCapitalize="none"
          autoCorrect={false}
          spellCheck={false}
          accessibilityLabel={label}
          style={styles.input}
        />
        {secret && (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={revealed ? '隐藏' : '显示'}
            hitSlop={10}
            onPress={onReveal}
            style={styles.eye}>
            <Icon icon={revealed ? faEyeSlash : faEye} size={14} color={t.t3} />
          </Pressable>
        )}
      </View>
    </View>
  );
}

function InfoRow({
  title,
  value,
  first,
  mono,
  onPress,
}: {
  title: string;
  value: string;
  first?: boolean;
  mono?: boolean;
  onPress?: () => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  const body = (
    <>
      <Text style={styles.infoTitle}>{title}</Text>
      <Text style={[styles.infoValue, mono && styles.mono]} numberOfLines={1} selectable={!onPress}>
        {value}
      </Text>
      {!!onPress && <Icon icon={faChevronRight} size={10} color={t.t4} />}
    </>
  );
  if (!onPress) {
    return <View style={[styles.infoRow, !first && styles.divider]}>{body}</View>;
  }
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${title}，${value}`}
      onPress={onPress}
      style={({pressed}) => [styles.infoRow, !first && styles.divider, pressed && styles.pressed]}>
      {body}
    </Pressable>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  flex: {flex: 1, minWidth: 0},
  body: {paddingTop: 6, flexGrow: 1},
  identity: {flexDirection: 'row', alignItems: 'center', gap: 14, paddingHorizontal: 18, paddingTop: 6, paddingBottom: 4},
  identityName: {fontSize: 17, fontWeight: '600', color: t.t1, letterSpacing: -0.3},
  identityMeta: {fontSize: 13, lineHeight: 19, color: t.t3, marginTop: 3},
  statusLine: {flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 5},
  dot: {width: 6, height: 6, borderRadius: 3},
  dotOn: {backgroundColor: t.accent},
  dotPending: {backgroundColor: t.kind.image[1]},
  statusText: {fontSize: 13, color: t.accent},
  pendingText: {color: t.kind.image[1]},
  section: {marginTop: 20},
  sectionTitle: {fontSize: 12, fontWeight: '600', letterSpacing: 0.6, color: t.t3, paddingHorizontal: 18, marginBottom: 10},
  segmentWrap: {marginBottom: 8},
  qrWrap: {marginHorizontal: 14},
  group: {
    marginHorizontal: 14,
    borderRadius: radius.md,
    backgroundColor: t.bg1,
    borderWidth: 1,
    borderColor: t.line1,
    overflow: 'hidden',
  },
  divider: {borderTopWidth: 1, borderTopColor: t.line1},
  pressed: {backgroundColor: t.bg2},
  fieldRow: {paddingHorizontal: 14, paddingTop: 11, paddingBottom: 4},
  boolRow: {flexDirection: 'row', alignItems: 'center', paddingBottom: 11},
  fieldLabel: {fontSize: 12, color: t.t3},
  inputLine: {flexDirection: 'row', alignItems: 'center', gap: 10},
  input: {
    flex: 1,
    minHeight: 38,
    paddingVertical: 8,
    paddingHorizontal: 0,
    fontFamily: MONO,
    fontSize: 14,
    color: t.t1,
  },
  eye: {paddingVertical: 8},
  help: {fontSize: 12, lineHeight: 18, color: t.t4, paddingHorizontal: 18, paddingTop: 10},
  formError: {fontSize: 13, lineHeight: 19, color: t.danger, paddingHorizontal: 18, paddingTop: 10},
  submit: {marginHorizontal: 14, marginTop: 16},
  infoRow: {flexDirection: 'row', alignItems: 'center', gap: 10, minHeight: 50, paddingHorizontal: 14, paddingVertical: 12},
  infoTitle: {fontSize: 15, color: t.t1},
  infoValue: {flex: 1, fontSize: 14, color: t.t3, textAlign: 'right'},
  mono: {fontFamily: MONO, fontSize: 12.5},
  starting: {flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 14, paddingVertical: 14},
  startingText: {fontSize: 13, color: t.t2},
  scanIntro: {
    alignItems: 'center',
    marginHorizontal: 14,
    paddingHorizontal: 22,
    paddingTop: 26,
    paddingBottom: 20,
    borderRadius: radius.md,
    backgroundColor: t.bg1,
    borderWidth: 1,
    borderColor: t.line1,
  },
  scanIcon: {
    width: 52,
    height: 52,
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: t.accentSoft,
  },
  scanTitle: {fontSize: 16, fontWeight: '600', color: t.t1, marginTop: 14, letterSpacing: -0.2},
  scanText: {fontSize: 13, lineHeight: 20, color: t.t3, marginTop: 6, textAlign: 'center'},
  scanButton: {alignSelf: 'stretch', marginTop: 18},
  disconnect: {marginHorizontal: 14, marginTop: 32},
}));
