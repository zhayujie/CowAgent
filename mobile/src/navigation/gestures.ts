import {Platform, useWindowDimensions} from 'react-native';

// Web preview renders inside a phone-sized frame (see web/index.html).
const FRAME_WIDTH = Platform.OS === 'web' ? 430 : Number.POSITIVE_INFINITY;

/** Pages whose content pans sideways only go back from the screen edge. */
export const EDGE_ONLY = 32;

/** How far from the left a swipe back may start on an ordinary page: anywhere. */
export function useFullBackSwipe(): number {
  const {width} = useWindowDimensions();
  return Math.min(width, FRAME_WIDTH);
}
