import {faMessage} from '@fortawesome/free-regular-svg-icons';
import {
  faArrowUpRightFromSquare,
  faChevronRight,
  faDownload,
  faLocationCrosshairs,
  faMagnifyingGlass,
  faShareNodes,
  faThumbtack,
  faXmark,
} from '@fortawesome/free-solid-svg-icons';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {
  ActivityIndicator,
  Image,
  Pressable,
  RefreshControl,
  ScrollView,
  Text,
  TextInput,
  View,
} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {getArtifacts, pinArtifact, serverUrl} from '../api/cowApi';
import {artifactFile, KIND_ICON, kindGroup, KindTile, openArtifact} from '../components/ArtifactStrip';
import {Icon} from '../components/Icon';
import {Sheet, SHEET_DISMISS_MS} from '../components/Sheet';
import {SwipeTabs} from '../components/SwipeTabs';
import {ToastHost} from '../components/Toast';
import {Chip, EmptyState, GroupLabel, IconButton, PageHeader} from '../components/ui';
import {downloadFile, openInBrowser, shareFile} from '../files/openFile';
import {tr, trf} from '../i18n';
import type {RootStackParamList} from '../navigation/types';
import type {Artifact} from '../protocol/events';
import {useAgentStore} from '../store/agentStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {dayLabel, shortTime, toDate} from '../utils/format';

type Props = StackScreenProps<RootStackParamList, 'Artifacts'>;

const filters = (): {key: string; label: string}[] => [
  {key: '', label: tr('common_all')},
  {key: 'web', label: tr('artifact_filter_web')},
  {key: 'doc', label: tr('artifact_filter_doc')},
  {key: 'image', label: tr('artifact_filter_image')},
  {key: 'media', label: tr('artifact_filter_media')},
];
const FILTER_KEYS = ['', 'web', 'doc', 'image', 'media'];
const PAGE = 60;

interface Group {
  title: string;
  cards: Artifact[];
  rows: Artifact[];
}

/** Pictures and pages read best as thumbnails; everything else as a row. */
const isCard = (a: Artifact) => {
  const g = kindGroup(a.kind);
  return g === 'image' || g === 'web';
};

function groupArtifacts(items: Artifact[]): Group[] {
  const groups: Group[] = [];
  const pinned = items.filter(a => a.pinned_at);
  const rest = items.filter(a => !a.pinned_at);
  const push = (title: string, a: Artifact) => {
    let g = groups.find(x => x.title === title);
    if (!g) {
      g = {title, cards: [], rows: []};
      groups.push(g);
    }
    (isCard(a) ? g.cards : g.rows).push(a);
  };
  pinned.forEach(a => push(tr('artifact_pinned'), a));
  rest.forEach(a => {
    const d = toDate(a.created_at);
    push(d ? dayLabel(d) : tr('artifact_earlier'), a);
  });
  return groups;
}

