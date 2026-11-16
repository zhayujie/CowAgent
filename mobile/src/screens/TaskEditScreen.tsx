import {faCheck, faPlay, faRotateRight} from '@fortawesome/free-solid-svg-icons';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useEffect, useMemo, useState} from 'react';
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
import {
  createScheduledTask,
  deleteScheduledTask,
  getTaskInstances,
  getTaskRecipients,
  runTaskNow,
  type TaskDraft,
  updateScheduledTask,
} from '../api/cowApi';
import {Icon} from '../components/Icon';
import {ActionButton, ChoiceSheet, ConfirmSheet, MONO, SettingRow, Toggle} from '../components/settings';
import {Sheet} from '../components/Sheet';
import {showToast, ToastHost} from '../components/Toast';
import {PageHeader} from '../components/ui';
import {WheelColumn, WheelGroup} from '../components/WheelPicker';
import {tr, trf, type MessageKey} from '../i18n';
import type {RootStackParamList} from '../navigation/types';
import type {ScheduleType, TaskAction, TaskActionType, TaskInstance, TaskRecipient, TaskSchedule} from '../protocol/resources';
import {describeConnectError} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {dateVars, daysAgo, fullTime, pad, startOfDay, toDate} from '../utils/format';

type Props = StackScreenProps<RootStackParamList, 'TaskEdit'>;
type OpenSheet = 'schedule' | 'action' | 'instance' | 'recipient' | 'once' | 'delete' | 'run' | null;

const WEEKDAY: MessageKey[] = [
  'task_weekday_0',
  'task_weekday_1',
  'task_weekday_2',
  'task_weekday_3',
  'task_weekday_4',
  'task_weekday_5',
  'task_weekday_6',
];
const HOUR_ITEMS = Array.from({length: 24}, (_, i) => pad(i));
const MINUTE_ITEMS = Array.from({length: 60}, (_, i) => pad(i));
const DAYS_AHEAD = 366;
const DAY_MS = 86_400_000;

const startOfToday = () => new Date(startOfDay(new Date()));

function addDays(d: Date, n: number): Date {
  const next = new Date(d);
  next.setDate(next.getDate() + n);
  return next;
}

