import {createStackNavigator} from '@react-navigation/stack';
import React, {useMemo} from 'react';
import {ActivityIndicator, Platform, StyleSheet, View} from 'react-native';
import {newSessionId} from '../api/cowApi';
import {useLangStore} from '../i18n';
import {AccessScreen} from '../screens/AccessScreen';
import {AgentCreateScreen} from '../screens/AgentCreateScreen';
import {AgentDetailScreen} from '../screens/AgentDetailScreen';
import {AgentFileScreen} from '../screens/AgentFileScreen';
import {AgentSkillsScreen} from '../screens/AgentSkillsScreen';
import {AgentsScreen} from '../screens/AgentsScreen';
import {ArtifactsScreen} from '../screens/ArtifactsScreen';
import {CapabilityScreen} from '../screens/CapabilityScreen';
import {ChannelScreen} from '../screens/ChannelScreen';
import {ChannelsScreen} from '../screens/ChannelsScreen';
import {ChatScreen} from '../screens/ChatScreen';
import {DevicesScreen} from '../screens/DevicesScreen';
import {ExternalApiScreen} from '../screens/ExternalApiScreen';
import {FilePreviewScreen} from '../screens/FilePreviewScreen';
import {GuestShareEditScreen} from '../screens/GuestShareEditScreen';
import {GuestSharesScreen} from '../screens/GuestSharesScreen';
import {KnowledgeDocScreen} from '../screens/KnowledgeDocScreen';
import {KnowledgeScreen} from '../screens/KnowledgeScreen';
import {LoginScreen} from '../screens/LoginScreen';
import {LogsScreen} from '../screens/LogsScreen';
import {McpDetailScreen} from '../screens/McpDetailScreen';
import {McpEditScreen} from '../screens/McpEditScreen';
import {MemoryDocScreen} from '../screens/MemoryDocScreen';
import {MemoryScreen} from '../screens/MemoryScreen';
import {MenuEditorScreen} from '../screens/MenuEditorScreen';
import {ModelsScreen} from '../screens/ModelsScreen';
import {PermissionsScreen} from '../screens/PermissionsScreen';
import {RuntimeScreen} from '../screens/RuntimeScreen';
import {SessionsScreen} from '../screens/SessionsScreen';
import {SettingsScreen} from '../screens/SettingsScreen';
import {SkillCreateScreen} from '../screens/SkillCreateScreen';
import {SkillDetailScreen} from '../screens/SkillDetailScreen';
import {SkillFileScreen} from '../screens/SkillFileScreen';
import {SkillsScreen} from '../screens/SkillsScreen';
import {TaskEditScreen} from '../screens/TaskEditScreen';
import {TaskRunScreen} from '../screens/TaskRunScreen';
import {TaskRunsScreen} from '../screens/TaskRunsScreen';
import {TasksScreen} from '../screens/TasksScreen';
import {VersionScreen} from '../screens/VersionScreen';
import {WebPageScreen} from '../screens/WebPageScreen';
import {WebSearchScreen} from '../screens/WebSearchScreen';
import {useServerStore} from '../store/serverStore';
import {usePrefsStore, useTheme} from '../theme/theme';
import {EDGE_ONLY, useFullBackSwipe} from './gestures';
import {forSlide} from './transitions';
import type {RootStackParamList} from './types';

const Stack = createStackNavigator<RootStackParamList>();

