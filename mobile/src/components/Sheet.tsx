import React, {useEffect, useState, type ReactNode} from 'react';
import {Keyboard, Modal, Platform, Pressable, StyleSheet, Text, View} from 'react-native';
import Animated, {Easing, useAnimatedStyle, useSharedValue, withTiming} from 'react-native-reanimated';
import {scheduleOnRN} from 'react-native-worklets';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {faChevronRight} from '@fortawesome/free-solid-svg-icons';
import {tr} from '../i18n';
import {useDialogLayout} from '../theme/layout';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {Icon} from './Icon';
import {AvoidKeyboard} from './AvoidKeyboard';

const EASE = Easing.bezier(0.22, 0.61, 0.36, 1);
const DIALOG_WIDTH = 520;

/** iOS cannot present another modal while the sheet's modal is still dismissing. */
export const SHEET_DISMISS_MS = Platform.OS === 'ios' ? 360 : 0;

/**
 * HarmonyOS draws a Modal in its own dialog layer, which the page's keyboard
 * RESIZE mode (harmony/entry/src/main/ets/pages/Index.ets) does not reach, so
 * the keyboard would cover the sheet. There the sheet makes room itself.
 */
function useHarmonyKeyboardHeight(active: boolean): number {
  const [height, setHeight] = useState(0);
  useEffect(() => {
    if (!active || (Platform.OS as string) !== 'harmony') {
      return;
    }
    const show = Keyboard.addListener('keyboardDidShow', e => setHeight(e.endCoordinates.height));
    const hide = Keyboard.addListener('keyboardDidHide', () => setHeight(0));
    return () => {
      show.remove();
      hide.remove();
      setHeight(0);
    };
  }, [active]);
  return height;
}

/**
 * Bottom sheet: slides up over a scrim, closes on scrim tap or back. On a wide screen it floats
 * in the middle as a dialog, as the web console's do.
 */
export function Sheet({
  visible,
  onClose,
  title,
  action,
  children,
}: {
  visible: boolean;
  onClose: () => void;
  title?: string;
  /** A link on the title row, for going somewhere fuller than the sheet. */
  action?: {label: string; onPress: () => void};
  children: ReactNode;
}) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const progress = useSharedValue(0);
  const [mounted, setMounted] = useState(visible);
  const [panelHeight, setPanelHeight] = useState(420);
  const keyboardHeight = useHarmonyKeyboardHeight(mounted);
  const floating = useDialogLayout();

  useEffect(() => {
    if (visible) {
      setMounted(true);
    }
    progress.value = withTiming(visible ? 1 : 0, {duration: visible ? 280 : 200, easing: EASE}, done => {
      if (done && !visible) {
        scheduleOnRN(setMounted, false);
      }
    });
  }, [visible, progress]);

  // Explicit dependencies keep the web preview working, where no worklets Babel plugin runs.
  const scrim = useAnimatedStyle(() => ({opacity: progress.value}), [progress]);
  const slide = useAnimatedStyle(
    () =>
      floating
        ? {opacity: progress.value, transform: [{translateY: (1 - progress.value) * 24}]}
        : {transform: [{translateY: (1 - progress.value) * panelHeight}]},
    [progress, panelHeight, floating],
  );

  if (!mounted) {
    return null;
  }

  return (
    <Modal transparent visible animationType="none" onRequestClose={onClose} statusBarTranslucent>
      <AvoidKeyboard style={[styles.root, floating && styles.rootFloating, {paddingBottom: keyboardHeight}]}>
        <Animated.View style={[StyleSheet.absoluteFill, styles.scrim, scrim]}>
          <Pressable style={styles.fill} onPress={onClose} accessibilityLabel={tr('common_close')} />
        </Animated.View>
        <Animated.View
          onLayout={e => setPanelHeight(e.nativeEvent.layout.height + 40)}
          style={[styles.panel, floating ? styles.panelFloating : {paddingBottom: insets.bottom + 12}, slide]}>
          {!floating && <View style={styles.grabber} />}
          {action ? (
            <View style={styles.head}>
              <Text style={[styles.title, styles.headTitle]} numberOfLines={1}>
                {title}
              </Text>
              <Pressable
                accessibilityRole="button"
                hitSlop={8}
                onPress={action.onPress}
                style={({pressed}) => [styles.headAction, pressed && styles.pressed]}>
                <Text style={styles.headActionText}>{action.label}</Text>
                <Icon icon={faChevronRight} size={10} color={t.accent} />
              </Pressable>
            </View>
          ) : (
            !!title && <Text style={styles.title}>{title}</Text>
          )}
          {children}
        </Animated.View>
      </AvoidKeyboard>
    </Modal>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, justifyContent: 'flex-end'},
  rootFloating: {justifyContent: 'center', alignItems: 'center', padding: 24},
  fill: {flex: 1},
  scrim: {backgroundColor: t.scrim},
  panel: {
    maxHeight: '86%',
    paddingHorizontal: 8,
    paddingTop: 8,
    borderTopLeftRadius: radius.lg + 4,
    borderTopRightRadius: radius.lg + 4,
    backgroundColor: t.isDark ? t.bg1 : t.bg0,
    borderWidth: t.isDark ? 1 : 0,
    borderBottomWidth: 0,
    borderColor: t.line2,
  },
  panelFloating: {
    width: '100%',
    maxWidth: DIALOG_WIDTH,
    maxHeight: '80%',
    paddingTop: 14,
    paddingBottom: 12,
    borderRadius: radius.lg + 4,
    borderBottomWidth: t.isDark ? 1 : 0,
  },
  grabber: {
    alignSelf: 'center',
    width: 36,
    height: 4,
    borderRadius: 2,
    marginBottom: 10,
    backgroundColor: t.line2,
  },
  title: {
    fontSize: 17,
    fontWeight: '600',
    letterSpacing: -0.3,
    color: t.t1,
    paddingHorizontal: 12,
    paddingTop: 2,
    paddingBottom: 10,
  },
  head: {flexDirection: 'row', alignItems: 'center', paddingRight: 12},
  headTitle: {flex: 1},
  headAction: {flexDirection: 'row', alignItems: 'center', gap: 4, paddingBottom: 8},
  headActionText: {fontSize: 14, fontWeight: '500', color: t.accent},
  pressed: {opacity: 0.6},
}));
