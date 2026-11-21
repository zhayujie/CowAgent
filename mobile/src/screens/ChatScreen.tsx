import {faComments} from '@fortawesome/free-regular-svg-icons';
import {faArrowDown, faChevronDown, faPlus} from '@fortawesome/free-solid-svg-icons';
import {useFocusEffect} from '@react-navigation/native';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {
  ActivityIndicator,
  BackHandler,
  FlatList,
  Keyboard,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  Text,
  TextInput,
  View,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
} from 'react-native';
import {Gesture, GestureDetector} from 'react-native-gesture-handler';
import Animated, {FadeIn, FadeOut, useSharedValue} from 'react-native-reanimated';
import {scheduleOnRN} from 'react-native-worklets';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {getModels, newSessionId, optimizePrompt, searchWorkspace, serverUrl, transcribeVoice} from '../api/cowApi';
import {AgentAvatar} from '../components/AgentAvatar';
import {AgentSheet} from '../components/AgentSheet';
import {
  AttachSheet,
  ModelSheet,
  modelDisplayName,
  PermissionSheet,
  type AttachSource,
} from '../components/ComposerSheets';
import {Dock} from '../components/Dock';
import {DrawerMenu, type DrawerRoute, type DrawerView} from '../components/DrawerMenu';
import {Icon} from '../components/Icon';
import {Intro} from '../components/Intro';
import {ListGrowContext, ListShiftContext} from '../components/listAnchor';
import {MessageItem} from '../components/MessageItem';
import {ServerSheet} from '../components/ServerSheet';
import {SessionActions} from '../components/SessionActions';
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
import type {AgentBadge, PermissionMode, WorkspaceHit} from '../protocol/resources';
import {agentParam, useAgentStore, useCurrentAgent} from '../store/agentStore';
import {MAX_REPLYING, useChatStore, type ChatMessage} from '../store/chatStore';
import {MAX_ATTACHMENTS, useComposerStore} from '../store/composerStore';
import {useMenuStore} from '../store/menuStore';
import {useOverviewStore} from '../store/overviewStore';
import {useSessionSettingsStore} from '../store/sessionSettingsStore';
import {useSessionStore} from '../store/sessionStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {chatModelReady} from '../utils/capabilities';

type Props = StackScreenProps<RootStackParamList, 'Chat'>;

