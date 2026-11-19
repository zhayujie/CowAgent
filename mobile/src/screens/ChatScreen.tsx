import {faComments} from '@fortawesome/free-regular-svg-icons';
import {faArrowDown, faChevronDown, faEllipsis, faPlus} from '@fortawesome/free-solid-svg-icons';
import {useFocusEffect} from '@react-navigation/native';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {
  ActivityIndicator,
  FlatList,
  Keyboard,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  Text,
  View,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
} from 'react-native';
import {Gesture, GestureDetector} from 'react-native-gesture-handler';
import Animated, {FadeIn, FadeOut} from 'react-native-reanimated';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {getModels, newSessionId, optimizePrompt, serverUrl, transcribeVoice} from '../api/cowApi';
import {AgentAvatar} from '../components/AgentAvatar';
import {AgentSheet} from '../components/AgentSheet';
import {
  AttachSheet,
  ModelSheet,
  PermissionSheet,
  type AttachSource,
} from '../components/ComposerSheets';
import {Dock} from '../components/Dock';
import {DrawerMenu, type DrawerMode, type DrawerRoute} from '../components/DrawerMenu';
import {Icon} from '../components/Icon';
import {Intro} from '../components/Intro';
import {MessageItem} from '../components/MessageItem';
import {ServerSheet} from '../components/ServerSheet';
import {SessionSheet} from '../components/SessionSheet';
import {SHEET_DISMISS_MS} from '../components/Sheet';
import {ConfirmSheet, FieldSheet} from '../components/settings';
import {SlideDrawer, type SlideDrawerHandle} from '../components/SlideDrawer';
import {TeamChatSheet} from '../components/TeamChatSheet';
import {showToast, ToastHost} from '../components/Toast';
import {Burger, IconButton} from '../components/ui';
import {VoiceOverlay} from '../components/VoiceInput';
import type {ChatFile} from '../files/chatFile';
import {openFile} from '../files/openFile';
import {tr, trf} from '../i18n';
import {canTakePhoto, pickDocuments, pickPhotos, takePhoto} from '../media/picker';
import type {Recording} from '../media/types';
import {linkAsPage} from '../navigation/menuViews';
import {openWebPage} from '../navigation/openWeb';
import type {RootStackParamList} from '../navigation/types';
import type {SessionItem} from '../protocol/events';
import type {PermissionMode} from '../protocol/resources';
import {agentParam, useAgentStore, useCurrentAgent} from '../store/agentStore';
import {MAX_REPLYING, useChatStore, type ChatMessage} from '../store/chatStore';
import {MAX_ATTACHMENTS, useComposerStore} from '../store/composerStore';
import {useMenuStore} from '../store/menuStore';
import {useOverviewStore} from '../store/overviewStore';
import {useSessionSettingsStore} from '../store/sessionSettingsStore';
import {useSessionStore} from '../store/sessionStore';
import {radius} from '../theme/palette';
import {makeStyles, usePrefsStore, useTheme} from '../theme/theme';
import {chatModelReady} from '../utils/capabilities';

type Props = StackScreenProps<RootStackParamList, 'Chat'>;

const EMPTY: ChatMessage[] = [];
const OPTIMIZE_CONTEXT = 6;
/** Further than this from the newest message counts as reading back. */
const AWAY_PX = 240;
/** Within this of the bottom, a new bubble is followed instead of held below the screen. */
const FOLLOW_PX = 80;
const KEEP_POSITION = {minIndexForVisible: 0, autoscrollToTopThreshold: FOLLOW_PX};

const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