export function ArtifactsScreen({navigation, route}: Props) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const focusPath = route.params?.focusPath;
  const focusName = route.params?.focusName;
  const [focus, setFocus] = useState(focusPath ? {path: focusPath, name: focusName || focusPath} : null);
  useEffect(() => {
    if (focusPath) {
      setFocus(prev => (prev?.path === focusPath ? prev : {path: focusPath, name: focusName || focusPath}));
    }
  }, [focusPath, focusName]);
  const [kind, setKind] = useState('');
  const [query, setQuery] = useState('');
  const [searching, setSearching] = useState(false);
  const [items, setItems] = useState<Artifact[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [acting, setActing] = useState<Artifact | null>(null);
  const actingFile = acting?.exists === false ? null : acting && artifactFile(acting);
  const requestId = useRef(0);

  const load = useCallback(
    async (mode: 'reset' | 'refresh' | 'more') => {
      const id = ++requestId.current;
      const offset = mode === 'more' ? items.length : 0;
      if (mode === 'reset') {
        setLoading(true);
      } else if (mode === 'refresh') {
        setRefreshing(true);
      } else {
        setLoadingMore(true);
      }
      try {
        const res = focus
          ? await getArtifacts({path: focus.path, offset, limit: PAGE})
          : await getArtifacts({kind, q: query.trim(), offset, limit: PAGE});
        if (id !== requestId.current) {
          return;
        }
        setItems(prev => (mode === 'more' ? [...prev, ...res.items] : res.items));
        setHasMore(res.has_more);
        setError(null);
      } catch (e) {
        if (id === requestId.current) {
          setError(e instanceof Error ? e.message : String(e));
        }
      } finally {
        if (id === requestId.current) {
          setLoading(false);
          setRefreshing(false);
          setLoadingMore(false);
        }
      }
    },
    [kind, query, focus, items.length],
  );

  useEffect(() => {
    const timer = setTimeout(() => load('reset'), query ? 250 : 0);
    return () => clearTimeout(timer);
    // Only filter changes start a fresh list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, query, focus]);

  const groups = useMemo(() => groupArtifacts(items), [items]);

  const jumpTo = (a: Artifact) => {
    setActing(null);
    if (a.agent_id) {
      useAgentStore.getState().select(a.agent_id);
    }
    navigation.popTo('Chat', {sessionId: a.session_id, isNew: false});
  };

  const togglePin = async (a: Artifact) => {
    setActing(null);
    const pinned = !a.pinned_at;
    setItems(prev =>
      prev.map(x => (x.id === a.id && x.agent_id === a.agent_id ? {...x, pinned_at: pinned ? Date.now() / 1000 : 0} : x)),
    );
    try {
      await pinArtifact(a.id, a.agent_id, pinned);
    } catch {
      load('refresh');
    }
  };

  return (
    <View style={styles.root}>
      {searching ? (
        <View style={[styles.searchBar, {paddingTop: insets.top + 6}]}>
          <View style={styles.searchBox}>
            <Icon icon={faMagnifyingGlass} size={12} color={t.t3} />
            <TextInput
              value={query}
              onChangeText={setQuery}
              autoFocus
              placeholder={tr('artifact_search_placeholder')}
              placeholderTextColor={t.t3}
              selectionColor={t.accent}
              style={styles.searchInput}
              returnKeyType="search"
            />
          </View>
          <Pressable
            accessibilityRole="button"
            onPress={() => {
              setSearching(false);
              setQuery('');
            }}
            hitSlop={8}>
            <Text style={styles.searchCancel}>{tr('common_cancel')}</Text>
          </Pressable>
        </View>
      ) : (
        <PageHeader
          title={tr('artifact_title')}
          count={loading ? undefined : `${items.length}${hasMore ? '+' : ''}`}
          onBack={navigation.goBack}
          right={
            focus ? undefined : (
              <IconButton
                icon={faMagnifyingGlass}
                label={tr('common_search')}
                onPress={() => setSearching(true)}
                size={14}
              />
            )
          }
        />
      )}

      {focus ? (
        <View style={styles.focusBar}>
          <Icon icon={faLocationCrosshairs} size={12} color={t.accent} />
          <Text style={styles.focusText} numberOfLines={1} ellipsizeMode="middle">
            {trf('artifact_focus_on', {name: focus.name})}
          </Text>
          <Chip label={tr('artifact_view_all')} onPress={() => setFocus(null)} />
        </View>
      ) : (
        <View>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.filters}>
            {filters().map(f => (
              <Chip key={f.key || 'all'} label={f.label} active={kind === f.key} onPress={() => setKind(f.key)} />
            ))}
          </ScrollView>
        </View>
      )}

      <SwipeTabs tabs={FILTER_KEYS} value={kind} onChange={setKind} enabled={!focus && !searching}>
        <ScrollView
          contentContainerStyle={[styles.scrollBody, {paddingBottom: insets.bottom + 24}]}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => load('refresh')}
              tintColor={t.t3}
              colors={[t.green]}
            />
          }
          onScroll={e => {
            const {layoutMeasurement, contentOffset, contentSize} = e.nativeEvent;
            if (
              hasMore &&
              !loadingMore &&
              layoutMeasurement.height + contentOffset.y > contentSize.height - 300
            ) {
              load('more');
            }
          }}
          scrollEventThrottle={200}>
          {loading || items.length === 0 ? (
            <EmptyState
              loading={loading}
              title={
                error
                  ? tr('common_load_failed')
                  : focus
                  ? tr('artifact_focus_missing')
                  : query
                  ? tr('artifact_no_match')
                  : tr('artifact_empty_title')
              }
              hint={
                error ??
                (focus
                  ? tr('artifact_focus_missing_hint')
                  : query
                  ? tr('artifact_no_match_hint')
                  : tr('artifact_empty_hint'))
              }
            />
          ) : (
            groups.map(g => (
              <View key={g.title} style={styles.group}>
                <GroupLabel>{g.title}</GroupLabel>
                {g.cards.length > 0 && (
                  <View style={styles.cards}>
                    {g.cards.map(a => (
                      <ArtifactCard
                        key={`${a.agent_id}-${a.id}`}
                        artifact={a}
                        onPress={() => openArtifact(a)}
                        onLongPress={() => setActing(a)}
                      />
                    ))}
                  </View>
                )}
                {g.rows.map(a => (
                  <ArtifactRow
                    key={`${a.agent_id}-${a.id}`}
                    artifact={a}
                    onPress={() => openArtifact(a)}
                    onLongPress={() => setActing(a)}
                  />
                ))}
              </View>
            ))
          )}
          {loadingMore && <ActivityIndicator style={styles.more} color={t.t3} />}
        </ScrollView>
      </SwipeTabs>

      <Sheet visible={!!acting} onClose={() => setActing(null)} title={acting?.title || acting?.file_name}>
        {!!acting?.can_jump && (
          <SheetAction icon={faMessage} label={tr('artifact_jump')} onPress={() => acting && jumpTo(acting)} />
        )}
        <SheetAction
          icon={faThumbtack}
          label={acting?.pinned_at ? tr('artifact_unpin') : tr('artifact_pin')}
          onPress={() => acting && togglePin(acting)}
        />
        {!!actingFile && (
          <>
            <SheetAction
              icon={faDownload}
              label={tr('file_download')}
              onPress={() => {
                setActing(null);
                downloadFile(actingFile);
              }}
            />
            <SheetAction
              icon={faShareNodes}
              label={tr('file_share')}
              onPress={() => {
                setActing(null);
                setTimeout(() => shareFile(actingFile), SHEET_DISMISS_MS);
              }}
            />
            <SheetAction
              icon={faArrowUpRightFromSquare}
              label={tr('file_open_external')}
              onPress={() => {
                setActing(null);
                openInBrowser(actingFile);
              }}
            />
          </>
        )}
      </Sheet>
      <ToastHost bottom={insets.bottom + 28} />
    </View>
  );
}

