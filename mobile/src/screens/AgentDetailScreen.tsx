import type {StackScreenProps} from '@react-navigation/stack';
import React, {useState} from 'react';
import {ScrollView, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {getModels, newSessionId} from '../api/cowApi';
import {AgentAvatar} from '../components/AgentAvatar';
import {ModelPicker} from '../components/ModelPicker';
import {ActionButton, ConfirmSheet, FieldSheet, Footnote, SettingRow, SwitchRow} from '../components/settings';
import {showToast, ToastHost} from '../components/Toast';
import {EmptyState, GroupLabel, PageHeader} from '../components/ui';
import type {RootStackParamList} from '../navigation/types';
import type {AgentCoreFile, ProviderEntry} from '../protocol/resources';
import {useAgentStore} from '../store/agentStore';
import {useConfigStore} from '../store/configStore';
import {describeConnectError} from '../store/serverStore';
import {makeStyles} from '../theme/theme';
import {copyText} from '../utils/clipboard';
import {agentModelLabel} from './AgentsScreen';

type Props = StackScreenProps<RootStackParamList, 'AgentDetail'>;

export const CORE_FILE_META: {name: AgentCoreFile; label: string}[] = [
  {name: 'AGENT.md', label: '智能体设定'},
  {name: 'USER.md', label: '用户信息'},
  {name: 'RULE.md', label: '工作空间规则'},
  {name: 'MEMORY.md', label: '长期记忆'},
];

type Editing = 'name' | 'description' | null;

export function AgentDetailScreen({route, navigation}: Props) {
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const {agentId} = route.params;
  const agent = useAgentStore(s => s.roster.find(a => a.id === agentId));
  const defaultId = useAgentStore(s => s.defaultId);
  const currentId = useAgentStore(s => s.currentId);
  const update = useAgentStore(s => s.update);
  const globalModel = useConfigStore(s => s.config?.model);
  const [editing, setEditing] = useState<Editing>(null);
  const [providers, setProviders] = useState<ProviderEntry[] | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [confirmDefault, setConfirmDefault] = useState(false);

  if (!agent) {
    return (
      <View style={styles.root}>
        <PageHeader title="Agent" onBack={navigation.goBack} />
        <EmptyState title="这个 Agent 已不存在" hint="可能已在网页控制台删除" />
      </View>
    );
  }

  const isDefault = agent.id === defaultId;
  const archived = agent.enabled === false;

  const apply = async (patch: Parameters<typeof update>[1], done?: string) => {
    try {
      await update(agent.id, patch);
      if (done) {
        showToast(done);
      }
    } catch (e) {
      showToast(`保存失败：${describeConnectError(e)}`);
      throw e;
    }
  };

  const openPicker = async () => {
    setPickerOpen(true);
    if (!providers) {
      try {
        setProviders((await getModels()).providers);
      } catch (e) {
        setPickerOpen(false);
        showToast(`模型列表加载失败：${describeConnectError(e)}`);
      }
    }
  };

  const startChat = () => {
    useAgentStore.getState().select(agent.id);
    navigation.popTo('Chat', {sessionId: newSessionId(), isNew: true});
  };

  return (
    <View style={styles.root}>
      <PageHeader title={agent.name || agent.id} onBack={navigation.goBack} />
      <ScrollView contentContainerStyle={{paddingBottom: insets.bottom + 32}}>
        <View style={styles.hero}>
          <AgentAvatar agent={agent} isDefault={isDefault} size={56} />
          <View style={styles.heroText}>
            <Text style={styles.heroName} numberOfLines={1}>
              {agent.name || agent.id}
            </Text>
            <Text style={styles.heroMeta} numberOfLines={1}>
              {[isDefault ? '默认 Agent' : null, agent.id === currentId ? '在用' : null, archived ? '已归档' : null]
                .filter(Boolean)
                .join(' · ') || agent.id}
            </Text>
          </View>
        </View>
        {!!agent.description && <Text style={styles.heroDesc}>{agent.description}</Text>}
        {!archived && (
          <View style={styles.primary}>
            <ActionButton label="和它开始新对话" tone="primary" onPress={startChat} />
          </View>
        )}

        <GroupLabel style={styles.group}>概况</GroupLabel>
        <SettingRow title="名称" value={agent.name} onPress={() => setEditing('name')} chevron />
        <SettingRow
          title="职责"
          detail={agent.description || '暂无职责'}
          onPress={() => setEditing('description')}
          chevron
        />
        {isDefault ? (
          <SettingRow
            title="默认模型"
            detail="默认 Agent 使用主模型，在「模型与接口」中修改"
            value={globalModel}
            onPress={() => navigation.navigate('Models')}
            chevron
          />
        ) : (
          <SettingRow title="默认模型" value={agentModelLabel(agent, globalModel)} onPress={openPicker} chevron />
        )}
        <SettingRow
          title="知识库"
          value={agent.knowledge_mode === 'own' ? '独立' : '共享'}
          detail={agent.knowledge_mode === 'own' ? '拥有专属知识库，和其他成员互不影响' : '和团队读写同一个知识库'}
        />
        <SettingRow title="技能" value={agent.skills == null ? '全部已安装技能' : `${agent.skills.length} 个`} last />

        <GroupLabel style={styles.group}>核心文件</GroupLabel>
        {CORE_FILE_META.map((f, i) => (
          <SettingRow
            key={f.name}
            title={f.label}
            value={f.name}
            mono
            onPress={() => navigation.navigate('AgentFile', {agentId: agent.id, name: f.name})}
            chevron
            last={i === CORE_FILE_META.length - 1}
          />
        ))}

        {!isDefault && (
          <>
            <GroupLabel style={styles.group}>管理</GroupLabel>
            {!archived && (
              <SettingRow title="设为默认 Agent" detail="新会话和未绑定的通道都会交给它" onPress={() => setConfirmDefault(true)} chevron />
            )}
            <SwitchRow
              title="启用"
              detail={archived ? '已归档：保留工作空间和记录，不再接收新对话' : '关闭后归档，保留工作空间和记录'}
              value={!archived}
              onValueChange={v => apply({enabled: v}, v ? '已恢复' : '已归档').catch(() => undefined)}
              last
            />
          </>
        )}

        <GroupLabel style={styles.group}>信息</GroupLabel>
        <SettingRow
          title="ID"
          value={agent.id}
          mono
          onPress={async () => showToast((await copyText(agent.id)) ? '已复制 ID' : '复制失败')}
        />
        <SettingRow title="工作空间" detail={agent.workspace} last />
        <Footnote>头像、技能勾选和删除 Agent 请在网页控制台操作。</Footnote>
      </ScrollView>

      <FieldSheet
        visible={editing === 'name'}
        title="名称"
        initial={agent.name}
        placeholder="Agent 名称"
        onSubmit={async v => {
          await update(agent.id, {name: v.trim()});
          showToast('已保存');
        }}
        onClose={() => setEditing(null)}
      />
      <FieldSheet
        visible={editing === 'description'}
        title="职责"
        initial={agent.description ?? ''}
        placeholder="该 Agent 负责哪些工作、在什么场景被使用"
        hint="用于多 Agent 协作时的任务分配"
        multiline
        allowEmpty
        onSubmit={async v => {
          await update(agent.id, {description: v.trim()});
          showToast('已保存');
        }}
        onClose={() => setEditing(null)}
      />
      <ModelPicker
        visible={pickerOpen && !!providers}
        title="默认模型"
        providers={providers ?? []}
        selected={agent.model ? {provider: agent.bot_type ?? '', model: agent.model} : null}
        lead={{
          label: '跟随全局',
          desc: globalModel ? `当前全局模型 ${globalModel}` : undefined,
          active: !agent.model,
          onPress: () => {
            setPickerOpen(false);
            apply({model: '', bot_type: ''}, '已改为跟随全局').catch(() => undefined);
          },
        }}
        onSelect={pick => {
          setPickerOpen(false);
          apply({model: pick.model, bot_type: pick.provider}, '已保存').catch(() => undefined);
        }}
        onClose={() => setPickerOpen(false)}
      />
      <ConfirmSheet
        visible={confirmDefault}
        title={`把 ${agent.name} 设为默认`}
        message={
          agent.model
            ? '默认 Agent 统一使用主模型，它单独设置的模型会被清除。新会话和未绑定的通道都会交给它。'
            : '新会话和未绑定的通道都会交给它，原来的默认 Agent 变为普通成员。'
        }
        confirmLabel="设为默认"
        onConfirm={async () => {
          try {
            await apply({make_default: true}, '已设为默认');
          } finally {
            setConfirmDefault(false);
          }
        }}
        onClose={() => setConfirmDefault(false)}
      />
      <ToastHost bottom={insets.bottom + 28} />
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  hero: {flexDirection: 'row', alignItems: 'center', gap: 14, paddingHorizontal: 18, paddingTop: 10},
  heroText: {flex: 1, minWidth: 0},
  heroName: {fontSize: 20, fontWeight: '600', letterSpacing: -0.4, color: t.t1},
  heroMeta: {fontSize: 13, color: t.t3, marginTop: 4},
  heroDesc: {fontSize: 14, lineHeight: 22, color: t.t2, paddingHorizontal: 18, paddingTop: 14},
  primary: {paddingHorizontal: 18, paddingTop: 18},
  group: {marginTop: 28},
}));
