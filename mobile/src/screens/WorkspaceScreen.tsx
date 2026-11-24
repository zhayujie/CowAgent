import {faFolder} from '@fortawesome/free-regular-svg-icons';
import {faChevronRight} from '@fortawesome/free-solid-svg-icons';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useEffect, useRef, useState} from 'react';
import {FlatList, Pressable, RefreshControl, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {getWorkspaceTree} from '../api/cowApi';
import {KindTile} from '../components/ArtifactStrip';
import {FileSheet} from '../components/FileViews';
import {Icon} from '../components/Icon';
import {EmptyState, PageHeader} from '../components/ui';
import {fileFromPayload, type ChatFile} from '../files/chatFile';
import {openFile} from '../files/openFile';
import {tr} from '../i18n';
import type {RootStackParamList} from '../navigation/types';
import type {WorkspaceEntry, WorkspaceListing} from '../protocol/resources';
import {useProjectStore} from '../store/projectStore';
import {describeConnectError} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {formatBytes, shortTime} from '../utils/format';

type Props = StackScreenProps<RootStackParamList, 'Workspace'>;

const entryFile = (e: WorkspaceEntry): ChatFile | null =>
  fileFromPayload({
    abs_path: e.abs_path,
    rel_path: e.path,
    file_name: e.name,
    kind: e.kind,
    size: e.size,
    raw_url: e.raw_url,
    preview_url: e.preview_url,
  });

export function WorkspaceScreen({navigation, route}: Props) {
  const {sessionId, agentId, path = '', name} = route.params;
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const project = useProjectStore(s => s.bySession[sessionId]?.current?.name);
  const space = project || tr('composer_ws_default');
  const [listing, setListing] = useState<WorkspaceListing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  // The file stays after the sheet closes, so it can slide away still showing it.
  const [acting, setActing] = useState<ChatFile | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const live = useRef(true);

  const load = useCallback(
    async (refresh = false) => {
      if (refresh) {
        setRefreshing(true);
      }
      try {
        const next = await getWorkspaceTree(path, sessionId, agentId);
        if (live.current) {
          setListing(next);
          setError(null);
        }
      } catch (e) {
        if (live.current) {
          setError(describeConnectError(e));
        }
      } finally {
        if (live.current) {
          setRefreshing(false);
        }
      }
    },
    [path, sessionId, agentId],
  );

  useEffect(() => {
    live.current = true;
    load();
    return () => {
      live.current = false;
    };
  }, [load]);

  const open = (e: WorkspaceEntry) => {
    if (e.is_dir) {
      navigation.push('Workspace', {sessionId, agentId, path: e.path, name: e.name});
      return;
    }
    const file = entryFile(e);
    if (file) {
      openFile(file);
    }
  };

  const actOn = (e: WorkspaceEntry) => {
    const file = entryFile(e);
    if (file) {
      setActing(file);
      setSheetOpen(true);
    }
  };

  return (
    <View style={styles.root}>
      <PageHeader title={name ?? tr('composer_ws_title')} subtitle={space} onBack={navigation.goBack} />
      <FlatList
        data={listing?.entries ?? []}
        keyExtractor={e => e.path}
        contentContainerStyle={[styles.list, {paddingBottom: insets.bottom + 24}]}
        renderItem={({item}) => (
          <Pressable
            accessibilityRole="button"
            onPress={() => open(item)}
            onLongPress={item.is_dir ? undefined : () => actOn(item)}
            delayLongPress={350}
            style={({pressed}) => [styles.row, pressed && styles.rowPressed]}>
            {item.is_dir ? (
              <View style={styles.folder}>
                <Icon icon={faFolder} size={15} color={t.t2} />
              </View>
            ) : (
              <KindTile kind={item.kind} previewUrl={item.kind === 'image' ? item.preview_url : undefined} />
            )}
            <View style={styles.rowText}>
              <Text style={styles.name} numberOfLines={1} ellipsizeMode="middle">
                {item.name}
              </Text>
              <Text style={styles.meta} numberOfLines={1}>
                {[item.is_dir ? '' : formatBytes(item.size), shortTime(item.mtime)].filter(Boolean).join(' · ')}
              </Text>
            </View>
            {item.is_dir && <Icon icon={faChevronRight} size={10} color={t.t4} />}
          </Pressable>
        )}
        ListFooterComponent={listing?.truncated ? <Text style={styles.note}>{tr('workspace_truncated')}</Text> : null}
        ListEmptyComponent={
          <EmptyState
            loading={!listing && !error}
            icon={error ? undefined : faFolder}
            title={error ? tr('common_load_failed') : tr('workspace_empty')}
            hint={error ?? undefined}
          />
        }
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={() => load(true)} tintColor={t.t3} colors={[t.green]} />
        }
      />
      {acting && <FileSheet file={acting} visible={sheetOpen} onClose={() => setSheetOpen(false)} />}
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  list: {paddingTop: 4, flexGrow: 1},
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
  folder: {
    width: 34,
    height: 34,
    borderRadius: 9,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: t.bg2,
  },
  rowText: {flex: 1, minWidth: 0},
  name: {fontSize: 15, color: t.t1},
  meta: {fontSize: 12, color: t.t3, marginTop: 3, fontVariant: ['tabular-nums']},
  note: {fontSize: 12, color: t.t3, textAlign: 'center', paddingVertical: 16},
}));
