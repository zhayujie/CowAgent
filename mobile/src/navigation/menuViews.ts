import {
  faAddressCard,
  faBookmark,
  faCalendar,
  faChartBar,
  faClock,
  faComments,
  faEnvelope,
  faFileLines,
  faFlag,
  faFolder,
  faFolderOpen,
  faHeart,
  faHouse,
  faImage,
  faLightbulb,
  faNewspaper,
  faPaperPlane,
  faStar,
} from '@fortawesome/free-regular-svg-icons';
import {
  faBolt,
  faBook,
  faBox,
  faBrain,
  faCartShopping,
  faCode,
  faFilm,
  faGauge,
  faGlobe,
  faLayerGroup,
  faLink,
  faMagnifyingGlass,
  faMusic,
  faPen,
  faRobot,
  faRocket,
  faSliders,
  faTable,
  faTerminal,
} from '@fortawesome/free-solid-svg-icons';
import type {IconDefinition} from '@fortawesome/fontawesome-svg-core';
import {fileFromPayload, type ChatFile} from '../files/chatFile';
import {tr, type MessageKey} from '../i18n';
import type {MenuDoc, MenuItem} from '../protocol/resources';
import {menuGroupLabel} from '../store/menuStore';

export type MenuRoute =
  | 'Sessions'
  | 'Artifacts'
  | 'Agents'
  | 'Settings'
  | 'Skills'
  | 'Memory'
  | 'Knowledge'
  | 'Channels'
  | 'Tasks'
  | 'Logs';

type BuiltinView = {label: string; icon: IconDefinition; route: MenuRoute};

/** `label` is a getter so it follows the current language. */
const builtin = (key: MessageKey, icon: IconDefinition, route: MenuRoute): BuiltinView => ({
  get label() {
    return tr(key);
  },
  icon,
  route,
});

/**
 * Built-in pages of the shared menu this app lists; others (desktop-only) are
 * skipped. Logs is left out too: it sits behind the drawer's version sheet and
 * in Settings rather than in the menu.
 */
export const BUILTIN_VIEWS: Record<string, BuiltinView> = {
  chat: builtin('menu_chat', faComments, 'Sessions'),
  artifacts: builtin('menu_artifacts', faFolderOpen, 'Artifacts'),
  agents: builtin('menu_agents', faAddressCard, 'Agents'),
  config: builtin('menu_config', faSliders, 'Settings'),
  skills: builtin('menu_skills', faLightbulb, 'Skills'),
  memory: builtin('menu_memory', faBookmark, 'Memory'),
  knowledge: builtin('menu_knowledge', faNewspaper, 'Knowledge'),
  channels: builtin('menu_channels', faPaperPlane, 'Channels'),
  tasks: builtin('menu_tasks', faClock, 'Tasks'),
};

/** Same names as MENU_ICONS in the web console's core/menu.js. */
const MENU_ICONS: Record<string, IconDefinition> = {
  globe: faGlobe,
  link: faLink,
  chart: faChartBar,
  gauge: faGauge,
  table: faTable,
  file: faFileLines,
  book: faBook,
  image: faImage,
  video: faFilm,
  music: faMusic,
  code: faCode,
  calendar: faCalendar,
  star: faStar,
  bookmark: faBookmark,
  folder: faFolder,
  box: faBox,
  rocket: faRocket,
  flag: faFlag,
  heart: faHeart,
  bolt: faBolt,
  brain: faBrain,
  clock: faClock,
  terminal: faTerminal,
  home: faHouse,
  cart: faCartShopping,
  mail: faEnvelope,
  layers: faLayerGroup,
  robot: faRobot,
  pen: faPen,
  search: faMagnifyingGlass,
};

export type MenuEntry =
  | {key: string; label: string; icon: IconDefinition; kind: 'route'; view: string; route: MenuRoute}
  /** A pinned artifact; `file` is null once it has been deleted from the server. */
  | {key: string; label: string; icon: IconDefinition; kind: 'file'; file: ChatFile | null}
  /** `external` links leave the app, as `open: 'tab'` leaves the web console. */
  | {key: string; label: string; icon: IconDefinition; kind: 'link'; url: string; external: boolean};

