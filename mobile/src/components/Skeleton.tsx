import React, {useEffect, useState} from 'react';
import {StyleSheet, View} from 'react-native';
import Animated, {
  cancelAnimation,
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withDelay,
  withRepeat,
  withSequence,
  withTiming,
} from 'react-native-reanimated';
import {scheduleOnRN} from 'react-native-worklets';
import {tr} from '../i18n';
import {makeStyles} from '../theme/theme';

const BREATHE = {duration: 900, easing: Easing.inOut(Easing.quad)};

/** Line widths of a page of prose; `0` is a paragraph break. */
const LINES = ['46%', 0, '94%', '88%', '97%', '62%', 0, '91%', '84%', '95%', '72%', 0, '89%', '56%'] as const;

/**
 * Where the text will land, shown while it loads. Inline, it waits a beat
 * before appearing so fast loads never flash it; as an overlay it covers the
 * page from the first frame. Either way it fades out instead of vanishing.
 */
export function PreviewSkeleton({visible, overlay}: {visible: boolean; overlay?: boolean}) {
  const styles = useStyles();
  const [mounted, setMounted] = useState(visible);
  const shown = useSharedValue(overlay && visible ? 1 : 0);
  const pulse = useSharedValue(1);

  useEffect(() => {
    if (visible) {
      setMounted(true);
      shown.value = withDelay(overlay ? 0 : 120, withTiming(1, {duration: 220}));
    } else {
      shown.value = withTiming(0, {duration: 200}, done => {
        if (done) {
          scheduleOnRN(setMounted, false);
        }
      });
    }
    return () => cancelAnimation(shown);
  }, [visible, overlay, shown]);

  useEffect(() => {
    if (!mounted) {
      return;
    }
    pulse.value = withRepeat(withSequence(withTiming(0.45, BREATHE), withTiming(1, BREATHE)), -1);
    return () => cancelAnimation(pulse);
  }, [mounted, pulse]);

  // Explicit dependencies keep the web preview working, where no worklets Babel plugin runs.
  const fade = useAnimatedStyle(() => ({opacity: shown.value}), [shown]);
  const breathe = useAnimatedStyle(() => ({opacity: pulse.value}), [pulse]);

  if (!mounted) {
    return null;
  }
  return (
    <Animated.View
      pointerEvents={visible ? 'auto' : 'none'}
      accessibilityLabel={tr('ui_loading')}
      style={[overlay ? styles.overlay : styles.inline, fade]}>
      <Animated.View style={[styles.lines, breathe]}>
        {LINES.map((w, i) => (w ? <View key={i} style={[styles.line, {width: w}]} /> : <View key={i} style={styles.gap} />))}
      </Animated.View>
    </Animated.View>
  );
}

const useStyles = makeStyles(t => ({
  inline: {flex: 1, backgroundColor: t.bg0},
  overlay: {...StyleSheet.absoluteFillObject, backgroundColor: t.bg0},
  lines: {paddingHorizontal: 18, paddingTop: 16, gap: 11},
  line: {height: 9, borderRadius: 4.5, backgroundColor: t.bg2},
  gap: {height: 8},
}));
