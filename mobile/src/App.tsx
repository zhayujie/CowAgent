import {DarkTheme, DefaultTheme, NavigationContainer, type Theme} from '@react-navigation/native';
import React, {useEffect, useMemo} from 'react';
import {StatusBar, StyleSheet} from 'react-native';
import {GestureHandlerRootView} from 'react-native-gesture-handler';
import {SafeAreaProvider} from 'react-native-safe-area-context';
import {ImageViewerHost} from './components/FileViews';
import {navigationRef} from './navigation/ref';
import {RootNavigator} from './navigation/RootNavigator';
import {useServerStore} from './store/serverStore';
import {usePrefsStore, useTheme} from './theme/theme';

export default function App() {
  const t = useTheme();

  useEffect(() => {
    usePrefsStore.getState().hydrate();
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
        <NavigationContainer ref={navigationRef} theme={navTheme}>
          <RootNavigator />
        </NavigationContainer>
        <ImageViewerHost />
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}

const styles = StyleSheet.create({
  root: {flex: 1},
});