export function RootNavigator() {
  const t = useTheme();
  const fullBackSwipe = useFullBackSwipe();
  const hydrated = useServerStore(s => s.hydrated);
  const prefsHydrated = usePrefsStore(s => s.hydrated);
  const langHydrated = useLangStore(s => s.hydrated);
  const authed = useServerStore(s => s.authed);
  const activeId = useServerStore(s => s.activeId);
  // A fresh chat for every sign-in or server switch; the last one's session lives on the server left.
  const initialSessionId = useMemo(newSessionId, [authed, activeId]);

  if (!hydrated || !prefsHydrated || !langHydrated) {
    return (
      <View style={[styles.splash, {backgroundColor: t.bg0}]}>
        <ActivityIndicator color={t.t3} />
      </View>
    );
  }

  return (
    <Stack.Navigator
      // Switching servers rebuilds the stack, so no page keeps showing the previous server's data.
      key={authed ? `server:${activeId}` : 'login'}
      // On Android's new architecture a push can detach the page underneath while the new one is still
      // sliding over it, so the old page vanishes halfway. Pages below stay attached instead; on the web
      // the screens package drops each page's layout when detaching is off, so it keeps the default there.
      detachInactiveScreens={Platform.OS === 'web'}
      screenOptions={{
        headerShown: false,
        // A browser page the stack fills would otherwise scroll as a whole,
        // carrying every fixed bar off screen with it.
        headerMode: Platform.OS === 'web' ? 'float' : undefined,
        cardStyle: {backgroundColor: t.bg0},
        animation: 'slide_from_right',
        cardStyleInterpolator: forSlide,
        cardOverlayEnabled: false,
        // Swipe right anywhere on a page to go back, with the previous page following the finger.
        gestureEnabled: true,
        gestureDirection: 'horizontal',
        gestureResponseDistance: fullBackSwipe,
      }}>
      {authed ? (
        <>
          <Stack.Screen
            name="Chat"
            component={ChatScreen}
            initialParams={{sessionId: initialSessionId, isNew: true}}
          />
          <Stack.Screen name="Sessions" component={SessionsScreen} />
          <Stack.Screen name="Artifacts" component={ArtifactsScreen} />
          <Stack.Screen name="Skills" component={SkillsScreen} />
          <Stack.Screen name="SkillDetail" component={SkillDetailScreen} />
          <Stack.Screen name="SkillFile" component={SkillFileScreen} />
          <Stack.Screen name="SkillCreate" component={SkillCreateScreen} />
          <Stack.Screen name="Memory" component={MemoryScreen} />
          <Stack.Screen name="MemoryDoc" component={MemoryDocScreen} />
          <Stack.Screen name="Knowledge" component={KnowledgeScreen} options={{gestureResponseDistance: EDGE_ONLY}} />
          <Stack.Screen name="KnowledgeDoc" component={KnowledgeDocScreen} />
          <Stack.Screen name="FilePreview" component={FilePreviewScreen} options={{gestureResponseDistance: EDGE_ONLY}} />
          <Stack.Screen name="WebPage" component={WebPageScreen} options={{gestureResponseDistance: EDGE_ONLY}} />
          <Stack.Screen name="Tasks" component={TasksScreen} />
          <Stack.Screen name="TaskEdit" component={TaskEditScreen} />
          <Stack.Screen name="TaskRuns" component={TaskRunsScreen} />
          <Stack.Screen name="TaskRun" component={TaskRunScreen} />
          <Stack.Screen name="Channels" component={ChannelsScreen} />
          <Stack.Screen name="Channel" component={ChannelScreen} />
          <Stack.Screen name="Settings" component={SettingsScreen} />
          <Stack.Screen name="Agents" component={AgentsScreen} />
          <Stack.Screen name="AgentCreate" component={AgentCreateScreen} />
          <Stack.Screen name="AgentDetail" component={AgentDetailScreen} />
          <Stack.Screen name="AgentSkills" component={AgentSkillsScreen} />
          <Stack.Screen name="AgentFile" component={AgentFileScreen} />
          <Stack.Screen name="Models" component={ModelsScreen} />
          <Stack.Screen name="Capability" component={CapabilityScreen} />
          <Stack.Screen name="WebSearch" component={WebSearchScreen} />
          <Stack.Screen name="Runtime" component={RuntimeScreen} />
          <Stack.Screen name="Permissions" component={PermissionsScreen} />
          <Stack.Screen name="ExternalApi" component={ExternalApiScreen} />
          <Stack.Screen name="Access" component={AccessScreen} />
          <Stack.Screen name="Devices" component={DevicesScreen} />
          <Stack.Screen name="GuestShares" component={GuestSharesScreen} />
          <Stack.Screen name="GuestShareEdit" component={GuestShareEditScreen} />
          <Stack.Screen name="McpDetail" component={McpDetailScreen} />
          <Stack.Screen name="McpEdit" component={McpEditScreen} />
          <Stack.Screen name="Logs" component={LogsScreen} />
          <Stack.Screen name="MenuEditor" component={MenuEditorScreen} />
          <Stack.Screen name="Version" component={VersionScreen} />
        </>
      ) : (
        <Stack.Screen name="Login" component={LoginScreen} />
      )}
    </Stack.Navigator>
  );
}

const styles = StyleSheet.create({
  splash: {flex: 1, alignItems: 'center', justifyContent: 'center'},
});
