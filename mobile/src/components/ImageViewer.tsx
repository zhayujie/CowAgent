import {faArrowUpRightFromSquare, faDownload, faXmark} from '@fortawesome/free-solid-svg-icons';
import type {IconDefinition} from '@fortawesome/fontawesome-svg-core';
import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {Image, Modal, Pressable, StyleSheet, Text, View} from 'react-native';
import {Gesture, GestureDetector, GestureHandlerRootView} from 'react-native-gesture-handler';
import Animated, {
  interpolate,
  useAnimatedStyle,
  useSharedValue,
  withSpring,
  withTiming,
} from 'react-native-reanimated';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {scheduleOnRN} from 'react-native-worklets';
import {Icon} from './Icon';

const MAX_SCALE = 5;
const DOUBLE_TAP_SCALE = 2.5;
/** Pulled this far (or flung) while not zoomed, the picture closes. */
const DISMISS_DISTANCE = 120;
const DISMISS_VELOCITY = 900;
const SPRING = {damping: 22, stiffness: 220, mass: 0.6};

function clamp(v: number, lo: number, hi: number) {
  'worklet';
  return Math.min(Math.max(v, lo), hi);
}

/**
 * Full-screen look at one picture: pinch or double-tap to zoom, drag to look
 * around, pull down to close. A single tap also closes it.
 */
export function ImageViewer({
  uri,
  onClose,
  title,
  onDownload,
  onOpen,
}: {
  uri: string | null;
  onClose: () => void;
  title?: string;
  onDownload?: () => void;
  onOpen?: () => void;
}) {
  const insets = useSafeAreaInsets();
  const stageW = useSharedValue(0);
  const stageH = useSharedValue(0);
  // The picture's own aspect, so panning stops at its edges rather than the stage's.
  const aspect = useSharedValue(0);
  const scale = useSharedValue(1);
  const savedScale = useSharedValue(1);
  const tx = useSharedValue(0);
  const ty = useSharedValue(0);
  const savedTx = useSharedValue(0);
  const savedTy = useSharedValue(0);
  const pull = useSharedValue(0);
  // Set by a pinch, so a finger left on the glass carries on from where the pinch put the picture.
  const rebase = useSharedValue(false);
  // Decoded at full size so zooming stays sharp, unless Android has no memory left for that.
  const [fit, setFit] = useState(false);

  useEffect(() => {
    scale.value = 1;
    savedScale.value = 1;
    tx.value = 0;
    ty.value = 0;
    pull.value = 0;
    aspect.value = 0;
    setFit(false);
  }, [uri, scale, savedScale, tx, ty, pull, aspect]);

  // Built once: a detector handed new gestures on a re-render can stop answering touches.
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  const close = useCallback(() => closeRef.current(), []);

  const gesture = useMemo(() => {
    const bounds = (s: number) => {
      'worklet';
      const w = stageW.value;
      const h = stageH.value;
      let cw = w;
      let ch = h;
      if (aspect.value > 0 && w > 0 && h > 0) {
        if (w / h > aspect.value) {
          cw = h * aspect.value;
        } else {
          ch = w / aspect.value;
        }
      }
      return {x: Math.max(0, (cw * s - w) / 2), y: Math.max(0, (ch * s - h) / 2)};
    };

    const settle = () => {
      'worklet';
      const s = clamp(scale.value, 1, MAX_SCALE);
      const b = bounds(s);
      scale.value = withSpring(s, SPRING);
      tx.value = withSpring(clamp(tx.value, -b.x, b.x), SPRING);
      ty.value = withSpring(clamp(ty.value, -b.y, b.y), SPRING);
      savedScale.value = s;
    };

    const pinch = Gesture.Pinch()
      .onStart(() => {
        rebase.value = true;
        savedScale.value = scale.value;
        savedTx.value = tx.value;
        savedTy.value = ty.value;
      })
      .onUpdate(e => {
        const s = clamp(savedScale.value * e.scale, 0.7, MAX_SCALE * 1.2);
        const ratio = s / savedScale.value;
        // Keep the point under the fingers still while the picture grows around it.
        const fx = e.focalX - stageW.value / 2;
        const fy = e.focalY - stageH.value / 2;
        scale.value = s;
        tx.value = fx - (fx - savedTx.value) * ratio;
        ty.value = fy - (fy - savedTy.value) * ratio;
      })
      .onEnd(() => settle());

    const pan = Gesture.Pan()
      .maxPointers(1)
      .onStart(() => {
        rebase.value = false;
        savedTx.value = tx.value;
        savedTy.value = ty.value;
      })
      .onUpdate(e => {
        if (e.numberOfPointers > 1) {
          return;
        }
        if (rebase.value) {
          rebase.value = false;
          savedTx.value = tx.value - e.translationX;
          savedTy.value = ty.value - e.translationY;
        }
        // The scale being settled on, not the one on screen: a drag that starts
        // while a reset is still springing back should already pull to close.
        if (savedScale.value > 1.01) {
          const b = bounds(savedScale.value);
          // Past an edge the picture follows at a third of the finger's pace.
          const x = savedTx.value + e.translationX;
          const y = savedTy.value + e.translationY;
          tx.value = x > b.x ? b.x + (x - b.x) / 3 : x < -b.x ? -b.x + (x + b.x) / 3 : x;
          ty.value = y > b.y ? b.y + (y - b.y) / 3 : y < -b.y ? -b.y + (y + b.y) / 3 : y;
        } else {
          pull.value = e.translationY;
          tx.value = e.translationX * 0.4;
        }
      })
      .onEnd(e => {
        if (savedScale.value > 1.01) {
          const b = bounds(savedScale.value);
          tx.value = withSpring(clamp(tx.value, -b.x, b.x), SPRING);
          ty.value = withSpring(clamp(ty.value, -b.y, b.y), SPRING);
          return;
        }
        if (Math.abs(pull.value) > DISMISS_DISTANCE || Math.abs(e.velocityY) > DISMISS_VELOCITY) {
          const away = (pull.value >= 0 ? 1 : -1) * stageH.value;
          pull.value = withTiming(away, {duration: 180}, done => {
            if (done) {
              scheduleOnRN(close);
            }
          });
          return;
        }
        pull.value = withSpring(0, SPRING);
        tx.value = withSpring(0, SPRING);
      });

    const doubleTap = Gesture.Tap()
      .numberOfTaps(2)
      .maxDistance(24)
      .onEnd(e => {
        if (savedScale.value > 1.01) {
          scale.value = withSpring(1, SPRING);
          tx.value = withSpring(0, SPRING);
          ty.value = withSpring(0, SPRING);
          savedScale.value = 1;
          return;
        }
        const s = DOUBLE_TAP_SCALE;
        const b = bounds(s);
        const fx = e.x - stageW.value / 2;
        const fy = e.y - stageH.value / 2;
        scale.value = withSpring(s, SPRING);
        tx.value = withSpring(clamp(fx * (1 - s), -b.x, b.x), SPRING);
        ty.value = withSpring(clamp(fy * (1 - s), -b.y, b.y), SPRING);
        savedScale.value = s;
      });

    const singleTap = Gesture.Tap()
      .maxDistance(10)
      .onEnd(() => {
        scheduleOnRN(close);
      });

    return Gesture.Simultaneous(
      Gesture.Simultaneous(pinch, pan),
      Gesture.Exclusive(doubleTap, singleTap),
    );
  }, [close, stageW, stageH, aspect, scale, savedScale, tx, ty, savedTx, savedTy, pull, rebase]);

  // Explicit dependencies keep the web preview working, where no worklets Babel plugin runs.
  const imageStyle = useAnimatedStyle(
    () => ({
      transform: [
        {translateX: tx.value},
        {translateY: ty.value + pull.value},
        {scale: scale.value * interpolate(Math.abs(pull.value), [0, 400], [1, 0.82], 'clamp')},
      ],
    }),
    [tx, ty, pull, scale],
  );
  const fadeStyle = useAnimatedStyle(
    () => ({opacity: interpolate(Math.abs(pull.value), [0, 260], [1, 0], 'clamp')}),
    [pull],
  );

  return (
    <Modal visible={!!uri} transparent animationType="fade" onRequestClose={onClose} statusBarTranslucent>
      <GestureHandlerRootView style={styles.root}>
        <Animated.View style={[StyleSheet.absoluteFill, styles.backdrop, fadeStyle]} />
        <GestureDetector gesture={gesture}>
          <View
            style={StyleSheet.absoluteFill}
            accessibilityLabel="图片，双指或双击放大，下拉或单击关闭"
            onLayout={e => {
              stageW.value = e.nativeEvent.layout.width;
              stageH.value = e.nativeEvent.layout.height;
            }}>
            {!!uri && (
              <Animated.View style={[styles.fill, imageStyle]}>
                <Image
                  source={{uri}}
                  style={styles.fill}
                  resizeMode="contain"
                  resizeMethod={fit ? 'resize' : 'auto'}
                  onError={() => setFit(true)}
                  onLoad={e => {
                    const src = e.nativeEvent.source;
                    if (src?.width && src?.height) {
                      aspect.value = src.width / src.height;
                    }
                  }}
                />
              </Animated.View>
            )}
          </View>
        </GestureDetector>
        <Animated.View
          pointerEvents="box-none"
          style={[styles.top, {paddingTop: insets.top + 8}, fadeStyle]}>
          <Text style={styles.title} numberOfLines={1}>
            {title ?? ''}
          </Text>
          <Round icon={faXmark} label="关闭" onPress={onClose} />
        </Animated.View>
        {(onDownload || onOpen) && (
          <Animated.View
            pointerEvents="box-none"
            style={[styles.bottom, {paddingBottom: insets.bottom + 16}, fadeStyle]}>
            {onDownload && <Pill icon={faDownload} label="下载" onPress={onDownload} />}
            {onOpen && <Pill icon={faArrowUpRightFromSquare} label="浏览器打开" onPress={onOpen} />}
          </Animated.View>
        )}
      </GestureHandlerRootView>
    </Modal>
  );
}