const EMPTY: ChatMessage[] = [];
const OPTIMIZE_CONTEXT = 6;
/** Further than this from the newest message counts as reading back. */
const AWAY_PX = 240;
const HISTORY_MAX = 20;
/** Within this of the bottom, a new bubble is followed instead of held below the screen. */
const FOLLOW_PX = 80;
const KEEP_POSITION = {minIndexForVisible: 0, autoscrollToTopThreshold: FOLLOW_PX};
/** The list's padding before the newest message (paddingTop, as the list is inverted). */
const LIST_PAD = 20;

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
  const pinned = useSessionStore(s => !!s.sessions.find(x => x.session_id === sessionId)?.pinned);
  const agent = useCurrentAgent();
  const defaultAgentId = useAgentStore(s => s.defaultId);
  const currentAgentId = useAgentStore(s => s.currentId);
  const attachments = useComposerStore(s => s.items);
  const settings = useSessionSettingsStore(s => s.bySession[sessionId]);
  const team = settings?.team;
  const teamSize = team?.members.length ?? 0;
  const [draft, setDraft] = useState('');
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerView, setDrawerView] = useState<DrawerView>('menu');
  const [drawerNested, setDrawerNested] = useState(false);
  const [agentSheetOpen, setAgentSheetOpen] = useState(false);
  const [serverSheetOpen, setServerSheetOpen] = useState(false);
  const [teamSheetOpen, setTeamSheetOpen] = useState(false);
  const [attachOpen, setAttachOpen] = useState(false);
  const [modelOpen, setModelOpen] = useState(false);
  const [permissionOpen, setPermissionOpen] = useState(false);
  const [optimizing, setOptimizing] = useState(false);
  const [sessionOpen, setSessionOpen] = useState(false);
  const [contextOnly, setContextOnly] = useState(false);
  const [renameOpen, setRenameOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [actingSession, setActingSession] = useState<SessionItem | null>(null);
  const dock = useRef<TextInput>(null);
  // The keyboard covers the home indicator, so the composer sits right on it.
  const [keyboardShown, setKeyboardShown] = useState(false);
  useEffect(() => {
    const ios = Platform.OS === 'ios';
    const show = Keyboard.addListener(ios ? 'keyboardWillShow' : 'keyboardDidShow', () => setKeyboardShown(true));
    const hide = Keyboard.addListener(ios ? 'keyboardWillHide' : 'keyboardDidHide', () => setKeyboardShown(false));
    return () => {
      show.remove();
      hide.remove();
    };
  }, []);

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
    (view: DrawerView) => {
      setDrawerView(view);
      setDrawerNested(false);
      setDrawerOpen(true);
      refreshDrawer();
    },
    [refreshDrawer],
  );
  const closeDrawer = useCallback(() => setDrawerOpen(false), []);

  // Conversations visited in this screen, so back returns to the previous one before leaving the app.
  const visited = useRef<{sessionId: string; agentId: string | null}[]>([]);
  const goingBack = useRef(false);
  const shownRef = useRef({sessionId, isNew: !!isNew, agentId: currentAgentId});
  const emptyRef = useRef(true);
  useEffect(() => {
    const prev = shownRef.current;
    if (prev.sessionId !== sessionId) {
      // A blank new chat left behind holds nothing to come back to.
      const blank = prev.isNew && emptyRef.current;
      const top = visited.current[visited.current.length - 1];
      if (!goingBack.current && !blank && top?.sessionId !== prev.sessionId) {
        visited.current = [...visited.current, {sessionId: prev.sessionId, agentId: prev.agentId}].slice(-HISTORY_MAX);
      }
      goingBack.current = false;
    }
    shownRef.current = {sessionId, isNew: !!isNew, agentId: useAgentStore.getState().currentId};
  }, [sessionId, isNew]);

  // An existing conversation always speaks as the Agent it belongs to, however it was reached.
  const sessionAgentId = useSessionStore(s =>
    isNew ? undefined : s.sessions.find(x => x.session_id === sessionId)?.agent?.id,
  );
  const sessionAgentKnown = useAgentStore(s => !!sessionAgentId && s.agents.some(a => a.id === sessionAgentId));
  useEffect(() => {
    if (sessionAgentId && sessionAgentKnown) {
      useAgentStore.getState().select(sessionAgentId);
      shownRef.current = {...shownRef.current, agentId: sessionAgentId};
    }
  }, [sessionAgentId, sessionAgentKnown]);

  useFocusEffect(
    useCallback(() => {
      const sub = BackHandler.addEventListener('hardwareBackPress', () => {
        const prev = visited.current[visited.current.length - 1];
        if (!prev) {
          return false;
        }
        visited.current = visited.current.slice(0, -1);
        goingBack.current = true;
        const owner =
          useSessionStore.getState().sessions.find(s => s.session_id === prev.sessionId)?.agent?.id ?? prev.agentId;
        if (owner) {
          useAgentStore.getState().select(owner);
        }
        setDraft('');
        navigation.setParams({sessionId: prev.sessionId, isNew: false});
        return true;
      });
      return () => sub.remove();
    }, [navigation]),
  );

  const forgetSession = useCallback((id: string) => {
    visited.current = visited.current.filter(v => v.sessionId !== id);
  }, []);

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
  const offsetRef = useRef(0);
  const shiftList = useCallback((dy: number) => {
    const next = Math.max(0, offsetRef.current + dy);
    offsetRef.current = next;
    list.current?.scrollToOffset({offset: next, animated: false});
  }, []);
  // A reply growing at the bottom pushes up whatever is read above it. The list keeps that still
  // only while the reply sits off screen, so while it is in view the page follows it by hand.
  const holdForReader = useCallback(
    (dy: number, before: number) => {
      const offset = offsetRef.current;
      if (offset > FOLLOW_PX && offset < before + LIST_PAD) {
        shiftList(dy);
      }
    },
    [shiftList],
  );
  // The list is inverted, so its bottom is offset 0; wait a frame for the new bubble to be laid out.
  const toBottom = useCallback(() => {
    requestAnimationFrame(() => list.current?.scrollToOffset({offset: 0, animated: true}));
  }, []);

  // Scrolled up to read: the reply keeps growing below without moving the page, and a button leads back.
  const [away, setAway] = useState(false);
  const [unread, setUnread] = useState(false);
  const awayRef = useRef(false);
  const onListScroll = useCallback((e: NativeSyntheticEvent<NativeScrollEvent>) => {
    offsetRef.current = e.nativeEvent.contentOffset.y;
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
    offsetRef.current = 0;
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

  const pickExample = useCallback((text: string) => {
    setDraft(text);
    dock.current?.focus();
  }, []);

  // Who `@` can address: only a shared conversation has anyone besides its owner.
  const roster = useMemo<AgentBadge[]>(
    () => (team && team.members.length ? [team.owner, ...team.members.filter(m => m.available !== false)] : []),
    [team],
  );
  const searchFiles = useCallback(
    async (q: string) =>
      (await searchWorkspace(q, sessionId, agentParam(useAgentStore.getState().currentId))).results ?? [],
    [sessionId],
  );
  const pickFile = useCallback((hit: WorkspaceHit) => {
    useComposerStore.getState().addRef(hit.path, hit.name);
  }, []);

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

  const togglePin = useCallback(() => {
    setSessionOpen(false);
    const item = sessionItem();
    useSessionStore
      .getState()
      .setPinned(item, !item.pinned)
      .then(() => showToast(item.pinned ? tr('session_unpinned') : tr('session_pinned')))
      .catch(e => showToast(trf('common_save_failed_detail', {error: errorText(e)})));
  }, [sessionItem]);

  const deleteSession = useCallback(async () => {
    try {
      await useSessionStore.getState().remove(sessionItem());
      forgetSession(sessionId);
      setDeleteOpen(false);
      startNewChat();
    } catch (e) {
      setDeleteOpen(false);
      showToast(trf('common_delete_failed', {error: errorText(e)}));
    }
  }, [sessionItem, startNewChat, forgetSession, sessionId]);

  // Swiping right anywhere pulls the features drawer out under the finger.
  // It runs as a native gesture so the message list cannot steal a sideways
  // drag; sideways scrollers such as code blocks still win their own drags.
  // Built once: a detector handed a new gesture can stop answering touches, so
  // what decides a touch lives in shared values instead of toggling `enabled`.
  // The callbacks are worklets: only there can a touch be failed outright.
  const drawerRef = useRef<SlideDrawerHandle>(null);
  const swipeBlocked = useSharedValue(false);
  const bandTop = useSharedValue(-1);
  const bandBottom = useSharedValue(-1);
  useEffect(() => {
    swipeBlocked.value = drawerOpen;
  }, [drawerOpen, swipeBlocked]);
  const onCardsBand = useCallback(
    (band: {top: number; bottom: number} | null) => {
      bandTop.value = band ? band.top : -1;
      bandBottom.value = band ? band.bottom : -1;
    },
    [bandTop, bandBottom],
  );
  const swipeStart = useCallback(() => {
    Keyboard.dismiss();
    setDrawerView('menu');
    setDrawerNested(false);
    refreshDrawer();
  }, [refreshDrawer]);
  const swipeMove = useCallback((dx: number) => drawerRef.current?.drag(dx), []);
  const swipeEnd = useCallback((success: boolean, dx: number, vx: number) => {
    // Pan velocity is in px/s; the drawer's fling threshold is px/ms.
    const opened = success ? drawerRef.current?.release(dx, vx / 1000) : drawerRef.current?.release(0, 0);
    setDrawerOpen(!!opened);
  }, []);
  const drawerSwipe = useMemo(
    () =>
      Gesture.Pan()
        .activeOffsetX(12)
        .failOffsetX(-12)
        .failOffsetY([-14, 14])
        .onTouchesDown((e, manager) => {
          'worklet';
          const y = e.allTouches[0]?.absoluteY ?? -1;
          if (swipeBlocked.value || (y >= bandTop.value && y <= bandBottom.value)) {
            manager.fail();
          }
        })
        .onStart(() => {
          'worklet';
          scheduleOnRN(swipeStart);
        })
        .onUpdate(e => {
          'worklet';
          scheduleOnRN(swipeMove, e.translationX);
        })
        .onEnd((e, success) => {
          'worklet';
          scheduleOnRN(swipeEnd, success, e.translationX, e.velocityX);
        }),
    [swipeBlocked, bandTop, bandBottom, swipeStart, swipeMove, swipeEnd],
  );

  // Inverted list keeps the newest message pinned to the bottom while streaming.
  const data = useMemo(() => [...messages].reverse(), [messages]);
  // A shared conversation names whoever said each reply.
  const shared = teamSize > 0;
  const openContext = useCallback(() => {
    setContextOnly(true);
    setSessionOpen(true);
  }, []);
  const renderItem = useCallback(
    ({item}: {item: ChatMessage}) => <MessageItem message={item} labelled={shared} onOpenContext={openContext} />,
    [shared, openContext],
  );
  const empty = messages.length === 0;
  emptyRef.current = empty;
  // A conversation that exists, or already has teammates, is about itself rather than about who to start one with.
  const showInfo = !empty || teamSize > 0;
  const crew = team && teamSize > 0 ? [team.owner, ...team.members] : null;

  return (
    <GestureDetector gesture={drawerSwipe}>
      <View style={styles.root}>
        <View style={[styles.top, {paddingTop: insets.top + 6}]}>
          <View style={styles.topLeft}>
            <View style={styles.panes}>
              <IconButton label={tr('chat_features')} onPress={() => openDrawer('menu')}>
                <Burger />
              </IconButton>
              <View style={styles.panesDivider} />
              <IconButton icon={faComments} label={tr('chat_session_list')} onPress={() => openDrawer('sessions')} size={15} />
            </View>
          </View>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={trf(showInfo ? 'chat_info_a11y' : 'chat_agent_a11y', {
              name: agent?.name ?? 'CowAgent',
              team: teamSize ? trf('chat_agent_a11y_team', {n: teamSize}) : '',
            })}
            onPress={() => {
              if (showInfo) {
                setContextOnly(false);
                setSessionOpen(true);
              } else {
                setAgentSheetOpen(true);
              }
            }}
            style={({pressed}) => [styles.agent, pressed && styles.agentPressed]}>
            {crew ? (
              <AvatarStack agents={crew} defaultId={defaultAgentId} />
            ) : (
              <AgentAvatar agent={agent} isDefault={!agent || agent.id === defaultAgentId} size={24} />
            )}
            <Text style={styles.agentName} numberOfLines={1}>
              {crew ? crew.map(a => a.name).join(tr('chat_names_sep')) : (agent?.name ?? 'CowAgent')}
            </Text>
            <Icon icon={faChevronDown} size={8} color={t.t3} />
          </Pressable>
          <View style={styles.topRight}>
            {!empty && (
              <IconButton icon={faPlus} label={tr('session_new')} onPress={startNewChat} size={18} />
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
                agent={agent}
                isDefault={!agent || agent.id === defaultAgentId}
                onPick={pickExample}
                onCardsBand={onCardsBand}
                onSetupModel={modelMissing ? () => navigation.navigate('Models') : undefined}
              />
            )
          ) : (
            <ListShiftContext.Provider value={shiftList}>
              <ListGrowContext.Provider value={holdForReader}>
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
                        <Icon icon={faArrowDown} size={12} color={t.t2} />
                        {unread && <View style={styles.unreadDot} />}
                      </Pressable>
                    </Animated.View>
                  )}
                </View>
              </ListGrowContext.Provider>
            </ListShiftContext.Provider>
          )}
          <Dock
            ref={dock}
            text={draft}
            onChangeText={setDraft}
            placeholder={shared ? tr('composer_placeholder_team') : tr('composer_placeholder')}
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
            model={modelDisplayName(settings?.model)}
            onOpenModel={() => openSettingsSheet(setModelOpen)}
            permission={settings?.permission.mode}
            onOpenPermission={() => openSettingsSheet(setPermissionOpen)}
            roster={roster}
            defaultAgentId={defaultAgentId}
            searchFiles={searchFiles}
            onPickFile={pickFile}
          />
          {!keyboardShown && <View style={{height: insets.bottom}} />}
        </KeyboardAvoidingView>

        <VoiceOverlay />
        <ToastHost bottom={insets.bottom + 150} />

        <SlideDrawer ref={drawerRef} open={drawerOpen} onClose={closeDrawer}>
          <DrawerMenu
            view={drawerView}
            nested={drawerNested}
            onViewChange={view => {
              setDrawerView(view);
              setDrawerNested(view === 'sessions');
            }}
            currentSessionId={sessionId}
            onNewChat={startNewChat}
            onOpenSession={openSession}
            onSessionActions={setActingSession}
            onNavigate={goTo}
            onOpenFile={openMenuFile}
            onOpenLink={openLink}
            onSwitchServer={() => {
              setDrawerOpen(false);
              setServerSheetOpen(true);
            }}
          />
        </SlideDrawer>

        <ServerSheet
          visible={serverSheetOpen}
          onClose={() => setServerSheetOpen(false)}
          onManage={() => navigation.navigate('Devices')}
        />

        <TeamChatSheet visible={teamSheetOpen} onClose={() => setTeamSheetOpen(false)} onStart={startTeamChat} />

        <AgentSheet
          visible={agentSheetOpen}
          onClose={() => setAgentSheetOpen(false)}
          onSelect={switchAgent}
          onTeamChat={() => {
            setAgentSheetOpen(false);
            setTimeout(() => setTeamSheetOpen(true), SHEET_DISMISS_MS);
          }}
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
          title={contextOnly ? tr('session_ctx_title') : sessionItem().title || tr('session_untitled')}
          contextOnly={contextOnly}
          sessionId={sessionId}
          agentId={currentAgentId}
          isNew={!!isNew && empty}
          replying={busy}
          pinned={pinned}
          onTogglePin={togglePin}
          onRename={() => fromSessionSheet(() => setRenameOpen(true))}
          onDelete={() => fromSessionSheet(() => setDeleteOpen(true))}
        />
        <SessionActions
          session={actingSession}
          onClose={() => setActingSession(null)}
          onDeleted={s => {
            forgetSession(s.session_id);
            if (s.session_id === sessionId) {
              startNewChat();
            }
          }}
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
  stack: {flexDirection: 'row', alignItems: 'center'},
  stackItem: {borderRadius: 9, borderWidth: 1.5, borderColor: t.bg2, overflow: 'hidden', backgroundColor: t.bg2},
  stackOverlap: {marginLeft: -9},
  stackMore: {
    width: 24,
    height: 24,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: t.bg3,
  },
  stackMoreText: {fontSize: 10, fontWeight: '600', color: t.t2, fontVariant: ['tabular-nums']},
  agentName: {fontSize: 15, fontWeight: '500', letterSpacing: -0.2, color: t.t1, flexShrink: 1},
  body: {flex: 1},
  center: {flex: 1, alignItems: 'center', justifyContent: 'center'},
  // The list is inverted: flex-end is the visual top, so a short conversation starts there.
  list: {flexGrow: 1, justifyContent: 'flex-end', paddingTop: 20, paddingBottom: 8},
  toBottom: {position: 'absolute', right: 22, bottom: 10},
  // No elevation: Android draws a fading elevated circle's shadow as a jagged polygon.
  toBottomButton: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: t.isDark ? t.bg2 : t.bg0,
    borderWidth: 1,
    borderColor: t.line2,
    shadowColor: '#000',
    shadowOpacity: t.isDark ? 0 : 0.08,
    shadowRadius: 8,
    shadowOffset: {width: 0, height: 2},
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

const STACK_MAX = 3;

/** Overlapping faces for a shared conversation: owner first, then teammates. */
function AvatarStack({agents, defaultId}: {agents: AgentBadge[]; defaultId: string | null}) {
  const styles = useStyles();
  const shown = agents.slice(0, STACK_MAX);
  const rest = agents.length - shown.length;
  return (
    <View style={styles.stack}>
      {shown.map((a, i) => (
        <View key={a.id} style={[styles.stackItem, i > 0 && styles.stackOverlap, {zIndex: STACK_MAX - i}]}>
          <AgentAvatar agent={a} isDefault={a.id === defaultId} size={24} />
        </View>
      ))}
      {rest > 0 && (
        <View style={[styles.stackItem, styles.stackOverlap]}>
          <View style={styles.stackMore}>
            <Text style={styles.stackMoreText}>+{rest}</Text>
          </View>
        </View>
      )}
    </View>
  );
}
