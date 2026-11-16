import React, {useEffect} from 'react';
import {Text} from 'react-native';
import Animated, {
  cancelAnimation,
  Easing,
  interpolate,
  useAnimatedStyle,
  useSharedValue,
  withDelay,
  withSequence,
  withTiming,
} from 'react-native-reanimated';
import {scheduleOnRN} from 'react-native-worklets';
import {create} from 'zustand';
import {makeStyles} from '../theme/theme';

const VISIBLE_MS = 2200;

const useToastStore = create<{message: string | null; seq: number}>(() => ({
  message: null,
  seq: 0,
}));

/** Brief, non-blocking notice; a newer one replaces the current. */
export function showToast(message: string) {
  useToastStore.setState(s => ({message, seq: s.seq + 1}));
}

function clearToast() {
  useToastStore.setState({message: null});
}

export function ToastHost({bottom}: {bottom: number}) {
  const styles = useStyles();
  const {message, seq} = useToastStore();
  const opacity = useSharedValue(0);

  useEffect(() => {
    if (!message) {
      return;
    }
    opacity.value = 0;
    opacity.value = withSequence(
      withTiming(1, {duration: 160, easing: Easing.out(Easing.quad)}),
      withDelay(
        VISIBLE_MS,
        withTiming(0, {duration: 220}, done => {
          if (done) {
            scheduleOnRN(clearToast);
          }
        }),
      ),
    );
    return () => cancelAnimation(opacity);
  }, [message, seq, opacity]);

  // Explicit dependencies keep the web preview working, where no worklets Babel plugin runs.
  const animated = useAnimatedStyle(
    () => ({
      opacity: opacity.value,
      transform: [{translateY: interpolate(opacity.value, [0, 1], [6, 0])}],
    }),
    [opacity],
  );

  if (!message) {
    return null;
  }
  return (
    <Animated.View
      pointerEvents="none"
      accessibilityLiveRegion="polite"
      style={[styles.wrap, {bottom}, animated]}>
      <Text style={styles.text}>{message}</Text>
    </Animated.View>
  );
}

const useStyles = makeStyles(t => ({
  wrap: {
    position: 'absolute',
    alignSelf: 'center',
    maxWidth: '82%',
    paddingHorizontal: 14,
    paddingVertical: 9,
    borderRadius: 999,
    backgroundColor: t.isDark ? '#2A2A2F' : 'rgba(23,23,26,0.88)',
  },
  text: {fontSize: 13, lineHeight: 18, color: '#F4F4F5', textAlign: 'center'},
}));
