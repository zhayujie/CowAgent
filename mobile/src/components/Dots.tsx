import React, {useEffect} from 'react';
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
import {useTheme} from '../theme/theme';

const EASE = Easing.bezier(0.22, 0.61, 0.36, 1);

/** Three pulsing dots for work in progress. */
export function Dots({size = 4}: {size?: number}) {
  return (
    <View style={styles.row}>
      {[0, 1, 2].map(i => (
        <Dot key={i} index={i} size={size} />
      ))}
    </View>
  );
}

function Dot({index, size}: {index: number; size: number}) {
  const t = useTheme();
  const v = useSharedValue(0.2);

  useEffect(() => {
    v.value = withRepeat(
      withSequence(
        withDelay(index * 180, withTiming(1, {duration: 600, easing: EASE})),
        withTiming(0.2, {duration: 750}),
        withDelay((2 - index) * 180, withTiming(0.2, {duration: 0})),
      ),
      -1,
    );
    return () => cancelAnimation(v);
  }, [index, v]);

  // Explicit dependencies keep the web preview working, where no worklets Babel plugin runs.
  const style = useAnimatedStyle(() => ({opacity: v.value}), [v]);
  return (
    <Animated.View style={[{width: size, height: size, borderRadius: size / 2, backgroundColor: t.accent}, style]} />
  );
}

const styles = StyleSheet.create({
  row: {flexDirection: 'row', alignItems: 'center', gap: 3},
});
