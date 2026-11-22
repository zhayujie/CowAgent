import {createContext, useCallback, useContext, useRef} from 'react';
import type {LayoutChangeEvent} from 'react-native';

/**
 * Scrolls the message list by `dy` pixels of content, without animation, for a row that grew.
 * The newest row says so: the list may already be holding still around it natively.
 */
export const ListShiftContext = createContext<((dy: number, newest: boolean) => void) | null>(null);

/** Hands a toggle inside a message to the row that measures it. */
export const RowToggleContext = createContext<((apply: () => void) => void) | null>(null);

const PENDING_MS = 600;

/**
 * Keeps a tapped control under the finger when it opens or closes something.
 * The chat list is inverted: a message that grows pushes everything above its
 * bottom edge upwards, the control included, so the list follows by as much
 * as the row grew.
 */
export function useAnchoredRow(newest = false) {
  const shift = useContext(ListShiftContext);
  const height = useRef(0);
  const pending = useRef(0);

  const onLayout = useCallback(
    (e: LayoutChangeEvent) => {
      const h = e.nativeEvent.layout.height;
      const before = height.current;
      height.current = h;
      if (!before || h === before) {
        return;
      }
      if (pending.current > Date.now()) {
        pending.current = 0;
        shift?.(h - before, newest);
      }
    },
    [shift, newest],
  );

  const toggle = useCallback((apply: () => void) => {
    pending.current = Date.now() + PENDING_MS;
    apply();
  }, []);

  return {onLayout, toggle};
}

/** A toggle nested in a message row; falls back to a plain toggle outside one. */
export function useRowToggle() {
  const toggle = useContext(RowToggleContext);
  return toggle ?? ((apply: () => void) => apply());
}
