import {faCircleUser, faComments, faMessage, faPenToSquare} from '@fortawesome/free-regular-svg-icons';
import {faArrowUpRightFromSquare, faUserGroup} from '@fortawesome/free-solid-svg-icons';
import type {IconDefinition} from '@fortawesome/fontawesome-svg-core';
import React, {useMemo} from 'react';
import {Image, Pressable, ScrollView, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import logo from '../assets/logo-mark.png';
import type {ChatFile} from '../files/chatFile';
import {BUILTIN_VIEWS, menuSections, type MenuEntry, type MenuRoute} from '../navigation/menuViews';
import type {SessionItem} from '../protocol/events';
import {useAgentStore} from '../store/agentStore';
import {useMenuStore} from '../store/menuStore';
import {useOverviewStore} from '../store/overviewStore';
import {activeServer, useServerStore} from '../store/serverStore';
import {useSessionStore} from '../store/sessionStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {clockTime, shortTime} from '../utils/format';
import {groupSessions} from '../utils/sessionGroups';
import {Icon} from './Icon';

export type DrawerRoute = 'Sessions' | MenuRoute;

/** "chat" lists conversations only; "features" lists every other menu page. */
export type DrawerMode = 'features' | 'chat';

const MODES: {key: DrawerMode; label: string}[] = [
  {key: 'features', label: '功能'},
  {key: 'chat', label: '对话'},
];

const RECENT_LIMIT = 30;

export function DrawerMenu({
  mode,
  onModeChange,
  currentSessionId,
  onNewChat,
  onNewTeamChat,
  onOpenSession,
  onNavigate,
  onOpenFile,
  onOpenLink,
  onSwitchAgent,
}: {
  mode: DrawerMode;
  onModeChange: (mode: DrawerMode) => void;
  currentSessionId: string;
  onNewChat: () => void;
  onNewTeamChat: () => void;
  onOpenSession: (session: SessionItem) => void;
  onNavigate: (route: DrawerRoute) => void;
  onOpenFile: (file: ChatFile) => void;
  onOpenLink: (label: string, url: string, external: boolean) => void;
  onSwitchAgent: () => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const sessions = useSessionStore(s => s.sessions);
  const total = useSessionStore(s => s.total);
  const agentCount = useAgentStore(s => s.agents.length);
  const counts = useOverviewStore(s => s.counts);
  const version = useOverviewStore(s => s.version);
  const realtime = useServerStore(s => s.realtimeStatus);
  const doc = useMenuStore(s => s.doc);
  const sections = useMemo(() => menuSections(doc), [doc]);
  const server = activeServer();
  const host = server?.baseUrl.replace(/^https?:\/\//, '') ?? '';
  const groups = useMemo(() => groupSessions(sessions.slice(0, RECENT_LIMIT)), [sessions]);

  const countOf = (view: string): number | string | undefined => {
    const n =
      view === 'artifacts'
        ? counts.artifacts
        : view === 'skills'
          ? counts.skills
          : view === 'tasks'
            ? counts.tasks
            : view === 'channels'
              ? counts.channels
              : view === 'agents'
                ? agentCount
                : undefined;
    return n || undefined;
  };

  const renderEntry = (e: MenuEntry) => {
    if (e.kind === 'route') {
      return (
        <Item
          key={e.key}
          icon={e.icon}
          label={e.label}
          count={countOf(e.view)}
          onPress={() => onNavigate(e.route)}
        />
      );
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

  const chatBody = (
    <>
      <View style={styles.newRow}>
        <Pressable
          accessibilityRole="button"
          onPress={onNewChat}
          style={({pressed}) => [styles.newChat, pressed && styles.pressed]}>
          <Icon icon={faPenToSquare} size={14} color={t.accent} />
          <Text style={styles.newChatText}>新对话</Text>
        </Pressable>
        <Pressable
          accessibilityRole="button"
          onPress={onNewTeamChat}
          style={({pressed}) => [styles.newChat, pressed && styles.pressed]}>
          <Icon icon={faUserGroup} size={13} color={t.accent} />
          <Text style={styles.newChatText}>多智能体对话</Text>
        </Pressable>
      </View>
      <View style={styles.chatLinks}>
        <Item icon={faComments} label="全部会话" count={total || undefined} onPress={() => onNavigate('Sessions')} />
        <Item
          icon={BUILTIN_VIEWS.artifacts.icon}
          label={BUILTIN_VIEWS.artifacts.label}
          count={countOf('artifacts')}
          onPress={() => onNavigate('Artifacts')}
        />
        <Item icon={faCircleUser} label="切换 Agent" onPress={onSwitchAgent} />
      </View>

      {groups.map(g => (
        <React.Fragment key={g.title}>
          <Section label={g.title} />
          {g.data.map(s => (
            <Item
              key={s.session_id}
              icon={faMessage}
              label={s.title || '未命名对话'}
              count={g.title === '昨天' ? clockTime(s.last_active) : shortTime(s.last_active)}
              active={s.session_id === currentSessionId}
              onPress={() => onOpenSession(s)}
            />
          ))}
        </React.Fragment>
      ))}
      {!groups.length && <Text style={styles.empty}>还没有对话，发一条消息就会出现在这里</Text>}
      {total > RECENT_LIMIT && (
        <Pressable accessibilityRole="button" hitSlop={6} onPress={() => onNavigate('Sessions')} style={styles.more}>
          <Text style={styles.moreText}>查看全部 {total} 个对话</Text>
        </Pressable>
      )}
    </>
  );

  // The chat group may also hold pages such as Artifacts; those belong with the features, unlabelled on top.
  const featuresBody = sections
    .filter(section => section.entries.length)
    .map((section, i) => (
      <React.Fragment key={section.id}>
        {section.hasChat ? (
          <View style={i === 0 ? styles.gapFirst : styles.gap} />
        ) : (
          <Section label={section.label} first={i === 0} />
        )}
        {section.entries.map(renderEntry)}
      </React.Fragment>
    ));

  return (
    <View style={[styles.root, {paddingTop: insets.top}]}>
      <View style={styles.header}>
        <View style={styles.switch} accessibilityRole="tablist">
          {MODES.map(m => {
            const active = m.key === mode;
            return (
              <Pressable
                key={m.key}
                accessibilityRole="tab"
                accessibilityState={{selected: active}}
                onPress={() => onModeChange(m.key)}
                style={[styles.switchItem, active && styles.switchItemActive]}>
                <Text style={[styles.switchText, active && styles.switchTextActive]}>{m.label}</Text>
              </Pressable>
            );
          })}
        </View>
        <Image source={logo} style={styles.logo} accessibilityLabel="CowAgent" />
      </View>

      <ScrollView
        key={mode}
        style={styles.scroll}
        contentContainerStyle={styles.scrollBody}
        showsVerticalScrollIndicator={false}>
        {mode === 'chat' ? chatBody : featuresBody}
      </ScrollView>

      <Pressable
        accessibilityRole="button"
        onPress={() => onNavigate('Settings')}
        style={({pressed}) => [styles.footer, {paddingBottom: insets.bottom + 14}, pressed && styles.pressed]}>
        <View style={styles.serverDot}>
          <Text style={styles.serverLetter}>{(server?.name || host || 'C').slice(0, 1).toUpperCase()}</Text>
        </View>
        <View style={styles.footerText}>
          <Text style={styles.serverName} numberOfLines={1}>
            {host || '未连接'}
          </Text>
          <View style={styles.statusRow}>
            <View style={[styles.statusDot, realtime === 'closed' && styles.statusDotOff]} />
            <Text style={styles.serverStatus}>
              {realtime === 'closed' ? '重新连接中' : '已连接'}
              {version ? ` · v${version}` : ''}
            </Text>
          </View>
        </View>
      </Pressable>
    </View>
  );
}

function Section({label, first}: {label: string; first?: boolean}) {
  const styles = useStyles();
  return <Text style={[styles.section, first && styles.sectionFirst]}>{label}</Text>;
}

function Item({
  icon,
  label,
  count,
  active,
  external,
  dim,
  onPress,
}: {
  icon: IconDefinition;
  label: string;
  count?: number | string;
  active?: boolean;
  /** Opens outside the app, in the browser. */
  external?: boolean;
  dim?: boolean;
  onPress: () => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  return (
    <Pressable
      accessibilityRole={external ? 'link' : 'button'}
      accessibilityState={{selected: active, disabled: dim}}
      onPress={onPress}
      style={({pressed}) => [styles.item, active && styles.itemActive, pressed && !active && styles.pressed]}>
      <View style={styles.itemIcon}>
        <Icon icon={icon} size={14} color={active ? t.accent : t.t3} />
      </View>
      <Text style={[styles.itemLabel, active && styles.itemLabelActive, dim && styles.itemDim]} numberOfLines={1}>
        {label}
      </Text>
      {count !== undefined && <Text style={styles.itemCount}>{count}</Text>}
      {external && !dim && <Icon icon={faArrowUpRightFromSquare} size={9} color={t.t4} />}
    </Pressable>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1},
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginHorizontal: 14,
    paddingTop: 10,
    paddingBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: t.line1,
  },
  switch: {
    flexDirection: 'row',
    padding: 3,
    borderRadius: radius.sm,
    backgroundColor: t.bg2,
  },
  switchItem: {paddingHorizontal: 16, paddingVertical: 6, borderRadius: radius.xs},
  switchItemActive: {
    backgroundColor: t.bg0,
    shadowColor: '#000',
    shadowOpacity: t.isDark ? 0 : 0.06,
    shadowRadius: 3,
    shadowOffset: {width: 0, height: 1},
    elevation: t.isDark ? 0 : 1,
  },
  switchText: {fontSize: 14, color: t.t3},
  switchTextActive: {color: t.t1, fontWeight: '600'},
  logo: {width: 24, height: 24, marginRight: 4},
  scroll: {flex: 1},
  scrollBody: {paddingHorizontal: 10, paddingTop: 12, paddingBottom: 12},
  newRow: {flexDirection: 'row', gap: 8},
  newChat: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    paddingHorizontal: 8,
    paddingVertical: 11,
    borderRadius: radius.sm,
    backgroundColor: t.bg2,
    borderWidth: 1,
    borderColor: t.line1,
  },
  newChatText: {fontSize: 14, fontWeight: '500', color: t.t1},
  section: {
    fontSize: 11,
    fontWeight: '600',
    letterSpacing: 1.6,
    color: t.t4,
    paddingHorizontal: 12,
    marginTop: 20,
    marginBottom: 6,
  },
  sectionFirst: {marginTop: 4},
  gap: {height: 14},
  gapFirst: {height: 4},
  chatLinks: {marginTop: 8},
  empty: {fontSize: 13, lineHeight: 20, color: t.t4, paddingHorizontal: 12, marginTop: 20},
  more: {paddingHorizontal: 12, paddingVertical: 12},
  moreText: {fontSize: 13, color: t.accent},
  item: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 11,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: radius.sm,
  },
  itemActive: {backgroundColor: t.accentSoft},
  pressed: {backgroundColor: t.bg2},
  itemIcon: {width: 16, alignItems: 'center'},
  itemLabel: {flex: 1, fontSize: 15, color: t.t2, letterSpacing: -0.1},
  itemLabelActive: {color: t.t1, fontWeight: '500'},
  itemDim: {color: t.t4},
  itemCount: {fontSize: 12, color: t.t4, fontVariant: ['tabular-nums']},
  footer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingHorizontal: 18,
    paddingTop: 14,
    borderTopWidth: 1,
    borderTopColor: t.line1,
  },
  serverDot: {
    width: 28,
    height: 28,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: t.avatarBg,
  },
  serverLetter: {fontSize: 12, fontWeight: '600', color: t.avatarText},
  footerText: {flex: 1},
  serverName: {fontSize: 13, color: t.t2},
  statusRow: {flexDirection: 'row', alignItems: 'center', gap: 5, marginTop: 3},
  statusDot: {width: 5, height: 5, borderRadius: 3, backgroundColor: t.accent},
  statusDotOff: {backgroundColor: t.t4},
  serverStatus: {fontSize: 11, color: t.t4},
}));
