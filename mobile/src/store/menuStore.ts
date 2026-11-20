import {create} from 'zustand';
import {getMenu, saveMenu} from '../api/cowApi';
import {tr, type MessageKey} from '../i18n';
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
const GROUP_LABELS: Record<string, MessageKey> = {
  chat: 'menu_group_chat',
  manage: 'menu_group_manage',
  monitor: 'menu_group_monitor',
};

const CACHE_KEY = 'menu:saved';
const ARTIFACTS_HIDDEN_KEY = 'menu:artifacts-hidden';

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
  return group.title || tr(GROUP_LABELS[group.id] ?? 'menu_group_untitled');
}

interface MenuState {
  doc: MenuDoc;
  /** Whether a layout has been saved at all; an unsaved menu is the built-in one. */
  customised: boolean;
  /** This device hides Artifacts from its drawer; the shared menu's flag is the web console's. */
  artifactsHidden: boolean;
  setArtifactsHidden: (hidden: boolean) => void;
  load: () => Promise<void>;
  setHidden: (view: string, hidden: boolean) => Promise<void>;
  /** Renames a custom entry (a pinned file or a link). */
  renameItem: (id: string, title: string) => Promise<void>;
  /** Takes an entry out of the menu; a pinned file itself stays where it is. */
  removeItem: (id: string) => Promise<void>;
  /** Appends a custom entry (a file or a link) to a group. */
  addItem: (groupId: string, item: CustomMenuItem) => Promise<void>;
  reset: () => Promise<void>;
}

export type CustomMenuItem = Exclude<MenuItem, {type: 'builtin'}>;

/** Same shape as the web console's ids (`_meId`), which the server checks. */
export const newMenuItemId = () => `m_${Math.random().toString(36).slice(2, 10)}`;

export const useMenuStore = create<MenuState>((set, get) => {
  const apply = (saved: MenuDoc | null) => {
    set({doc: menuMerge(saved), customised: !!saved});
    writeJSON(CACHE_KEY, saved).catch(() => undefined);
  };

  /** Shows the edit at once and saves it; a save the server refuses puts the menu back. */
  const commit = async (edit: (items: MenuItem[], group: MenuGroup) => MenuItem[]) => {
    const before = get().doc;
    const doc: MenuDoc = {groups: before.groups.map(g => ({...g, items: edit(g.items, g)}))};
    set({doc});
    try {
      const res = await saveMenu(doc);
      apply(res.menu);
    } catch (e) {
      set({doc: before});
      throw e;
    }
  };

  readJSON<MenuDoc | null>(CACHE_KEY, null)
    .then(cached => {
      if (cached && !get().customised) {
        set({doc: menuMerge(cached), customised: true});
      }
    })
    .catch(() => undefined);
  readJSON<boolean>(ARTIFACTS_HIDDEN_KEY, false)
    .then(hidden => set({artifactsHidden: hidden}))
    .catch(() => undefined);

  return {
    doc: menuMerge(null),
    customised: false,
    artifactsHidden: false,

    setArtifactsHidden: hidden => {
      set({artifactsHidden: hidden});
      writeJSON(ARTIFACTS_HIDDEN_KEY, hidden).catch(() => undefined);
    },

    load: async () => {
      const res = await getMenu();
      apply(res.menu);
    },

    setHidden: (view, hidden) =>
      commit(items => items.map(i => (i.type === 'builtin' && i.view === view ? {...i, hidden} : i))),

    renameItem: (id, title) =>
      commit(items => items.map(i => (i.id === id && i.type !== 'builtin' ? {...i, title} : i))),

    removeItem: id => commit(items => items.filter(i => i.id !== id || i.type === 'builtin')),

    addItem: (groupId, item) => commit((items, group) => (group.id === groupId ? [...items, item] : items)),

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
