import {faFileLines, faFolder} from '@fortawesome/free-regular-svg-icons';
import {
  faArrowRightArrowLeft,
  faChevronRight,
  faEllipsis,
  faFileCirclePlus,
  faFileImport,
  faFolderPlus,
  faMagnifyingGlass,
  faPen,
  faPlus,
  faTrashCan,
  faXmark,
} from '@fortawesome/free-solid-svg-icons';
import {useFocusEffect} from '@react-navigation/native';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useMemo, useRef, useState} from 'react';
import {FlatList, Pressable, RefreshControl, Text, TextInput, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {getKnowledgeGraph, getKnowledgeTree, importKnowledge, knowledgeAction} from '../api/cowApi';
import {ApiError} from '../api/http';
import {AgentSheet} from '../components/AgentSheet';
import {Icon} from '../components/Icon';
import {KnowledgeGraph} from '../components/KnowledgeGraph';
import {ChoiceSheet, ConfirmSheet, FieldSheet, type Choice} from '../components/settings';
import {SHEET_DISMISS_MS} from '../components/Sheet';
import {showToast, ToastHost} from '../components/Toast';
import {SwipeTabs} from '../components/SwipeTabs';
import {EmptyState, IconButton, PageHeader, Segmented} from '../components/ui';
import {tr, trf} from '../i18n';
import {pickDocuments} from '../media/picker';
import type {RootStackParamList} from '../navigation/types';
import type {KnowledgeGraph as GraphData, KnowledgeTree} from '../protocol/resources';
import {agentParam, useViewedAgent} from '../store/agentStore';
import {describeConnectError} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {formatBytes} from '../utils/format';
import {
  docPath,
  docTemplate,
  docTitle,
  flattenCategories,
  isImportable,
  isProtectedPage,
  pageFileName,
} from '../utils/knowledge';

type Props = StackScreenProps<RootStackParamList, 'Knowledge'>;
type Tab = 'docs' | 'graph';
const TABS: readonly Tab[] = ['docs', 'graph'];

type Row =
  | {kind: 'category'; key: string; path: string; name: string; depth: number; total: number}
  | {kind: 'doc'; key: string; path: string; title: string; name: string; size?: number; depth: number}
  | {kind: 'empty'; key: string; depth: number};

type SheetState =
  | {kind: 'create'}
  | {kind: 'pickCategory'; purpose: 'doc' | 'import'}
  | {kind: 'newCategory'; parent?: string}
  | {kind: 'newDoc'; category: string}
  | {kind: 'category'; path: string; total: number}
  | {kind: 'rename'; path: string}
  | {kind: 'deleteCategory'; path: string; total: number}
  | {kind: 'doc'; path: string; title: string}
  | {kind: 'move'; path: string; title: string}
  | {kind: 'deleteDoc'; path: string; title: string}
  | {kind: 'agent'};

/** The server's reasons are fixed English phrases; these are the ones a person can act on. */
function actionError(e: unknown): string {
  const msg = e instanceof ApiError ? e.message : '';
  if (/already exists/i.test(msg)) {
    return tr('knowledge_err_exists');
  }
  if (/not empty/i.test(msg)) {
    return tr('knowledge_err_not_empty');
  }
  if (/invalid|outside|traversal/i.test(msg)) {
    return tr('knowledge_err_invalid_name');
  }
  if (/too large/i.test(msg)) {
    return tr('knowledge_err_too_large');
  }
  return describeConnectError(e);
}

function buildRows(tree: KnowledgeTree, search: string): Row[] {
  const q = search.trim().toLowerCase();
  const hit = (title: string, name: string) => !q || title.toLowerCase().includes(q) || name.toLowerCase().includes(q);
  const rows: Row[] = [];
  for (const f of tree.root_files ?? []) {
    const title = docTitle(f);
    if (hit(title, f.name)) {
      rows.push({kind: 'doc', key: f.name, path: f.name, title, name: f.name, size: f.size, depth: 0});
    }
  }
  for (const cat of flattenCategories(tree.tree)) {
    const docs = cat.files
      .map(f => ({f, title: docTitle(f)}))
      .filter(({f, title}) => hit(title, f.name));
    if (q && !docs.length && !cat.path.toLowerCase().includes(q)) {
      continue;
    }
    rows.push({kind: 'category', key: `c:${cat.path}`, path: cat.path, name: cat.name, depth: cat.depth, total: cat.total});
    for (const {f, title} of docs) {
      const path = docPath(cat.path, f);
      rows.push({kind: 'doc', key: path, path, title, name: f.name, size: f.size, depth: cat.depth + 1});
    }
    if (!q && !cat.files.length && cat.total === 0) {
      rows.push({kind: 'empty', key: `e:${cat.path}`, depth: cat.depth + 1});
    }
  }
  return rows;
}

export function KnowledgeScreen({navigation}: Props) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const viewed = useViewedAgent('knowledge');
  const scope = agentParam(viewed.agentId);
  const [tab, setTab] = useState<Tab>('docs');
  const [tree, setTree] = useState<KnowledgeTree | null>(null);
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [graphError, setGraphError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch] = useState('');
  const [sheet, setSheet] = useState<SheetState | null>(null);
  const generation = useRef(0);

  const loadTree = useCallback(
    async (refresh = false) => {
      const gen = generation.current;
      if (refresh) {
        setRefreshing(true);
      }
      try {
        const res = await getKnowledgeTree(scope);
        if (gen === generation.current) {
          setTree(res);
          setError(null);
        }
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

  const loadGraph = useCallback(async () => {
    const gen = generation.current;
    try {
      const res = await getKnowledgeGraph(scope);
      if (gen === generation.current) {
        setGraph(res);
        setGraphError(null);
      }
    } catch (e) {
      if (gen === generation.current) {
        setGraphError(describeConnectError(e));
      }
    }
  }, [scope]);

  /** After any change the graph is stale; it is re-read the next time it is shown. */
  const reload = useCallback(async () => {
    setGraph(null);
    await loadTree();
    if (tab === 'graph') {
      loadGraph();
    }
  }, [loadTree, loadGraph, tab]);

  useFocusEffect(
    useCallback(() => {
      if (viewed.ready) {
        loadTree();
      }
    }, [viewed.ready, loadTree]),
  );

  useFocusEffect(
    useCallback(() => {
      if (viewed.ready && tab === 'graph') {
        loadGraph();
      }
    }, [viewed.ready, tab, loadGraph]),
  );

  const categories = useMemo(() => flattenCategories(tree?.tree).map(c => c.path), [tree]);
  const rows = useMemo(() => (tree ? buildRows(tree, search) : []), [tree, search]);

  const next = (s: SheetState | null) => {
    setSheet(null);
    if (s) {
      setTimeout(() => setSheet(s), SHEET_DISMISS_MS);
    }
  };

  const switchAgent = (id: string) => {
    setSheet(null);
    generation.current += 1;
    setTree(null);
    setGraph(null);
    setError(null);
    setGraphError(null);
    setSearch('');
    viewed.select(id);
  };

  const openDoc = (path: string, title: string) =>
    navigation.navigate('KnowledgeDoc', {path, title, agentId: scope});

  const needCategory = (purpose: 'doc' | 'import') => {
    if (!categories.length) {
      next({kind: 'newCategory'});
      showToast(tr('knowledge_need_category'));
      return;
    }
    next({kind: 'pickCategory', purpose});
  };

  const runImport = async (category: string) => {
    setSheet(null);
    let files;
    try {
      files = await pickDocuments();
    } catch (e) {
      showToast(e instanceof Error ? e.message : String(e));
      return;
    }
    if (!files.length) {
      return;
    }
    const ok = files.filter(f => isImportable(f.name));
    if (!ok.length) {
      showToast(tr('knowledge_import_only_md_txt'));
      return;
    }
    showToast(trf('knowledge_importing_n', {n: ok.length}));
    try {
      const res = await importKnowledge(ok, category, scope);
      const parts = [trf('knowledge_import_imported', {n: res.imported})];
      if (res.skipped) {
        parts.push(trf('knowledge_import_skipped', {n: res.skipped}));
      }
      if (res.failed || ok.length < files.length) {
        parts.push(trf('knowledge_import_failed_n', {n: res.failed + files.length - ok.length}));
      }
      showToast(parts.join(tr('knowledge_import_sep')));
      await reload();
    } catch (e) {
      showToast(trf('knowledge_import_failed', {error: actionError(e)}));
    }
  };

  const createCategory = async (value: string, parent?: string) => {
    const name = value.replace(/^\/+|\/+$/g, '');
    if (!name) {
      throw new Error(tr('knowledge_category_name_required'));
    }
    const path = parent ? `${parent}/${name}` : name;
    try {
      const res = await knowledgeAction<{created: boolean; reason?: string}>(
        {action: 'create_category', payload: {path}},
        scope,
      );
      if (!res.created) {
        throw new Error(tr('knowledge_category_exists'));
      }
    } catch (e) {
      throw new Error(e instanceof ApiError ? actionError(e) : (e as Error).message);
    }
    showToast(tr('knowledge_category_created'));
    await reload();
  };

  const createDoc = async (value: string, category: string) => {
    const name = pageFileName(value);
    let created: string;
    try {
      const res = await knowledgeAction<{path: string}>(
        {action: 'create_document', payload: {path: `${category}/${name}`, content: docTemplate(name)}},
        scope,
      );
      created = res.path || `${category}/${name}`;
    } catch (e) {
      throw new Error(actionError(e));
    }
    await reload();
    navigation.navigate('KnowledgeDoc', {path: created, title: name.replace(/\.md$/i, ''), agentId: scope, edit: true});
  };

  const renameCategory = async (value: string, path: string) => {
    const target = value.replace(/^\/+|\/+$/g, '');
    if (!target || target === path) {
      return;
    }
    try {
      const res = await knowledgeAction<{moved?: boolean; reason?: string}>(
        {action: 'rename_category', payload: {path, new_path: target}},
        scope,
      );
      if (res.moved === false) {
        throw new Error(tr('knowledge_category_gone'));
      }
    } catch (e) {
      throw new Error(e instanceof ApiError ? actionError(e) : (e as Error).message);
    }
    showToast(tr('knowledge_renamed'));
    await reload();
  };

  const deleteCategory = async (path: string) => {
    try {
      await knowledgeAction({action: 'delete_category', payload: {path, confirm: true}}, scope);
      setSheet(null);
      showToast(tr('knowledge_category_deleted'));
      await reload();
    } catch (e) {
      setSheet(null);
      showToast(trf('common_delete_failed', {error: actionError(e)}));
    }
  };

  const moveDoc = async (path: string, target: string) => {
    setSheet(null);
    try {
      const res = await knowledgeAction<{results: {moved: boolean; reason?: string}[]}>(
        {action: 'move_documents', payload: {paths: [path], target_category: target}},
        scope,
      );
      const r = res.results?.[0];
      showToast(
        r?.moved
          ? trf('knowledge_moved_to', {target})
          : r?.reason === 'target_exists'
            ? tr('knowledge_move_target_exists')
            : tr('knowledge_move_failed'),
      );
      await reload();
    } catch (e) {
      showToast(trf('knowledge_move_failed_detail', {error: actionError(e)}));
    }
  };

  const deleteDoc = async (path: string) => {
    try {
      await knowledgeAction({action: 'delete_documents', payload: {paths: [path]}}, scope);
      setSheet(null);
      showToast(tr('common_deleted'));
      await reload();
    } catch (e) {
      setSheet(null);
      showToast(trf('common_delete_failed', {error: actionError(e)}));
    }
  };

  const pages = tree?.stats?.pages ?? 0;
  const shared = viewed.multi && !viewed.isDefault && viewed.agent?.knowledge_mode === 'shared';
  const statsLine = tree
    ? [trf('knowledge_pages_count', {n: pages}), formatBytes(tree.stats?.size ?? 0), shared ? tr('knowledge_shared_with_default') : null]
        .filter(Boolean)
        .join(' · ')
    : '';

  const renderRow = ({item}: {item: Row}) => {
    const indent = {paddingLeft: 10 + item.depth * 16};
    if (item.kind === 'category') {
      return (
        <View style={[styles.catRow, indent]}>
          <Icon icon={faFolder} size={13} color={t.t3} />
          <Text style={styles.catName} numberOfLines={1}>
            {item.name}
          </Text>
          <Text style={styles.catCount}>{item.total}</Text>
          <IconButton
            icon={faEllipsis}
            label={trf('knowledge_category_actions', {path: item.path})}
            size={13}
            color={t.t3}
            onPress={() => setSheet({kind: 'category', path: item.path, total: item.total})}
          />
        </View>
      );
    }
    if (item.kind === 'empty') {
      return <Text style={[styles.emptyCat, {paddingLeft: 10 + item.depth * 16 + 22}]}>{tr('knowledge_empty_category')}</Text>;
    }
    const locked = isProtectedPage(item.path);
    return (
      <Pressable
        accessibilityRole="button"
        accessibilityHint={locked ? undefined : tr('knowledge_doc_row_hint')}
        onPress={() => openDoc(item.path, item.title)}
        onLongPress={locked ? undefined : () => setSheet({kind: 'doc', path: item.path, title: item.title})}
        style={({pressed}) => [styles.docRow, indent, pressed && styles.rowPressed]}>
        <Icon icon={faFileLines} size={13} color={locked ? t.t4 : t.t3} />
        <View style={styles.docText}>
          <Text style={styles.docTitle} numberOfLines={1}>
            {item.title}
          </Text>
          <Text style={styles.docMeta} numberOfLines={1}>
            {[item.name, formatBytes(item.size), locked ? tr('knowledge_agent_maintained') : null].filter(Boolean).join(' · ')}
          </Text>
        </View>
        <Icon icon={faChevronRight} size={10} color={t.t4} />
      </Pressable>
    );
  };

  const createOptions: Choice<'category' | 'doc' | 'import'>[] = [
    {key: 'doc', label: tr('knowledge_new_doc'), desc: tr('knowledge_new_doc_desc'), icon: faFileCirclePlus},
    {key: 'category', label: tr('knowledge_new_category'), desc: tr('knowledge_new_category_desc'), icon: faFolderPlus},
    {key: 'import', label: tr('knowledge_import'), desc: tr('knowledge_import_desc'), icon: faFileImport},
  ];

  const categoryOptions: Choice<'doc' | 'import' | 'sub' | 'rename' | 'delete'>[] = [
    {key: 'doc', label: tr('knowledge_new_doc_here'), icon: faFileCirclePlus},
    {key: 'import', label: tr('knowledge_import_here'), icon: faFileImport},
    {key: 'sub', label: tr('knowledge_new_subcategory'), icon: faFolderPlus},
    {key: 'rename', label: tr('knowledge_rename_or_move'), icon: faPen},
    {key: 'delete', label: tr('knowledge_delete_category'), icon: faTrashCan},
  ];

  return (
    <View style={styles.root}>
      <PageHeader
        title={tr('knowledge_title')}
        subtitle={viewed.multi ? viewed.agent?.name ?? viewed.agentId ?? undefined : undefined}
        onTitlePress={viewed.multi ? () => setSheet({kind: 'agent'}) : undefined}
        onBack={navigation.goBack}
        right={
          <IconButton
            icon={faPlus}
            label={tr('common_create')}
            filled
            size={13}
            color={t.t1}
            onPress={() => setSheet({kind: 'create'})}
          />
        }
      />
      <Segmented
        value={tab}
        onChange={setTab}
        options={[
          {key: 'docs', label: tr('knowledge_tab_docs'), count: pages || undefined},
          {key: 'graph', label: tr('knowledge_tab_graph')},
        ]}
      />
      <SwipeTabs tabs={TABS} value={tab} onChange={setTab} enabled={tab === 'docs'}>
        {tab === 'docs' ? (
          <>
            {!!tree && (pages > 0 || categories.length > 0) && (
              <View style={styles.searchBox}>
                <Icon icon={faMagnifyingGlass} size={12} color={t.t4} />
                <TextInput
                  value={search}
                  onChangeText={setSearch}
                  placeholder={tr('knowledge_search_placeholder')}
                  placeholderTextColor={t.t4}
                  selectionColor={t.accent}
                  cursorColor={t.accent}
                  autoCapitalize="none"
                  autoCorrect={false}
                  style={styles.searchInput}
                />
                {!!search && (
                  <Pressable accessibilityLabel={tr('knowledge_clear_search')} hitSlop={8} onPress={() => setSearch('')}>
                    <Icon icon={faXmark} size={12} color={t.t3} />
                  </Pressable>
                )}
              </View>
            )}
            {!!statsLine && <Text style={styles.stats}>{statsLine}</Text>}
            <FlatList
              data={rows}
              keyExtractor={r => r.key}
              renderItem={renderRow}
              keyboardShouldPersistTaps="handled"
              contentContainerStyle={[styles.list, {paddingBottom: insets.bottom + 24}]}
              ListEmptyComponent={
                <EmptyState
                  loading={!tree && !error}
                  title={
                    error
                      ? tr('common_load_failed')
                      : search
                        ? tr('knowledge_no_match')
                        : tree?.enabled === false
                          ? tr('knowledge_disabled')
                          : tr('knowledge_empty')
                  }
                  hint={error ?? (search ? undefined : tr('knowledge_empty_hint'))}
                />
              }
              refreshControl={
                <RefreshControl refreshing={refreshing} onRefresh={() => loadTree(true)} tintColor={t.t3} colors={[t.green]} />
              }
            />
          </>
        ) : graph && graph.nodes.length ? (
          <KnowledgeGraph data={graph} onOpen={openDoc} />
        ) : (
          <EmptyState
            loading={!graph && !graphError}
            title={graphError ? tr('common_load_failed') : tr('knowledge_graph_empty')}
            hint={graphError ?? tr('knowledge_graph_empty_hint')}
          />
        )}
      </SwipeTabs>

      <ChoiceSheet
        visible={sheet?.kind === 'create'}
        title={tr('common_create')}
        options={createOptions}
        onSelect={key => (key === 'category' ? next({kind: 'newCategory'}) : needCategory(key))}
        onClose={() => setSheet(null)}
      />
      <ChoiceSheet
        visible={sheet?.kind === 'pickCategory'}
        title={
          sheet?.kind === 'pickCategory' && sheet.purpose === 'import'
            ? tr('knowledge_pick_import_category')
            : tr('knowledge_pick_doc_category')
        }
        options={categories.map(c => ({key: c, label: c}))}
        onSelect={c =>
          sheet?.kind === 'pickCategory' && sheet.purpose === 'import' ? runImport(c) : next({kind: 'newDoc', category: c})
        }
        onClose={() => setSheet(null)}
      />
      <FieldSheet
        visible={sheet?.kind === 'newCategory'}
        title={
          sheet?.kind === 'newCategory' && sheet.parent
            ? trf('knowledge_new_category_in', {parent: sheet.parent})
            : tr('knowledge_new_category')
        }
        placeholder={
          sheet?.kind === 'newCategory' && sheet.parent
            ? tr('knowledge_subcategory_placeholder')
            : tr('knowledge_category_placeholder')
        }
        hint={tr('knowledge_category_field_hint')}
        allowEmpty={false}
        submitLabel={tr('knowledge_create')}
        onSubmit={v => createCategory(v, sheet?.kind === 'newCategory' ? sheet.parent : undefined)}
        onClose={() => setSheet(null)}
      />
      <FieldSheet
        visible={sheet?.kind === 'newDoc'}
        title={sheet?.kind === 'newDoc' ? trf('knowledge_new_doc_in', {category: sheet.category}) : tr('knowledge_new_doc')}
        placeholder={tr('knowledge_doc_name_placeholder')}
        hint={tr('knowledge_doc_name_hint')}
        allowEmpty={false}
        submitLabel={tr('knowledge_create_and_edit')}
        onSubmit={v => (sheet?.kind === 'newDoc' ? createDoc(v, sheet.category) : undefined)}
        onClose={() => setSheet(null)}
      />
      <ChoiceSheet
        visible={sheet?.kind === 'category'}
        title={sheet?.kind === 'category' ? sheet.path : tr('knowledge_category')}
        options={categoryOptions}
        onSelect={key => {
          if (sheet?.kind !== 'category') {
            return;
          }
          const {path, total} = sheet;
          if (key === 'doc') {
            next({kind: 'newDoc', category: path});
          } else if (key === 'import') {
            runImport(path);
          } else if (key === 'sub') {
            next({kind: 'newCategory', parent: path});
          } else if (key === 'rename') {
            next({kind: 'rename', path});
          } else {
            next({kind: 'deleteCategory', path, total});
          }
        }}
        onClose={() => setSheet(null)}
      />
      <FieldSheet
        visible={sheet?.kind === 'rename'}
        title={tr('knowledge_rename_category')}
        initial={sheet?.kind === 'rename' ? sheet.path : ''}
        hint={tr('knowledge_rename_hint')}
        allowEmpty={false}
        onSubmit={v => (sheet?.kind === 'rename' ? renameCategory(v, sheet.path) : undefined)}
        onClose={() => setSheet(null)}
      />
      <ConfirmSheet
        visible={sheet?.kind === 'deleteCategory'}
        title={tr('knowledge_delete_category')}
        message={
          sheet?.kind === 'deleteCategory'
            ? sheet.total
              ? trf('knowledge_delete_category_msg', {path: sheet.path, n: sheet.total})
              : trf('knowledge_delete_empty_category_msg', {path: sheet.path})
            : ''
        }
        confirmLabel={tr('common_delete')}
        danger
        onConfirm={() => (sheet?.kind === 'deleteCategory' ? deleteCategory(sheet.path) : undefined)}
        onClose={() => setSheet(null)}
      />
      <ChoiceSheet
        visible={sheet?.kind === 'doc'}
        title={sheet?.kind === 'doc' ? sheet.title : tr('knowledge_doc')}
        options={[
          {key: 'move', label: tr('knowledge_move_to_other'), icon: faArrowRightArrowLeft},
          {key: 'delete', label: tr('common_delete'), icon: faTrashCan},
        ]}
        onSelect={key => {
          if (sheet?.kind !== 'doc') {
            return;
          }
          const {path, title} = sheet;
          const here = path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '';
          if (key === 'move') {
            if (!categories.some(c => c !== here)) {
              setSheet(null);
              showToast(tr('knowledge_no_other_category'));
              return;
            }
            next({kind: 'move', path, title});
          } else {
            next({kind: 'deleteDoc', path, title});
          }
        }}
        onClose={() => setSheet(null)}
      />
      <ChoiceSheet
        visible={sheet?.kind === 'move'}
        title={tr('knowledge_move_to')}
        options={categories
          .filter(c => sheet?.kind !== 'move' || !sheet.path.startsWith(`${c}/`) || sheet.path.slice(c.length + 1).includes('/'))
          .map(c => ({key: c, label: c}))}
        onSelect={c => (sheet?.kind === 'move' ? moveDoc(sheet.path, c) : undefined)}
        onClose={() => setSheet(null)}
      />
      <ConfirmSheet
        visible={sheet?.kind === 'deleteDoc'}
        title={tr('knowledge_delete_doc')}
        message={sheet?.kind === 'deleteDoc' ? trf('knowledge_delete_doc_msg', {title: sheet.title}) : ''}
        confirmLabel={tr('common_delete')}
        danger
        onConfirm={() => (sheet?.kind === 'deleteDoc' ? deleteDoc(sheet.path) : undefined)}
        onClose={() => setSheet(null)}
      />
      <AgentSheet
        visible={sheet?.kind === 'agent'}
        title={tr('knowledge_pick_agent')}
        selectedId={viewed.agentId}
        onSelect={switchAgent}
        onClose={() => setSheet(null)}
      />
      <ToastHost bottom={insets.bottom + 28} />
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  list: {paddingTop: 2, flexGrow: 1},
  searchBox: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginHorizontal: 14,
    marginTop: 4,
    paddingHorizontal: 12,
    height: 38,
    borderRadius: radius.sm,
    backgroundColor: t.bg2,
  },
  searchInput: {flex: 1, fontSize: 14, color: t.t1, paddingVertical: 0},
  stats: {fontSize: 12, color: t.t4, paddingHorizontal: 18, paddingTop: 8, paddingBottom: 2, fontVariant: ['tabular-nums']},
  catRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginHorizontal: 8,
    paddingRight: 0,
    marginTop: 8,
  },
  catName: {flex: 1, fontSize: 13, fontWeight: '600', color: t.t2},
  catCount: {fontSize: 12, color: t.t4, fontVariant: ['tabular-nums']},
  emptyCat: {fontSize: 12, color: t.t4, paddingVertical: 6, marginHorizontal: 8},
  docRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    marginHorizontal: 8,
    paddingRight: 10,
    paddingVertical: 10,
    borderRadius: radius.sm,
  },
  rowPressed: {backgroundColor: t.bg2},
  docText: {flex: 1, minWidth: 0},
  docTitle: {fontSize: 15, color: t.t1},
  docMeta: {fontSize: 12, color: t.t3, marginTop: 3, fontVariant: ['tabular-nums']},
}));