function formatOnce(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function defaultOnce(): Date {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  d.setHours(9, 0, 0, 0);
  return d;
}

function parseOnce(value: string): Date {
  return toDate(value) ?? defaultOnce();
}

function dayLabel(d: Date, today: Date): string {
  const ahead = -daysAgo(d, today);
  if (ahead === 0) {
    return tr('common_today');
  }
  if (ahead === 1) {
    return tr('common_tomorrow');
  }
  const vars = {...dateVars(d), weekday: tr(WEEKDAY[d.getDay()])};
  return trf(d.getFullYear() === today.getFullYear() ? 'task_once_day' : 'task_once_day_year', vars);
}

const schedTypes = (): {key: ScheduleType; label: string}[] => [
  {key: 'cron', label: tr('task_sched_cron')},
  {key: 'interval', label: tr('task_sched_interval')},
  {key: 'once', label: tr('task_sched_once')},
];
const actionTypes = (): {key: TaskActionType; label: string}[] => [
  {key: 'send_message', label: tr('task_action_send')},
  {key: 'agent_task', label: tr('task_action_agent')},
];

const recipientInstance = (r: TaskRecipient) => r.instance_id || r.channel_type;
const schedLabel = (type: ScheduleType) => schedTypes().find(x => x.key === type)?.label ?? type;
const actionLabel = (type: TaskActionType) => actionTypes().find(x => x.key === type)?.label ?? type;

function explain(e: unknown): string {
  const message = describeConnectError(e);
  if (/trusted directory/i.test(message)) {
    return tr('task_err_untrusted');
  }
  if (/next run time/i.test(message)) {
    return tr('task_err_next_run');
  }
  return message;
}

export function TaskEditScreen({navigation, route}: Props) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const task = route.params?.task;
  const original = task?.schedule ?? {};
  const origAction: TaskAction = task?.action ?? {};
  const isWebTask = !!task && (origAction.channel_type || 'web') === 'web';

  const [name, setName] = useState(task?.name ?? '');
  const [enabled, setEnabled] = useState(task?.enabled ?? true);
  const [schedType, setSchedType] = useState<ScheduleType>(
    original.type === 'interval' ? 'interval' : original.type === 'once' ? 'once' : 'cron',
  );
  const [cron, setCron] = useState(original.expression ?? '');
  const [interval, setInterval] = useState(original.seconds ? String(original.seconds) : '');
  const [runAt, setRunAt] = useState(
    original.type === 'once' ? (original.run_at ? original.run_at.slice(0, 16) : formatOnce(defaultOnce())) : '',
  );
  const [actionType, setActionType] = useState<TaskActionType>(
    origAction.type === 'agent_task' ? 'agent_task' : 'send_message',
  );
  const [content, setContent] = useState(origAction.content || origAction.task_description || '');

  const [instances, setInstances] = useState<TaskInstance[] | null>(isWebTask ? [] : null);
  const [recipients, setRecipients] = useState<TaskRecipient[]>([]);
  const [instanceId, setInstanceId] = useState(origAction.instance_id || origAction.channel_type || '');
  const [receiver, setReceiver] = useState(origAction.receiver ?? '');
  const [loadError, setLoadError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshed, setRefreshed] = useState(false);

  const [sheet, setSheet] = useState<OpenSheet>(null);
  const [busy, setBusy] = useState<'save' | 'delete' | 'run' | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadDirectory = async () => {
    const [inst, rec] = await Promise.all([getTaskInstances(), getTaskRecipients()]);
    setInstances(inst.instances ?? []);
    setRecipients(rec.recipients ?? []);
    setLoadError(null);
    return rec.recipients ?? [];
  };

  useEffect(() => {
    if (isWebTask) {
      return;
    }
    let alive = true;
    loadDirectory().catch(e => {
      if (alive) {
        setInstances([]);
        setLoadError(explain(e));
      }
    });
    return () => {
      alive = false;
    };
  }, [isWebTask]);

  const scoped = useMemo(() => recipients.filter(r => recipientInstance(r) === instanceId), [recipients, instanceId]);
  const instance = instances?.find(i => i.instance_id === instanceId);
  const recipient = scoped.find(r => r.receiver === receiver);

  useEffect(() => {
    if (!instanceId || isWebTask) {
      return;
    }
    if (!scoped.some(r => r.receiver === receiver)) {
      setReceiver(scoped[0]?.receiver ?? '');
    }
  }, [instanceId, scoped, receiver, isWebTask]);

  const pickInstance = (id: string) => {
    setSheet(null);
    setError(null);
    if (id === instanceId) {
      return;
    }
    setInstanceId(id);
    setReceiver(recipients.find(r => recipientInstance(r) === id)?.receiver ?? '');
  };

  const refreshRecipients = async () => {
    setRefreshing(true);
    try {
      const list = await getTaskRecipients();
      setRecipients(list.recipients ?? []);
      setRefreshed(true);
      setTimeout(() => setRefreshed(false), 1200);
    } catch (e) {
      setError(explain(e));
    } finally {
      setRefreshing(false);
    }
  };

  const buildSchedule = (): TaskSchedule | string => {
    if (schedType === 'cron') {
      return cron.trim() ? {type: 'cron', expression: cron.trim()} : tr('task_cron_required');
    }
    if (schedType === 'interval') {
      const seconds = Number(interval);
      return Number.isInteger(seconds) && seconds >= 60 ? {type: 'interval', seconds} : tr('task_interval_required');
    }
    if (!runAt.trim()) {
      return tr('task_once_required');
    }
    return parseOnce(runAt).getTime() > Date.now() ? {type: 'once', run_at: runAt.trim()} : tr('task_once_past');
  };

  const buildAction = (): TaskAction | string => {
    const body: TaskAction =
      actionType === 'send_message' ? {type: actionType, content: content.trim()} : {type: actionType, task_description: content.trim()};
    if (isWebTask) {
      return {
        ...origAction,
        ...body,
        channel_type: origAction.channel_type || 'web',
        receiver: origAction.receiver || '',
        receiver_name: origAction.receiver_name || '',
        is_group: origAction.is_group || false,
        notify_session_id: origAction.notify_session_id || '',
      };
    }
    if (!instanceId) {
      return tr('task_instance_required');
    }
    if (!recipient) {
      return tr('task_recipient_required');
    }
    return {
      ...origAction,
      ...body,
      channel_type: recipient.channel_type,
      instance_id: recipientInstance(recipient),
      receiver: recipient.receiver,
      receiver_name: recipient.name || recipient.receiver,
      is_group: recipient.is_group || false,
      notify_session_id: recipient.session_id || recipient.receiver,
    };
  };

  const save = async () => {
    if (!name.trim()) {
      setError(tr('task_name_required'));
      return;
    }
    const schedule = buildSchedule();
    if (typeof schedule === 'string') {
      setError(schedule);
      return;
    }
    if (!content.trim()) {
      setError(tr('task_content_required'));
      return;
    }
    const action = buildAction();
    if (typeof action === 'string') {
      setError(action);
      return;
    }
    const draft: TaskDraft = {name: name.trim(), enabled, schedule, action};
    setBusy('save');
    setError(null);
    try {
      if (task) {
        await updateScheduledTask(task, draft);
      } else {
        await createScheduledTask(draft);
      }
      showToast(task ? tr('common_saved') : tr('task_created'));
      navigation.goBack();
    } catch (e) {
      setError(explain(e));
    } finally {
      setBusy(null);
    }
  };

  const remove = async () => {
    if (!task) {
      return;
    }
    setBusy('delete');
    try {
      await deleteScheduledTask(task);
      setSheet(null);
      showToast(tr('common_deleted'));
      navigation.goBack();
    } catch (e) {
      setSheet(null);
      setError(trf('common_delete_failed', {error: explain(e)}));
    } finally {
      setBusy(null);
    }
  };

  const runNow = async () => {
    if (!task) {
      return;
    }
    setBusy('run');
    setError(null);
    try {
      await runTaskNow(task.id, task.agent_id);
      setSheet(null);
      showToast(tr('task_run_started'));
    } catch (e) {
      setError(explain(e));
    } finally {
      setBusy(null);
    }
  };

  const field = (
    value: string,
    onChange: (v: string) => void,
    opts: {placeholder: string; mono?: boolean; lines?: number; numeric?: boolean; label: string},
  ) => (
    <TextInput
      value={value}
      onChangeText={v => {
        onChange(v);
        setError(null);
      }}
      placeholder={opts.placeholder}
      placeholderTextColor={t.t4}
      selectionColor={t.accent}
      cursorColor={t.accent}
      autoCapitalize="none"
      autoCorrect={false}
      multiline={!!opts.lines}
      keyboardType={opts.numeric ? 'number-pad' : 'default'}
      accessibilityLabel={opts.label}
      style={[styles.field, opts.mono && styles.mono, !!opts.lines && styles.multi]}
    />
  );
  const contentLabel = actionType === 'send_message' ? tr('task_fixed_content') : tr('task_description');

  return (
    <View style={styles.root}>
      <PageHeader title={task ? tr('task_edit_title') : tr('task_add_title')} onBack={navigation.goBack} />
      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={[styles.body, {paddingBottom: insets.bottom + 32}]} keyboardShouldPersistTaps="handled">
          <Text style={styles.label}>{tr('task_name')}</Text>
          {field(name, setName, {placeholder: tr('task_name'), label: tr('task_name')})}

          <View style={styles.switchRow}>
            <Text style={styles.switchTitle}>{tr('task_enabled')}</Text>
            <Toggle value={enabled} onValueChange={setEnabled} label={tr('task_enabled')} />
          </View>

          <SettingRow
            title={tr('task_schedule_type')}
            value={schedLabel(schedType)}
            onPress={() => setSheet('schedule')}
            last
          />
          {schedType === 'cron' && (
            <>
              <Text style={styles.label}>{tr('task_sched_cron')}</Text>
              {field(cron, setCron, {placeholder: '0 9 * * *', mono: true, label: tr('task_sched_cron')})}
              <Text style={styles.hint}>{tr('task_cron_hint')}</Text>
            </>
          )}
          {schedType === 'interval' && (
            <>
              <Text style={styles.label}>{tr('task_interval_seconds')}</Text>
              {field(interval, setInterval, {placeholder: '3600', numeric: true, label: tr('task_interval_seconds')})}
              <Text style={styles.hint}>{tr('task_interval_hint')}</Text>
            </>
          )}
          {schedType === 'once' && (
            <SettingRow
              title={tr('task_once_time')}
              value={runAt ? fullTime(runAt) : tr('task_pick')}
              onPress={() => {
                if (!runAt) {
                  setRunAt(formatOnce(defaultOnce()));
                }
                setSheet('once');
              }}
              last
            />
          )}

          <SettingRow
            title={tr('task_action_type')}
            value={actionLabel(actionType)}
            onPress={() => setSheet('action')}
            last
          />
          {isWebTask ? (
            <>
              <SettingRow title={tr('task_channel')} value={origAction.channel_type || 'web'} last />
              <SettingRow
                title={tr('task_receiver')}
                value={origAction.receiver_name || origAction.receiver || '--'}
                last
              />
              <Text style={styles.hint}>{tr('task_channel_locked')}</Text>
            </>
          ) : (
            <>
              <SettingRow
                title={tr('task_channel')}
                value={instance ? instance.name : instances ? tr('task_instance_placeholder') : tr('common_loading')}
                detail={loadError || undefined}
                onPress={instances?.length ? () => setSheet('instance') : undefined}
                last
              />
              {!!instanceId && (
                <View style={styles.recipientHead}>
                  <Text style={styles.recipientLabel}>{tr('task_recipient')}</Text>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel={tr('task_recipient_refresh')}
                    disabled={refreshing}
                    onPress={refreshRecipients}
                    hitSlop={8}
                    style={({pressed}) => pressed && styles.pressed}>
                    {refreshing ? (
                      <ActivityIndicator size="small" color={t.t3} />
                    ) : (
                      <Icon icon={refreshed ? faCheck : faRotateRight} size={12} color={refreshed ? t.accent : t.t3} />
                    )}
                  </Pressable>
                </View>
              )}
              {!!instanceId && (
                <SettingRow
                  title={
                    recipient
                      ? recipient.name || recipient.receiver
                      : scoped.length
                        ? tr('task_recipient_placeholder')
                        : tr('task_recipient_none')
                  }
                  detail={recipient ? recipient.receiver : undefined}
                  onPress={scoped.length ? () => setSheet('recipient') : undefined}
                  last
                />
              )}
              {!!instanceId && !scoped.length && (
                <Text style={styles.hint}>{tr('task_recipient_empty_hint')}</Text>
              )}
              {!instances?.length && instances && (
                <Text style={styles.hint}>{tr('task_instance_empty')}</Text>
              )}
            </>
          )}

          <Text style={styles.label}>{contentLabel}</Text>
          {field(content, setContent, {placeholder: contentLabel, lines: 3, label: contentLabel})}

          {!!error && <Text style={styles.error}>{error}</Text>}
          <ActionButton
            label={tr('common_save')}
            tone="primary"
            loading={busy === 'save'}
            onPress={save}
            style={styles.submit}
          />
          {!!task && (
            <View style={styles.rowActions}>
              <ActionButton
                label={tr('task_run_now')}
                icon={faPlay}
                loading={busy === 'run'}
                onPress={() => setSheet('run')}
                style={styles.flex}
              />
              <ActionButton label={tr('common_delete')} tone="danger" onPress={() => setSheet('delete')} style={styles.flex} />
            </View>
          )}
        </ScrollView>
      </KeyboardAvoidingView>

      <ChoiceSheet
        visible={sheet === 'schedule'}
        title={tr('task_schedule_type')}
        options={schedTypes()}
        selected={schedType}
        onSelect={k => {
          setSchedType(k);
          if (k === 'once' && !runAt) {
            setRunAt(formatOnce(defaultOnce()));
          }
          setSheet(null);
          setError(null);
        }}
        onClose={() => setSheet(null)}
      />
      <ChoiceSheet
        visible={sheet === 'action'}
        title={tr('task_action_type')}
        options={actionTypes()}
        selected={actionType}
        onSelect={k => {
          setActionType(k);
          setSheet(null);
          setError(null);
        }}
        onClose={() => setSheet(null)}
      />
      <ChoiceSheet
        visible={sheet === 'instance'}
        title={tr('task_channel')}
        options={(instances ?? []).map(i => ({
          key: i.instance_id,
          label: i.name,
          desc: i.channel_label || i.channel_type,
        }))}
        selected={instanceId || undefined}
        onSelect={pickInstance}
        onClose={() => setSheet(null)}
      />
      <OnceTimeSheet
        visible={sheet === 'once'}
        value={runAt}
        onChange={v => {
          setRunAt(v);
          setError(null);
        }}
        onClose={() => setSheet(null)}
      />
      <ChoiceSheet
        visible={sheet === 'recipient'}
        title={tr('task_recipient')}
        options={scoped.map(r => ({
          key: r.receiver,
          label: r.name || r.receiver,
          desc: r.receiver,
        }))}
        selected={receiver || undefined}
        onSelect={k => {
          setReceiver(k);
          setSheet(null);
          setError(null);
        }}
        onClose={() => setSheet(null)}
      />
      <ConfirmSheet
        visible={sheet === 'delete'}
        title={tr('common_delete')}
        message={tr('task_delete_confirm')}
        confirmLabel={tr('common_delete')}
        danger
        onConfirm={remove}
        onClose={() => setSheet(null)}
      />
      <ConfirmSheet
        visible={sheet === 'run'}
        title={tr('task_run_now')}
        message={tr('task_run_confirm')}
        confirmLabel={tr('task_run_now')}
        onConfirm={runNow}
        onClose={() => setSheet(null)}
      />
      <ToastHost bottom={insets.bottom + 28} />
    </View>
  );
}

