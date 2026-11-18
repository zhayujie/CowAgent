import {faChevronRight, faPlus} from '@fortawesome/free-solid-svg-icons';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useEffect, useState} from 'react';
import {Pressable, RefreshControl, ScrollView, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {AgentAvatar} from '../components/AgentAvatar';
import {Icon} from '../components/Icon';
import {Footnote} from '../components/settings';
import {EmptyState, IconButton, PageHeader} from '../components/ui';
import {tr, trf} from '../i18n';
import type {RootStackParamList} from '../navigation/types';
import type {AgentProfile} from '../protocol/resources';
import {useAgentStore} from '../store/agentStore';
import {useConfigStore} from '../store/configStore';
import {describeConnectError} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';

type Props = StackScreenProps<RootStackParamList, 'Agents'>;

/** "gpt-5" for an Agent with its own model, "跟随全局 · gpt-5" otherwise. */
export function agentModelLabel(agent: AgentProfile, globalModel?: string): string {
  if (agent.model) {
    return agent.model;
  }
  return globalModel ? trf('agent_follow_global_model', {model: globalModel}) : tr('agent_follow_global');
}

export function AgentsScreen({navigation}: Props) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const roster = useAgentStore(s => s.roster);
  const defaultId = useAgentStore(s => s.defaultId);
  const currentId = useAgentStore(s => s.currentId);
  const load = useAgentStore(s => s.load);
  const config = useConfigStore(s => s.config);
  const loadConfig = useConfigStore(s => s.load);
  const [loaded, setLoaded] = useState(roster.length > 0);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [bannerClosed, setBannerClosed] = useState(false);

  const reload = useCallback(async () => {
    try {
      await Promise.all([load(), loadConfig().catch(() => undefined)]);
      setError(null);
    } catch (e) {
      setError(describeConnectError(e));
    } finally {
      setLoaded(true);
    }
  }, [load, loadConfig]);

  useEffect(() => {
    reload();
  }, [reload]);

  const sorted = [...roster].sort((a, b) => {
    const rank = (x: AgentProfile) => (x.id === defaultId ? 0 : x.enabled === false ? 2 : 1);
    return rank(a) - rank(b);
  });
  const readOnly = config?.agent_permission_mode === 'read-only';

  return (
    <View style={styles.root}>
      <PageHeader
        title={tr('agent_title')}
        count={roster.length || undefined}
        onBack={navigation.goBack}
        right={
          <IconButton
            icon={faPlus}
            label={tr('agent_create')}
            filled
            size={13}
            color={t.t1}
            onPress={() => navigation.navigate('AgentCreate')}
          />
        }
      />
      <ScrollView
        contentContainerStyle={[styles.body, {paddingBottom: insets.bottom + 32}]}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={async () => {
              setRefreshing(true);
              await reload();
              setRefreshing(false);
            }}
            tintColor={t.t3}
            colors={[t.green]}
          />
        }>
        {readOnly && !bannerClosed && (
          <View style={styles.banner}>
            <Text style={styles.bannerText} numberOfLines={1}>
              <Text style={styles.bannerStrong}>{tr('agent_read_only')}</Text>
              <Text style={styles.bannerDot}> · </Text>
              {tr('agent_read_only_desc')}
            </Text>
            <Pressable hitSlop={10} accessibilityLabel={tr('agent_dismiss_banner')} onPress={() => setBannerClosed(true)}>
              <Text style={styles.bannerClose}>×</Text>
            </Pressable>
          </View>
        )}

        {!sorted.length ? (
          <EmptyState
            loading={!loaded}
            title={error ? tr('common_load_failed') : tr('agent_empty')}
            hint={error ?? undefined}
          />
        ) : (
          sorted.map(agent => {
            const isDefault = agent.id === defaultId;
            const archived = agent.enabled === false;
            const inUse = !archived && agent.id === currentId;
            const tag = archived
              ? tr('agent_archived')
              : inUse
                ? tr('agent_in_use')
                : isDefault
                  ? tr('agent_default_badge')
                  : '';
            const skills = agent.skills == null ? tr('common_all') : String(agent.skills.length);
            return (
              <Pressable
                key={agent.id}
                accessibilityRole="button"
                onPress={() => navigation.navigate('AgentDetail', {agentId: agent.id})}
                style={({pressed}) => [styles.card, archived && styles.cardArchived, pressed && styles.pressed]}>
                <View style={styles.head}>
                  <AgentAvatar agent={agent} isDefault={isDefault} size={38} />
                  <View style={styles.headText}>
                    <Text style={styles.name} numberOfLines={1}>
                      {agent.name || agent.id}
                    </Text>
                    <Text style={styles.model} numberOfLines={1}>
                      {agentModelLabel(agent, config?.model)}
                    </Text>
                  </View>
                  {!!tag && (
                    <View style={[styles.tag, inUse && styles.tagOn]}>
                      <Text style={[styles.tagText, inUse && styles.tagTextOn]}>{tag}</Text>
                    </View>
                  )}
                </View>
                {!!agent.description && (
                  <Text style={styles.desc} numberOfLines={2}>
                    {agent.description}
                  </Text>
                )}
                <View style={styles.meta}>
                  <Text style={styles.metaText}>
                    {tr('agent_skills')} <Text style={styles.metaValue}>{skills}</Text>
                  </Text>
                  <Text style={styles.metaText}>
                    {tr('agent_knowledge')}{' '}
                    <Text style={styles.metaValue}>
                      {agent.knowledge_mode === 'own' ? tr('agent_knowledge_own') : tr('agent_knowledge_shared')}
                    </Text>
                  </Text>
                  <View style={styles.metaFlex} />
                  <Icon icon={faChevronRight} size={10} color={t.t4} />
                </View>
              </Pressable>
            );
          })
        )}
        {sorted.length > 1 && (
          <Footnote>{tr('agent_team_note')}</Footnote>
        )}
      </ScrollView>
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  body: {paddingTop: 6, flexGrow: 1},
  banner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    marginHorizontal: 14,
    marginBottom: 12,
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: radius.sm,
    backgroundColor: t.bg1,
    borderWidth: 1,
    borderColor: t.line2,
  },
  bannerText: {flex: 1, fontSize: 13, color: t.t2},
  bannerStrong: {color: t.t1, fontWeight: '600'},
  bannerDot: {color: t.t4},
  bannerClose: {fontSize: 17, lineHeight: 18, color: t.t4},
  card: {
    marginHorizontal: 14,
    marginBottom: 10,
    paddingHorizontal: 16,
    paddingTop: 15,
    paddingBottom: 13,
    borderRadius: radius.md,
    backgroundColor: t.bg1,
    borderWidth: 1,
    borderColor: t.line1,
  },
  cardArchived: {opacity: 0.6},
  pressed: {backgroundColor: t.bg2},
  head: {flexDirection: 'row', alignItems: 'center', gap: 12},
  headText: {flex: 1, minWidth: 0},
  name: {fontSize: 16, fontWeight: '600', letterSpacing: -0.2, color: t.t1},
  model: {fontSize: 12, color: t.t3, marginTop: 3},
  tag: {paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6, backgroundColor: t.bg3},
  tagOn: {backgroundColor: t.accentSoft},
  tagText: {fontSize: 11, fontWeight: '500', color: t.t3},
  tagTextOn: {color: t.accent},
  desc: {fontSize: 13, lineHeight: 20, color: t.t2, marginTop: 11},
  meta: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 16,
    marginTop: 13,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: t.line1,
  },
  metaText: {fontSize: 12, color: t.t4},
  metaValue: {color: t.t2, fontWeight: '500'},
  metaFlex: {flex: 1},
}));
