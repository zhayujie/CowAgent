import React, {useEffect, useImperativeHandle, useMemo, useRef, useState, type ReactNode, type Ref} from 'react';
import {BackHandler, PanResponder, Platform, Pressable, StyleSheet, useWindowDimensions} from 'react-native';
import Animated, {Easing, useAnimatedStyle, useSharedValue, withTiming} from 'react-native-reanimated';
import {scheduleOnRN} from 'react-native-worklets';
import {tr} from '../i18n';
import {makeStyles} from '../theme/theme';

const EASE = Easing.bezier(0.22, 0.61, 0.36, 1);
const MAX_WIDTH = 304;
// Web preview renders inside a phone-sized frame (see web/index.html).
const FRAME_WIDTH = Platform.OS === 'web' ? 430 : Number.POSITIVE_INFINITY;

export interface SlideDrawerHandle {
  /** Pulls the closed drawer out by `dx`, so it follows the finger. */
  drag: (dx: number) => void;
  /** Ends a pull; true means it went far or fast enough to open, otherwise it slides back. */
  release: (dx: number, vx: number) => boolean;
}

/** Left drawer over a scrim; drag it left or tap the scrim to dismiss. */
export function SlideDrawer({
  open,
  onClose,
  children,
  ref,
}: {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  ref?: Ref<SlideDrawerHandle>;
}) {
  const styles = useStyles();
  const {width: windowWidth} = useWindowDimensions();
  const width = Math.min(MAX_WIDTH, Math.round(Math.min(windowWidth, FRAME_WIDTH) * 0.8));
  const progress = useSharedValue(0);
  const [mounted, setMounted] = useState(open);
  const mountedRef = useRef(open);

  const show = (value: boolean) => {
    if (mountedRef.current !== value) {
      mountedRef.current = value;
      setMounted(value);
    }
  };

  const animateTo = (value: 0 | 1, done?: () => void) => {
    progress.value = withTiming(value, {duration: value ? 280 : 200, easing: EASE}, finished => {
      if (finished && done) {
        scheduleOnRN(done);
      }
    });
  };

  useImperativeHandle(ref, () => ({
    drag: dx => {
      show(true);
      progress.value = Math.max(0, Math.min(1, dx / width));
    },
    release: (dx, vx) => {
      const opens = dx > 0 && (dx > width * 0.35 || vx > 0.5);
      if (!opens) {
        animateTo(0, () => show(false));
      }
      return opens;
    },
  }));

  useEffect(() => {
    if (open) {
      show(true);
      animateTo(1);
    } else {
      animateTo(0, () => show(false));
    }
    // animateTo only closes over stable refs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const sub = BackHandler.addEventListener('hardwareBackPress', () => {
      onClose();
      return true;
    });
    return () => sub.remove();
  }, [open, onClose]);

  const pan = useMemo(
    () =>
      PanResponder.create({
        onMoveShouldSetPanResponder: (_, g) => g.dx < -8 && Math.abs(g.dx) > Math.abs(g.dy) * 1.5,
        onPanResponderMove: (_, g) => {
          progress.value = Math.max(0, Math.min(1, 1 + g.dx / width));
        },
        onPanResponderRelease: (_, g) => {
          if (g.dx < -width * 0.3 || g.vx < -0.5) {
            onClose();
          } else {
            progress.value = withTiming(1, {duration: 200, easing: EASE});
          }
        },
      }),
    [progress, width, onClose],
  );

  // Explicit dependencies keep the web preview working, where no worklets Babel plugin runs.
  const scrim = useAnimatedStyle(() => ({opacity: progress.value}), [progress]);
  const slide = useAnimatedStyle(() => ({transform: [{translateX: (progress.value - 1) * width}]}), [progress, width]);

  if (!mounted) {
    return null;
  }

  return (
    <>
      <Animated.View {...pan.panHandlers} style={[StyleSheet.absoluteFill, styles.scrim, scrim]}>
        <Pressable style={styles.fill} onPress={onClose} accessibilityLabel={tr('ui_close_menu')} />
      </Animated.View>
      <Animated.View {...pan.panHandlers} style={[styles.panel, {width}, slide]}>
        {children}
      </Animated.View>
    </>
  );
}

const useStyles = makeStyles(t => ({
  fill: {flex: 1},
  scrim: {backgroundColor: t.scrim, zIndex: 5},
  panel: {
    position: 'absolute',
    top: 0,
    bottom: 0,
    left: 0,
    zIndex: 6,
    backgroundColor: t.isDark ? t.bg1 : t.bg0,
    borderRightWidth: 1,
    borderRightColor: t.line2,
  },
}));
