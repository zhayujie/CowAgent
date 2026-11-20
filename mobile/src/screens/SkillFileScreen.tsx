import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useMemo} from 'react';
import {readSkillFile, writeSkillFile} from '../api/cowApi';
import {DocPage, type DocSource} from '../components/DocPage';
import {tr} from '../i18n';
import type {RootStackParamList} from '../navigation/types';
import {skillFileForReading} from '../utils/skills';

type Props = StackScreenProps<RootStackParamList, 'SkillFile'>;

export function SkillFileScreen({route, navigation}: Props) {
  const {name, path, title, edit} = route.params;
  const file = path || 'SKILL.md';

  const source = useMemo<DocSource>(
    () => ({
      load: async () => {
        const res = await readSkillFile(name, path);
        const readonlyReason = res.ships_with_install
          ? tr('skill_ro_builtin')
          : res.truncated
            ? tr('skill_ro_too_large')
            : res.lossy
              ? tr('skill_ro_lossy')
              : tr('skill_ro_default');
        return {
          content: res.content,
          mtime: res.mtime,
          editable: res.editable,
          readonlyReason: res.editable ? undefined : readonlyReason,
        };
      },
      save: async (content, mtime) => {
        const res = await writeSkillFile(name, path, content, mtime);
        return res.mtime;
      },
    }),
    [name, path],
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
