import {create} from 'zustand';
import {getMenu, saveMenu} from '../api/cowApi';
import type {MenuDoc, MenuGroup, MenuItem} from '../protocol/resources';
import {readJSON, removeKey, writeJSON} from '../storage/kv';
import {resetOnSignOut} from './reset';

/** Mirrors MENU_DEFAULT / MENU_DEFAULT_HIDDEN / MENU_REQUIRED in the web console's core/menu.js. */
const MENU_DEFAULT: {id: string; views: string[]}[] = [
  {id: 'chat', views: ['chat', 'artifacts']},
  {id: 'manage', views: ['agents', 'config', 'skills', 'memory', 'knowledge', 'channels', 'tasks']},
  {id: 'monitor', views: ['logs']},
];
const MENU_DEFAULT_HIDDEN = new Set(['artifacts']);
export const MENU_REQUIRED = new Set(['chat', 'config']);
const GROUP_LABELS: Record<string, string> = {chat: '对话', manage: '管理', monitor: '监控'};

const CACHE_KEY = 'menu:saved';

const defaultItem = (view: string): MenuItem => ({
  id: view,
  type: 'builtin',
  view,
  title: '',
  icon: '',
  hidden: MENU_DEFAULT_HIDDEN.has(view),
});

/** The menu to draw: the saved one, plus any built-in page added since it was saved. */
export function menuMerge(saved: MenuDoc | null): MenuDoc {
  if (!saved || !Array.isArray(saved.groups) || !saved.groups.length) {
    return {groups: MENU_DEFAULT.map(g => ({id: g.id, title: '', items: g.views.map(defaultItem)}))};
  }
  const groups: MenuGroup[] = saved.groups.map(g => ({
    id: g.id,
    title: g.title || '',
    items: (g.items || []).map(i => ({...i})),
  }));
  const present = new Set<string>();
  groups.forEach(g => g.items.forEach(i => i.type === 'builtin' && present.add(i.view)));
  MENU_DEFAULT.forEach(def =>
    def.views.forEach(view => {
      if (present.has(view)) {
        return;
      }
      const home = groups.find(g => g.id === def.id) || groups[groups.length - 1];
      home.items.push(defaultItem(view));
    }),
  );
  return {groups};
}

export function menuGroupLabel(group: MenuGroup): string {
  return group.title || GROUP_LABELS[group.id] || '未命名分组';
}

interface MenuState {
  doc: MenuDoc;
  /** Whether a layout has been saved at all; an unsaved menu is the built-in one. */
  customised: boolean;
  load: () => Promise<void>;
  setHidden: (view: string, hidden: boolean) => Promise<void>;
  reset: () => Promise<void>;
}

export const useMenuStore = create<MenuState>((set, get) => {
  const apply = (saved: MenuDoc | null) => {
    set({doc: menuMerge(saved), customised: !!saved});
    writeJSON(CACHE_KEY, saved).catch(() => undefined);
  };

  readJSON<MenuDoc | null>(CACHE_KEY, null)
    .then(cached => {
      if (cached && !get().customised) {
        set({doc: menuMerge(cached), customised: true});
      }
    })
    .catch(() => undefined);

  return {
    doc: menuMerge(null),
    customised: false,

    load: async () => {
      const res = await getMenu();
      apply(res.menu);
    },

    setHidden: async (view, hidden) => {
      const before = get().doc;
      const doc: MenuDoc = {
        groups: before.groups.map(g => ({
          ...g,
          items: g.items.map(i => (i.type === 'builtin' && i.view === view ? {...i, hidden} : i)),
        })),
      };
      set({doc});
      try {
        const res = await saveMenu(doc);
        apply(res.menu);
      } catch (e) {
        set({doc: before});
        throw e;
      }
    },

    reset: async () => {
      const res = await saveMenu(null);
      apply(res.menu);
    },
  };
});

// The cached menu belongs to the server signed out of.
resetOnSignOut(useMenuStore, () => {
  removeKey(CACHE_KEY).catch(() => undefined);
});