export function ChatScreen({route, navigation}: Props) {
  const {sessionId, isNew} = route.params;
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const messages = useChatStore(s => s.messages[sessionId] ?? EMPTY);
  const loading = useChatStore(s => !!s.loading[sessionId]);
  const busy = useChatStore(s => !!s.active[sessionId]);
  const replying = useChatStore(s => Object.keys(s.active).sort().join('\n'));
  const recent = useSessionStore(s => s.sessions);
  const agent = useCurrentAgent();
  const defaultAgentId = useAgentStore(s => s.defaultId);
  const currentAgentId = useAgentStore(s => s.currentId);
  const agentCount = useAgentStore(s => s.agents.length);
  const onboarded = usePrefsStore(s => s.onboarded);
  const attachments = useComposerStore(s => s.items);
  const settings = useSessionSettingsStore(s => s.bySession[sessionId]);
  const teamSize = settings?.team?.members.length ?? 0;
  const [draft, setDraft] = useState('');
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerMode, setDrawerMode] = useState<DrawerMode>('chat');
  const [agentSheetOpen, setAgentSheetOpen] = useState(false);
  const [serverSheetOpen, setServerSheetOpen] = useState(false);
  const [teamSheetOpen, setTeamSheetOpen] = useState(false);
  const [attachOpen, setAttachOpen] = useState(false);
  const [modelOpen, setModelOpen] = useState(false);
  const [permissionOpen, setPermissionOpen] = useState(false);
  const [optimizing, setOptimizing] = useState(false);
  const [sessionOpen, setSessionOpen] = useState(false);
  const [renameOpen, setRenameOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  useEffect(() => {
    useAgentStore.getState().load().catch(() => undefined);
    useMenuStore.getState().load().catch(() => undefined);
    useSessionStore.getState().refresh();
    useOverviewStore.getState().load().catch(() => undefined);
  }, []);

  // Checked again on every return, so the card goes away once a model is set up.
  const [modelMissing, setModelMissing] = useState(false);
  useFocusEffect(
    useCallback(() => {
      let live = true;
      getModels().then(
        state => live && setModelMissing(!chatModelReady(state)),
        () => undefined,
      );
      return () => {
        live = false;
      };
    }, []),
  );

  // Anyone with history has already used the product; the guide is for strangers only.
  useEffect(() => {
    if (!onboarded && recent.length > 0) {
      usePrefsStore.getState().markOnboarded();
    }
  }, [onboarded, recent.length]);

  useEffect(() => {
    const chat = useChatStore.getState();
    chat.setCurrentSession(sessionId);
    if (!isNew) {
      chat.loadHistory(sessionId, useAgentStore.getState().currentId).catch(() => undefined);
    }
  }, [sessionId, isNew]);

  // Uploads are filed under the session they were picked in; never carry them over.
  useEffect(() => {
    useComposerStore.getState().clear();
  }, [sessionId]);

  const loadSettings = useCallback(
    () => useSessionSettingsStore.getState().load(sessionId, useAgentStore.getState().currentId),
    [sessionId],
  );

  useEffect(() => {
    if (currentAgentId) {
      loadSettings().catch(() => undefined);
    }
  }, [loadSettings, currentAgentId]);

  // A finished reply may have titled a new session or produced artifacts.
  const wasReplying = useRef(replying);
  useEffect(() => {
    const now = replying.split('\n');
    if (wasReplying.current && wasReplying.current.split('\n').some(id => !now.includes(id))) {
      useSessionStore.getState().refresh();
      useOverviewStore.getState().load().catch(() => undefined);
    }
    wasReplying.current = replying;
  }, [replying]);

  const refreshDrawer = useCallback(() => {
    useMenuStore.getState().load().catch(() => undefined);
    useSessionStore.getState().refresh();
    useOverviewStore.getState().load().catch(() => undefined);
  }, []);
  const openDrawer = useCallback(
    (mode?: DrawerMode) => {
      if (mode) {
        setDrawerMode(mode);
      }
      setDrawerOpen(true);
      refreshDrawer();
    },
    [refreshDrawer],
  );
  const closeDrawer = useCallback(() => setDrawerOpen(false), []);

  const startNewChat = useCallback(() => {
    setDrawerOpen(false);
    setDraft('');
    navigation.setParams({sessionId: newSessionId(), isNew: true});
  }, [navigation]);

  const openSession = useCallback(
    (session: SessionItem) => {
      setDrawerOpen(false);
      if (session.agent?.id) {
        useAgentStore.getState().select(session.agent.id);
      }
      navigation.setParams({sessionId: session.session_id, isNew: false});
    },
    [navigation],
  );

  const goTo = useCallback(
    (target: DrawerRoute) => {
      setDrawerOpen(false);
      navigation.navigate(target);
    },
    [navigation],
  );

  const openMenuFile = useCallback((file: ChatFile) => {
    setDrawerOpen(false);
    openFile(file);
  }, []);

  const openLink = useCallback(
    (label: string, url: string, external: boolean) => {
      setDrawerOpen(false);
      if (external) {
        openWebPage(serverUrl(url), label);
        return;
      }
      navigation.navigate('FilePreview', {file: linkAsPage(label, url)});
    },
    [navigation],
  );

  const startTeamChat = useCallback(
    async (owner: string, members: string[]) => {
      setTeamSheetOpen(false);
      const sid = newSessionId();
      try {
        await useSessionSettingsStore.getState().setMembers(sid, owner, members);
      } catch (e) {
        showToast(trf('chat_team_create_failed', {error: errorText(e)}));
        return;
      }
      if (owner !== useAgentStore.getState().currentId) {
        useAgentStore.getState().select(owner);
      }
      setDraft('');
      navigation.setParams({sessionId: sid, isNew: true});
    },
    [navigation],
  );

  const switchAgent = useCallback(
    (agentId: string) => {
      setAgentSheetOpen(false);
      if (agentId !== useAgentStore.getState().currentId) {
        useAgentStore.getState().select(agentId);
      }
      startNewChat();
    },
    [startNewChat],
  );

  const list = useRef<FlatList<ChatMessage>>(null);
  // The list is inverted, so its bottom is offset 0; wait a frame for the new bubble to be laid out.
  const toBottom = useCallback(() => {
    requestAnimationFrame(() => list.current?.scrollToOffset({offset: 0, animated: true}));
  }, []);

  // Scrolled up to read: the reply keeps growing below without moving the page, and a button leads back.
  const [away, setAway] = useState(false);
  const [unread, setUnread] = useState(false);
  const awayRef = useRef(false);
  const onListScroll = useCallback((e: NativeSyntheticEvent<NativeScrollEvent>) => {
    const next = e.nativeEvent.contentOffset.y > AWAY_PX;
    if (next !== awayRef.current) {
      awayRef.current = next;
      setAway(next);
      if (!next) {
        setUnread(false);
      }
    }
  }, []);
  useEffect(() => {
    awayRef.current = false;
    setAway(false);
    setUnread(false);
  }, [sessionId]);
  const tail = messages[messages.length - 1];
  const tailKey = tail ? `${tail.id}:${tail.content.length}:${tail.steps?.length ?? 0}:${tail.files?.length ?? 0}` : '';
  useEffect(() => {
    if (awayRef.current && tailKey) {
      setUnread(true);
    }
  }, [tailKey]);

  const send = useCallback(
    (text: string, voice?: {replaceId: string}) => {
      const chat = useChatStore.getState();
      // The store would drop this one silently.
      const own = !!chat.active[sessionId];
      if (own || Object.keys(chat.active).length >= MAX_REPLYING) {
        if (voice) {
          chat.removeMessage(sessionId, voice.replaceId);
        }
        showToast(own ? tr('chat_busy_wait') : trf('chat_too_many_replying', {n: MAX_REPLYING}));
        return false;
      }
      usePrefsStore.getState().markOnboarded();
      const files = useComposerStore.getState().take();
      chat
        .send(sessionId, text, useAgentStore.getState().currentId, {
          attachments: files,
          voice: !!voice,
          replaceId: voice?.replaceId,
        })
        .catch(() => undefined);
      toBottom();
      return true;
    },
    [sessionId, toBottom],
  );
  const sendText = useCallback((text: string) => send(text), [send]);

  const sendVoice = useCallback(
    async (rec: Recording) => {
      const chat = useChatStore.getState();
      const placeholder = chat.addTranscribing(sessionId);
      toBottom();
      try {
        const res = await transcribeVoice(rec, agentParam(useAgentStore.getState().currentId));
        const text = res.text?.trim();
        if (text) {
          send(text, {replaceId: placeholder});
          return;
        }
        chat.removeMessage(sessionId, placeholder);
        showToast(tr('voice_not_heard'));
      } catch (e) {
        chat.removeMessage(sessionId, placeholder);
        showToast(trf('voice_failed', {error: errorText(e)}));
      }
    },
    [sessionId, send, toBottom],
  );
  const transcribing = useMemo(() => messages.some(m => m.transcribing), [messages]);

  const pick = useCallback(
    (source: AttachSource) => {
      setAttachOpen(false);
      setTimeout(async () => {
        try {
          let files;
          if (source === 'photos') {
            files = await pickPhotos();
          } else if (source === 'camera') {
            files = await takePhoto();
          } else {
            files = await pickDocuments();
          }
          if (!files.length) {
            return;
          }
          const skipped = useComposerStore
            .getState()
            .add(files, sessionId, useAgentStore.getState().currentId);
          if (skipped) {
            showToast(trf('chat_attach_skipped', {max: MAX_ATTACHMENTS, n: skipped}));
          }
        } catch (e) {
          showToast(errorText(e));
        }
      }, SHEET_DISMISS_MS);
    },
    [sessionId],
  );

  const optimize = useCallback(async () => {
    const input = draft.trim();
    if (!input) {
      return;
    }
    setOptimizing(true);
    try {
      const context = messages
        .filter(m => m.content)
        .slice(-OPTIMIZE_CONTEXT)
        .map(m => ({role: m.role, content: m.content.slice(0, 200)}));
      const res = await optimizePrompt(input, context);
      const optimized = res.optimized?.trim();
      if (optimized) {
        setDraft(optimized);
        setAttachOpen(false);
      } else {
        showToast(tr('composer_optimize_noop'));
      }
    } catch (e) {
      showToast(trf('composer_optimize_failed', {error: errorText(e)}));
    } finally {
      setOptimizing(false);
    }
  }, [draft, messages]);

  const openSettingsSheet = useCallback(
    (open: (v: boolean) => void) => {
      open(true);
      if (!useSessionSettingsStore.getState().bySession[sessionId]) {
        loadSettings().catch(e => {
          open(false);
          showToast(trf('session_settings_load_failed', {error: errorText(e)}));
        });
      }
    },
    [sessionId, loadSettings],
  );

  const selectModel = useCallback(
    (choice: {provider: string; model: string} | null) => {
      setModelOpen(false);
      useSessionSettingsStore
        .getState()
        .setModel(sessionId, useAgentStore.getState().currentId, choice)
        .catch(e => showToast(trf('composer_model_switch_failed', {error: errorText(e)})));
    },
    [sessionId],
  );

  const selectPermission = useCallback(
    (mode: PermissionMode | null) => {
      setPermissionOpen(false);
      useSessionSettingsStore
        .getState()
        .setPermission(sessionId, useAgentStore.getState().currentId, mode)
        .catch(e => showToast(trf('composer_perm_switch_failed', {error: errorText(e)})));
    },
    [sessionId],
  );

  const sessionItem = useCallback((): SessionItem => {
    const found = useSessionStore.getState().sessions.find(s => s.session_id === sessionId);
    const current = useAgentStore.getState().currentId;
    return (
      found ?? {
        session_id: sessionId,
        title: '',
        created_at: 0,
        last_active: 0,
        msg_count: messages.length,
        agent: current ? {id: current, name: ''} : undefined,
      }
    );
  }, [sessionId, messages.length]);

  const fromSessionSheet = useCallback((open: () => void) => {
    setSessionOpen(false);
    setTimeout(open, SHEET_DISMISS_MS);
  }, []);

  const renameSession = useCallback(
    async (title: string) => {
      await useSessionStore.getState().rename(sessionItem(), title.trim());
      showToast(tr('session_renamed'));
    },
    [sessionItem],
  );

  const deleteSession = useCallback(async () => {
    try {
      await useSessionStore.getState().remove(sessionItem());
      setDeleteOpen(false);
      startNewChat();
    } catch (e) {
      setDeleteOpen(false);
      showToast(trf('common_delete_failed', {error: errorText(e)}));
    }
  }, [sessionItem, startNewChat]);

  // Swiping right anywhere pulls the features drawer out under the finger.
  // It runs as a native gesture so the message list cannot steal a sideways
  // drag; sideways scrollers such as code blocks still win their own drags.
  // Built once: a detector handed a new gesture can stop answering touches, so
  // the open state is read from a ref instead of toggling `enabled`.
  const drawerRef = useRef<SlideDrawerHandle>(null);
  const drawerOpenRef = useRef(drawerOpen);
  drawerOpenRef.current = drawerOpen;
  const drawerSwipe = useMemo(
    () =>
      Gesture.Pan()
        .runOnJS(true)
        .activeOffsetX(12)
        .failOffsetX(-12)
        .failOffsetY([-14, 14])
        .onTouchesDown((_, manager) => {
          if (drawerOpenRef.current) {
            manager.fail();
          }
        })
        .onStart(() => {
          Keyboard.dismiss();
          setDrawerMode('features');
          refreshDrawer();
        })
        .onUpdate(e => drawerRef.current?.drag(e.translationX))
        .onEnd((e, success) => {
          // Pan velocity is in px/s; the drawer's fling threshold is px/ms.
          const opened = success
            ? drawerRef.current?.release(e.translationX, e.velocityX / 1000)
            : drawerRef.current?.release(0, 0);
          if (opened) {
            setDrawerOpen(true);
          }
        }),
    [refreshDrawer],
  );

  // Inverted list keeps the newest message pinned to the bottom while streaming.
  const data = useMemo(() => [...messages].reverse(), [messages]);
  // A shared conversation names whoever said each reply.
  const shared = teamSize > 0;
  const renderItem = useCallback(
    ({item}: {item: ChatMessage}) => <MessageItem message={item} labelled={shared} />,
    [shared],
  );
  const empty = messages.length === 0;

  return (
    <GestureDetector gesture={drawerSwipe}>
      <View style={styles.root}>
        <View style={[styles.top, {paddingTop: insets.top + 6}]}>
          <View style={styles.topLeft}>
            <View style={styles.panes}>
              <IconButton label={tr('chat_features')} onPress={() => openDrawer('features')}>
                <Burger />
              </IconButton>
              <View style={styles.panesDivider} />
              <IconButton icon={faComments} label={tr('chat_session_list')} onPress={() => openDrawer('chat')} size={15} />
            </View>
          </View>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={trf('chat_agent_a11y', {
              name: agent?.name ?? 'CowAgent',
              team: teamSize ? trf('chat_agent_a11y_team', {n: teamSize}) : '',
            })}
            onPress={() => setAgentSheetOpen(true)}
            style={({pressed}) => [styles.agent, pressed && styles.agentPressed]}>
            <AgentAvatar
              agent={agent}
              isDefault={!agent || agent.id === defaultAgentId}
              size={24}
            />
            <Text style={styles.agentName} numberOfLines={1}>
              {agent?.name ?? 'CowAgent'}
            </Text>
            {teamSize > 0 && (
              <View style={styles.teamBadge}>
                <Text style={styles.teamBadgeText}>+{teamSize}</Text>
              </View>
            )}
            <Icon icon={faChevronDown} size={8} color={t.t3} />
          </Pressable>
          <View style={styles.topRight}>
            {(!empty || agentCount > 1) && (
              <IconButton icon={faEllipsis} label={tr('session_current')} onPress={() => setSessionOpen(true)} size={15} />
            )}
            {!empty && (
              <IconButton icon={faPlus} label={tr('session_new')} onPress={startNewChat} filled size={14} />
            )}
          </View>
        </View>

        <KeyboardAvoidingView
          style={styles.body}
          behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
          {empty ? (
            loading ? (
              <View style={styles.center}>
                <ActivityIndicator color={t.t3} />
              </View>
            ) : (
              <Intro
                firstRun={!onboarded}
                recent={recent}
                onPick={sendText}
                onOpenSession={openSession}
                onSetupModel={modelMissing ? () => navigation.navigate('Models') : undefined}
              />
            )
          ) : (
            <View style={styles.body}>
              <FlatList
                ref={list}
                inverted
                data={data}
                keyExtractor={m => m.id}
                renderItem={renderItem}
                contentContainerStyle={styles.list}
                keyboardShouldPersistTaps="handled"
                keyboardDismissMode="interactive"
                maintainVisibleContentPosition={KEEP_POSITION}
                onScroll={onListScroll}
                scrollEventThrottle={32}
              />
              {away && (
                <Animated.View entering={FadeIn.duration(160)} exiting={FadeOut.duration(120)} style={styles.toBottom}>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel={unread ? tr('chat_back_to_latest_unread') : tr('chat_back_to_latest')}
                    onPress={toBottom}
                    hitSlop={8}
                    style={({pressed}) => [styles.toBottomButton, pressed && styles.agentPressed]}>
                    <Icon icon={faArrowDown} size={13} color={t.t2} />
                    {unread && <View style={styles.unreadDot} />}
                  </Pressable>
                </Animated.View>
              )}
            </View>
          )}
          <Dock
            text={draft}
            onChangeText={setDraft}
            placeholder={empty ? tr('composer_placeholder_empty') : tr('composer_placeholder_followup')}
            busy={busy}
            onSend={sendText}
            onStop={() => {
              useChatStore.getState().cancel(sessionId).catch(() => undefined);
            }}
            onVoice={sendVoice}
            transcribing={transcribing}
            attachments={attachments}
            onRemoveAttachment={id => useComposerStore.getState().remove(id)}
            onRetryAttachment={id =>
              useComposerStore.getState().retry(id, sessionId, useAgentStore.getState().currentId)
            }
            onOpenAttach={() => setAttachOpen(true)}
            model={settings?.model.model}
            modelPinned={settings?.model.source === 'session'}
            onOpenModel={() => openSettingsSheet(setModelOpen)}
            permission={settings?.permission.mode}
            permissionPinned={settings?.permission.source === 'session'}
            onOpenPermission={() => openSettingsSheet(setPermissionOpen)}
          />
          <View style={{height: insets.bottom}} />
        </KeyboardAvoidingView>

        <VoiceOverlay />
        <ToastHost bottom={insets.bottom + 150} />

        <SlideDrawer ref={drawerRef} open={drawerOpen} onClose={closeDrawer}>
          <DrawerMenu
            mode={drawerMode}
            onModeChange={setDrawerMode}
            currentSessionId={sessionId}
            onNewChat={startNewChat}
            onNewTeamChat={() => {
              setDrawerOpen(false);
              setTeamSheetOpen(true);
            }}
            onOpenSession={openSession}
            onNavigate={goTo}
            onOpenFile={openMenuFile}
            onOpenLink={openLink}
            onSwitchAgent={() => {
              setDrawerOpen(false);
              setAgentSheetOpen(true);
            }}
            onSwitchServer={() => {
              setDrawerOpen(false);
              setServerSheetOpen(true);
            }}
          />
        </SlideDrawer>

        <ServerSheet visible={serverSheetOpen} onClose={() => setServerSheetOpen(false)} />

        <TeamChatSheet visible={teamSheetOpen} onClose={() => setTeamSheetOpen(false)} onStart={startTeamChat} />

        <AgentSheet
          visible={agentSheetOpen}
          onClose={() => setAgentSheetOpen(false)}
          onSelect={switchAgent}
          onManage={() => {
            setAgentSheetOpen(false);
            navigation.navigate('Agents');
          }}
        />
        <AttachSheet
          visible={attachOpen}
          onClose={() => setAttachOpen(false)}
          onPick={pick}
          canTakePhoto={canTakePhoto}
          remaining={MAX_ATTACHMENTS - attachments.length}
          canOptimize={draft.trim().length > 0}
          optimizing={optimizing}
          onOptimize={optimize}
        />
        <ModelSheet
          visible={modelOpen}
          onClose={() => setModelOpen(false)}
          settings={settings}
          onSelect={selectModel}
        />
        <PermissionSheet
          visible={permissionOpen}
          onClose={() => setPermissionOpen(false)}
          settings={settings}
          onSelect={selectPermission}
        />
        <SessionSheet
          visible={sessionOpen}
          onClose={() => setSessionOpen(false)}
          sessionId={sessionId}
          agentId={currentAgentId}
          isNew={!!isNew && empty}
          replying={busy}
          onRename={() => fromSessionSheet(() => setRenameOpen(true))}
          onDelete={() => fromSessionSheet(() => setDeleteOpen(true))}
        />
        <FieldSheet
          visible={renameOpen}
          title={tr('session_rename_title')}
          initial={sessionItem().title}
          placeholder={tr('session_title_placeholder')}
          onSubmit={renameSession}
          onClose={() => setRenameOpen(false)}
        />
        <ConfirmSheet
          visible={deleteOpen}
          title={tr('session_delete_title')}
          message={
            (settings?.team?.members.length ?? 0) > 0 ? tr('session_delete_team_msg') : tr('session_delete_msg')
          }
          confirmLabel={tr('common_delete')}
          danger
          onConfirm={deleteSession}
          onClose={() => setDeleteOpen(false)}
        />
      </View>
    </GestureDetector>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  top: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
    paddingHorizontal: 12,
    paddingBottom: 8,
  },
  // Equal-width sides keep the agent pill on the true centre line.
  topLeft: {flex: 1, flexBasis: 0, flexDirection: 'row', alignItems: 'center'},
  panes: {
    flexDirection: 'row',
    alignItems: 'center',
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: t.line1,
  },
  panesDivider: {width: 1, height: 16, backgroundColor: t.line1},
  topRight: {flex: 1, flexBasis: 0, flexDirection: 'row', alignItems: 'center', justifyContent: 'flex-end', gap: 4},
  agent: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    flexShrink: 1,
    maxWidth: '54%',
    paddingLeft: 4,
    paddingRight: 12,
    paddingVertical: 4,
    borderRadius: 999,
    backgroundColor: t.bg2,
  },
  agentPressed: {backgroundColor: t.bg3},
  teamBadge: {paddingHorizontal: 6, paddingVertical: 1, borderRadius: 999, backgroundColor: t.accentSoft},
  teamBadgeText: {fontSize: 11, fontWeight: '600', color: t.accent, fontVariant: ['tabular-nums']},
  agentName: {fontSize: 15, fontWeight: '500', letterSpacing: -0.2, color: t.t1, flexShrink: 1},
  body: {flex: 1},
  center: {flex: 1, alignItems: 'center', justifyContent: 'center'},
  // The list is inverted: flex-end is the visual top, so a short conversation starts there.
  list: {flexGrow: 1, justifyContent: 'flex-end', paddingTop: 20, paddingBottom: 8},
  toBottom: {position: 'absolute', alignSelf: 'center', bottom: 10},
  toBottomButton: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: t.isDark ? t.bg2 : t.bg0,
    borderWidth: 1,
    borderColor: t.line2,
    shadowColor: '#000',
    shadowOpacity: t.isDark ? 0 : 0.08,
    shadowRadius: 8,
    shadowOffset: {width: 0, height: 2},
    elevation: t.isDark ? 0 : 3,
  },
  unreadDot: {
    position: 'absolute',
    top: 3,
    right: 3,
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: t.green,
    borderWidth: 1.5,
    borderColor: t.isDark ? t.bg2 : t.bg0,
  },
}));
