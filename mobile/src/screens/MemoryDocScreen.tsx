import type {StackScreenProps} from '@react-navigation/stack';
import React, {useMemo} from 'react';
import {getMemoryContent, readWorkspaceText, writeWorkspaceText} from '../api/cowApi';
import {DocPage, type DocSource} from '../components/DocPage';
import {tr} from '../i18n';
import type {RootStackParamList} from '../navigation/types';
import type {MemoryCategory} from '../protocol/resources';

type Props = StackScreenProps<RootStackParamList, 'MemoryDoc'>;

function memoryRelPath(filename: string, category: MemoryCategory): string {
  if (filename === 'MEMORY.md') {
    return filename;
  }
  return category === 'evolution'
    ? `memory/evolution/${filename}`
    : category === 'dream'
      ? `memory/dreams/${filename}`
      : `memory/${filename}`;
}

export function MemoryDocScreen({route, navigation}: Props) {
  const {filename, category, title, agentId} = route.params;

  // Memory files are listed by name and category, but edited by workspace path.
  const source = useMemo<DocSource>(() => {
    let relPath: string | null = null;
    return {
      load: async () => {
        const meta = await getMemoryContent(filename, category, agentId);
        relPath = meta.rel_path ?? null;
        if (!relPath) {
          return {content: meta.content, mtime: null, editable: false, readonlyReason: tr('memory_readonly_old_server')};
        }
        const text = await readWorkspaceText(relPath, agentId).catch(() => null);
        if (!text) {
          return {content: meta.content, mtime: null, editable: false, readonlyReason: tr('memory_readonly_unavailable')};
        }
        return {
          content: text.content,
          mtime: text.mtime,
          editable: text.editable,
          readonlyReason: text.editable ? undefined : tr('memory_readonly_unreadable'),
        };
      },
      save: async (content, mtime) => {
        const res = await writeWorkspaceText(relPath as string, content, mtime, agentId);
        return res.mtime;
      },
    };
  }, [filename, category, agentId]);

  return <DocPage navigation={navigation} title={title} meta={memoryRelPath(filename, category)} source={source} />;
}
