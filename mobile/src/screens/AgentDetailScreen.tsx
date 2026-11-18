import type {StackScreenProps} from '@react-navigation/stack';
import React, {useState} from 'react';
import {ScrollView, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {getModels, newSessionId} from '../api/cowApi';
import {AgentAvatar} from '../components/AgentAvatar';
import {ModelPicker} from '../components/ModelPicker';
import {
  ActionButton,
  ChoiceSheet,
  ConfirmSheet,
  FieldSheet,
  SettingRow,
  SwitchRow,
  type Choice,
} from '../components/settings';
import {showToast, ToastHost} from '../components/Toast';
import {EmptyState, GroupLabel, PageHeader} from '../components/ui';
import {tr, trf} from '../i18n';
import type {RootStackParamList} from '../navigation/types';
import type {AgentCoreFile, ProviderEntry} from '../protocol/resources';
import {useAgentStore} from '../store/agentStore';
import {useConfigStore} from '../store/configStore';
import {describeConnectError} from '../store/serverStore';
import {makeStyles} from '../theme/theme';
import {copyText} from '../utils/clipboard';
import {agentModelLabel} from './AgentsScreen';

type Props = StackScreenProps<RootStackParamList, 'AgentDetail'>;

const KNOWLEDGE_OPTIONS = (): Choice<'shared' | 'own'>[] => [
  {key: 'shared', label: tr('agent_knowledge_shared'), desc: tr('agent_knowledge_shared_desc')},
  {key: 'own', label: tr('agent_knowledge_own'), desc: tr('agent_knowledge_own_desc')},
];

export const CORE_FILE_META: {name: AgentCoreFile; label: string}[] = [
  {
    name: 'AGENT.md',
    get label() {
      return tr('agent_core_file_agent');
    },
  },
  {
    name: 'USER.md',
    get label() {
      return tr('agent_core_file_user');
    },
  },
  {
    name: 'RULE.md',
    get label() {
      return tr('agent_core_file_rule');
    },
  },
  {
    name: 'MEMORY.md',
    get label() {
      return tr('agent_core_file_memory');
    },
  },
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
  const setKnowledgeMode = useAgentStore(s => s.setKnowledgeMode);
  const globalModel = useConfigStore(s => s.config?.model);
  const [editing, setEditing] = useState<Editing>(null);
  const [providers, setProviders] = useState<ProviderEntry[] | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [confirmDefault, setConfirmDefault] = useState(false);
  const [knowledgeSheet, setKnowledgeSheet] = useState(false);
  const [knowledgeBusy, setKnowledgeBusy] = useState(false);

  if (!agent) {
    return (
      <View style={styles.root}>
        <PageHeader title="Agent" onBack={navigation.goBack} />
        <EmptyState title={tr('agent_gone')} hint={tr('agent_gone_hint')} />
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
      showToast(trf('common_save_failed_detail', {error: describeConnectError(e)}));
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
        showToast(trf('agent_models_load_failed', {error: describeConnectError(e)}));
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
              {[
                isDefault ? tr('agent_default') : null,
                agent.id === currentId ? tr('agent_in_use') : null,
                archived ? tr('agent_archived') : null,
              ]
                .filter(Boolean)
                .join(' · ') || agent.id}
            </Text>
          </View>
        </View>
        {!!agent.description && <Text style={styles.heroDesc}>{agent.description}</Text>}
        {!archived && (
          <View style={styles.primary}>
            <ActionButton label={tr('agent_start_chat')} tone="primary" onPress={startChat} />
          </View>
        )}

        <GroupLabel style={styles.group}>{tr('agent_overview')}</GroupLabel>
        <SettingRow title={tr('common_name')} value={agent.name} onPress={() => setEditing('name')} chevron />
        <SettingRow
          title={tr('agent_duty')}
          detail={agent.description || tr('agent_no_duty')}
          onPress={() => setEditing('description')}
          chevron
        />
        {isDefault ? (
          <SettingRow
            title={tr('agent_default_model')}
            detail={tr('agent_default_model_hint')}
            value={globalModel}
            onPress={() => navigation.navigate('Models')}
            chevron
          />
        ) : (
          <SettingRow
            title={tr('agent_default_model')}
            value={agentModelLabel(agent, globalModel)}
            onPress={openPicker}
            chevron
          />
        )}
        <SettingRow
          title={tr('agent_knowledge')}
          value={agent.knowledge_mode === 'own' ? tr('agent_knowledge_own') : tr('agent_knowledge_shared')}
          detail={agent.knowledge_mode === 'own' ? tr('agent_knowledge_own_desc') : tr('agent_knowledge_shared_desc')}
          // The default Agent's knowledge directory is the shared library; only members can switch.
          onPress={isDefault || knowledgeBusy ? undefined : () => setKnowledgeSheet(true)}
          chevron={!isDefault}
        />
        <SettingRow
          title={tr('agent_skills')}
          value={agent.skills == null ? tr('agent_skills_all') : trf('agent_skills_count', {n: agent.skills.length})}
          onPress={() => navigation.navigate('AgentSkills', {agentId: agent.id})}
          chevron
          last
        />

        <GroupLabel style={styles.group}>{tr('agent_core_files')}</GroupLabel>
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
            <GroupLabel style={styles.group}>{tr('agent_manage')}</GroupLabel>
            {!archived && (
              <SettingRow
                title={tr('agent_make_default')}
                detail={tr('agent_make_default_desc')}
                onPress={() => setConfirmDefault(true)}
                chevron
              />
            )}
            <SwitchRow
              title={tr('agent_enabled')}
              detail={archived ? tr('agent_archived_desc') : tr('agent_archive_desc')}
              value={!archived}
              onValueChange={v => apply({enabled: v}, v ? tr('agent_restored') : tr('agent_archived')).catch(() => undefined)}
              last
            />
          </>
        )}

        <GroupLabel style={styles.group}>{tr('agent_info')}</GroupLabel>
        <SettingRow
          title="ID"
          value={agent.id}
          mono
          onPress={async () => showToast((await copyText(agent.id)) ? tr('agent_id_copied') : tr('agent_copy_failed'))}
          last
        />
      </ScrollView>

      <FieldSheet
        visible={editing === 'name'}
        title={tr('common_name')}
        initial={agent.name}
        placeholder={tr('agent_name_placeholder')}
        onSubmit={async v => {
          await update(agent.id, {name: v.trim()});
          showToast(tr('common_saved'));
        }}
        onClose={() => setEditing(null)}
      />
      <FieldSheet
        visible={editing === 'description'}
        title={tr('agent_duty')}
        initial={agent.description ?? ''}
        placeholder={tr('agent_duty_placeholder')}
        hint={tr('agent_duty_hint')}
        multiline
        allowEmpty
        onSubmit={async v => {
          await update(agent.id, {description: v.trim()});
          showToast(tr('common_saved'));
        }}
        onClose={() => setEditing(null)}
      />
      <ModelPicker
        visible={pickerOpen && !!providers}
        title={tr('agent_default_model')}
        providers={providers ?? []}
        selected={agent.model ? {provider: agent.bot_type ?? '', model: agent.model} : null}
        lead={{
          label: tr('agent_follow_global'),
          desc: globalModel ? trf('agent_global_model_current', {model: globalModel}) : undefined,
          active: !agent.model,
          onPress: () => {
            setPickerOpen(false);
            apply({model: '', bot_type: ''}, tr('agent_followed_global')).catch(() => undefined);
          },
        }}
        onSelect={pick => {
          setPickerOpen(false);
          apply({model: pick.model, bot_type: pick.provider}, tr('common_saved')).catch(() => undefined);
        }}
        onClose={() => setPickerOpen(false)}
      />
      <ConfirmSheet
        visible={confirmDefault}
        title={trf('agent_make_default_title', {name: agent.name})}
        message={agent.model ? tr('agent_make_default_msg_model') : tr('agent_make_default_msg')}
        confirmLabel={tr('agent_set_default')}
        onConfirm={async () => {
          try {
            await apply({make_default: true}, tr('agent_set_default_done'));
          } finally {
            setConfirmDefault(false);
          }
        }}
        onClose={() => setConfirmDefault(false)}
      />
      <ChoiceSheet
        visible={knowledgeSheet}
        title={tr('agent_knowledge')}
        selected={agent.knowledge_mode === 'own' ? 'own' : 'shared'}
        options={KNOWLEDGE_OPTIONS()}
        onSelect={async mode => {
          setKnowledgeSheet(false);
          if (mode === (agent.knowledge_mode === 'own' ? 'own' : 'shared')) {
            return;
          }
          setKnowledgeBusy(true);
          try {
            await setKnowledgeMode(agent.id, mode);
            showToast(tr('common_saved'));
          } catch (e) {
            showToast(trf('agent_knowledge_failed', {error: describeConnectError(e)}));
          } finally {
            setKnowledgeBusy(false);
          }
        }}
        onClose={() => setKnowledgeSheet(false)}
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
