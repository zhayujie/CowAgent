import {
  DarkTheme,
  DefaultTheme,
  NavigationContainer,
  type NavigationState,
  type Theme,
} from '@react-navigation/native';
import React, {useEffect, useMemo, useRef, useState} from 'react';
import {StatusBar, StyleSheet} from 'react-native';
import {GestureHandlerRootView} from 'react-native-gesture-handler';
import {SafeAreaProvider} from 'react-native-safe-area-context';
import {AppUpdateHost} from './components/AppUpdateHost';
import {ImageViewerHost} from './components/FileViews';
import {PairLinkHost} from './components/PairFlow';
import {PhoneHost} from './components/PhoneHost';
import {useLangStore} from './i18n';
import {navigationRef} from './navigation/ref';
import {watchNotices} from './notify/notice';
import {watchReplies} from './notify/replies';
import {watchNotificationTaps} from './notify/taps';
import {RootNavigator} from './navigation/RootNavigator';
import {useScheduledDeliveries} from './scheduler/deliveries';
import {listenForShares} from './share/incoming';
import {useTaskReminders} from './scheduler/reminders';
import {useServerStore} from './store/serverStore';
import {paintNavigationBar, routeBackground} from './theme/systemBars';
import {usePrefsStore, useTheme} from './theme/theme';

export default function App() {
  const t = useTheme();
  const lang = useLangStore(s => s.lang);
  const hydrated = useServerStore(s => s.hydrated);
  // Text is resolved during render, so switching language remounts the tree;
  // the navigation state is carried over so the user stays where they were.
  const navState = useRef<NavigationState | undefined>(undefined);
  const [route, setRoute] = useState<string | undefined>();
  const barColor = routeBackground(route, t);
  const trackRoute = () => setRoute(navigationRef.getCurrentRoute()?.name);

  useEffect(() => {
    usePrefsStore.getState().hydrate();
    useLangStore.getState().hydrate();
    useServerStore.getState().hydrate();
    listenForShares();
    watchReplies();
    watchNotices();
    watchNotificationTaps();
  }, []);

  useEffect(() => paintNavigationBar(barColor, t.isDark), [barColor, t.isDark]);

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
          backgroundColor={barColor}
        />
        <React.Fragment key={lang}>
          <NavigationContainer
            ref={navigationRef}
            theme={navTheme}
            initialState={navState.current}
            onReady={trackRoute}
            onStateChange={state => {
              navState.current = state;
              trackRoute();
            }}>
            <RootNavigator />
          </NavigationContainer>
          <ImageViewerHost />
          {hydrated && <PairLinkHost />}
          {hydrated && <PhoneHost />}
          {hydrated && <SchedulerWatch />}
          {hydrated && <AppUpdateHost />}
        </React.Fragment>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}

/** Scheduled deliveries shown as they land, and reminders handed to the system for when the app is away. */
function SchedulerWatch() {
  useScheduledDeliveries();
  useTaskReminders();
  return null;
}

const styles = StyleSheet.create({
  root: {flex: 1},
});
