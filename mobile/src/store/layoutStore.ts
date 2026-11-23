import {create} from 'zustand';
import type {DrawerView} from '../components/DrawerMenu';
import type {ChatFile} from '../files/chatFile';
import type {SessionItem} from '../protocol/events';

/** What the sidebar asks of the chat page, which stays mounted at the bottom of the stack. */
export interface ChatCommands {
  newChat: () => void;
  openSession: (session: SessionItem) => void;
  sessionActions: (session: SessionItem) => void;
  openFile: (file: ChatFile) => void;
  openLink: (label: string, url: string, external: boolean) => void;
  switchServer: () => void;
}

/** The menu kept open beside the page on wide screens. */
interface LayoutState {
  sidebarHidden: boolean;
  sidebarView: DrawerView;
  /** The conversations were opened from the menu, so they offer a way back to it. */
  sidebarNested: boolean;
  /** The chat on screen, for the sidebar to mark. */
  sessionId: string;
  chat: ChatCommands | null;
  /** The header buttons: show `view`, or hide the sidebar when it already shows it. */
  toggleSidebar: (view: DrawerView) => void;
  setSidebarView: (view: DrawerView, nested: boolean) => void;
}

export const useLayoutStore = create<LayoutState>((set, get) => ({
  sidebarHidden: false,
  sidebarView: 'menu',
  sidebarNested: false,
  sessionId: '',
  chat: null,
  toggleSidebar: view => {
    const {sidebarHidden, sidebarView} = get();
    if (!sidebarHidden && sidebarView === view) {
      set({sidebarHidden: true});
    } else {
      set({sidebarHidden: false, sidebarView: view, sidebarNested: false});
    }
  },
  setSidebarView: (view, nested) => set({sidebarView: view, sidebarNested: nested}),
}));
