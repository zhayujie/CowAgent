import {faCircleCheck, faCircleXmark, faClock, faClockRotateLeft, faTrashCan} from '@fortawesome/free-solid-svg-icons';
import {useNavigation} from '@react-navigation/native';
import type {StackNavigationProp} from '@react-navigation/stack';
import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {ActivityIndicator, Pressable, RefreshControl, SectionList, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {deleteTaskRun, getTaskRuns} from '../api/cowApi';
import type {RootStackParamList} from '../navigation/types';
import type {TaskRun} from '../protocol/resources';
import {useAgentStore} from '../store/agentStore';
import {describeConnectError} from '../store/serverStore';
import {makeStyles, useTheme} from '../theme/theme';
import {daysAgo, formatDuration, pad, toDate} from '../utils/format';
import {AgentAvatar} from './AgentAvatar';
import {Icon} from './Icon';
import {ConfirmSheet} from './settings';
import {showToast} from './Toast';
import {EmptyState} from './ui';

const PAGE = 30;

export const RUN_STATUS: Record<string, {label: string; tone: 'ok' | 'bad' | 'busy'}> = {
  done: {label: '成功', tone: 'ok'},
  success: {label: '成功', tone: 'ok'},
  error: {label: '失败', tone: 'bad'},
  failed: {label: '失败', tone: 'bad'},
  running: {label: '执行中', tone: 'busy'},
};

export const runStatus = (run: TaskRun) => RUN_STATUS[run.status] ?? {label: run.status, tone: 'busy' as const};

export function runDuration(run: TaskRun): string {
  return run.ended_at && run.started_at ? formatDuration((run.ended_at - run.started_at) * 1000) : '';
}

function dayTitle(d: Date | null, now = new Date()): string {
  if (!d) {
    return '';
  }
  const diff = daysAgo(d, now);
  if (diff === 0) {
    return '今天';
  }
  if (diff === 1) {
    return '昨天';
  }
  const md = `${d.getMonth() + 1}月${d.getDate()}日`;
  return d.getFullYear() === now.getFullYear() ? md : `${d.getFullYear()}年${md}`;
}

export const triggerLabel = (run: TaskRun) => (run.trigger === 'manual' ? '手动执行' : '定时触发');

/** Run history grouped by day; reloads whenever the screen regains focus so deletions show up. */
export function RunList({taskId, header}: {taskId?: string; header?: React.ReactElement}) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const navigation = useNavigation<StackNavigationProp<RootStackParamList>>();
  const [runs, setRuns] = useState<TaskRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [deleting, setDeleting] = useState<TaskRun | null>(null);
  const count = useRef(0);
  const agents = useAgentStore(s => s.agents);
  const defaultId = useAgentStore(s => s.defaultId);

  const remove = async () => {
    const run = deleting;
    if (!run) {
      return;
    }
    try {
      await deleteTaskRun(run.run_id);
      setRuns(prev => (prev ? prev.filter(r => r.run_id !== run.run_id) : prev));
      count.current = Math.max(0, count.current - 1);
    } catch (e) {
      showToast(`删除失败：${describeConnectError(e)}`);
    } finally {
      setDeleting(null);
    }
  };

  const load = useCallback(async () => {
    try {
      const res = await getTaskRuns({taskId, limit: Math.max(PAGE, count.current)});
      count.current = res.runs.length;
      setRuns(res.runs);
      setHasMore(res.runs.length >= PAGE);
      setError(null);
    } catch (e) {
      setError(describeConnectError(e));
    }
  }, [taskId]);

  useEffect(() => navigation.addListener('focus', load), [navigation, load]);
  useEffect(() => {
    load();
  }, [load]);

  const more = async () => {
    if (!hasMore || loadingMore || !runs) {
      return;
    }
    setLoadingMore(true);
    try {
      const res = await getTaskRuns({taskId, limit: PAGE, offset: runs.length});
      const seen = new Set(runs.map(r => r.run_id));
      const next = [...runs, ...res.runs.filter(r => !seen.has(r.run_id))];
      count.current = next.length;
      setRuns(next);
      setHasMore(res.runs.length >= PAGE);
    } catch {
      setHasMore(false);
    } finally {
      setLoadingMore(false);
    }
  };

  const sections = useMemo(() => {
    const out: {title: string; data: TaskRun[]}[] = [];
    for (const run of runs ?? []) {
      const title = dayTitle(toDate(run.started_at));
      const last = out[out.length - 1];
      if (last && last.title === title) {
        last.data.push(run);
      } else {
        out.push({title, data: [run]});
      }
    }
    return out;
  }, [runs]);

  return (
    <>
    <SectionList
      sections={sections}
      keyExtractor={r => r.run_id}
      stickySectionHeadersEnabled={false}
      ListHeaderComponent={header}
      contentContainerStyle={[styles.list, {paddingBottom: insets.bottom + 24}]}
      renderSectionHeader={({section}) => <Text style={styles.day}>{section.title}</Text>}
      renderItem={({item, index, section}) => {
        const d = toDate(item.started_at);
        const status = runStatus(item);
        const failed = status.tone === 'bad';
        const body = failed && item.error ? item.error : item.output_preview || '';
        const duration = runDuration(item);
        const owner = agents.length > 1 && item.agent_id ? agents.find(a => a.id === item.agent_id) : undefined;
        const statusColor = failed ? t.danger : status.tone === 'busy' ? t.t3 : t.accent;
        return (
          <Pressable
            accessibilityRole="button"
            onPress={() => navigation.navigate('TaskRun', {runId: item.run_id, run: item})}
            style={({pressed}) => [styles.row, index === section.data.length - 1 && styles.rowLast, pressed && styles.pressed]}>
            <View style={styles.titleLine}>
              <View style={styles.statusWrap}>
                {status.tone === 'busy' ? (
                  <ActivityIndicator size="small" color={statusColor} />
                ) : (
                  <Icon icon={failed ? faCircleXmark : faCircleCheck} size={13} color={statusColor} />
                )}
                <Text style={[styles.status, {color: statusColor}]}>{status.label}</Text>
              </View>
              <Text style={styles.name} numberOfLines={1}>
                {item.task_name || item.task_id || '定时任务'}
              </Text>
              {!!owner && <AgentAvatar agent={owner} isDefault={owner.id === defaultId} size={16} />}
              <Text style={styles.trigger}>{triggerLabel(item)}</Text>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="删除执行记录"
                hitSlop={8}
                onPress={() => setDeleting(item)}
                style={({pressed}) => pressed && styles.pressed}>
                <Icon icon={faTrashCan} size={12} color={t.t4} />
              </Pressable>
            </View>
            {!!body && (
              <Text style={[styles.body, failed && styles.bad]} numberOfLines={2}>
                {body}
              </Text>
            )}
            {!body && !failed && <Text style={styles.noOutput}>无输出内容</Text>}
            <View style={styles.metaLine}>
              <Icon icon={faClock} size={11} color={t.t4} />
              <Text style={styles.meta}>
                {d ? `${pad(d.getHours())}:${pad(d.getMinutes())}` : '--'}
                {duration ? ` · 耗时 ${duration}` : ''}
              </Text>
            </View>
          </Pressable>
        );
      }}
      onEndReachedThreshold={0.4}
      onEndReached={more}
      ListFooterComponent={loadingMore ? <ActivityIndicator style={styles.more} color={t.t3} /> : null}
      ListEmptyComponent={
        <EmptyState
          icon={error ? undefined : faClockRotateLeft}
          loading={!runs && !error}
          title={error ? '加载失败' : '暂无执行记录'}
          hint={error ?? '任务执行后，成功与失败的记录都会显示在这里'}
        />
      }
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={async () => {
            setRefreshing(true);
            count.current = 0;
            await load();
            setRefreshing(false);
          }}
          tintColor={t.t3}
          colors={[t.green]}
        />
      }
    />
    <ConfirmSheet
      visible={!!deleting}
      title="删除执行记录"
      message="确定删除这条执行记录吗？此操作不可恢复。"
      confirmLabel="删除"
      danger
      onConfirm={remove}
      onClose={() => setDeleting(null)}
    />
    </>
  );
}

