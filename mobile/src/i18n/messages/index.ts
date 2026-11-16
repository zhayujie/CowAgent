import access from './access';
import chat from './chat';
import common from './common';
import files from './files';
import knowledge from './knowledge';
import settings from './settings';
import skills from './skills';
import tasks from './tasks';

/** One module per area, each with its own key prefix; __tests__/i18n.test.ts rejects keys defined twice. */
export const MESSAGE_MODULES = {access, chat, common, files, knowledge, settings, skills, tasks};

export const zh = {
  ...common.zh,
  ...access.zh,
  ...chat.zh,
  ...files.zh,
  ...knowledge.zh,
  ...settings.zh,
  ...skills.zh,
  ...tasks.zh,
};

export type MessageKey = keyof typeof zh;

export const en: Record<MessageKey, string> = {
  ...common.en,
  ...access.en,
  ...chat.en,
  ...files.en,
  ...knowledge.en,
  ...settings.en,
  ...skills.en,
  ...tasks.en,
};
