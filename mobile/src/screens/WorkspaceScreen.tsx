import {faFolder} from '@fortawesome/free-regular-svg-icons';
import {faChevronRight, faMagnifyingGlass} from '@fortawesome/free-solid-svg-icons';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useEffect, useRef, useState} from 'react';
import {FlatList, Pressable, RefreshControl, Text, TextInput, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {getWorkspaceTree, searchWorkspace} from '../api/cowApi';
import {KindTile} from '../components/ArtifactStrip';
import {FileSheet} from '../components/FileViews';
import {Icon} from '../components/Icon';
import {FieldSheet} from '../components/settings';
import {SHEET_DISMISS_MS} from '../components/Sheet';
import {showToast, ToastHost} from '../components/Toast';
import {EmptyState, IconButton, PageHeader} from '../components/ui';
import {WorkspaceSheet} from '../components/WorkspaceSheet';
import {fileFromPayload, type ChatFile} from '../files/chatFile';
import {openFile} from '../files/openFile';
import {tr, trf} from '../i18n';
import type {RootStackParamList} from '../navigation/types';
import type {WorkspaceEntry, WorkspaceHit, WorkspaceListing} from '../protocol/resources';
import {useProjectStore} from '../store/projectStore';
import {describeConnectError, useLocalServer} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {formatBytes} from '../utils/format';

type Props = StackScreenProps<RootStackParamList, 'Workspace'>;

/** A folder's own entry, or a search hit, which may lack the size. */
type Row = WorkspaceEntry | WorkspaceHit;

const SEARCH_LIMIT = 60;
const SEARCH_DELAY_MS = 200;

const entryFile = (e: Row): ChatFile | null =>
  fileFromPayload({
    abs_path: e.abs_path,
    rel_path: e.path,
    file_name: e.name,
    kind: e.kind,
    size: e.size,
    raw_url: e.raw_url,
    preview_url: e.preview_url,
  });

const parentOf = (path: string) => path.split('/').slice(0, -1).join('/');

export function WorkspaceScreen({navigation, route}: Props) {
  const {sessionId, agentId, path = '', name} = route.params;
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const projects = useProjectStore(s => (sessionId ? s.bySession[sessionId] : undefined));
  const project = projects?.current?.name;
  const projectPath = projects?.current?.path ?? null;
  const space = project || tr('composer_ws_default');
  const local = useLocalServer();
  // Switching moves the chat it belongs to, as the composer's picker does; the phone's own Agent has no projects.
  const canSwitch = !local && !!sessionId && !path;
  const [pickerOpen, setPickerOpen] = useState(false);
  const [newProjectOpen, setNewProjectOpen] = useState(false);
  const [listing, setListing] = useState<WorkspaceListing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  // The file stays after the sheet closes, so it can slide away still showing it.
  const [acting, setActing] = useState<ChatFile | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [searching, setSearching] = useState(false);
  const [query, setQuery] = useState('');
  const [hits, setHits] = useState<WorkspaceHit[] | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const latest = useRef(0);
  const q = query.trim();

  useEffect(() => {
    setHits(null);
    setSearchError(null);
    if (!q) {
      return;
    }
    let current = true;
    const timer = setTimeout(() => {
      searchWorkspace(q, sessionId, agentId, SEARCH_LIMIT)
        .then(res => current && setHits(res.results ?? []))
        .catch(e => current && setSearchError(describeConnectError(e)));
    }, SEARCH_DELAY_MS);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [q, sessionId, agentId, projectPath]);

  // Only the listing asked for last may land: one sent before a switch would show the old folder.
  const load = useCallback(
    async (refresh = false) => {
      const id = ++latest.current;
      if (refresh) {
        setRefreshing(true);
      }
      try {
        const next = await getWorkspaceTree(path, sessionId, agentId);
        if (latest.current === id) {
          setListing(next);
          setError(null);
        }
      } catch (e) {
        if (latest.current === id) {
          setError(describeConnectError(e));
        }
      } finally {
        if (latest.current === id) {
          setRefreshing(false);
        }
      }
    },
    [path, sessionId, agentId],
  );

  // A switch changes the folder the same session lists, so it lists again.
  useEffect(() => {
    load();
  }, [load, projectPath]);

  // Recent projects may have been opened from another device since they were read.
  const openPicker = () => {
    setPickerOpen(true);
    if (sessionId) {
      useProjectStore.getState().load(sessionId, agentId ?? null).catch(() => undefined);
    }
  };

  const switchTo = (projectDir: string | null) => {
    setPickerOpen(false);
    if (sessionId) {
      useProjectStore
        .getState()
        .select(sessionId, agentId ?? null, projectDir)
        .catch(e => showToast(trf('composer_ws_switch_failed', {error: describeConnectError(e)})));
    }
  };

  const createProject = async (projectName: string) => {
    if (!projectName) {
      throw new Error(tr('composer_ws_name_required'));
    }
    if (/[/\\]/.test(projectName)) {
      throw new Error(tr('composer_ws_name_no_slash'));
    }
    if (sessionId) {
      await useProjectStore.getState().create(sessionId, agentId ?? null, projectName);
    }
  };

  const open = (e: Row) => {
    if (e.is_dir) {
      navigation.push('Workspace', {sessionId, agentId, path: e.path, name: e.name});
      return;
    }
    const file = entryFile(e);
    if (file) {
      openFile(file);
    }
  };

  const actOn = (e: Row) => {
    const file = entryFile(e);
    if (file) {
      setActing(file);
      setSheetOpen(true);
    }
  };

  const found = searching && !!q;
  const rows: Row[] = found ? (hits ?? []) : (listing?.entries ?? []);
  const meta = (item: Row) => {
    if (found) {
      return parentOf(item.path) || '/';
    }
    return item.is_dir ? '' : formatBytes(item.size);
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
              autoCapitalize="none"
              autoCorrect={false}
              placeholder={tr('workspace_search_placeholder')}
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
          title={name ?? tr('composer_ws_title')}
          subtitle={space}
          onTitlePress={canSwitch ? openPicker : undefined}
          onBack={navigation.goBack}
          right={
            <IconButton icon={faMagnifyingGlass} label={tr('common_search')} onPress={() => setSearching(true)} size={14} />
          }
        />
      )}
      <FlatList
        data={rows}
        keyExtractor={e => e.path}
        keyboardShouldPersistTaps="handled"
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
              {!!meta(item) && (
                <Text style={styles.meta} numberOfLines={1} ellipsizeMode="middle">
                  {meta(item)}
                </Text>
              )}
            </View>
            {item.is_dir && <Icon icon={faChevronRight} size={10} color={t.t4} />}
          </Pressable>
        )}
        ListFooterComponent={
          !found && listing?.truncated ? <Text style={styles.note}>{tr('workspace_truncated')}</Text> : null
        }
        ListEmptyComponent={
          found ? (
            <EmptyState
              loading={!hits && !searchError}
              icon={searchError ? undefined : faMagnifyingGlass}
              title={searchError ? tr('common_load_failed') : tr('workspace_no_results')}
              hint={searchError ?? undefined}
            />
          ) : (
            <EmptyState
              loading={!listing && !error}
              icon={error ? undefined : faFolder}
              title={error ? tr('common_load_failed') : tr('workspace_empty')}
              hint={error ?? undefined}
            />
          )
        }
        refreshControl={
          found ? undefined : (
            <RefreshControl refreshing={refreshing} onRefresh={() => load(true)} tintColor={t.t3} colors={[t.green]} />
          )
        }
      />
      {acting && <FileSheet file={acting} visible={sheetOpen} onClose={() => setSheetOpen(false)} />}
      {canSwitch && (
        <>
          <WorkspaceSheet
            visible={pickerOpen}
            onClose={() => setPickerOpen(false)}
            state={projects}
            onSelect={switchTo}
            onNew={() => {
              setPickerOpen(false);
              setTimeout(() => setNewProjectOpen(true), SHEET_DISMISS_MS);
            }}
          />
          <FieldSheet
            visible={newProjectOpen}
            title={tr('composer_ws_new_title')}
            placeholder={tr('composer_ws_new_placeholder')}
            hint={projects ? trf('composer_ws_new_hint', {root: projects.projects_root}) : undefined}
            describe={v => (/[/\\]/.test(v) ? {text: tr('composer_ws_name_no_slash'), tone: 'danger'} : null)}
            allowEmpty={false}
            submitLabel={tr('composer_ws_create')}
            onSubmit={createProject}
            onClose={() => setNewProjectOpen(false)}
          />
        </>
      )}
      <ToastHost bottom={insets.bottom + 28} />
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
  searchBar: {flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 14, paddingBottom: 8},
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
}));
