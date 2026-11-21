import {faChevronRight} from '@fortawesome/free-solid-svg-icons';
import {useFocusEffect} from '@react-navigation/native';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useMemo, useRef, useState} from 'react';
import {ActivityIndicator, Pressable, RefreshControl, SectionList, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {getMemoryFiles} from '../api/cowApi';
import {AgentSheet} from '../components/AgentSheet';
import {Icon} from '../components/Icon';
import {SwipeTabs} from '../components/SwipeTabs';
import {EmptyState, GroupLabel, PageHeader, Segmented} from '../components/ui';
import {tr, trf, type MessageKey} from '../i18n';
import type {RootStackParamList} from '../navigation/types';
import type {MemoryCategory, MemoryFile} from '../protocol/resources';
import {agentParam, useViewedAgent} from '../store/agentStore';
import {describeConnectError} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {dateVars, formatBytes, shortTime, toDate} from '../utils/format';

type Props = StackScreenProps<RootStackParamList, 'Memory'>;
type Tab = 'memory' | 'evolution';
const TABS: readonly Tab[] = ['memory', 'evolution'];

const PAGE_SIZE = 50;

const TYPE_LABEL: Record<string, MessageKey> = {evolution: 'memory_evolution', dream: 'memory_dream'};

function fileTitle(f: MemoryFile): string {
  if (f.type === 'global') {
    return tr('memory_long_term');
  }
  const d = toDate(f.filename.replace(/\.md$/, ''));
  return d ? trf('memory_date', dateVars(d)) : f.filename.replace(/\.md$/, '');
}

function sectionsOf(tab: Tab, files: MemoryFile[]) {
  if (tab === 'evolution') {
    return files.length ? [{title: tr('memory_by_date'), data: files}] : [];
  }
  const global = files.filter(f => f.type === 'global');
  const daily = files.filter(f => f.type !== 'global');
  return [
    ...(global.length ? [{title: tr('memory_section_long'), data: global}] : []),
    ...(daily.length ? [{title: tr('memory_section_daily'), data: daily}] : []),
  ];
}

interface ListState {
  files: MemoryFile[];
  total: number;
  page: number;
}

export function MemoryScreen({navigation}: Props) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const viewed = useViewedAgent('memory');
  const scope = agentParam(viewed.agentId);
  const [tab, setTab] = useState<Tab>('memory');
  const [lists, setLists] = useState<Partial<Record<Tab, ListState>>>({});
  const [refreshing, setRefreshing] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [agentSheet, setAgentSheet] = useState(false);
  const generation = useRef(0);

  const load = useCallback(
    async (which: Tab, opts: {refresh?: boolean; page?: number} = {}) => {
      const gen = generation.current;
      const page = opts.page ?? 1;
      if (opts.refresh) {
        setRefreshing(true);
      }
      try {
        const res = await getMemoryFiles({category: which, agentId: scope, page, pageSize: PAGE_SIZE});
        if (gen !== generation.current) {
          return;
        }
        setLists(prev => ({
          ...prev,
          [which]: {
            files: page > 1 ? [...(prev[which]?.files ?? []), ...res.list] : res.list,
            total: res.total,
            page,
          },
        }));
        setError(null);
      } catch (e) {
        if (gen === generation.current) {
          setError(describeConnectError(e));
        }
      } finally {
        setRefreshing(false);
      }
    },
    [scope],
  );

  // Back from a file that was just edited shows its new size and time.
  useFocusEffect(
    useCallback(() => {
      if (viewed.ready) {
        load(tab);
      }
    }, [viewed.ready, load, tab]),
  );

  const switchAgent = (id: string) => {
    setAgentSheet(false);
    generation.current += 1;
    setLists({});
    setError(null);
    viewed.select(id);
  };

  const list = lists[tab];
  const sections = useMemo(() => (list ? sectionsOf(tab, list.files) : []), [tab, list]);
  const hasMore = !!list && list.files.length < list.total;

  const loadMore = async () => {
    if (!list || !hasMore || loadingMore) {
      return;
    }
    setLoadingMore(true);
    await load(tab, {page: list.page + 1});
    setLoadingMore(false);
  };

  const open = (f: MemoryFile) => {
    const category: MemoryCategory = tab === 'memory' ? 'memory' : f.type === 'dream' ? 'dream' : 'evolution';
    navigation.navigate('MemoryDoc', {filename: f.filename, category, title: fileTitle(f), agentId: scope});
  };

  return (
    <View style={styles.root}>
      <PageHeader
        title={tr('memory_title')}
        subtitle={viewed.multi ? viewed.agent?.name ?? viewed.agentId ?? undefined : undefined}
        onTitlePress={viewed.multi ? () => setAgentSheet(true) : undefined}
        onBack={navigation.goBack}
      />
      <Segmented
        value={tab}
        onChange={setTab}
        options={[
          {key: 'memory', label: tr('memory_title'), count: lists.memory?.total},
          {key: 'evolution', label: tr('memory_evolution'), count: lists.evolution?.total},
        ]}
      />
      <SwipeTabs tabs={TABS} value={tab} onChange={setTab}>
        <SectionList
          sections={sections}
          keyExtractor={f => `${f.type}:${f.filename}`}
          stickySectionHeadersEnabled={false}
          contentContainerStyle={[styles.list, {paddingBottom: insets.bottom + 24}]}
          renderSectionHeader={({section}) => <GroupLabel style={styles.groupLabel} small>{section.title}</GroupLabel>}
          renderItem={({item}) => (
            <Pressable
              accessibilityRole="button"
              onPress={() => open(item)}
              style={({pressed}) => [styles.row, pressed && styles.rowPressed]}>
              <View style={styles.rowText}>
                <View style={styles.titleRow}>
                  <Text style={styles.title} numberOfLines={1}>
                    {fileTitle(item)}
                  </Text>
                  {!!TYPE_LABEL[item.type] && (
                    <Text style={[styles.badge, item.type === 'dream' && styles.badgeDream]}>{tr(TYPE_LABEL[item.type])}</Text>
                  )}
                </View>
                <Text style={styles.meta} numberOfLines={1}>
                  {[item.filename, formatBytes(item.size), trf('memory_updated_at', {time: shortTime(item.updated_at)})].join(' · ')}
                </Text>
              </View>
              <Icon icon={faChevronRight} size={10} color={t.t4} />
            </Pressable>
          )}
          onEndReachedThreshold={0.4}
          onEndReached={loadMore}
          ListFooterComponent={loadingMore ? <ActivityIndicator style={styles.more} color={t.t3} /> : null}
          ListEmptyComponent={
            <EmptyState
              loading={!list && !error}
              title={
                error ? tr('common_load_failed') : tab === 'memory' ? tr('memory_empty') : tr('memory_evolution_empty')
              }
              hint={error ?? (tab === 'memory' ? tr('memory_empty_hint') : tr('memory_evolution_empty_hint'))}
            />
          }
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => load(tab, {refresh: true})}
              tintColor={t.t3}
              colors={[t.green]}
            />
          }
        />
      </SwipeTabs>
      <AgentSheet
        visible={agentSheet}
        title={tr('memory_pick_agent')}
        selectedId={viewed.agentId}
        onSelect={switchAgent}
        onClose={() => setAgentSheet(false)}
      />
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  list: {paddingTop: 4, flexGrow: 1},
  groupLabel: {marginTop: 16},
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    marginHorizontal: 8,
    paddingHorizontal: 10,
    paddingVertical: 11,
    borderRadius: radius.sm,
  },
  rowPressed: {backgroundColor: t.bg2},
  rowText: {flex: 1, minWidth: 0},
  titleRow: {flexDirection: 'row', alignItems: 'center', gap: 8},
  title: {fontSize: 15, color: t.t1, flexShrink: 1},
  badge: {
    fontSize: 11,
    color: t.green,
    backgroundColor: t.bg2,
    paddingHorizontal: 6,
    paddingVertical: 1,
    borderRadius: 4,
    overflow: 'hidden',
  },
  badgeDream: {color: t.accent},
  meta: {fontSize: 12, color: t.t3, marginTop: 4, fontVariant: ['tabular-nums']},
  more: {paddingVertical: 16},
}));