export interface MenuSection {
  id: string;
  label: string;
  entries: MenuEntry[];
}

export function menuItemIcon(item: MenuItem): IconDefinition {
  const custom = item.icon ? MENU_ICONS[item.icon] : undefined;
  if (custom) {
    return custom;
  }
  if (item.type === 'builtin') {
    return BUILTIN_VIEWS[item.view]?.icon ?? faFileLines;
  }
  return item.type === 'url' ? faGlobe : faFileLines;
}

/** Pages the kernel embedded in this app cannot back: it runs no IM channels. */
const LOCAL_UNAVAILABLE_VIEWS = new Set(['channels']);

function entryOf(item: MenuItem, local: boolean): MenuEntry | null {
  const icon = menuItemIcon(item);
  if (item.type === 'builtin') {
    const meta = BUILTIN_VIEWS[item.view];
    if (!meta || item.hidden || (local && LOCAL_UNAVAILABLE_VIEWS.has(item.view))) {
      return null;
    }
    return {
      key: item.id,
      label: item.title || meta.label,
      icon,
      kind: 'route',
      view: item.view,
      route: meta.route,
    };
  }
  if (item.type === 'url') {
    return {key: item.id, label: item.title, icon, kind: 'link', url: item.url, external: item.open === 'tab'};
  }
  const file = item.file?.exists
    ? fileFromPayload({
        abs_path: item.path,
        file_name: item.file.file_name,
        kind: item.file.kind,
        raw_url: item.file.raw_url,
        preview_url: item.file.preview_url,
      })
    : null;
  return {key: item.id, label: item.title, icon, kind: 'file', file: file && item.title ? {...file, name: item.title} : file};
}

/** A web link shown inside the app, through the same page viewer as a generated HTML file. */
export function linkAsPage(label: string, url: string): ChatFile {
  return {name: label || url, kind: 'html', rawUrl: url};
}

/**
 * The web console keeps Artifacts hidden in its chat group; this app lists it
 * right below the chat page, wherever and however the shared menu has it,
 * behind a switch kept on the device.
 */
const PINNED_VIEW = 'artifacts';
const PINNED_GROUP = 'chat';

/** The entry Artifacts follows. */
export const isPinnedAnchor = (item: MenuItem) => item.type === 'builtin' && item.view === 'chat';

/** Where Artifacts is listed: the chat page's group, else the first one; null opens a Chat section. */
export function pinnedGroupId(doc: MenuDoc): string | null {
  const home = doc.groups.find(g => g.items.some(isPinnedAnchor)) ?? doc.groups[0];
  return home?.id ?? null;
}

export const pinnedGroupLabel = () => menuGroupLabel({id: PINNED_GROUP, title: '', items: []});

/** The shared menu's own Artifacts entry, which this app lists in its place instead. */
export const isPinnedMenuItem = (item: MenuItem) => item.type === 'builtin' && item.view === PINNED_VIEW;

/** `local`: the active server is the embedded kernel. `showPinned`: this device's switch for Artifacts. */
export function menuSections(doc: MenuDoc, local = false, showPinned = true): MenuSection[] {
  const pinned = showPinned
    ? entryOf({id: PINNED_VIEW, type: 'builtin', view: PINNED_VIEW, title: '', icon: ''}, local)
    : null;
  const homeId = pinned ? pinnedGroupId(doc) : null;
  const sections: MenuSection[] = doc.groups.map(g => {
    const items = g.items.filter(i => !isPinnedMenuItem(i));
    const home = pinned && g.id === homeId ? pinned : null;
    const entries: MenuEntry[] = home && !items.some(isPinnedAnchor) ? [home] : [];
    items.forEach(i => {
      const entry = entryOf(i, local);
      if (entry) {
        entries.push(entry);
      }
      if (home && isPinnedAnchor(i)) {
        entries.push(home);
      }
    });
    return {id: g.id, label: menuGroupLabel(g), entries};
  });
  if (pinned && homeId === null) {
    sections.push({id: PINNED_GROUP, label: pinnedGroupLabel(), entries: [pinned]});
  }
  return sections.filter(s => s.entries.length);
}
