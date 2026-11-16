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
import type {RootStackParamList} from '../navigation/types';
import type {ScheduleType, TaskAction, TaskActionType, TaskInstance, TaskRecipient, TaskSchedule} from '../protocol/resources';
import {describeConnectError} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {daysAgo, fullTime, pad, startOfDay, toDate} from '../utils/format';

type Props = StackScreenProps<RootStackParamList, 'TaskEdit'>;
type OpenSheet = 'schedule' | 'action' | 'instance' | 'recipient' | 'once' | 'delete' | 'run' | null;

const WEEKDAY = ['日', '一', '二', '三', '四', '五', '六'];
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
    return '今天';
  }
  if (ahead === 1) {
    return '明天';
  }
  const base = `${d.getMonth() + 1}月${d.getDate()}日 周${WEEKDAY[d.getDay()]}`;
  return d.getFullYear() === today.getFullYear() ? base : `${d.getFullYear()}年${base}`;
}

const SCHED_TYPES: {key: ScheduleType; label: string}[] = [
  {key: 'cron', label: 'Cron 表达式'},
  {key: 'interval', label: '固定间隔'},
  {key: 'once', label: '单次执行'},
];
const ACTION_TYPES: {key: TaskActionType; label: string}[] = [
  {key: 'send_message', label: '固定消息'},
  {key: 'agent_task', label: 'AI 任务'},
];

const recipientInstance = (r: TaskRecipient) => r.instance_id || r.channel_type;
const schedLabel = (type: ScheduleType) => SCHED_TYPES.find(x => x.key === type)?.label ?? type;
const actionLabel = (type: TaskActionType) => ACTION_TYPES.find(x => x.key === type)?.label ?? type;