function ArtifactCard({
  artifact: a,
  onPress,
  onLongPress,
}: {
  artifact: Artifact;
  onPress: () => void;
  onLongPress: () => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  const group = kindGroup(a.kind);
  const [bg, fg] = t.kind[group];
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      onLongPress={onLongPress}
      delayLongPress={350}
      style={({pressed}) => [styles.card, pressed && styles.pressedDim]}>
      <View style={[styles.thumb, {backgroundColor: bg}]}>
        {group === 'image' && a.preview_url ? (
          <Image
            source={{uri: serverUrl(a.preview_url)}}
            style={styles.thumbImage}
            resizeMode="cover"
            // Android otherwise decodes every thumbnail at full size, and a page of
            // screenshots fills the bitmap pool until the full-screen view can't open one.
            resizeMethod="resize"
          />
        ) : (
          <Icon icon={KIND_ICON[group]} size={22} color={fg} />
        )}
        {!!a.pinned_at && (
          <View style={styles.pin}>
            <Text style={styles.pinText}>{tr('artifact_pinned')}</Text>
          </View>
        )}
      </View>
      <View style={styles.cardBody}>
        <Text style={styles.cardTitle} numberOfLines={2}>
          {a.title || a.file_name}
        </Text>
        <View style={styles.cardMeta}>
          <Text style={styles.metaText} numberOfLines={1}>
            {a.session_title || a.agent_name || ''}
          </Text>
          <Text style={styles.metaText}>{shortTime(a.created_at)}</Text>
        </View>
      </View>
    </Pressable>
  );
}

