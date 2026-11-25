import {createContext, useCallback, useContext, useRef} from 'react';
import type {LayoutChangeEvent} from 'react-native';

/**
 * Scrolls the message list by `dy` pixels of content, without animation, for a row that grew.
 * The newest row says so: the list may already be holding still around it natively.
 */
export const ListShiftContext = createContext<((dy: number, newest: boolean) => void) | null>(null);

/**
 * Asks the list to hold the row above message `id` still, then runs `apply` once it does.
 * False when there is no row above to hold.
 */
export const ListPinContext = createContext<((id: string, apply: () => void) => boolean) | null>(null);

/** Hands a toggle inside a message to the row that measures it. */
export const RowToggleContext = createContext<((apply: () => void) => void) | null>(null);

const PENDING_MS = 600;

/**
 * Keeps a tapped control under the finger when it opens or closes something.
 * The chat list is inverted: a message that grows pushes everything above its
 * bottom edge upwards, the control included. Holding the row above still lets
 * the message grow downwards in the same frame; the topmost message, with
 * nothing above it, has the list follow by as much as it grew instead.
 */
export function useAnchoredRow(id: string, newest = false) {
  const shift = useContext(ListShiftContext);
  const pin = useContext(ListPinContext);
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

  const toggle = useCallback(
    (apply: () => void) => {
      if (pin?.(id, apply)) {
        return;
      }
      pending.current = Date.now() + PENDING_MS;
      apply();
    },
    [pin, id],
  );

  return {onLayout, toggle};
}

/** A toggle nested in a message row; falls back to a plain toggle outside one. */
export function useRowToggle() {
  const toggle = useContext(RowToggleContext);
  return toggle ?? ((apply: () => void) => apply());
}
