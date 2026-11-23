import {useNavigation, type ParamListBase} from '@react-navigation/native';
import type {StackNavigationProp} from '@react-navigation/stack';
import React, {useCallback, useEffect, useLayoutEffect, useMemo, useRef, type ReactNode} from 'react';
import {StyleSheet, type StyleProp, type ViewStyle} from 'react-native';
import {Gesture, GestureDetector} from 'react-native-gesture-handler';
import Animated, {Easing, interpolate, useAnimatedStyle, useSharedValue, withTiming} from 'react-native-reanimated';
import {scheduleOnRN} from 'react-native-worklets';
import {EDGE_ONLY, useFullBackSwipe} from '../navigation/gestures';
import {usePaneWidth} from '../theme/layout';

const ACTIVATE = 16;
/** Moved this far up or down first, the touch is a scroll. */
const VERTICAL_SLOP = 12;
/** Released past this share of the width (or flung), the swipe changes tab. */
const COMMIT_SHARE = 0.22;
const COMMIT_VELOCITY = 600;
/** How far the outgoing page slides before it is gone; fading tracks the same distance. */
const EXIT_SHARE = 0.3;
const ENTER_SHIFT = 28;
const EASE = Easing.bezier(0.22, 0.61, 0.36, 1);

/**
 * The body under a tab bar: swipe left for the next tab, right for the previous
 * one, and a tapped tab slides in from its side. On the first tab a swipe right
 * still goes back a page; past it, only a swipe from the screen edge does.
 */
export function SwipeTabs<K extends string>({
  tabs,
  value,
  onChange,
  enabled = true,
  style,
  children,
}: {
  tabs: readonly K[];
  value: K;
  onChange: (key: K) => void;
  /** Off where the body pans sideways itself, such as a graph. */
  enabled?: boolean;
  style?: StyleProp<ViewStyle>;
  children: ReactNode;
}) {
  const navigation = useNavigation<StackNavigationProp<ParamListBase>>();
  const fullBackSwipe = useFullBackSwipe();
  const width = usePaneWidth();
  const index = tabs.indexOf(value);
  const x = useSharedValue(0);
  const w = useSharedValue(width);
  const canPrev = useSharedValue(false);
  const canNext = useSharedValue(false);
  const startX = useSharedValue(0);
  const startY = useSharedValue(0);

  useEffect(() => {
    canPrev.value = enabled && index > 0;
    canNext.value = enabled && index >= 0 && index < tabs.length - 1;
  }, [enabled, index, tabs.length, canPrev, canNext]);

  useEffect(() => {
    navigation.setOptions({gestureResponseDistance: index > 0 ? EDGE_ONLY : fullBackSwipe});
  }, [navigation, index, fullBackSwipe]);

  const shown = useRef(index);
  useLayoutEffect(() => {
    const dir = Math.sign(index - shown.current);
    shown.current = index;
    if (dir) {
      x.value = dir * ENTER_SHIFT;
      x.value = withTiming(0, {duration: 220, easing: EASE});
    }
  }, [index, x]);

  // The gesture is built once and reads the tab from here: a detector handed a
  // new gesture after every tab change can stop answering touches.
  const latest = useRef({tabs, index, onChange});
  latest.current = {tabs, index, onChange};
  const go = useCallback((dir: number) => {
    const {tabs: keys, index: at, onChange: change} = latest.current;
    const key = keys[at + dir];
    if (key !== undefined) {
      change(key);
    }
  }, []);

  const gesture = useMemo(
    () =>
      Gesture.Pan()
        .manualActivation(true)
        .onTouchesDown(e => {
          const touch = e.changedTouches[0];
          if (touch) {
            startX.value = touch.absoluteX;
            startY.value = touch.absoluteY;
          }
        })
        .onTouchesMove((e, manager) => {
          const touch = e.allTouches[0];
          if (!touch) {
            return;
          }
          const dx = touch.absoluteX - startX.value;
          const dy = touch.absoluteY - startY.value;
          if (Math.abs(dy) > VERTICAL_SLOP && Math.abs(dy) >= Math.abs(dx)) {
            manager.fail();
          } else if (Math.abs(dx) >= ACTIVATE) {
            if ((dx < 0 && canNext.value) || (dx > 0 && canPrev.value)) {
              manager.activate();
            } else {
              manager.fail();
            }
          }
        })
        .onUpdate(e => {
          x.value = e.translationX * 0.6;
        })
        .onEnd((e, success) => {
          const dir = e.translationX < 0 ? 1 : -1;
          const allowed = dir === 1 ? canNext.value : canPrev.value;
          const far = Math.abs(e.translationX) > w.value * COMMIT_SHARE;
          const flung = Math.abs(e.velocityX) > COMMIT_VELOCITY && Math.sign(e.velocityX) === -dir;
          if (success && allowed && (far || flung)) {
            x.value = withTiming(-dir * w.value * EXIT_SHARE, {duration: 120}, done => {
              if (done) {
                scheduleOnRN(go, dir);
              }
            });
            return;
          }
          x.value = withTiming(0, {duration: 180, easing: EASE});
        }),
    [go, x, w, canPrev, canNext, startX, startY],
  );

  // Explicit dependencies keep the web preview working, where no worklets Babel plugin runs.
  const animated = useAnimatedStyle(
    () => ({
      opacity: interpolate(Math.abs(x.value), [0, Math.max(w.value * EXIT_SHARE, 1)], [1, 0], 'clamp'),
      transform: [{translateX: x.value}],
    }),
    [x, w],
  );

  return (
    <GestureDetector gesture={gesture}>
      <Animated.View
        style={[styles.fill, style, animated]}
        onLayout={e => {
          w.value = e.nativeEvent.layout.width;
        }}>
        {children}
      </Animated.View>
    </GestureDetector>
  );
}

const styles = StyleSheet.create({
  fill: {flex: 1},
});
