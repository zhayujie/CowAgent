import type {StackScreenProps} from '@react-navigation/stack';
import React, {useEffect, useState} from 'react';
import {ScrollView, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {ChoiceSheet, FieldSheet, Footnote, SettingRow, SwitchRow} from '../components/settings';
import {showToast, ToastHost} from '../components/Toast';
import {EmptyState, GroupLabel, PageHeader} from '../components/ui';
import type {RootStackParamList} from '../navigation/types';
import type {ConfigUpdates, GlobalConfig, ReasoningMeta} from '../protocol/resources';
import {useConfigStore} from '../store/configStore';
import {describeConnectError} from '../store/serverStore';
import {makeStyles} from '../theme/theme';
import {formatCount} from '../utils/format';

type Props = StackScreenProps<RootStackParamList, 'Runtime'>;

type NumberKey = 'agent_max_context_tokens' | 'agent_max_context_turns' | 'agent_max_steps';

const NUMBER_FIELDS: Record<NumberKey, {title: string; hint: string; min: number}> = {
  agent_max_context_tokens: {
    title: '最大上下文 Token',
    hint: '上下文输入预算上限，达到后会压缩历史以控制成本；仍不会超过当前模型窗口。填 0 表示不限制、跟随模型窗口。',
    min: 0,
  },
  agent_max_context_turns: {
    title: '最大记忆轮次',
    hint: '一问一答为一轮，超过后会智能压缩处理。',
    min: 1,
  },
  agent_max_steps: {
    title: '最大执行步数',
    hint: '单次对话中 Agent 最多调用工具的次数。',
    min: 1,
  },
};

/** The provider the console keys efforts by: LinkAI routing wins over the vendor. */
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
      showToast(`保存失败：${describeConnectError(e)}`);
    }
  };

  if (!config) {
    return (
      <View style={styles.root}>
        <PageHeader title="Agent 运行" onBack={navigation.goBack} />
        <EmptyState loading={!error} title="加载失败" hint={error ?? undefined} />
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
      <PageHeader title="Agent 运行" onBack={navigation.goBack} />
      <ScrollView contentContainerStyle={{paddingBottom: insets.bottom + 32}}>
        <GroupLabel style={styles.firstGroup}>上下文</GroupLabel>
        <SettingRow
          title="最大上下文 Token"
          detail="达到后压缩历史，0 为跟随模型窗口"
          value={tokens ? formatCount(tokens) : '跟随模型'}
          onPress={() => setEditing('agent_max_context_tokens')}
        />
        <SettingRow
          title="最大记忆轮次"
          detail="一问一答为一轮"
          value={`${config.agent_max_context_turns} 轮`}
          onPress={() => setEditing('agent_max_context_turns')}
        />
        <SettingRow
          title="最大执行步数"
          detail="单次对话最多调用工具的次数"
          value={`${config.agent_max_steps} 步`}
          onPress={() => setEditing('agent_max_steps')}
          last
        />

        <GroupLabel style={styles.group}>思考</GroupLabel>
        <SwitchRow
          title="深度思考"
          detail={`当前模型 ${config.model || '未配置'}`}
          value={config.enable_thinking}
          onValueChange={v => save({enable_thinking: v})}
          last={!config.enable_thinking || !effortOptions.length}
        />
        {config.enable_thinking && effortOptions.length > 0 && (
          <SettingRow
            title="思考强度"
            detail="按当前模型厂商支持的取值发送"
            value={effortOptions.find(o => o.value === effort)?.label ?? effort}
            onPress={() => setEffortOpen(true)}
            last
          />
        )}

        <GroupLabel style={styles.group}>协作与成长</GroupLabel>
        <SwitchRow
          title="子 Agent"
          detail="把可独立完成的任务交给子 Agent 并行执行，只把结论带回主对话"
          value={config.subagent_enabled}
          onValueChange={v => save({subagent_enabled: v})}
        />
        <SwitchRow
          title="自主进化"
          detail="会话空闲后自动复盘，沉淀记忆、优化技能、处理未完成事项"
          value={config.self_evolution_enabled}
          onValueChange={v => save({self_evolution_enabled: v})}
          last
        />
        <Footnote>保存后立即生效，不会清空已有会话。和网页控制台的「Agent 配置」是同一份设置。</Footnote>
      </ScrollView>

      <FieldSheet
        visible={!!editing}
        title={field?.title ?? ''}
        initial={editing ? String(config[editing]) : ''}
        keyboardType="number-pad"
        hint={field?.hint}
        allowEmpty={false}
        onSubmit={async raw => {
          if (!editing || !field) {
            return;
          }
          const value = Number(raw);
          if (!Number.isInteger(value) || value < field.min) {
            throw new Error(field.min ? `请输入不小于 ${field.min} 的整数` : '请输入 0 或正整数');
          }
          await update({[editing]: value});
        }}
        onClose={() => setEditing(null)}
      />
      <ChoiceSheet
        visible={effortOpen}
        title="思考强度"
        options={effortOptions.map(o => ({key: o.value, label: o.label}))}
        selected={effort}
        note="只对当前模型生效，换模型后按各自的设置。"
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
