import {faArrowRightArrowLeft, faTrashCan} from '@fortawesome/free-solid-svg-icons';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useMemo, useState} from 'react';
import {getKnowledgeDoc, getKnowledgeTree, knowledgeAction} from '../api/cowApi';
import {DocPage, type DocSource} from '../components/DocPage';
import {ChoiceSheet, ConfirmSheet} from '../components/settings';
import {SHEET_DISMISS_MS} from '../components/Sheet';
import {showToast} from '../components/Toast';
import {tr, trf} from '../i18n';
import type {RootStackParamList} from '../navigation/types';
import {describeConnectError} from '../store/serverStore';
import {flattenCategories, isProtectedPage, linkCandidates, stripDuplicateH1} from '../utils/knowledge';

type Props = StackScreenProps<RootStackParamList, 'KnowledgeDoc'>;

type Sheet = 'more' | 'move' | 'delete' | null;

export function KnowledgeDocScreen({route, navigation}: Props) {
  const {path, title, agentId, edit} = route.params;
  const [sheet, setSheet] = useState<Sheet>(null);
  const [categories, setCategories] = useState<string[]>([]);
  const category = path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '';

  const source = useMemo<DocSource>(
    () => ({
      load: async () => {
        const res = await getKnowledgeDoc(path, agentId);
        return {
          content: res.content,
          mtime: res.mtime,
          editable: res.editable,
          readonlyReason: isProtectedPage(res.path) ? tr('knowledge_readonly_protected') : tr('knowledge_readonly_large'),
        };
      },
      save: async (content, mtime) => {
        const res = await knowledgeAction<{mtime: number}>(
          {action: 'update_document', payload: {path, content, expected_mtime: mtime}},
          agentId,
        );
        return res.mtime;
      },
    }),
    [path, agentId],
  );

  const openLink = useCallback(
    (href: string) => {
      const candidates = linkCandidates(path, href);
      if (!candidates.length) {
        return false;
      }
      (async () => {
        for (const candidate of candidates) {
          const hit = await getKnowledgeDoc(candidate, agentId).catch(() => null);
          if (hit) {
            const label = hit.content.match(/^\s*#\s+(.+)/)?.[1]?.trim();
            navigation.push('KnowledgeDoc', {path: hit.path, title: label || candidate.split('/').pop() || candidate, agentId});
            return;
          }
        }
        showToast(tr('knowledge_link_missing'));
      })();
      return true;
    },
    [path, agentId, navigation],
  );

  const next = (s: Sheet) => {
    setSheet(null);
    setTimeout(() => setSheet(s), SHEET_DISMISS_MS);
  };

  const pickMove = async () => {
    try {
      const tree = await getKnowledgeTree(agentId);
      const paths = flattenCategories(tree.tree)
        .map(c => c.path)
        .filter(p => p !== category);
      if (!paths.length) {
        setSheet(null);
        showToast(tr('knowledge_no_other_category'));
        return;
      }
      setCategories(paths);
      next('move');
    } catch (e) {
      setSheet(null);
      showToast(describeConnectError(e));
    }
  };

  const move = async (target: string) => {
    setSheet(null);
    try {
      const res = await knowledgeAction<{results: {moved: boolean; target?: string; reason?: string}[]}>(
        {action: 'move_documents', payload: {paths: [path], target_category: target}},
        agentId,
      );
      const r = res.results?.[0];
      if (!r?.moved || !r.target) {
        showToast(r?.reason === 'target_exists' ? tr('knowledge_move_target_exists') : tr('knowledge_move_failed'));
        return;
      }
      showToast(trf('knowledge_moved_to', {target}));
      navigation.setParams({path: r.target, edit: false});
    } catch (e) {
      showToast(trf('knowledge_move_failed_detail', {error: describeConnectError(e)}));
    }
  };

  const remove = async () => {
    try {
      await knowledgeAction({action: 'delete_documents', payload: {paths: [path]}}, agentId);
      setSheet(null);
      showToast(tr('common_deleted'));
      navigation.goBack();
    } catch (e) {
      setSheet(null);
      showToast(trf('common_delete_failed', {error: describeConnectError(e)}));
    }
  };

  const transform = useCallback((content: string) => stripDuplicateH1(content, title), [title]);

  return (
    <>
      <DocPage
        navigation={navigation}
        title={title}
        meta={path}
        source={source}
        startEditing={edit}
        onLink={openLink}
        onMore={isProtectedPage(path) ? undefined : () => setSheet('more')}
        transform={transform}
      />
      <ChoiceSheet
        visible={sheet === 'more'}
        title={tr('knowledge_doc')}
        options={[
          {key: 'move', label: tr('knowledge_move_to_other'), icon: faArrowRightArrowLeft},
          {key: 'delete', label: tr('common_delete'), icon: faTrashCan},
        ]}
        onSelect={key => (key === 'move' ? pickMove() : next('delete'))}
        onClose={() => setSheet(null)}
      />
      <ChoiceSheet
        visible={sheet === 'move'}
        title={tr('knowledge_move_to')}
        options={categories.map(c => ({key: c, label: c}))}
        onSelect={move}
        onClose={() => setSheet(null)}
      />
      <ConfirmSheet
        visible={sheet === 'delete'}
        title={tr('knowledge_delete_doc')}
        message={trf('knowledge_delete_doc_msg', {title})}
        confirmLabel={tr('common_delete')}
        danger
        onConfirm={remove}
        onClose={() => setSheet(null)}
      />
    </>
  );
}
