import {faChevronRight, faEye, faEyeSlash, faQrcode} from '@fortawesome/free-solid-svg-icons';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useEffect, useMemo, useRef, useState} from 'react';
import {
  ActivityIndicator,
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
import {tr, trf} from '../i18n';
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
import {AvoidKeyboard} from '../components/AvoidKeyboard';

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
        <PageHeader title={tr('channel_title')} onBack={navigation.goBack} />
        <EmptyState
          loading={!data && !error}
          title={data ? tr('channel_gone') : tr('common_load_failed')}
          hint={data ? tr('channel_gone_hint') : error ?? undefined}
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
    showToast(downloading ? tr('channel_connected_downloading') : trf('channel_connected_named', {name: label}));
    navigation.replace('Channel', {name: params.name, instanceId: multiAgent && multiType ? instanceId : undefined});
  };

  const submit = async (action: 'connect' | 'save') => {
    if (action === 'connect' && missing.length) {
      setFormError(
        trf('channel_missing', {fields: missing.map(f => localized(f.label, f.key)).join(tr('channel_list_sep'))}),
      );
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
      showToast(tr('channel_saved_reconnect'));
    } catch (e) {
      const vars = {error: describeConnectError(e)};
      setFormError(trf(action === 'connect' ? 'channel_connect_failed' : 'common_save_failed_detail', vars));
    } finally {
      setBusy(null);
    }
  };

  const disconnect = async () => {
    try {
      await channelAction('disconnect', params.name, undefined, multiAgent ? target.instance_id || undefined : undefined);
      setSheet(null);
      await load();
      showToast(trf('channel_disconnected_named', {name: channelTitle(target)}));
      navigation.goBack();
    } catch (e) {
      setSheet(null);
      showToast(trf('channel_disconnect_failed', {error: describeConnectError(e)}));
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
    showToast(tr('channel_binding_updated'));
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
          {[hasMasked && !creating ? tr('channel_secret_keep') : '', help ?? ''].filter(Boolean).join('')}
        </Text>
      ) : null}
      {!!formError && <Text style={styles.formError}>{formError}</Text>}
      <ActionButton
        label={creating ? tr('channel_connect') : tr('common_save')}
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
      <Text style={styles.scanTitle}>
        {creating ? tr('channel_feishu_scan_create') : tr('channel_feishu_scan_replace')}
      </Text>
      <Text style={styles.scanText}>
        {creating ? tr('channel_feishu_scan_create_desc') : tr('channel_feishu_scan_replace_desc')}
      </Text>
      <ActionButton
        label={tr('channel_feishu_scan_btn')}
        tone="primary"
        onPress={() => setFeishuScanning(true)}
        style={styles.scanButton}
      />
    </View>
  );

  return (
    <View style={styles.root}>
      <PageHeader
        title={creating ? trf('channel_add_named', {name: label}) : channelTitle(target)}
        onBack={navigation.goBack}
      />
      <AvoidKeyboard style={styles.flex}>
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
                  {CHANNEL_BLURB[params.name] ?? tr('channel_fill_credentials')}
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
              <InfoRow
                first
                title={tr('common_name')}
                value={target.instance_name || tr('common_untitled')}
                onPress={() => setSheet('rename')}
              />
              <InfoRow
                title={tr('channel_who_replies')}
                value={bindingSummary(target, nameOf)}
                onPress={() => setSheet('agents')}
              />
              <InfoRow title={tr('channel_id')} value={target.instance_id ?? ''} mono />
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
              <Text style={styles.startingText}>{tr('channel_starting_hint')}</Text>
            </View>
          )}
          {isWeixin && !creating && pending === 'none' && (
            <Text style={styles.help}>{tr('channel_weixin_logged_in')}</Text>
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
                    {key: 'scan', label: tr('channel_mode_scan')},
                    {key: 'manual', label: tr('channel_mode_manual')},
                  ]}
                />
              </View>
              {mode === 'scan' ? feishuScan : form}
            </View>
          ) : (
            !!fields.length && (
              <View style={styles.section}>
                {!creating && <Text style={styles.sectionTitle}>{tr('channel_config')}</Text>}
                {form}
              </View>
            )
          )}

          {!creating && (
            <ActionButton
              label={tr('channel_disconnect')}
              tone="danger"
              onPress={() => setSheet('disconnect')}
              style={styles.disconnect}
            />
          )}
        </ScrollView>
      </AvoidKeyboard>

      <FieldSheet
        visible={sheet === 'rename'}
        title={tr('channel_name')}
        initial={target.instance_name ?? ''}
        placeholder={trf('channel_name_placeholder', {name: label})}
        hint={tr('channel_name_hint')}
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
        title={trf('channel_disconnect_named', {name: channelTitle(target)})}
        message={isInstance ? tr('channel_disconnect_instance_msg') : tr('channel_disconnect_msg')}
        confirmLabel={tr('channel_disconnect_short')}
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
      : trf('channel_field_placeholder', {label});
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
            accessibilityLabel={revealed ? tr('channel_hide') : tr('channel_show')}
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
      accessibilityLabel={trf('channel_a11y_pair', {title, value})}
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
  sectionTitle: {fontSize: 16, fontWeight: '600', letterSpacing: -0.2, color: t.t1, paddingHorizontal: 18, marginBottom: 10},
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
