import {
  faCalendarDays,
  faClock,
  faClockRotateLeft,
  faPlay,
  faPlus,
  faRotateRight,
} from '@fortawesome/free-solid-svg-icons';
import {useFocusEffect} from '@react-navigation/native';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useState} from 'react';
import {ActivityIndicator, FlatList, Pressable, RefreshControl, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {getScheduledTasks, runTaskNow, toggleScheduledTask} from '../api/cowApi';
import {AgentAvatar} from '../components/AgentAvatar';
import {Icon} from '../components/Icon';
import {RunList} from '../components/RunList';
import {ActionButton, ConfirmSheet, MONO, Notice, Toggle} from '../components/settings';
import {Sheet, SHEET_DISMISS_MS} from '../components/Sheet';
import {showToast, ToastHost} from '../components/Toast';
import {SwipeTabs} from '../components/SwipeTabs';
import {EmptyState, IconButton, PageHeader, Segmented} from '../components/ui';
import {tr, trf} from '../i18n';
import type {RootStackParamList} from '../navigation/types';
import type {ScheduledTask, TaskSchedule} from '../protocol/resources';
import {useAgentStore} from '../store/agentStore';
import {describeConnectError, useLocalServer} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {fullTime} from '../utils/format';

/** Same wording the desktop client uses on each card. */
function scheduleLabel(task: ScheduledTask): string {
  const s: TaskSchedule = task.schedule ?? {};
  if (s.type === 'cron') {
    return s.expression || 'cron';
  }
  if (s.type === 'interval') {
    const sec = s.seconds || 0;
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const r = sec % 60;
    const parts: string[] = [];
    if (h) {
      parts.push(`${h}h`);
    }
    if (m) {
      parts.push(`${m}m`);
    }
    if (r || !parts.length) {
      parts.push(`${r}s`);
    }
    return parts.join(' ');
  }
  return s.type || 'once';
}

type Props = StackScreenProps<RootStackParamList, 'Tasks'>;
type Tab = 'tasks' | 'runs';
const TABS: readonly Tab[] = ['tasks', 'runs'];

const contentOf = (task: ScheduledTask) => task.action?.content || task.action?.task_description || '';

export function TasksScreen({navigation}: Props) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const local = useLocalServer();
  const [tab, setTab] = useState<Tab>('tasks');
  const [tasks, setTasks] = useState<ScheduledTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [opened, setOpened] = useState<ScheduledTask | null>(null);
  const [running, setRunning] = useState(false);
  const [confirmRun, setConfirmRun] = useState<ScheduledTask | null>(null);
  const [runningId, setRunningId] = useState('');
  const agents = useAgentStore(s => s.agents);
  const defaultId = useAgentStore(s => s.defaultId);
  const ownerOf = (task: ScheduledTask) =>
    agents.length > 1 && task.agent_id ? agents.find(a => a.id === task.agent_id) : undefined;

  const load = useCallback(async (refresh = false) => {
    if (refresh) {
      setRefreshing(true);
    }
    try {
      const res = await getScheduledTasks();
      setTasks(res.tasks);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  // Coming back from the editor brings the saved task with it.
  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  const edit = (task?: ScheduledTask) => {
    setOpened(null);
    setTimeout(() => navigation.navigate('TaskEdit', task ? {task} : undefined), task ? SHEET_DISMISS_MS : 0);
  };

  const toggle = async (task: ScheduledTask, enabled: boolean) => {
    setTasks(prev => prev.map(x => (x.id === task.id ? {...x, enabled} : x)));
    try {
      await toggleScheduledTask(task.id, enabled);
    } catch {
      setTasks(prev => prev.map(x => (x.id === task.id ? {...x, enabled: !enabled} : x)));
    }
  };

  const runNow = async (task: ScheduledTask) => {
    setRunning(true);
    try {
      await runTaskNow(task.id, task.agent_id);
      setOpened(null);
      showToast(tr('task_run_started_hint'));
    } catch (e) {
      showToast(trf('task_run_failed_detail', {error: describeConnectError(e)}));
    } finally {
      setRunning(false);
    }
  };

  const runFromRow = async () => {
    const task = confirmRun;
    if (!task) {
      return;
    }
    setConfirmRun(null);
    setRunningId(task.id);
    try {
      await runTaskNow(task.id, task.agent_id);
      showToast(tr('task_run_started_hint'));
    } catch (e) {
      showToast(trf('task_run_failed_detail', {error: describeConnectError(e)}));
    } finally {
      setRunningId('');
    }
  };

  const openedContent = opened ? contentOf(opened) : '';
  const openedNext = opened?.enabled ? fullTime(opened.next_run_at ?? null) : '';

  return (
    <View style={styles.root}>
      <PageHeader
        title={tr('task_title')}
        onBack={navigation.goBack}
        right={
          <View style={styles.headerActions}>
            {tab === 'tasks' && (
              <IconButton label={tr('common_refresh')} onPress={() => load(true)} size={13}>
                {refreshing ? (
                  <ActivityIndicator size="small" color={t.t2} />
                ) : (
                  <Icon icon={faRotateRight} size={13} color={t.t2} />
                )}
              </IconButton>
            )}
            <IconButton icon={faPlus} label={tr('task_new')} filled size={13} color={t.t1} onPress={() => edit()} />
          </View>
        }
      />
      <Segmented
        value={tab}
        onChange={setTab}
        options={[
          {key: 'tasks', label: tr('task_tab_tasks'), count: loading ? 0 : tasks.length, icon: faCalendarDays},
          {key: 'runs', label: tr('task_runs'), icon: faClockRotateLeft},
        ]}
      />
      <SwipeTabs tabs={TABS} value={tab} onChange={setTab}>
        {tab === 'runs' ? (
          <RunList />
        ) : (
          <FlatList
            data={tasks}
            keyExtractor={x => x.id}
            contentContainerStyle={[styles.list, {paddingBottom: insets.bottom + 24}]}
            ListHeaderComponent={
              local ? <Notice style={styles.localNote}>{tr('task_local_note')}</Notice> : null
            }
            renderItem={({item}) => {
              const content = contentOf(item);
              const next = item.enabled ? fullTime(item.next_run_at ?? null) : '';
              const owner = ownerOf(item);
              return (
                <Pressable
                  accessibilityRole="button"
                  onPress={() => setOpened(item)}
                  style={({pressed}) => [styles.row, !item.enabled && styles.rowOff, pressed && styles.pressed]}>
                  <View style={styles.titleLine}>
                    <View style={[styles.dot, item.enabled && styles.dotOn]} />
                    <Text style={[styles.name, !item.enabled && styles.off]} numberOfLines={1}>
                      {item.name || content || tr('task_untitled')}
                    </Text>
                    {!!owner && (
                      <View style={styles.owner}>
                        <AgentAvatar agent={owner} isDefault={owner.id === defaultId} size={14} />
                        <Text style={styles.ownerName} numberOfLines={1}>
                          {owner.name || owner.id}
                        </Text>
                      </View>
                    )}
                    <Text style={styles.schedule} numberOfLines={1}>
                      {scheduleLabel(item)}
                    </Text>
                  </View>
                  {!!content && !!item.name && (
                    <Text style={styles.content} numberOfLines={2}>
                      {content}
                    </Text>
                  )}
                  <View style={styles.footLine}>
                    <Icon icon={faClock} size={11} color={t.t3} />
                    <Text style={styles.meta} numberOfLines={1}>
                      {trf('task_next_run', {time: next || (item.enabled ? '--' : tr('task_paused'))})}
                    </Text>
                    <Pressable
                      accessibilityRole="button"
                      accessibilityLabel={trf('task_run_named', {name: item.name || tr('task_fallback_name')})}
                      disabled={runningId === item.id}
                      hitSlop={6}
                      onPress={() => setConfirmRun(item)}
                      style={({pressed}) => [styles.play, pressed && styles.pressed]}>
                      {runningId === item.id ? (
                        <ActivityIndicator size="small" color={t.t2} />
                      ) : (
                        <Icon icon={faPlay} size={10} color={t.t2} />
                      )}
                    </Pressable>
                    <Toggle
                      value={item.enabled}
                      onValueChange={v => toggle(item, v)}
                      label={trf('task_enable_named', {name: item.name || tr('task_fallback_name')})}
                    />
                  </View>
                </Pressable>
              );
            }}
            ListEmptyComponent={
              <EmptyState
                icon={error ? undefined : faCalendarDays}
                loading={loading}
                title={error ? tr('common_load_failed') : tr('task_empty')}
                hint={error ?? tr('task_empty_hint')}
              />
            }
            refreshControl={
              <RefreshControl refreshing={refreshing} onRefresh={() => load(true)} tintColor={t.t3} colors={[t.green]} />
            }
          />
        )}
      </SwipeTabs>

      <Sheet visible={!!opened} onClose={() => setOpened(null)} title={opened?.name || tr('task_title')}>
        {opened && (
          <View style={styles.sheet}>
            <Text style={styles.sheetMeta}>
              {scheduleLabel(opened)}
              {openedNext
                ? ` · ${trf('task_next_short', {time: openedNext})}`
                : opened.enabled
                  ? ''
                  : ` · ${tr('task_paused')}`}
            </Text>
            {!!openedContent && (
              <Text style={styles.sheetContent} numberOfLines={8}>
                {openedContent}
              </Text>
            )}
            <View style={styles.sheetActions}>
              <ActionButton label={tr('common_edit')} style={styles.flex} onPress={() => edit(opened)} />
              <ActionButton
                label={tr('task_runs')}
                icon={faClockRotateLeft}
                style={styles.flex}
                onPress={() => {
                  const task = opened;
                  setOpened(null);
                  navigation.navigate('TaskRuns', {taskId: task.id, title: task.name || tr('task_runs')});
                }}
              />
              <ActionButton
                label={tr('task_run_now')}
                icon={faPlay}
                tone="primary"
                loading={running}
                style={styles.flex}
                onPress={() => runNow(opened)}
              />
            </View>
            <Text style={styles.sheetNote}>{tr('task_run_now_note')}</Text>
          </View>
        )}
      </Sheet>
      <ConfirmSheet
        visible={!!confirmRun}
        title={tr('task_run_now')}
        message={tr('task_run_confirm')}
        confirmLabel={tr('task_run_now')}
        onConfirm={runFromRow}
        onClose={() => setConfirmRun(null)}
      />
      <ToastHost bottom={insets.bottom + 28} />
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  list: {paddingTop: 2, flexGrow: 1},
  localNote: {marginHorizontal: 18, marginTop: 8, marginBottom: 4},
  headerActions: {flexDirection: 'row', alignItems: 'center', gap: 6},
  row: {
    marginHorizontal: 18,
    paddingVertical: 14,
    borderBottomWidth: 1,
    borderBottomColor: t.line1,
  },
  rowOff: {opacity: 0.6},
  pressed: {opacity: 0.6},
  titleLine: {flexDirection: 'row', alignItems: 'center', gap: 8},
  dot: {width: 7, height: 7, borderRadius: 4, backgroundColor: t.t4},
  dotOn: {backgroundColor: t.green},
  name: {flexShrink: 1, fontSize: 15, fontWeight: '500', color: t.t1},
  off: {color: t.t3},
  owner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    maxWidth: 110,
    paddingLeft: 3,
    paddingRight: 7,
    paddingVertical: 2,
    borderRadius: 999,
    backgroundColor: t.bg2,
  },
  ownerName: {flexShrink: 1, fontSize: 11, color: t.t2},
  schedule: {flex: 1, minWidth: 60, fontFamily: MONO, fontSize: 12, color: t.t3, textAlign: 'right'},
  content: {fontSize: 13, lineHeight: 20, color: t.t2, marginTop: 6},
  footLine: {flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 8},
  meta: {flex: 1, fontSize: 12, color: t.t3, fontVariant: ['tabular-nums']},
  play: {
    width: 30,
    height: 26,
    borderRadius: radius.sm,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: t.line2,
  },
  sheet: {paddingHorizontal: 12, paddingBottom: 4},
  sheetMeta: {fontSize: 13, color: t.t3, fontVariant: ['tabular-nums']},
  sheetContent: {fontSize: 14, lineHeight: 22, color: t.t2, marginTop: 10},
  sheetActions: {flexDirection: 'row', gap: 10, marginTop: 20},
  flex: {flex: 1},
  sheetNote: {fontSize: 12, lineHeight: 18, color: t.t4, marginTop: 10},
}));
