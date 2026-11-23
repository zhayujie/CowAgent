import {useFrameWidth} from '../theme/layout';

/** Pages whose content pans sideways only go back from the screen edge. */
export const EDGE_ONLY = 32;

/** How far from the left a swipe back may start on an ordinary page: anywhere. */
export function useFullBackSwipe(): number {
  return useFrameWidth();
}
