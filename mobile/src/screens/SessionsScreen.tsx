import type {StackScreenProps} from '@react-navigation/stack';
import React, {useEffect, useMemo, useState} from 'react';
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  SectionList,
  Text,
  View,
} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {SessionActions, SpaceActions} from '../components/SessionActions';
import {SpaceHeader, SpaceMore} from '../components/SpaceHeader';
import {EmptyState, GroupLabel, PageHeader} from '../components/ui';
import {tr, trf} from '../i18n';
import type {RootStackParamList} from '../navigation/types';
import type {SessionItem} from '../protocol/events';
import {useAgentStore} from '../store/agentStore';
import {useChatStore} from '../store/chatStore';
import {useLayoutStore} from '../store/layoutStore';
import {useSessionStore} from '../store/sessionStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {shortTime} from '../utils/format';
import {groupSessions, type SessionGroup, type Space} from '../utils/sessionGroups';

type Props = StackScreenProps<RootStackParamList, 'Sessions'>;

export function SessionsScreen({navigation}: Props) {
  const styles = useStyles();
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const sessions = useSessionStore(s => s.sessions);
  const total = useSessionStore(s => s.total);
  const loading = useSessionStore(s => s.loading);
  const loadingMore = useSessionStore(s => s.loadingMore);
  const error = useSessionStore(s => s.error);
  const currentSessionId = useChatStore(s => s.currentSessionId);
  const agentCount = useAgentStore(s => s.agents.length);
  const groupMode = useSessionStore(s => s.groupMode);
  const projectOrder = useSessionStore(s => s.projectOrder);
  const spaces = useSessionStore(s => s.spaces);
  const spacesLoading = useSessionStore(s => s.spacesLoading);
  const collapsed = useSessionStore(s => s.collapsed);
  const [acting, setActing] = useState<SessionItem | null>(null);
  const [actingSpace, setActingSpace] = useState<SessionGroup | null>(null);

  useEffect(() => {
    useSessionStore.getState().refresh();
  }, []);

  const bySpace = groupMode === 'project';
  // Spaces page on their own once the server lists them; older servers page the whole list.
  const pagesAll = !bySpace || !spaces.length;
  const groups = useMemo(
    () => groupSessions(sessions, groupMode, projectOrder, spaces),
    [sessions, groupMode, projectOrder, spaces],
  );
  const sections = useMemo(
    () => groups.map(g => ({...g, group: g, data: bySpace && collapsed.includes(g.key) ? [] : g.data})),
    [groups, bySpace, collapsed],
  );

  const open = (session: SessionItem) => {
    if (session.agent?.id) {
      useAgentStore.getState().select(session.agent.id);
    }
    navigation.popTo('Chat', {sessionId: session.session_id, isNew: false});
  };

  const newChatIn = (space: Space) => {
    navigation.popToTop();
    useLayoutStore.getState().chat?.newChatIn(space);
  };

  return (
    <View style={styles.root}>
      <PageHeader title={tr('session_all_title')} count={total || undefined} onBack={navigation.goBack} />
      <SectionList
        sections={sections}
        keyExtractor={s => s.session_id}
        stickySectionHeadersEnabled={false}
        contentContainerStyle={[styles.list, {paddingBottom: insets.bottom + 24}]}
        renderSectionHeader={({section}) =>
          bySpace ? (
            <SpaceHeader
              group={section.group}
              collapsed={collapsed.includes(section.key)}
              onToggle={() => useSessionStore.getState().toggleCollapsed(section.key)}
              onLongPress={() => setActingSpace(section.group)}
              style={styles.space}
            />
          ) : (
            <GroupLabel style={styles.groupLabel} small>{section.title}</GroupLabel>
          )
        }
        renderSectionFooter={({section}) =>
          bySpace && !collapsed.includes(section.key) ? (
            <SpaceMore
              group={section.group}
              loading={spacesLoading.includes(section.key)}
              onPress={() => useSessionStore.getState().loadSpace(section.key)}
              style={styles.spaceMore}
            />
          ) : null
        }
        renderItem={({item}) => (
          <SessionRow
            session={item}
            active={item.session_id === currentSessionId}
            showAgent={agentCount > 1}
            onPress={() => open(item)}
            onLongPress={() => setActing(item)}
          />
        )}
        refreshControl={
          <RefreshControl
            refreshing={loading && sessions.length > 0}
            onRefresh={() => useSessionStore.getState().refresh()}
            tintColor={t.t3}
            colors={[t.green]}
          />
        }
        onEndReachedThreshold={0.4}
        onEndReached={() => pagesAll && useSessionStore.getState().loadMore()}
        ListEmptyComponent={
          <EmptyState
            loading={loading}
            title={error ? tr('common_load_failed') : tr('session_empty')}
            hint={error ?? tr('session_empty_hint')}
          />
        }
        ListFooterComponent={
          loadingMore ? <ActivityIndicator style={styles.footer} color={t.t3} /> : null
        }
      />
      <SessionActions session={acting} onClose={() => setActing(null)} />
      <SpaceActions
        group={actingSpace}
        keys={groups.map(g => g.key)}
        onClose={() => setActingSpace(null)}
        onNewChat={newChatIn}
      />
    </View>
  );
}

function SessionRow({
  session,
  active,
  showAgent,
  onPress,
  onLongPress,
}: {
  session: SessionItem;
  active: boolean;
  showAgent: boolean;
  onPress: () => void;
  onLongPress: () => void;
}) {
  const styles = useStyles();
  const meta = [showAgent ? session.agent?.name : null, trf('session_msg_count', {n: session.msg_count})]
    .filter(Boolean)
    .join(' · ');
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{selected: active}}
      accessibilityHint={tr('session_row_hint')}
      onPress={onPress}
      onLongPress={onLongPress}
      delayLongPress={350}
      style={({pressed}) => [styles.row, active && styles.rowActive, pressed && !active && styles.rowPressed]}>
      <View style={styles.rowText}>
        <Text style={[styles.title, active && styles.titleActive]} numberOfLines={1}>
          {session.title || tr('session_untitled')}
        </Text>
        <Text style={styles.meta} numberOfLines={1}>
          {meta}
        </Text>
      </View>
      <Text style={styles.time}>{shortTime(session.last_active)}</Text>
    </Pressable>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  list: {paddingTop: 10, flexGrow: 1},
  groupLabel: {marginTop: 14},
  space: {marginHorizontal: 10, marginTop: 10},
  spaceMore: {marginHorizontal: 10, paddingHorizontal: 12},
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    marginHorizontal: 10,
    paddingHorizontal: 12,
    paddingVertical: 12,
    borderRadius: radius.sm,
  },
  rowActive: {backgroundColor: t.accentSoft},
  rowPressed: {backgroundColor: t.bg2},
  rowText: {flex: 1, minWidth: 0},
  title: {fontSize: 15, color: t.t1, letterSpacing: -0.1},
  titleActive: {fontWeight: '600'},
  meta: {fontSize: 12, color: t.t3, marginTop: 4},
  time: {fontSize: 12, color: t.t4, fontVariant: ['tabular-nums']},
  footer: {paddingVertical: 16},
}));
