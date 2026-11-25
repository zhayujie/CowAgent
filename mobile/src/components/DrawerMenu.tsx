import {faMessage} from '@fortawesome/free-regular-svg-icons';
import {
  faArrowUpRightFromSquare,
  faArrowsRotate,
  faBars,
  faChevronLeft,
  faChevronUp,
  faGear,
  faMobileScreen,
  faPlus,
  faServer,
  faSort,
  faTerminal,
} from '@fortawesome/free-solid-svg-icons';
import type {IconDefinition} from '@fortawesome/fontawesome-svg-core';
import React, {useEffect, useMemo, useRef, useState} from 'react';
import {ActivityIndicator, Pressable, ScrollView, SectionList, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import type {ChatFile} from '../files/chatFile';
import {tr, trf} from '../i18n';
import {useLocalDeviceName} from '../kernel/localKernel';
import {menuSections, type MenuEntry, type MenuRoute} from '../navigation/menuViews';
import type {SessionItem} from '../protocol/events';
import {useLinkStore} from '../store/linkStore';
import {useMenuStore} from '../store/menuStore';
import {activeServer, useLocalServer, useServerStore} from '../store/serverStore';
import {useSessionStore} from '../store/sessionStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {useAgentVersion} from '../update/useAgentVersion';
import {clockTime, shortTime} from '../utils/format';
import {DEFAULT_SPACE, groupSessions, type SessionGroup, type Space} from '../utils/sessionGroups';
import {Icon} from './Icon';
import {SpaceActions} from './SessionActions';
import {ChoiceSheet} from './settings';
import {SHEET_DISMISS_MS} from './Sheet';
import {SpaceHeader, SpaceMore} from './SpaceHeader';

/** Pages the version sheet in the footer leads to. */
type AboutKey = 'Version' | 'Logs' | 'MenuEditor';

export type DrawerRoute = MenuRoute | AboutKey;

/** The menu, or the conversations it leads to. */
export type DrawerView = 'menu' | 'sessions';


export function DrawerMenu({
  view,
  nested,
  open = true,
  onViewChange,
  currentSessionId,
  activeSection,
  onNewChat,
  onNewChatIn,
  onOpenSession,
  onSessionActions,
  onNavigate,
  onOpenFile,
  onOpenLink,
  onSwitchServer,
}: {
  view: DrawerView;
  /** The conversations were opened from the menu, so they offer a way back to it. */
  nested: boolean;
  /** Whether the drawer is showing; a sidebar always is. */
  open?: boolean;
  onViewChange: (view: DrawerView) => void;
  currentSessionId: string;
  /** The page shown beside a sidebar, marked in the menu; none in the drawer, which covers it. */
  activeSection?: string;
  onNewChat: () => void;
  /** A new chat working in the given space; a null path is the default workspace. */
  onNewChatIn: (space: Space) => void;
  onOpenSession: (session: SessionItem) => void;
  /** Long press on a conversation: pin, rename, delete. */
  onSessionActions: (session: SessionItem) => void;
  onNavigate: (route: DrawerRoute) => void;
  onOpenFile: (file: ChatFile) => void;
  onOpenLink: (label: string, url: string, external: boolean) => void;
  onSwitchServer: () => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const version = useAgentVersion();
  const realtime = useServerStore(s => s.realtimeStatus);
  const doc = useMenuStore(s => s.doc);
  const artifactsHidden = useMenuStore(s => s.artifactsHidden);
  const local = useLocalServer();
  const sections = useMemo(() => menuSections(doc, local, !artifactsHidden), [doc, local, artifactsHidden]);
  const [aboutOpen, setAboutOpen] = useState(false);
  const server = activeServer();
  // Servers go by the name they gave themselves; the address is only a fallback.
  const localName = useLocalDeviceName();
  const name = server?.local ? localName : server?.name || server?.baseUrl.replace(/^https?:\/\//, '');
  const down = useLinkStore(s => s.down);
  const offline = realtime === 'closed' || down;
  const status = !server
    ? tr('menu_not_connected')
    : offline
      ? tr(down ? 'menu_unreachable' : 'menu_reconnecting')
      : server.local
        ? tr('server_local_meta')
        : tr('menu_remote_device');

  const renderEntry = (e: MenuEntry) => {
    if (e.kind === 'route') {
      const go = e.view === 'chat' ? () => onViewChange('sessions') : () => onNavigate(e.route);
      const active = !!activeSection && (e.view === 'chat' ? activeSection === 'Chat' : e.route === activeSection);
      return <Item key={e.key} icon={e.icon} label={e.label} active={active} onPress={go} />;
    }
    if (e.kind === 'file') {
      const file = e.file;
      return <Item key={e.key} icon={e.icon} label={e.label} dim={!file} onPress={() => file && onOpenFile(file)} />;
    }
    return (
      <Item
        key={e.key}
        icon={e.icon}
        label={e.label}
        external={e.external}
        dim={!e.url}
        onPress={() => e.url && onOpenLink(e.label, e.url, e.external)}
      />
    );
  };

  const openAbout = (key: AboutKey) => {
    setAboutOpen(false);
    setTimeout(() => onNavigate(key), SHEET_DISMISS_MS);
  };

  const versionLabel = version ? `CowAgent v${version}` : 'CowAgent';

  if (view === 'sessions') {
    return (
      <View style={[styles.root, {paddingTop: insets.top, paddingBottom: insets.bottom}]}>
        <SessionList
          open={open}
          currentSessionId={currentSessionId}
          onBack={nested ? () => onViewChange('menu') : undefined}
          onNewChat={onNewChat}
          onNewChatIn={onNewChatIn}
          onOpenSession={onOpenSession}
          onSessionActions={onSessionActions}
          onViewAll={() => onNavigate('Sessions')}
        />
      </View>
    );
  }

  return (
    <View style={[styles.root, {paddingTop: insets.top}]}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`${tr('server_switch')}: ${name ?? ''}, ${status}`}
        onPress={onSwitchServer}
        style={({pressed}) => [styles.device, pressed && styles.devicePressed]}>
        <View style={styles.deviceIcon}>
          <Icon icon={server?.local ? faMobileScreen : faServer} size={15} color={t.accent} />
        </View>
        <View style={styles.deviceText}>
          <Text style={styles.deviceName} numberOfLines={1}>
            {name || tr('menu_not_connected')}
          </Text>
          <View style={styles.statusRow}>
            <View style={[styles.statusDot, (offline || !server) && styles.statusDotOff]} />
            <Text style={styles.deviceStatus} numberOfLines={1}>
              {status}
            </Text>
          </View>
        </View>
        <Icon icon={faSort} size={12} color={t.t3} />
      </Pressable>

      <ScrollView style={styles.scroll} contentContainerStyle={styles.scrollBody} showsVerticalScrollIndicator={false}>
        {sections.map((section, i) => (
          <React.Fragment key={section.id}>
            <Text style={[styles.section, i === 0 && styles.sectionFirst]}>{section.label}</Text>
            {section.entries.map(renderEntry)}
          </React.Fragment>
        ))}
      </ScrollView>

      <View style={[styles.footer, {paddingBottom: Math.max(insets.bottom, 8)}]}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={versionLabel}
          hitSlop={4}
          onPress={() => setAboutOpen(true)}
          style={({pressed}) => [styles.version, pressed && styles.pressed]}>
          <Text style={styles.versionText} numberOfLines={1}>
            {versionLabel}
          </Text>
          <Icon icon={faChevronUp} size={9} color={t.t3} />
        </Pressable>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={tr('menu_config')}
          hitSlop={4}
          onPress={() => onNavigate('Settings')}
          style={({pressed}) => [styles.gear, pressed && styles.pressed]}>
          <Icon icon={faGear} size={16} color={t.t2} />
        </Pressable>
      </View>

      <ChoiceSheet<AboutKey>
        visible={aboutOpen}
        title={versionLabel}
        options={[
          {key: 'Version', label: tr('menu_about_update'), desc: tr('menu_about_update_desc'), icon: faArrowsRotate},
          {key: 'Logs', label: tr('menu_about_logs'), desc: tr('menu_about_logs_desc'), icon: faTerminal},
          {key: 'MenuEditor', label: tr('menu_about_menu'), desc: tr('menu_about_menu_desc'), icon: faBars},
        ]}
        onSelect={openAbout}
        onClose={() => setAboutOpen(false)}
      />
    </View>
  );
}

function SessionList({
  open,
  currentSessionId,
  onBack,
  onNewChat,
  onNewChatIn,
  onOpenSession,
  onSessionActions,
  onViewAll,
}: {
  open: boolean;
  currentSessionId: string;
  /** Leads back to the menu; absent when the list was opened on its own. */
  onBack?: () => void;
  onNewChat: () => void;
  onNewChatIn: (space: Space) => void;
  onOpenSession: (session: SessionItem) => void;
  onSessionActions: (session: SessionItem) => void;
  onViewAll: () => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  const sessions = useSessionStore(s => s.sessions);
  const total = useSessionStore(s => s.total);
  const failed = useSessionStore(s => !!s.error);
  const loading = useSessionStore(s => s.loading);
  const loadingMore = useSessionStore(s => s.loadingMore);
  const groupMode = useSessionStore(s => s.groupMode);
  const projectOrder = useSessionStore(s => s.projectOrder);
  const spaces = useSessionStore(s => s.spaces);
  const spacesLoading = useSessionStore(s => s.spacesLoading);
  const collapsed = useSessionStore(s => s.collapsed);
  const [actingSpace, setActingSpace] = useState<SessionGroup | null>(null);
  const list = useRef<SectionList<SessionItem, SessionGroup & {group: SessionGroup}>>(null);
  // A list too short to scroll, say with every group folded, must not page through every chat on its own.
  const scrolled = useRef(false);
  const bySpace = groupMode === 'project';
  // Spaces page on their own once the server lists them; older servers page the whole list.
  const pagesAll = !bySpace || !spaces.length;
  const groups = useMemo(
    () => groupSessions(sessions, groupMode, projectOrder, spaces),
    [sessions, groupMode, projectOrder, spaces],
  );
  const sections = useMemo(
    () => groups.map(g => ({...g, group: g, data: bySpace && collapsed.includes(g.key) ? [] : g.data})),
    [groups, bySpace, collapsed],
  );
  const latest = useRef(sections);
  latest.current = sections;
  const firstKey = sections[0]?.key;
  const ready = sessions.length > 0;

  // Opening the list lands on the current chat, its space unfolded.
  useEffect(() => {
    if (!open || !ready) {
      return;
    }
    const current = useSessionStore.getState().sessions.find(s => s.session_id === currentSessionId);
    if (!current) {
      return;
    }
    if (useSessionStore.getState().groupMode === 'project') {
      useSessionStore.getState().expand(current.project?.path ?? DEFAULT_SPACE);
    }
    const timer = setTimeout(() => {
      const sectionIndex = latest.current.findIndex(sec => sec.data.some(s => s.session_id === currentSessionId));
      if (sectionIndex < 0) {
        return;
      }
      const itemIndex = latest.current[sectionIndex].data.findIndex(s => s.session_id === currentSessionId);
      list.current?.scrollToLocation({sectionIndex, itemIndex, viewPosition: 0.3, animated: false});
    }, 60);
    return () => clearTimeout(timer);
  }, [open, ready, currentSessionId]);

  return (
    <>
      <View style={styles.listHead}>
        <View style={styles.listTitleRow}>
          {onBack ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={tr('chat_features')}
              hitSlop={6}
              onPress={onBack}
              style={({pressed}) => [styles.listBack, pressed && styles.pressed]}>
              <Icon icon={faChevronLeft} size={13} color={t.t2} />
              <Text style={styles.listTitle}>{tr('menu_chat')}</Text>
            </Pressable>
          ) : (
            <Text style={[styles.listTitle, styles.listTitleAlone]} accessibilityRole="header">
              {tr('menu_chat')}
            </Text>
          )}
        </View>
        <Pressable
          accessibilityRole="button"
          hitSlop={4}
          onPress={onNewChat}
          style={({pressed}) => [styles.newChat, pressed && styles.newChatPressed]}>
          <Icon icon={faPlus} size={12} color={t.accent} />
          <Text style={styles.newChatText}>{tr('menu_new_chat')}</Text>
        </Pressable>
      </View>
      <SectionList
        ref={list}
        style={styles.scroll}
        contentContainerStyle={styles.scrollBody}
        showsVerticalScrollIndicator={false}
        sections={sections}
        keyExtractor={s => s.session_id}
        stickySectionHeadersEnabled={false}
        initialNumToRender={20}
        windowSize={7}
        onScrollToIndexFailed={info =>
          list.current?.getScrollResponder()?.scrollTo({y: info.averageItemLength * info.index, animated: false})
        }
        renderSectionHeader={({section}) =>
          bySpace ? (
            <SpaceHeader
              group={section.group}
              collapsed={collapsed.includes(section.key)}
              onToggle={() => useSessionStore.getState().toggleCollapsed(section.key)}
              onLongPress={() => setActingSpace(section.group)}
              style={section.key === firstKey ? styles.spaceFirst : styles.space}
            />
          ) : (
            <Text style={[styles.section, section.key === firstKey && styles.sectionFirst]}>{section.title}</Text>
          )
        }
        renderSectionFooter={({section}) =>
          bySpace && !collapsed.includes(section.key) ? (
            <SpaceMore
              group={section.group}
              loading={spacesLoading.includes(section.key)}
              onPress={() => useSessionStore.getState().loadSpace(section.key)}
              style={styles.spaceMore}
            />
          ) : null
        }
        renderItem={({item, section}) => (
          <Item
            icon={faMessage}
            label={item.title || tr('menu_untitled_chat')}
            meta={section.key === 'yesterday' ? clockTime(item.last_active) : shortTime(item.last_active)}
            active={item.session_id === currentSessionId}
            onPress={() => onOpenSession(item)}
            onLongPress={() => onSessionActions(item)}
          />
        )}
        onScrollBeginDrag={() => (scrolled.current = true)}
        onEndReachedThreshold={0.5}
        onEndReached={() => pagesAll && scrolled.current && useSessionStore.getState().loadMore()}
        ListEmptyComponent={
          loading ? (
            <ActivityIndicator style={styles.loading} color={t.t3} />
          ) : (
            <Text style={styles.empty}>{tr(failed ? 'menu_chats_failed' : 'menu_no_chats')}</Text>
          )
        }
        ListFooterComponent={
          loadingMore ? (
            <ActivityIndicator style={styles.loading} color={t.t3} />
          ) : ready ? (
            <Pressable accessibilityRole="button" hitSlop={6} onPress={onViewAll} style={styles.more}>
              <Text style={styles.moreText}>{trf('menu_view_all', {n: total})}</Text>
            </Pressable>
          ) : null
        }
      />
      <SpaceActions
        group={actingSpace}
        keys={groups.map(g => g.key)}
        onClose={() => setActingSpace(null)}
        onNewChat={onNewChatIn}
      />
    </>
  );
}

function Item({
  icon,
  label,
  meta,
  active,
  external,
  dim,
  onPress,
  onLongPress,
}: {
  icon: IconDefinition;
  label: string;
  /** Quiet text on the right, such as when a chat was last active. */
  meta?: string;
  active?: boolean;
  /** Opens outside the app, in the browser. */
  external?: boolean;
  dim?: boolean;
  onPress: () => void;
  onLongPress?: () => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  return (
    <Pressable
      accessibilityRole={external ? 'link' : 'button'}
      accessibilityState={{selected: active, disabled: dim}}
      accessibilityHint={onLongPress ? tr('session_row_hint') : undefined}
      onPress={onPress}
      onLongPress={onLongPress}
      delayLongPress={350}
      style={({pressed}) => [styles.item, active && styles.itemActive, pressed && !active && styles.pressed]}>
      <View style={styles.itemIcon}>
        <Icon icon={icon} size={15} color={active ? t.accent : dim ? t.t4 : t.t2} />
      </View>
      <Text style={[styles.itemLabel, active && styles.itemLabelActive, dim && styles.itemDim]} numberOfLines={1}>
        {label}
      </Text>
      {!!meta && <Text style={styles.itemMeta}>{meta}</Text>}
      {external && !dim && <Icon icon={faArrowUpRightFromSquare} size={10} color={t.t3} />}
    </Pressable>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1},
  device: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    marginHorizontal: 12,
    marginTop: 10,
    paddingHorizontal: 12,
    paddingVertical: 12,
    borderRadius: radius.md,
    backgroundColor: t.isDark ? t.bg2 : t.bg1,
    borderWidth: 1,
    borderColor: t.line1,
  },
  devicePressed: {backgroundColor: t.isDark ? t.bg3 : t.bg2},
  deviceIcon: {
    width: 38,
    height: 38,
    borderRadius: radius.sm,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: t.accentSoft,
  },
  deviceText: {flex: 1, minWidth: 0},
  deviceName: {fontSize: 16, fontWeight: '600', color: t.t1, letterSpacing: -0.2},
  statusRow: {flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 4},
  statusDot: {width: 6, height: 6, borderRadius: 3, backgroundColor: t.green},
  statusDotOff: {backgroundColor: t.t4},
  deviceStatus: {flexShrink: 1, fontSize: 12, color: t.t2},
  scroll: {flex: 1},
  scrollBody: {paddingHorizontal: 12, paddingTop: 6, paddingBottom: 16},
  section: {
    fontSize: 12,
    fontWeight: '600',
    letterSpacing: 0.4,
    color: t.t3,
    paddingHorizontal: 12,
    marginTop: 22,
    marginBottom: 6,
  },
  sectionFirst: {marginTop: 14},
  space: {marginTop: 14, marginBottom: 2},
  spaceFirst: {marginTop: 8, marginBottom: 2},
  item: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 13,
    minHeight: 46,
    paddingHorizontal: 12,
    borderRadius: radius.sm,
  },
  pressed: {backgroundColor: t.bg2},
  itemIcon: {width: 18, alignItems: 'center'},
  itemActive: {backgroundColor: t.accentSoft},
  itemLabel: {flex: 1, fontSize: 16, color: t.t1, letterSpacing: -0.1},
  itemLabelActive: {fontWeight: '500'},
  itemDim: {color: t.t4},
  itemMeta: {fontSize: 12, color: t.t3, fontVariant: ['tabular-nums']},
  listHead: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginHorizontal: 12,
    marginTop: 14,
  },
  listBack: {flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 10, paddingVertical: 8, borderRadius: radius.sm},
  listTitleRow: {flexDirection: 'row', alignItems: 'center', gap: 2},
  listTitle: {fontSize: 18, fontWeight: '600', color: t.t1, letterSpacing: -0.3},
  listTitleAlone: {paddingHorizontal: 12, paddingVertical: 8},
  newChat: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 14,
    height: 36,
    borderRadius: 18,
    backgroundColor: t.accentSoft,
  },
  newChatPressed: {opacity: 0.7},
  newChatText: {fontSize: 14, fontWeight: '600', color: t.accent},
  empty: {fontSize: 14, lineHeight: 21, color: t.t3, paddingHorizontal: 12, marginTop: 20},
  loading: {paddingVertical: 14},
  more: {paddingHorizontal: 12, paddingVertical: 14},
  moreText: {fontSize: 13, color: t.accent},
  spaceMore: {paddingLeft: 43},
  footer: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 12,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: t.line1,
  },
  version: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 7,
    flexShrink: 1,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: radius.sm,
  },
  versionText: {flexShrink: 1, fontSize: 13, color: t.t2, fontVariant: ['tabular-nums']},
  gear: {width: 42, height: 42, borderRadius: radius.sm, alignItems: 'center', justifyContent: 'center'},
}));
