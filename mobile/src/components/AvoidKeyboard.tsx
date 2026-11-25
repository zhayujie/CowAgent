import React, {useEffect, useState} from 'react';
import {
  Keyboard,
  KeyboardAvoidingView,
  Platform,
  type KeyboardAvoidingViewProps,
  type StyleProp,
  type ViewStyle,
} from 'react-native';
import Animated, {useAnimatedKeyboard, useAnimatedStyle} from 'react-native-reanimated';

/**
 * iOS, and Android 15+ where pages are drawn edge to edge, keep the window's
 * size for the keyboard, so the view pads itself; older Android and HarmonyOS
 * resize the window instead.
 */
const PADS = Platform.OS === 'ios' || (Platform.OS === 'android' && Number(Platform.Version) >= 35);

/**
 * A KeyboardAvoidingView that pads only while the keyboard is up on Android:
 * its hide event reports the visible area's height as the keyboard's top,
 * which edge to edge leaves the system bars' height of padding behind.
 */
export function AvoidKeyboard({children, ...props}: Omit<KeyboardAvoidingViewProps, 'behavior'>) {
  const [shown, setShown] = useState(false);
  useEffect(() => {
    if (!PADS || Platform.OS === 'ios') {
      return;
    }
    const show = Keyboard.addListener('keyboardDidShow', () => setShown(true));
    const hide = Keyboard.addListener('keyboardDidHide', () => setShown(false));
    return () => {
      show.remove();
      hide.remove();
    };
  }, []);
  const pads = PADS && (Platform.OS === 'ios' || shown);
  return (
    <KeyboardAvoidingView {...props} behavior={pads ? 'padding' : undefined}>
      {children}
    </KeyboardAvoidingView>
  );
}

/**
 * iOS: pads by the keyboard's height frame by frame, less the bottom inset the
 * caller already leaves. KeyboardAvoidingView tweens its padding with
 * LayoutAnimation, which on the new architecture slides the rows of an
 * inverted list away and back while the keyboard opens.
 */
export function TrackKeyboard({
  children,
  inset = 0,
  style,
}: {
  children: React.ReactNode;
  inset?: number;
  style?: StyleProp<ViewStyle>;
}) {
  const keyboard = useAnimatedKeyboard();
  const pad = useAnimatedStyle(() => ({paddingBottom: Math.max(0, keyboard.height.value - inset)}));
  return <Animated.View style={[style, pad]}>{children}</Animated.View>;
}
