import React, {useEffect, useState} from 'react';
import {Keyboard, KeyboardAvoidingView, Platform, type KeyboardAvoidingViewProps} from 'react-native';

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
