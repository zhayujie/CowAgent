import React, {createContext, useContext, type ReactNode} from 'react';
import {Platform, useWindowDimensions} from 'react-native';

// Web preview renders inside a phone-sized frame (see web/index.html).
const FRAME_WIDTH = Platform.OS === 'web' ? 430 : Number.POSITIVE_INFINITY;

/** From here the menu stays open beside the page, as on the web console's wide screens. */
const SIDEBAR_MIN = 900;
/** From here sheets float as dialogs instead of rising from the bottom edge. */
const DIALOG_MIN = 600;

export const SIDEBAR_WIDTH = 288;
/** The web console's chat column. */
export const CHAT_WIDTH = 768;
/** Pages read best at about this width; wider, lists and forms only stretch. */
export const PAGE_WIDTH = 760;

/** Width of the app's window, or of the phone frame the web preview draws. */
export function useFrameWidth(): number {
  return Math.min(useWindowDimensions().width, FRAME_WIDTH);
}

export function useSidebarLayout(): boolean {
  return useFrameWidth() >= SIDEBAR_MIN;
}

export function useDialogLayout(): boolean {
  return useFrameWidth() >= DIALOG_MIN;
}

const PaneWidth = createContext<number | null>(null);

/** Width of the column content is laid out in: the page's on a tablet, the window's on a phone. */
export function usePaneWidth(): number {
  const frame = useFrameWidth();
  const pane = useContext(PaneWidth);
  return pane === null ? frame : Math.min(pane, frame);
}

export function PaneWidthProvider({width, children}: {width: number; children: ReactNode}) {
  return <PaneWidth.Provider value={width}>{children}</PaneWidth.Provider>;
}
