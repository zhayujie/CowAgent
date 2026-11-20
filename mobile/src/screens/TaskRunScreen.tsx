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
import {localizedLabel, tr, trf} from '../i18n';
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
        setChannelName(localizedLabel(c?.label) || null);
      })
      .catch(() => undefined);
  }, [run?.channel_type]);

  if (!run) {
    return (
      <View style={styles.root}>
        <PageHeader title={tr('task_run_detail')} onBack={navigation.goBack} />
        <EmptyState loading={!error} title={tr('common_load_failed')} hint={error ?? undefined} />
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
      <PageHeader title={run.task_name || tr('task_run_detail')} onBack={navigation.goBack} />
      <ScrollView contentContainerStyle={{paddingBottom: insets.bottom + 32}}>
        <View style={styles.kpis}>
          <Kpis
            items={[
              {value: status.label, label: tr('task_run_status')},
              {value: duration || '-', label: tr('task_run_elapsed')},
            ]}
          />
        </View>

        <SettingRow title={tr('task_run_started_at')} value={fullTime(run.started_at)} />
        <SettingRow title={tr('task_run_trigger')} value={triggerLabel(run)} />
        {!!run.channel_type && <SettingRow title={tr('task_channel')} value={channelName ?? run.channel_type} />}
        {!!agent && <SettingRow title={tr('task_run_agent')} value={agent.name || agent.id} />}
        <SettingRow title={tr('task_run_id')} value={run.run_id.slice(0, 12)} mono last />

        {failed && !!run.error && (
          <>
            <GroupLabel style={styles.group}>{tr('task_run_error')}</GroupLabel>
            <View style={styles.errorBox}>
              <Text style={styles.errorText} selectable>
                {run.error}
              </Text>
            </View>
          </>
        )}

        <View style={styles.outputHead}>
          <GroupLabel style={styles.outputLabel}>{tr('task_run_output')}</GroupLabel>
          {!!output && (
            <Pressable
              hitSlop={8}
              onPress={async () => showToast((await copyText(output)) ? tr('common_copied') : tr('task_copy_failed'))}
              style={styles.copy}>
              <Text style={styles.link}>{tr('common_copy')}</Text>
            </Pressable>
          )}
        </View>
        <View style={styles.output}>
          {output ? (
            <Markdown value={output} />
          ) : detailLoaded ? (
            <Text style={styles.none}>{tr('task_run_no_content')}</Text>
          ) : (
            <ActivityIndicator color={t.t3} />
          )}
        </View>

        <View style={styles.danger}>
          <ActionButton label={tr('task_run_delete')} tone="danger" onPress={() => setConfirmDelete(true)} />
        </View>
      </ScrollView>

      <ConfirmSheet
        visible={confirmDelete}
        title={tr('task_run_delete_title')}
        message={tr('task_run_delete_note')}
        confirmLabel={tr('common_delete')}
        danger
        onConfirm={async () => {
          try {
            await deleteTaskRun(run.run_id);
            setConfirmDelete(false);
            navigation.goBack();
          } catch (e) {
            setConfirmDelete(false);
            showToast(trf('common_delete_failed', {error: describeConnectError(e)}));
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
