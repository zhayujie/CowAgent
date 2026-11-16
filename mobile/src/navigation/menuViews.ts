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
  faRectangleList,
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
import type {MenuDoc, MenuItem} from '../protocol/resources';
import {menuGroupLabel} from '../store/menuStore';

export type MenuRoute =
  | 'Artifacts'
  | 'Agents'
  | 'Settings'
  | 'Skills'
  | 'Memory'
  | 'Knowledge'
  | 'Channels'
  | 'Tasks'
  | 'Logs';

/** Built-in pages of the shared menu this app has a screen for; others (desktop-only) are skipped. */
export const BUILTIN_VIEWS: Record<string, {label: string; icon: IconDefinition; route: MenuRoute}> = {
  artifacts: {label: '产物中心', icon: faFolderOpen, route: 'Artifacts'},
  agents: {label: 'Agent 与团队', icon: faAddressCard, route: 'Agents'},
  config: {label: '设置', icon: faSliders, route: 'Settings'},
  skills: {label: '技能', icon: faLightbulb, route: 'Skills'},
  memory: {label: '记忆', icon: faBookmark, route: 'Memory'},
  knowledge: {label: '知识库', icon: faNewspaper, route: 'Knowledge'},
  channels: {label: '通道', icon: faPaperPlane, route: 'Channels'},
  tasks: {label: '定时任务', icon: faClock, route: 'Tasks'},
  logs: {label: '日志', icon: faRectangleList, route: 'Logs'},
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
  /** The group holding the chat page; the drawer draws its conversation shortcuts there. */
  hasChat: boolean;
  entries: MenuEntry[];
}

export function menuItemIcon(item: MenuItem): IconDefinition {
  const custom = item.icon ? MENU_ICONS[item.icon] : undefined;
  if (custom) {
    return custom;
  }
  if (item.type === 'builtin') {
    return item.view === 'chat' ? faComments : BUILTIN_VIEWS[item.view]?.icon ?? faFileLines;
  }
  return item.type === 'url' ? faGlobe : faFileLines;
}

function entryOf(item: MenuItem): MenuEntry | null {
  const icon = menuItemIcon(item);
  if (item.type === 'builtin') {
    const meta = BUILTIN_VIEWS[item.view];
    if (!meta || item.hidden) {
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

export function menuSections(doc: MenuDoc): MenuSection[] {
  return doc.groups
    .map(g => ({
      id: g.id,
      label: menuGroupLabel(g),
      hasChat: g.items.some(i => i.type === 'builtin' && i.view === 'chat'),
      entries: g.items.map(entryOf).filter((e): e is MenuEntry => !!e),
    }))
    .filter(s => s.hasChat || s.entries.length);
}
