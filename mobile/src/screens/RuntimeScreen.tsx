import type {StackScreenProps} from '@react-navigation/stack';
import React, {useEffect, useState} from 'react';
import {ScrollView, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {ChoiceSheet, FieldSheet, Footnote, SettingRow, SwitchRow} from '../components/settings';
import {showToast, ToastHost} from '../components/Toast';
import {EmptyState, GroupLabel, PageHeader} from '../components/ui';
import {tr, trf, type MessageKey} from '../i18n';
import type {RootStackParamList} from '../navigation/types';
import type {ConfigUpdates, GlobalConfig, ReasoningMeta} from '../protocol/resources';
import {useConfigStore} from '../store/configStore';
import {describeConnectError} from '../store/serverStore';
import {makeStyles} from '../theme/theme';
import {formatCount} from '../utils/format';

type Props = StackScreenProps<RootStackParamList, 'Runtime'>;

type NumberKey = 'agent_max_context_tokens' | 'agent_max_context_turns' | 'agent_max_steps';

const NUMBER_FIELDS: Record<NumberKey, {title: MessageKey; hint: MessageKey; min: number}> = {
  agent_max_context_tokens: {title: 'settings_max_tokens', hint: 'settings_max_tokens_hint', min: 0},
  agent_max_context_turns: {title: 'settings_max_turns', hint: 'settings_max_turns_hint', min: 1},
  agent_max_steps: {title: 'settings_max_steps', hint: 'settings_max_steps_hint', min: 1},
};

/** The provider the console keys efforts by: `use_linkai` routing wins over the vendor. */
function effortContext(config: GlobalConfig): {key: string; meta?: ReasoningMeta} {
  const provider = config.use_linkai ? 'linkai' : config.bot_type;
  const entry = config.providers[provider];
  return {
    key: `${provider}:${config.model.trim().toLowerCase()}`,
    meta: entry?.reasoning_by_model?.[config.model] ?? entry?.reasoning,
  };
}

export function RuntimeScreen({navigation}: Props) {
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const config = useConfigStore(s => s.config);
  const error = useConfigStore(s => s.error);
  const load = useConfigStore(s => s.load);
  const update = useConfigStore(s => s.update);
  const [editing, setEditing] = useState<NumberKey | null>(null);
  const [effortOpen, setEffortOpen] = useState(false);

  useEffect(() => {
    load().catch(() => undefined);
  }, [load]);

  const save = async (updates: ConfigUpdates) => {
    try {
      await update(updates);
    } catch (e) {
      showToast(trf('common_save_failed_detail', {error: describeConnectError(e)}));
    }
  };

  if (!config) {
    return (
      <View style={styles.root}>
        <PageHeader title={tr('settings_runtime')} onBack={navigation.goBack} />
        <EmptyState loading={!error} title={tr('common_load_failed')} hint={error ?? undefined} />
      </View>
    );
  }

  const tokens = config.agent_max_context_tokens;
  const {key: effortKey, meta: effortMeta} = effortContext(config);
  const effortOptions = effortMeta?.supported ? effortMeta.options ?? [] : [];
  const effort =
    config.reasoning_effort_by_model?.[effortKey] ?? effortMeta?.default ?? config.reasoning_effort;
  const field = editing ? NUMBER_FIELDS[editing] : null;

  return (
    <View style={styles.root}>
      <PageHeader title={tr('settings_runtime')} onBack={navigation.goBack} />
      <ScrollView contentContainerStyle={{paddingBottom: insets.bottom + 32}}>
        <GroupLabel style={styles.firstGroup}>{tr('settings_group_context')}</GroupLabel>
        <SettingRow
          title={tr('settings_max_tokens')}
          detail={tr('settings_max_tokens_hint')}
          fullDetail
          value={tokens ? formatCount(tokens) : tr('settings_follow_model')}
          onPress={() => setEditing('agent_max_context_tokens')}
        />
        <SettingRow
          title={tr('settings_max_turns')}
          detail={tr('settings_max_turns_hint')}
          fullDetail
          value={trf('settings_turns_value', {n: config.agent_max_context_turns})}
          onPress={() => setEditing('agent_max_context_turns')}
        />
        <SettingRow
          title={tr('settings_max_steps')}
          detail={tr('settings_max_steps_hint')}
          fullDetail
          value={trf('settings_steps_value', {n: config.agent_max_steps})}
          onPress={() => setEditing('agent_max_steps')}
          last
        />

        <GroupLabel style={styles.group}>{tr('settings_group_thinking')}</GroupLabel>
        <SwitchRow
          title={tr('settings_thinking')}
          detail={trf('settings_current_model', {model: config.model || tr('common_not_configured')})}
          value={config.enable_thinking}
          onValueChange={v => save({enable_thinking: v})}
          last={!config.enable_thinking || !effortOptions.length}
        />
        {config.enable_thinking && effortOptions.length > 0 && (
          <SettingRow
            title={tr('settings_effort')}
            detail={tr('settings_effort_detail')}
            fullDetail
            value={effortOptions.find(o => o.value === effort)?.label ?? effort}
            onPress={() => setEffortOpen(true)}
            last
          />
        )}

        <GroupLabel style={styles.group}>{tr('settings_group_collab')}</GroupLabel>
        <SwitchRow
          title={tr('settings_subagent')}
          detail={tr('settings_subagent_detail')}
          fullDetail
          value={config.subagent_enabled}
          onValueChange={v => save({subagent_enabled: v})}
        />
        <SwitchRow
          title={tr('settings_evolution')}
          detail={tr('settings_evolution_detail')}
          fullDetail
          value={config.self_evolution_enabled}
          onValueChange={v => save({self_evolution_enabled: v})}
          last
        />
        <Footnote>{tr('settings_runtime_note')}</Footnote>
      </ScrollView>

      <FieldSheet
        visible={!!editing}
        title={field ? tr(field.title) : ''}
        initial={editing ? String(config[editing]) : ''}
        keyboardType="number-pad"
        hint={field ? tr(field.hint) : undefined}
        allowEmpty={false}
        onSubmit={async raw => {
          if (!editing || !field) {
            return;
          }
          const value = Number(raw);
          if (!Number.isInteger(value) || value < field.min) {
            throw new Error(field.min ? trf('settings_int_min', {min: field.min}) : tr('settings_int_nonneg'));
          }
          await update({[editing]: value});
        }}
        onClose={() => setEditing(null)}
      />
      <ChoiceSheet
        visible={effortOpen}
        title={tr('settings_effort')}
        options={effortOptions.map(o => ({key: o.value, label: o.label}))}
        selected={effort}
        note={tr('settings_effort_note')}
        onSelect={value => {
          setEffortOpen(false);
          save({reasoning_effort_by_model: {[effortKey]: value}});
        }}
        onClose={() => setEffortOpen(false)}
      />
      <ToastHost bottom={insets.bottom + 28} />
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  firstGroup: {marginTop: 8},
  group: {marginTop: 26},
}));
