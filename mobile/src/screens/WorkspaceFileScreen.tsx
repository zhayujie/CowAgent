import type {StackScreenProps} from '@react-navigation/stack';
import React, {useMemo} from 'react';
import {readWorkspaceText, writeWorkspaceText} from '../api/cowApi';
import {DocPage, type DocSource} from '../components/DocPage';
import {tr} from '../i18n';
import type {RootStackParamList} from '../navigation/types';
import type {WorkspaceText} from '../protocol/resources';
import {agentParam, useAgentStore} from '../store/agentStore';
import {useChatStore} from '../store/chatStore';
import {languageOf} from '../utils/highlight';

type Props = StackScreenProps<RootStackParamList, 'WorkspaceFile'>;

function readonlyReason(text: WorkspaceText): string | undefined {
  if (text.editable) {
    return undefined;
  }
  return tr(text.truncated ? 'workspace_edit_too_large' : text.lossy ? 'workspace_edit_encoding' : 'workspace_edit_unsupported');
}

/** Read as a code block, with a fence longer than any run of backticks inside. */
function fenced(content: string, lang: string | undefined): string {
  const longest = (content.match(/`+/g) ?? []).reduce((n, run) => Math.max(n, run.length), 2);
  const fence = '`'.repeat(longest + 1);
  return `${fence}${lang ?? ''}\n${content}\n${fence}`;
}

export function WorkspaceFileScreen({route, navigation}: Props) {
  const {path, name, kind, relPath} = route.params;

  const source = useMemo<DocSource>(() => {
    // The server finds the file in the project folder the chat on screen works in.
    const sessionId = useChatStore.getState().currentSessionId ?? undefined;
    const agentId = agentParam(useAgentStore.getState().currentId);
    return {
      load: async () => {
        const text = await readWorkspaceText(path, agentId, sessionId);
        return {content: text.content, mtime: text.mtime, editable: text.editable, readonlyReason: readonlyReason(text)};
      },
      save: async (content, mtime) => (await writeWorkspaceText(path, content, mtime, agentId, sessionId)).mtime,
    };
  }, [path]);

  const transform = useMemo(
    () => (kind === 'markdown' ? undefined : (content: string) => fenced(content, languageOf(name))),
    [kind, name],
  );

  return (
    <DocPage
      navigation={navigation}
      title={name}
      meta={relPath ?? path}
      source={source}
      startEditing
      transform={transform}
    />
  );
}
