import {
  DarkTheme,
  DefaultTheme,
  NavigationContainer,
  type NavigationState,
  type Theme,
} from '@react-navigation/native';
import React, {useEffect, useMemo, useRef} from 'react';
import {StatusBar, StyleSheet} from 'react-native';
import {GestureHandlerRootView} from 'react-native-gesture-handler';
import {SafeAreaProvider} from 'react-native-safe-area-context';
import {ImageViewerHost} from './components/FileViews';
import {PairLinkHost} from './components/PairFlow';
import {useLangStore} from './i18n';
import {navigationRef} from './navigation/ref';
import {RootNavigator} from './navigation/RootNavigator';
import {useServerStore} from './store/serverStore';
import {usePrefsStore, useTheme} from './theme/theme';

export default function App() {
  const t = useTheme();
  const lang = useLangStore(s => s.lang);
  const hydrated = useServerStore(s => s.hydrated);
  // Text is resolved during render, so switching language remounts the tree;
  // the navigation state is carried over so the user stays where they were.
  const navState = useRef<NavigationState | undefined>(undefined);

  useEffect(() => {
    usePrefsStore.getState().hydrate();
    useLangStore.getState().hydrate();
    useServerStore.getState().hydrate();
  }, []);

  const navTheme = useMemo<Theme>(() => {
    const base = t.isDark ? DarkTheme : DefaultTheme;
    return {
      ...base,
      colors: {
        ...base.colors,
        primary: t.green,
        background: t.bg0,
        card: t.bg0,
        text: t.t1,
        border: t.line1,
      },
    };
  }, [t]);

  return (
    <GestureHandlerRootView style={[styles.root, {backgroundColor: t.bg0}]}>
      <SafeAreaProvider>
        <StatusBar
          barStyle={t.isDark ? 'light-content' : 'dark-content'}
          backgroundColor={t.bg0}
        />
        <React.Fragment key={lang}>
          <NavigationContainer
            ref={navigationRef}
            theme={navTheme}
            initialState={navState.current}
            onStateChange={state => {
              navState.current = state;
            }}>
            <RootNavigator />
          </NavigationContainer>
          <ImageViewerHost />
          {hydrated && <PairLinkHost />}
        </React.Fragment>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}

const styles = StyleSheet.create({
  root: {flex: 1},
});
