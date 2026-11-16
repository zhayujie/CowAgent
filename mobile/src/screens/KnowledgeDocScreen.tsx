import {faArrowRightArrowLeft, faTrashCan} from '@fortawesome/free-solid-svg-icons';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useMemo, useState} from 'react';
import {getKnowledgeDoc, getKnowledgeTree, knowledgeAction} from '../api/cowApi';
import {DocPage, type DocSource} from '../components/DocPage';
import {ChoiceSheet, ConfirmSheet} from '../components/settings';
import {SHEET_DISMISS_MS} from '../components/Sheet';
import {showToast} from '../components/Toast';
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
          readonlyReason: isProtectedPage(res.path) ? '由 Agent 自动维护，只能查看' : '文件过大，只能查看',
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
        showToast('链接的文档不存在');
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
        showToast('没有其他分类可以移动过去');
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
        showToast(r?.reason === 'target_exists' ? '目标分类里已有同名文档' : '移动失败');
        return;
      }
      showToast(`已移动到 ${target}`);
      navigation.setParams({path: r.target, edit: false});
    } catch (e) {
      showToast(`移动失败：${describeConnectError(e)}`);
    }
  };

  const remove = async () => {
    try {
      await knowledgeAction({action: 'delete_documents', payload: {paths: [path]}}, agentId);
      setSheet(null);
      showToast('已删除');
      navigation.goBack();
    } catch (e) {
      setSheet(null);
      showToast(`删除失败：${describeConnectError(e)}`);
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
        title="文档"
        options={[
          {key: 'move', label: '移动到其他分类', icon: faArrowRightArrowLeft},
          {key: 'delete', label: '删除', icon: faTrashCan},
        ]}
        onSelect={key => (key === 'move' ? pickMove() : next('delete'))}
        onClose={() => setSheet(null)}
      />
      <ChoiceSheet
        visible={sheet === 'move'}
        title="移动到"
        options={categories.map(c => ({key: c, label: c}))}
        onSelect={move}
        onClose={() => setSheet(null)}
      />
      <ConfirmSheet
        visible={sheet === 'delete'}
        title="删除文档"
        message={`「${title}」会从知识库中删除，Agent 也将检索不到它。`}
        confirmLabel="删除"
        danger
        onConfirm={remove}
        onClose={() => setSheet(null)}
      />
    </>
  );
}
