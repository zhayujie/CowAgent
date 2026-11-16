import type {StackScreenProps} from '@react-navigation/stack';
import React, {useEffect, useState} from 'react';
import {ActivityIndicator, Pressable, ScrollView, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {deleteTaskRun, getChannels, getTaskRun} from '../api/cowApi';
import {Markdown} from '../components/Markdown';
import {runDuration, runStatus, triggerLabel} from '../components/RunList';
import {ActionButton, ConfirmSheet, Kpis, SettingRow} from '../components/settings';
import {showToast, ToastHost} from '../components/Toast';
import {EmptyState, GroupLabel, PageHeader} from '../components/ui';
import type {RootStackParamList} from '../navigation/types';
import type {TaskRun} from '../protocol/resources';
import {useAgentStore} from '../store/agentStore';
import {describeConnectError} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {copyText} from '../utils/clipboard';
import {fullTime} from '../utils/format';

type Props = StackScreenProps<RootStackParamList, 'TaskRun'>;

export function TaskRunScreen({route, navigation}: Props) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const [run, setRun] = useState<TaskRun | null>(route.params.run ?? null);
  const [detailLoaded, setDetailLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [channelName, setChannelName] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const agents = useAgentStore(s => s.agents);

  useEffect(() => {
    let live = true;
    getTaskRun(route.params.runId)
      .then(res => live && setRun(res.run))
      .catch(e => live && setError(describeConnectError(e)))
      .finally(() => live && setDetailLoaded(true));
    return () => {
      live = false;
    };
  }, [route.params.runId]);

  useEffect(() => {
    const type = run?.channel_type;
    if (!type) {
      return;
    }
    getChannels()
      .then(res => {
        const c = res.channels.find(x => x.name === type);
        const label = typeof c?.label === 'string' ? c.label : c?.label?.zh || c?.label?.en;
        setChannelName(label || null);
      })
      .catch(() => undefined);
  }, [run?.channel_type]);

  if (!run) {
    return (
      <View style={styles.root}>
        <PageHeader title="执行详情" onBack={navigation.goBack} />
        <EmptyState loading={!error} title="加载失败" hint={error ?? undefined} />
      </View>
    );
  }

  const status = runStatus(run);
  const duration = runDuration(run);
  const output = run.full_output || run.output_preview || '';
  const agent = agents.length > 1 ? agents.find(a => a.id === run.agent_id) : undefined;
  const failed = status.tone === 'bad';

  return (
    <View style={styles.root}>
      <PageHeader title={run.task_name || '执行详情'} onBack={navigation.goBack} />
      <ScrollView contentContainerStyle={{paddingBottom: insets.bottom + 32}}>
        <View style={styles.kpis}>
          <Kpis
            items={[
              {value: status.label, label: '状态'},
              {value: duration || '-', label: '耗时'},
            ]}
          />
        </View>

        <SettingRow title="开始时间" value={fullTime(run.started_at)} />
        <SettingRow title="触发方式" value={triggerLabel(run)} />
        {!!run.channel_type && <SettingRow title="通道" value={channelName ?? run.channel_type} />}
        {!!agent && <SettingRow title="智能体" value={agent.name || agent.id} />}
        <SettingRow title="记录 ID" value={run.run_id.slice(0, 12)} mono last />

        {failed && !!run.error && (
          <>
            <GroupLabel style={styles.group}>错误信息</GroupLabel>
            <View style={styles.errorBox}>
              <Text style={styles.errorText} selectable>
                {run.error}
              </Text>
            </View>
          </>
        )}

        <View style={styles.outputHead}>
          <GroupLabel style={styles.outputLabel}>发送内容</GroupLabel>
          {!!output && (
            <Pressable
              hitSlop={8}
              onPress={async () => showToast((await copyText(output)) ? '已复制' : '复制失败')}
              style={styles.copy}>
              <Text style={styles.link}>复制</Text>
            </Pressable>
          )}
        </View>
        <View style={styles.output}>
          {output ? (
            <Markdown value={output} />
          ) : detailLoaded ? (
            <Text style={styles.none}>（无内容）</Text>
          ) : (
            <ActivityIndicator color={t.t3} />
          )}
        </View>

        <View style={styles.danger}>
          <ActionButton label="删除这条记录" tone="danger" onPress={() => setConfirmDelete(true)} />
        </View>
      </ScrollView>

      <ConfirmSheet
        visible={confirmDelete}
        title="删除执行记录"
        message="删除后无法恢复，不影响任务本身和已经发出的内容。"
        confirmLabel="删除"
        danger
        onConfirm={async () => {
          try {
            await deleteTaskRun(run.run_id);
            setConfirmDelete(false);
            navigation.goBack();
          } catch (e) {
            setConfirmDelete(false);
            showToast(`删除失败：${describeConnectError(e)}`);
          }
        }}
        onClose={() => setConfirmDelete(false)}
      />
      <ToastHost bottom={insets.bottom + 28} />
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  kpis: {paddingTop: 8, paddingBottom: 6},
  group: {marginTop: 26},
  errorBox: {
    marginHorizontal: 18,
    padding: 14,
    borderRadius: radius.sm,
    backgroundColor: t.dangerSoft,
  },
  errorText: {fontSize: 13, lineHeight: 20, color: t.danger},
  outputHead: {flexDirection: 'row', alignItems: 'center', marginTop: 26},
  outputLabel: {flex: 1, marginBottom: 0},
  copy: {paddingRight: 18, paddingLeft: 4},
  link: {fontSize: 13, color: t.accent},
  output: {paddingHorizontal: 18, paddingTop: 12},
  none: {fontSize: 14, color: t.t4},
  danger: {paddingHorizontal: 18, marginTop: 36},
}));