function Round({icon, label, onPress}: {icon: IconDefinition; label: string; onPress: () => void}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={onPress}
      hitSlop={8}
      style={({pressed}) => [styles.round, pressed && styles.pressed]}>
      <Icon icon={icon} size={15} color="#fff" />
    </Pressable>
  );
}

function Pill({icon, label, onPress}: {icon: IconDefinition; label: string; onPress: () => void}) {
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      style={({pressed}) => [styles.pill, pressed && styles.pressed]}>
      <Icon icon={icon} size={12} color="#fff" />
      <Text style={styles.pillText}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  root: {flex: 1},
  backdrop: {backgroundColor: 'rgba(0,0,0,0.97)'},
  fill: {width: '100%', height: '100%'},
  top: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 16,
    paddingBottom: 8,
  },
  title: {flex: 1, fontSize: 14, fontWeight: '500', color: 'rgba(255,255,255,0.86)'},
  round: {
    width: 34,
    height: 34,
    borderRadius: 17,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(255,255,255,0.14)',
  },
  bottom: {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 0,
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 12,
    paddingTop: 8,
  },
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 7,
    paddingHorizontal: 16,
    height: 38,
    borderRadius: 19,
    backgroundColor: 'rgba(255,255,255,0.14)',
  },
  pillText: {fontSize: 13, fontWeight: '500', color: '#fff'},
  pressed: {opacity: 0.6},
});
