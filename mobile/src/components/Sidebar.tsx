import {CommonActions, StackActions} from '@react-navigation/native';
import React, {useEffect, useState} from 'react';
import {View} from 'react-native';
import {navigationRef} from '../navigation/ref';
import type {SessionItem} from '../protocol/events';
import {useLayoutStore, type ChatCommands} from '../store/layoutStore';
import {useMenuStore} from '../store/menuStore';
import {useOverviewStore} from '../store/overviewStore';
import {useSessionStore} from '../store/sessionStore';
import {SIDEBAR_WIDTH} from '../theme/layout';
import {makeStyles} from '../theme/theme';
import {DrawerMenu, type DrawerRoute} from './DrawerMenu';

/** The page beside the sidebar: the chat, or the menu page opened over it. */
function currentSection(): string {
  const routes = navigationRef.isReady() ? navigationRef.getRootState()?.routes : undefined;
  return routes && routes.length > 1 ? routes[1].name : 'Chat';
}

/** Menu pages replace one another over the chat, as the web console's sidebar switches views. */
function openSection(name: DrawerRoute) {
  const state = navigationRef.getRootState();
  if (!state?.routes.length) {
    return;
  }
  if (state.routes.length === 1) {
    navigationRef.navigate(name);
  } else if (state.routes.length > 2 || state.routes[1].name !== name) {
    navigationRef.dispatch(CommonActions.reset({...state, index: 1, routes: [state.routes[0], {name}]}));
  }
}

function backToChat() {
  if ((navigationRef.getRootState()?.routes.length ?? 0) > 1) {
    navigationRef.dispatch(StackActions.popToTop());
  }
}

/** The drawer's menu, kept open beside the page on wide screens. */
export function Sidebar() {
  const styles = useStyles();
  const view = useLayoutStore(s => s.sidebarView);
  const nested = useLayoutStore(s => s.sidebarNested);
  const sessionId = useLayoutStore(s => s.sessionId);
  const [section, setSection] = useState(currentSection);

  useEffect(() => navigationRef.addListener('state', () => setSection(currentSection())), []);
  useEffect(() => {
    useMenuStore.getState().load().catch(() => undefined);
    useSessionStore.getState().refresh();
    useOverviewStore.getState().load().catch(() => undefined);
  }, []);

  const chat = () => useLayoutStore.getState().chat;
  const inChat = (run: (commands: ChatCommands) => void) => {
    const commands = chat();
    if (commands) {
      backToChat();
      run(commands);
    }
  };

  return (
    <View style={styles.root}>
      <DrawerMenu
        view={view}
        nested={nested}
        onViewChange={next => {
          if (next === 'sessions') {
            backToChat();
          }
          useLayoutStore.getState().setSidebarView(next, next === 'sessions');
        }}
        currentSessionId={sessionId}
        activeSection={section}
        onNewChat={() => inChat(c => c.newChat())}
        onOpenSession={(session: SessionItem) => inChat(c => c.openSession(session))}
        onSessionActions={session => chat()?.sessionActions(session)}
        onNavigate={openSection}
        onOpenFile={file => chat()?.openFile(file)}
        onOpenLink={(label, url, external) => chat()?.openLink(label, url, external)}
        onSwitchServer={() => chat()?.switchServer()}
      />
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {
    width: SIDEBAR_WIDTH,
    borderRightWidth: 1,
    borderRightColor: t.line1,
    backgroundColor: t.isDark ? t.bg1 : t.bg0,
  },
}));
