import React, {useEffect, useRef, useState, type ReactNode} from 'react';
import {Keyboard, Modal, Platform, Pressable, StyleSheet, Text, View} from 'react-native';
import Animated, {Easing, useAnimatedStyle, useSharedValue, withTiming, type SharedValue} from 'react-native-reanimated';
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

const IOS = Platform.OS === 'ios';

/**
 * How long to wait after closing a sheet before presenting anything native (share, camera) or
 * navigating. Sheets themselves wait their turn (see usePresence).
 */
export const SHEET_DISMISS_MS = IOS ? 360 : 0;

/** Past this a native callback counts as lost, so one that never comes holds no sheet back. */
const NATIVE_WAIT_MS = 1500;

// Sheets whose modal is still on screen while they close, and sheets waiting for those to go.
const leaving = new Set<object>();
const waiting = new Set<() => void>();

function setLeaving(owner: object, on: boolean) {
  if (on) {
    leaving.add(owner);
    return;
  }
  leaving.delete(owner);
  if (!leaving.size) {
    const ready = [...waiting];
    waiting.clear();
    ready.forEach(fn => fn());
  }
}

type Phase = 'gone' | 'queued' | 'in' | 'out' | 'dismissing';

/**
 * When the sheet's modal is mounted and shown. iOS refuses to present a modal while another is
 * still up, and ignores a dismissal while its modal is still being presented: the app then shows
 * something other than what it believes, at worst an invisible modal that takes every touch. So
 * on iOS a sheet waits for closing ones to be gone before it shows, and to be shown before it goes.
 */
function usePresence(visible: boolean, progress: SharedValue<number>) {
  const [phase, setPhaseState] = useState<Phase>('gone');
  const visibleRef = useRef(visible);
  visibleRef.current = visible;
  const [m] = useState(() => {
    const self = {
      phase: 'gone' as Phase,
      shown: false,
      onShown: null as (() => void) | null,
      timer: null as ReturnType<typeof setTimeout> | null,
      set(next: Phase) {
        self.phase = next;
        setPhaseState(next);
      },
      wait(fn: () => void) {
        self.clearTimer();
        self.timer = setTimeout(fn, NATIVE_WAIT_MS);
      },
      clearTimer() {
        if (self.timer) {
          clearTimeout(self.timer);
          self.timer = null;
        }
      },
      open() {
        if (IOS && leaving.size) {
          self.set('queued');
          waiting.add(self.retry);
          return;
        }
        self.shown = false;
        self.set('in');
        progress.value = withTiming(1, {duration: 280, easing: EASE});
      },
      retry() {
        if (self.phase === 'queued') {
          self.set('gone');
          if (visibleRef.current) {
            self.open();
          }
        }
      },
      close() {
        self.set('out');
        if (IOS) {
          setLeaving(self, true);
        }
        const slidOut = self.slidOut;
        progress.value = withTiming(0, {duration: 200, easing: EASE}, done => {
          if (done) {
            scheduleOnRN(slidOut);
          }
        });
      },
      slidOut() {
        if (self.phase !== 'out') {
          return;
        }
        if (!IOS) {
          self.set('gone');
          return;
        }
        const dismiss = () => {
          self.onShown = null;
          if (self.phase === 'out') {
            self.set('dismissing');
            self.wait(self.dismissed);
          }
        };
        if (self.shown) {
          dismiss();
        } else {
          self.onShown = dismiss;
          self.wait(dismiss);
        }
      },
      shownNow() {
        self.shown = true;
        const next = self.onShown;
        if (next) {
          self.clearTimer();
          next();
        }
      },
      dismissed() {
        if (self.phase !== 'dismissing') {
          return;
        }
        self.clearTimer();
        self.set('gone');
        setLeaving(self, false);
        if (visibleRef.current) {
          self.open();
        }
      },
      dispose() {
        self.clearTimer();
        waiting.delete(self.retry);
        setLeaving(self, false);
      },
    };
    return self;
  });

  useEffect(() => {
    if (visible) {
      if (m.phase === 'out') {
        // Still on screen: slide back instead of leaving.
        setLeaving(m, false);
        m.set('in');
        progress.value = withTiming(1, {duration: 280, easing: EASE});
      } else if (m.phase === 'gone') {
        m.open();
      }
    } else if (m.phase === 'queued') {
      waiting.delete(m.retry);
      m.set('gone');
    } else if (m.phase === 'in') {
      m.close();
    }
  }, [visible, m, progress]);

  useEffect(() => () => m.dispose(), [m]);

  return {phase, onShow: m.shownNow, onDismiss: m.dismissed};
}

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
  const {phase, onShow, onDismiss} = usePresence(visible, progress);
  const mounted = phase !== 'gone' && phase !== 'queued';
  const [panelHeight, setPanelHeight] = useState(420);
  const keyboardHeight = useHarmonyKeyboardHeight(mounted);
  const floating = useDialogLayout();

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
    <Modal
      transparent
      visible={phase !== 'dismissing'}
      animationType="none"
      onRequestClose={onClose}
      onShow={onShow}
      onDismiss={onDismiss}
      statusBarTranslucent>
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
