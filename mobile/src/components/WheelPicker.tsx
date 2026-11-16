import React, {useEffect, useRef, useState} from 'react';
import {
  Platform,
  Pressable,
  ScrollView,
  Text,
  View,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
} from 'react-native';
import {radius} from '../theme/palette';
import {makeStyles} from '../theme/theme';

export const WHEEL_ITEM_HEIGHT = 40;
const VISIBLE = 5;
const PAD = WHEEL_ITEM_HEIGHT * Math.floor(VISIBLE / 2);
// react-native-web has no snapToInterval and no momentum events, so snapping is done once scrolling goes quiet.
const SETTLE_MS = Platform.OS === 'web' ? 120 : 60;

const clamp = (i: number, n: number) => Math.max(0, Math.min(n - 1, i));

/** One scrolling column; the row under the center band is the value. */
export function WheelColumn({
  items,
  index,
  onChange,
  flex = 1,
  label,
}: {
  items: string[];
  index: number;
  onChange: (index: number) => void;
  flex?: number;
  label: string;
}) {
  const styles = useStyles();
  const ref = useRef<ScrollView>(null);
  const y = useRef(index * WHEEL_ITEM_HEIGHT);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const placed = useRef(false);
  const [live, setLive] = useState(index);

  useEffect(
    () => () => {
      if (timer.current) {
        clearTimeout(timer.current);
      }
    },
    [],
  );

  // A value pushed from outside (e.g. the day column clamping) moves the wheel too.
  useEffect(() => {
    if (!placed.current || index === Math.round(y.current / WHEEL_ITEM_HEIGHT)) {
      return;
    }
    ref.current?.scrollTo({y: index * WHEEL_ITEM_HEIGHT, animated: true});
    setLive(index);
  }, [index]);

  const settle = () => {
    const i = clamp(Math.round(y.current / WHEEL_ITEM_HEIGHT), items.length);
    if (Math.abs(y.current - i * WHEEL_ITEM_HEIGHT) > 0.5) {
      ref.current?.scrollTo({y: i * WHEEL_ITEM_HEIGHT, animated: true});
    }
    setLive(i);
    if (i !== index) {
      onChange(i);
    }
  };

  const onScroll = (e: NativeSyntheticEvent<NativeScrollEvent>) => {
    y.current = e.nativeEvent.contentOffset.y;
    setLive(clamp(Math.round(y.current / WHEEL_ITEM_HEIGHT), items.length));
    if (timer.current) {
      clearTimeout(timer.current);
    }
    timer.current = setTimeout(settle, SETTLE_MS);
  };

  return (
    <View style={[styles.column, {flex}]} accessibilityLabel={label} accessibilityValue={{text: items[live]}}>
      <ScrollView
        ref={ref}
        showsVerticalScrollIndicator={false}
        snapToInterval={WHEEL_ITEM_HEIGHT}
        decelerationRate="fast"
        scrollEventThrottle={16}
        onScroll={onScroll}
        onMomentumScrollEnd={settle}
        onLayout={() => {
          if (!placed.current) {
            placed.current = true;
            ref.current?.scrollTo({y: index * WHEEL_ITEM_HEIGHT, animated: false});
          }
        }}
        contentContainerStyle={styles.content}>
        {items.map((item, i) => {
          const distance = Math.abs(i - live);
          return (
            <Pressable
              key={`${i}-${item}`}
              accessibilityRole="button"
              accessibilityLabel={`${label} ${item}`}
              onPress={() => ref.current?.scrollTo({y: i * WHEEL_ITEM_HEIGHT, animated: true})}
              style={styles.item}>
              <Text
                numberOfLines={1}
                style={[
                  styles.text,
                  distance === 0 && styles.textActive,
                  distance === 1 && styles.textNear,
                  distance >= 2 && styles.textFar,
                ]}>
                {item}
              </Text>
            </Pressable>
          );
        })}
      </ScrollView>
    </View>
  );
}

/** Columns side by side over one shared selection band. */
export function WheelGroup({children}: {children: React.ReactNode}) {
  const styles = useStyles();
  return (
    <View style={styles.group}>
      <View pointerEvents="none" style={styles.band} />
      {children}
    </View>
  );
}

const useStyles = makeStyles(t => ({
  group: {
    flexDirection: 'row',
    height: WHEEL_ITEM_HEIGHT * VISIBLE,
    overflow: 'hidden',
  },
  band: {
    position: 'absolute',
    left: 0,
    right: 0,
    top: PAD,
    height: WHEEL_ITEM_HEIGHT,
    borderRadius: radius.sm,
    backgroundColor: t.bg2,
  },
  column: {height: WHEEL_ITEM_HEIGHT * VISIBLE},
  content: {paddingVertical: PAD},
  item: {height: WHEEL_ITEM_HEIGHT, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 4},
  text: {fontSize: 17, color: t.t1, fontVariant: ['tabular-nums']},
  textActive: {fontWeight: '600'},
  textNear: {fontSize: 15, color: t.t3},
  textFar: {fontSize: 14, color: t.t4},
}));
