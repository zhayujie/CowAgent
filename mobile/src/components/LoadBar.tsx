import React, {useEffect} from 'react';
import {StyleSheet, View} from 'react-native';
import Animated, {
  cancelAnimation,
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withDelay,
  withTiming,
} from 'react-native-reanimated';
import {useTheme} from '../theme/theme';

const EASE = Easing.bezier(0.22, 0.61, 0.36, 1);

/**
 * A hairline of progress along the bottom edge of a bar. Without a real
 * `progress` it creeps towards 85% and waits; either way it only moves forward,
 * then runs out and fades once `active` drops.
 */
export function LoadBar({active, progress}: {active: boolean; progress?: number}) {
  const t = useTheme();
  const width = useSharedValue(0);
  const p = useSharedValue(0);
  const opacity = useSharedValue(0);

  useEffect(() => {
    if (active) {
      p.value = 0.06;
      opacity.value = 1;
      p.value = withTiming(0.85, {duration: 7000, easing: EASE});
    } else {
      p.value = withTiming(1, {duration: 200, easing: EASE});
      opacity.value = withDelay(260, withTiming(0, {duration: 260}));
    }
    return () => {
      cancelAnimation(p);
      cancelAnimation(opacity);
    };
  }, [active, p, opacity]);

  useEffect(() => {
    if (!active || progress === undefined) {
      return;
    }
    p.value = withTiming(Math.max(p.value, Math.min(progress, 0.94)), {duration: 240, easing: EASE});
  }, [active, progress, p]);

  // Explicit dependencies keep the web preview working, where no worklets Babel plugin runs.
  const fill = useAnimatedStyle(
    () => ({opacity: opacity.value, transform: [{translateX: (p.value - 1) * width.value}]}),
    [p, opacity, width],
  );

  return (
    <View
      pointerEvents="none"
      style={styles.track}
      onLayout={e => {
        width.value = e.nativeEvent.layout.width;
      }}
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants">
      <Animated.View style={[styles.fill, {backgroundColor: t.accent}, fill]} />
    </View>
  );
}

const styles = StyleSheet.create({
  track: {position: 'absolute', left: 0, right: 0, bottom: 0, height: 2, overflow: 'hidden'},
  fill: {...StyleSheet.absoluteFillObject, borderTopRightRadius: 1, borderBottomRightRadius: 1},
});