function OnceTimeSheet({
  visible,
  value,
  onChange,
  onClose,
}: {
  visible: boolean;
  value: string;
  onChange: (value: string) => void;
  onClose: () => void;
}) {
  return (
    <Sheet visible={visible} onClose={onClose} title={tr('task_once_time')}>
      <OnceWheels
        value={value}
        onDone={v => {
          onChange(v);
          onClose();
        }}
        onCancel={onClose}
      />
    </Sheet>
  );
}

/** Mounted fresh on every open, so the draft always starts from the saved value. */
function OnceWheels({value, onDone, onCancel}: {value: string; onDone: (value: string) => void; onCancel: () => void}) {
  const styles = useStyles();
  const today = useMemo(() => startOfToday(), []);
  const days = useMemo(() => Array.from({length: DAYS_AHEAD}, (_, i) => addDays(today, i)), [today]);
  const dayItems = useMemo(() => days.map(d => dayLabel(d, today)), [days, today]);

  const start = parseOnce(value);
  const [day, setDay] = useState(Math.max(0, Math.min(DAYS_AHEAD - 1, Math.round((startOfDay(start) - today.getTime()) / DAY_MS))));
  const [hour, setHour] = useState(start.getHours());
  const [minute, setMinute] = useState(start.getMinutes());

  const done = () => {
    const d = new Date(days[day]);
    d.setHours(hour, minute, 0, 0);
    onDone(formatOnce(d));
  };

  return (
    <View style={styles.sheetBody}>
      <WheelGroup>
        <WheelColumn label={tr('task_wheel_date')} items={dayItems} index={day} onChange={setDay} flex={2.2} />
        <WheelColumn label={tr('task_wheel_hour')} items={HOUR_ITEMS} index={hour} onChange={setHour} />
        <WheelColumn label={tr('task_wheel_minute')} items={MINUTE_ITEMS} index={minute} onChange={setMinute} />
      </WheelGroup>
      <View style={styles.sheetActions}>
        <ActionButton label={tr('common_cancel')} onPress={onCancel} style={styles.flex} />
        <ActionButton label={tr('common_confirm')} tone="primary" onPress={done} style={styles.flex} />
      </View>
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  flex: {flex: 1},
  body: {paddingTop: 4},
  label: {fontSize: 12, color: t.t3, marginTop: 18, marginBottom: 7, paddingHorizontal: 18},
  field: {
    marginHorizontal: 18,
    minHeight: 46,
    paddingHorizontal: 14,
    paddingVertical: 12,
    borderRadius: radius.sm,
    backgroundColor: t.bg1,
    borderWidth: 1,
    borderColor: t.line1,
    fontSize: 15,
    color: t.t1,
  },
  mono: {fontFamily: MONO, fontSize: 13, lineHeight: 20},
  multi: {minHeight: 110, maxHeight: 240, textAlignVertical: 'top'},
  hint: {fontSize: 12, lineHeight: 18, color: t.t4, paddingHorizontal: 18, paddingTop: 8},
  switchRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginHorizontal: 18,
    marginTop: 18,
    minHeight: 44,
  },
  switchTitle: {fontSize: 15, color: t.t1},
  recipientHead: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingHorizontal: 18,
    paddingTop: 16,
    paddingBottom: 2,
  },
  recipientLabel: {fontSize: 12, color: t.t3},
  pressed: {opacity: 0.6},
  error: {fontSize: 13, lineHeight: 19, color: t.danger, paddingHorizontal: 18, paddingTop: 18},
  submit: {marginHorizontal: 18, marginTop: 22},
  rowActions: {flexDirection: 'row', gap: 10, marginHorizontal: 18, marginTop: 12},
  sheetBody: {paddingHorizontal: 12, paddingTop: 4},
  sheetActions: {flexDirection: 'row', gap: 10, marginTop: 16, marginBottom: 4},
}));