const useStyles = makeStyles(t => ({
  list: {flexGrow: 1},
  day: {fontSize: 12, fontWeight: '600', color: t.t3, paddingHorizontal: 18, paddingTop: 20, paddingBottom: 4},
  row: {
    marginHorizontal: 18,
    paddingVertical: 13,
    borderBottomWidth: 1,
    borderBottomColor: t.line1,
  },
  rowLast: {borderBottomWidth: 0},
  pressed: {opacity: 0.6},
  titleLine: {flexDirection: 'row', alignItems: 'center', gap: 8},
  statusWrap: {flexDirection: 'row', alignItems: 'center', gap: 4},
  status: {fontSize: 12, fontWeight: '500'},
  name: {flex: 1, fontSize: 15, fontWeight: '500', color: t.t1},
  trigger: {
    fontSize: 11,
    color: t.t3,
    paddingHorizontal: 7,
    paddingVertical: 2,
    borderRadius: 999,
    overflow: 'hidden',
    backgroundColor: t.bg2,
  },
  bad: {color: t.danger},
  body: {fontSize: 13, lineHeight: 19, color: t.t2, marginTop: 6},
  noOutput: {fontSize: 13, color: t.t4, fontStyle: 'italic', marginTop: 6},
  metaLine: {flexDirection: 'row', alignItems: 'center', gap: 5, marginTop: 7},
  meta: {fontSize: 12, color: t.t4, fontVariant: ['tabular-nums']},
  more: {paddingVertical: 16},
}));
