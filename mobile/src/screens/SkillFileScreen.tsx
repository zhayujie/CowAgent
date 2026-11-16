import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useMemo} from 'react';
import {readSkillFile, writeSkillFile} from '../api/cowApi';
import {DocPage, type DocSource} from '../components/DocPage';
import type {RootStackParamList} from '../navigation/types';
import {skillFileForReading} from '../utils/skills';

type Props = StackScreenProps<RootStackParamList, 'SkillFile'>;

export function SkillFileScreen({route, navigation}: Props) {
  const {name, path, title, agentId, edit} = route.params;
  const file = path || 'SKILL.md';

  const source = useMemo<DocSource>(
    () => ({
      load: async () => {
        const res = await readSkillFile(name, path, agentId);
        const readonlyReason = res.ships_with_install
          ? '内置技能随安装包更新，只能查看'
          : res.truncated
            ? '文件过大，只能查看'
            : res.lossy
              ? '含有无法识别的字符，只能查看'
              : '这个文件只能查看';
        return {
          content: res.content,
          mtime: res.mtime,
          editable: res.editable,
          readonlyReason: res.editable ? undefined : readonlyReason,
        };
      },
      save: async (content, mtime) => {
        const res = await writeSkillFile(name, path, content, mtime, agentId);
        return res.mtime;
      },
    }),
    [name, path, agentId],
  );

  const transform = useCallback((content: string) => skillFileForReading(file, content), [file]);

  return (
    <DocPage
      navigation={navigation}
      title={title}
      meta={`${name}/${file}`}
      source={source}
      startEditing={edit}
      transform={transform}
    />
  );
}
