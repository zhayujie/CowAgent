import type {IconDefinition} from '@fortawesome/fontawesome-svg-core';
import {faCopy} from '@fortawesome/free-regular-svg-icons';
import {faICursor} from '@fortawesome/free-solid-svg-icons';
import React, {useEffect, useMemo, useRef, useState} from 'react';
import {
  BackHandler,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  useWindowDimensions,
  View,
} from 'react-native';
import {Gesture} from 'react-native-gesture-handler';
import Animated, {Easing, useAnimatedStyle, useSharedValue, withTiming} from 'react-native-reanimated';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {create} from 'zustand';
import {tr} from '../i18n';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {copyText} from '../utils/clipboard';
import {Icon} from './Icon';
import {Sheet} from './Sheet';
import {showToast} from './Toast';

export const copyMessage = (text: string) =>
  copyText(text).then(ok => ok && showToast(tr('common_copied')));

export type MenuAction = {icon: IconDefinition; label: string; onPress: () => void};

/** What a long press on a message offers: its raw text to copy, plain text to select, and its own actions. */
export type MessageMenuItems = {text: string; plain: string; actions: MenuAction[]};

type Anchor = {x: number; y: number; items: MessageMenuItems};

const useMenu = create<{anchor: Anchor | null; selecting: string | null}>(() => ({anchor: null, selecting: null}));
const closeMenu = () => useMenu.setState({anchor: null});

/** Opens a message's menu at a screen point, for parts that already take taps through a Pressable. */
export const openMessageMenu = (x: number, y: number, items: MessageMenuItems) =>
  useMenu.setState({anchor: {x, y, items}});

/**
 * A long press that opens a message's menu where the finger is.
 * A native gesture rather than a Pressable: on Android a pressed Pressable takes every later touch,
 * so code blocks and tables inside could no longer scroll sideways.
 */
export function useMessageMenu(getItems: () => MessageMenuItems) {
  const read = useRef(getItems);
  read.current = getItems;
  return useMemo(
    () =>
      Gesture.LongPress()
        .minDuration(350)
        .runOnJS(true)
        .onStart(e => openMessageMenu(e.absoluteX, e.absoluteY, read.current())),
    [],
  );
}

const MENU_WIDTH = 180;
const ROW_HEIGHT = 44;
const EDGE = 12;
const GAP = 10;

/**
 * Drawn over the app rather than in a modal: choosing "select text" opens a sheet at once, and
 * iOS will not present that while another modal is still leaving.
 */
export function MessageMenuHost() {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const win = useWindowDimensions();
  const anchor = useMenu(s => s.anchor);
  const selecting = useMenu(s => s.selecting);
  // Kept after closing so the sheet still has its text while it slides away.
  const [text, setText] = useState('');
  const shown = useSharedValue(0);

  useEffect(() => {
    if (anchor) {
      shown.value = 0;
      shown.value = withTiming(1, {duration: 140, easing: Easing.out(Easing.cubic)});
    }
  }, [anchor, shown]);

  useEffect(() => {
    if (!anchor) {
      return;
    }
    const sub = BackHandler.addEventListener('hardwareBackPress', () => {
      closeMenu();
      return true;
    });
    return () => sub.remove();
  }, [anchor]);

  useEffect(() => {
    if (selecting !== null) {
      setText(selecting);
    }
  }, [selecting]);

  const pop = useAnimatedStyle(
    () => ({opacity: shown.value, transform: [{scale: 0.94 + shown.value * 0.06}]}),
    [shown],
  );

  let card = null;
  if (anchor) {
    const {items} = anchor;
    const rows: MenuAction[] = [
      {icon: faCopy, label: tr('common_copy'), onPress: () => copyMessage(items.text)},
      ...items.actions,
      {icon: faICursor, label: tr('chat_select_text'), onPress: () => useMenu.setState({selecting: items.plain})},
    ];
    const height = rows.length * ROW_HEIGHT + 12;
    const left = Math.min(Math.max(anchor.x - MENU_WIDTH / 2, EDGE), win.width - MENU_WIDTH - EDGE);
    const below = anchor.y + GAP;
    const fitsBelow = below + height <= win.height - insets.bottom - EDGE;
    const top = fitsBelow ? below : Math.max(anchor.y - GAP - height, insets.top + EDGE);
    card = (
      <Animated.View
        style={[styles.card, fitsBelow ? styles.fromTop : styles.fromBottom, {left, top}, pop]}>
        {rows.map(row => (
          <Pressable
            key={row.label}
            accessibilityRole="button"
            onPress={() => {
              closeMenu();
              row.onPress();
            }}
            style={({pressed}) => [styles.row, pressed && styles.rowPressed]}>
            <View style={styles.rowIcon}>
              <Icon icon={row.icon} size={14} color={t.t2} />
            </View>
            <Text style={styles.rowText} numberOfLines={1}>
              {row.label}
            </Text>
          </Pressable>
        ))}
      </Animated.View>
    );
  }

  return (
    <>
      {anchor && (
        <View style={StyleSheet.absoluteFill}>
          <Pressable style={StyleSheet.absoluteFill} onPress={closeMenu} accessibilityLabel={tr('common_close')} />
          {card}
        </View>
      )}
      <Sheet
        visible={selecting !== null}
        onClose={() => useMenu.setState({selecting: null})}
        title={tr('chat_select_text')}>
        <SelectableText text={text} />
      </Sheet>
    </>
  );
}

/** A message's text on its own, where any part of it can be selected and copied. */
function SelectableText({text}: {text: string}) {
  const t = useTheme();
  const styles = useStyles();
  return Platform.OS === 'ios' ? (
    // On iOS only a text view selects part of a text; a Text copies it whole. A text view
    // sized to its text does not scroll inside a sheet capped in height, so the page scrolls it.
    <ScrollView style={styles.scroll}>
      <TextInput
        value={text}
        editable={false}
        multiline
        scrollEnabled={false}
        selectionColor={t.accent}
        style={[styles.text, styles.input]}
      />
    </ScrollView>
  ) : (
    <ScrollView style={styles.scroll}>
      <Text selectable style={[styles.text, styles.plain]}>
        {text}
      </Text>
    </ScrollView>
  );
}

const useStyles = makeStyles(t => ({
  card: {
    position: 'absolute',
    width: MENU_WIDTH,
    paddingVertical: 6,
    borderRadius: radius.lg,
    backgroundColor: t.isDark ? t.bg2 : t.card,
    borderWidth: 1,
    borderColor: t.line2,
    shadowColor: '#000',
    shadowOpacity: t.isDark ? 0 : 0.12,
    shadowRadius: 18,
    shadowOffset: {width: 0, height: 6},
    elevation: t.isDark ? 0 : 6,
  },
  fromTop: {transformOrigin: 'top'},
  fromBottom: {transformOrigin: 'bottom'},
  row: {
    height: ROW_HEIGHT,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    marginHorizontal: 6,
    paddingHorizontal: 10,
    borderRadius: radius.sm,
  },
  rowPressed: {backgroundColor: t.isDark ? t.bg3 : t.bg2},
  rowIcon: {width: 18, alignItems: 'center'},
  rowText: {flex: 1, fontSize: 15, color: t.t1},
  text: {fontSize: 15, lineHeight: 24, color: t.t1},
  input: {flexShrink: 1, paddingHorizontal: 12, paddingTop: 0, paddingBottom: 8},
  scroll: {flexGrow: 0, flexShrink: 1},
  plain: {paddingHorizontal: 12, paddingBottom: 8},
}));