function ArtifactRow({
  artifact: a,
  onPress,
  onLongPress,
}: {
  artifact: Artifact;
  onPress: () => void;
  onLongPress: () => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      onLongPress={onLongPress}
      delayLongPress={350}
      style={({pressed}) => [styles.row, pressed && styles.rowPressed]}>
      <KindTile kind={a.kind} previewUrl={a.preview_url} size={34} />
      <View style={styles.rowText}>
        <Text style={styles.rowTitle} numberOfLines={1}>
          {a.title || a.file_name}
        </Text>
        <Text style={styles.metaText} numberOfLines={1}>
          {[a.session_title || a.agent_name, shortTime(a.created_at)].filter(Boolean).join(' · ')}
        </Text>
      </View>
      {a.pinned_at ? (
        <Icon icon={faThumbtack} size={10} color={t.t3} />
      ) : (
        <Icon icon={faChevronRight} size={10} color={t.t4} />
      )}
    </Pressable>
  );
}

function SheetAction({
  icon,
  label,
  onPress,
}: {
  icon: typeof faXmark;
  label: string;
  onPress: () => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      style={({pressed}) => [styles.sheetAction, pressed && styles.rowPressed]}>
      <View style={styles.sheetIcon}>
        <Icon icon={icon} size={14} color={t.t2} />
      </View>
      <Text style={styles.sheetText}>{label}</Text>
    </Pressable>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  searchBar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 14,
    paddingBottom: 8,
  },
  searchBox: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 9,
    height: 38,
    paddingHorizontal: 12,
    borderRadius: radius.sm,
    backgroundColor: t.bg2,
    borderWidth: 1,
    borderColor: t.line1,
  },
  searchInput: {flex: 1, padding: 0, fontSize: 15, color: t.t1},
  searchCancel: {fontSize: 15, color: t.t2},
  filters: {gap: 7, paddingHorizontal: 14, paddingTop: 6, paddingBottom: 14},
  focusBar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingHorizontal: 16,
    paddingTop: 6,
    paddingBottom: 14,
  },
  focusText: {flex: 1, minWidth: 0, fontSize: 13, color: t.t2},
  scrollBody: {flexGrow: 1},
  group: {marginBottom: 18},
  cards: {flexDirection: 'row', flexWrap: 'wrap', gap: 10, paddingHorizontal: 14, marginBottom: 6},
  card: {
    width: '48.5%',
    flexGrow: 1,
    maxWidth: '48.5%',
    borderRadius: radius.md,
    overflow: 'hidden',
    backgroundColor: t.bg1,
    borderWidth: 1,
    borderColor: t.line1,
  },
  pressedDim: {opacity: 0.7},
  thumb: {height: 92, alignItems: 'center', justifyContent: 'center'},
  thumbImage: {width: '100%', height: '100%'},
  pin: {
    position: 'absolute',
    top: 7,
    right: 7,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 5,
    backgroundColor: 'rgba(0,0,0,0.45)',
  },
  pinText: {fontSize: 10, color: 'rgba(255,255,255,0.88)', letterSpacing: 0.3},
  cardBody: {paddingHorizontal: 10, paddingTop: 9, paddingBottom: 10},
  cardTitle: {fontSize: 13, lineHeight: 18, minHeight: 36, fontWeight: '500', color: t.t1},
  cardMeta: {flexDirection: 'row', justifyContent: 'space-between', gap: 6, marginTop: 6},
  metaText: {fontSize: 11, color: t.t3, flexShrink: 1, fontVariant: ['tabular-nums']},
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    marginHorizontal: 8,
    paddingHorizontal: 10,
    paddingVertical: 10,
    borderRadius: radius.sm,
  },
  rowPressed: {backgroundColor: t.bg2},
  rowText: {flex: 1, minWidth: 0, gap: 4},
  rowTitle: {fontSize: 14, fontWeight: '500', color: t.t1},
  more: {paddingVertical: 16},
  sheetAction: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 12,
    paddingVertical: 14,
    borderRadius: radius.md,
  },
  sheetIcon: {width: 18, alignItems: 'center'},
  sheetText: {fontSize: 16, color: t.t1},
}));