function explain(e: unknown): string {
  const message = describeConnectError(e);
  if (/trusted directory/i.test(message)) {
    return '这个接收人不在联系人里，请让 TA 先在这个通道给 Agent 发一条消息';
  }
  if (/next run time/i.test(message)) {
    return '无法计算下次执行时间，请检查 Cron 表达式或执行时间（单次任务须晚于现在）';
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
      return cron.trim() ? {type: 'cron', expression: cron.trim()} : '请填写 Cron 表达式';
    }
    if (schedType === 'interval') {
      const seconds = Number(interval);
      return Number.isInteger(seconds) && seconds >= 60 ? {type: 'interval', seconds} : '请填写间隔秒数（最小 60 秒）';
    }
    if (!runAt.trim()) {
      return '请选择执行时间';
    }
    return parseOnce(runAt).getTime() > Date.now() ? {type: 'once', run_at: runAt.trim()} : '执行时间须晚于现在';
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
      return '请先选择通道';
    }
    if (!recipient) {
      return '请先选择接收人';
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
      setError('请填写任务名称');
      return;
    }
    const schedule = buildSchedule();
    if (typeof schedule === 'string') {
      setError(schedule);
      return;
    }
    if (!content.trim()) {
      setError('请输入内容');
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
      showToast(task ? '已保存' : '已创建');
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
      showToast('已删除');
      navigation.goBack();
    } catch (e) {
      setSheet(null);
      setError(`删除失败：${explain(e)}`);
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
      showToast('任务已开始执行');
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

  return (
    <View style={styles.root}>
      <PageHeader title={task ? '编辑定时任务' : '新增定时任务'} onBack={navigation.goBack} />
      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={[styles.body, {paddingBottom: insets.bottom + 32}]} keyboardShouldPersistTaps="handled">
          <Text style={styles.label}>任务名称</Text>
          {field(name, setName, {placeholder: '任务名称', label: '任务名称'})}

          <View style={styles.switchRow}>
            <Text style={styles.switchTitle}>启用任务</Text>
            <Toggle value={enabled} onValueChange={setEnabled} label="启用任务" />
          </View>

          <SettingRow
            title="调度类型"
            value={schedLabel(schedType)}
            onPress={() => setSheet('schedule')}
            last
          />
          {schedType === 'cron' && (
            <>
              <Text style={styles.label}>Cron 表达式</Text>
              {field(cron, setCron, {placeholder: '0 9 * * *', mono: true, label: 'Cron 表达式'})}
              <Text style={styles.hint}>格式: 分 时 日 月 周，例如 “0 9 * * *” 表示每天 9:00</Text>
            </>
          )}
          {schedType === 'interval' && (
            <>
              <Text style={styles.label}>间隔秒数</Text>
              {field(interval, setInterval, {placeholder: '3600', numeric: true, label: '间隔秒数'})}
              <Text style={styles.hint}>最小 60 秒，例如 3600 表示每小时执行一次</Text>
            </>
          )}
          {schedType === 'once' && (
            <SettingRow
              title="执行时间"
              value={runAt ? fullTime(runAt) : '请选择'}
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
            title="任务类型"
            value={actionLabel(actionType)}
            onPress={() => setSheet('action')}
            last
          />
          {isWebTask ? (
            <>
              <SettingRow title="通道" value={origAction.channel_type || 'web'} last />
              <SettingRow title="接收者" value={origAction.receiver_name || origAction.receiver || '--'} last />
              <Text style={styles.hint}>通道与接收者创建后不可修改</Text>
            </>
          ) : (
            <>
              <SettingRow
                title="通道"
                value={instance ? instance.name : instances ? '请选择通道' : '加载中...'}
                detail={loadError || undefined}
                onPress={instances?.length ? () => setSheet('instance') : undefined}
                last
              />
              {!!instanceId && (
                <View style={styles.recipientHead}>
                  <Text style={styles.recipientLabel}>接收人</Text>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel="刷新接收人"
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
                  title={recipient ? recipient.name || recipient.receiver : scoped.length ? '请选择接收人' : '该通道下暂无接收人'}
                  detail={recipient ? recipient.receiver : undefined}
                  onPress={scoped.length ? () => setSheet('recipient') : undefined}
                  last
                />
              )}
              {!!instanceId && !scoped.length && (
                <Text style={styles.hint}>该通道下暂无接收人，请先在这个通道向智能体发送一条消息</Text>
              )}
              {!instances?.length && instances && (
                <Text style={styles.hint}>暂无可用通道</Text>
              )}
            </>
          )}

          <Text style={styles.label}>{actionType === 'send_message' ? '固定内容' : '任务描述'}</Text>
          {field(content, setContent, {
            placeholder: actionType === 'send_message' ? '固定内容' : '任务描述',
            lines: 3,
            label: actionType === 'send_message' ? '固定内容' : '任务描述',
          })}

          {!!error && <Text style={styles.error}>{error}</Text>}
          <ActionButton label="保存" tone="primary" loading={busy === 'save'} onPress={save} style={styles.submit} />
          {!!task && (
            <View style={styles.rowActions}>
              <ActionButton
                label="立即执行"
                icon={faPlay}
                loading={busy === 'run'}
                onPress={() => setSheet('run')}
                style={styles.flex}
              />
              <ActionButton label="删除" tone="danger" onPress={() => setSheet('delete')} style={styles.flex} />
            </View>
          )}
        </ScrollView>
      </KeyboardAvoidingView>

      <ChoiceSheet
        visible={sheet === 'schedule'}
        title="调度类型"
        options={SCHED_TYPES.map(x => ({key: x.key, label: x.label}))}
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
        title="任务类型"
        options={ACTION_TYPES.map(x => ({key: x.key, label: x.label}))}
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
        title="通道"
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
        title="接收人"
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
        title="删除"
        message="确定删除该任务吗？此操作不可撤销。"
        confirmLabel="删除"
        danger
        onConfirm={remove}
        onClose={() => setSheet(null)}
      />
      <ConfirmSheet
        visible={sheet === 'run'}
        title="立即执行"
        message="该任务会立即向已配置的通道和接收者发送内容。是否继续？"
        confirmLabel="立即执行"
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
    <Sheet visible={visible} onClose={onClose} title="执行时间">
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
        <WheelColumn label="日期" items={dayItems} index={day} onChange={setDay} flex={2.2} />
        <WheelColumn label="时" items={HOUR_ITEMS} index={hour} onChange={setHour} />
        <WheelColumn label="分" items={MINUTE_ITEMS} index={minute} onChange={setMinute} />
      </WheelGroup>
      <View style={styles.sheetActions}>
        <ActionButton label="取消" onPress={onCancel} style={styles.flex} />
        <ActionButton label="确定" tone="primary" onPress={done} style={styles.flex} />
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
