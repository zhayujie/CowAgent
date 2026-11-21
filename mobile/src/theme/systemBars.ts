import {NativeModules, Platform, processColor} from 'react-native';
import type {Palette} from './palette';

const native: {setNavigationBar(color: number, darkIcons: boolean): void} | undefined =
  Platform.OS === 'android' ? NativeModules.CowSystemBars : undefined;

/** Pages on the grouped background; the rest sit on bg0. */
const GROUPED_ROUTES: ReadonlySet<string> = new Set(['Settings', 'Devices', 'Permissions', 'Models']);

/** The background of a page, which the system bars around it take on. */
export function routeBackground(route: string | undefined, t: Palette): string {
  return route && GROUPED_ROUTES.has(route) ? t.grouped : t.bg0;
}

/** Fills Android's navigation bar with the page's colour, as the status bar is. */
export function paintNavigationBar(color: string, dark: boolean): void {
  const value = processColor(color);
  if (native && typeof value === 'number') {
    native.setNavigationBar(value, !dark);
  }
}
