import {
  faArrowUpRightFromSquare,
  faChevronRight,
  faCodeBranch,
  faCompass,
  faFileArrowUp,
  faFileLines,
  faPaw,
  faPenToSquare,
  faPlus,
  faStore,
  faTrashCan,
} from '@fortawesome/free-solid-svg-icons';
import {useFocusEffect} from '@react-navigation/native';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {FlatList, Pressable, RefreshControl, ScrollView, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {
  confirmSkillInstall,
  deleteSkill,
  discardSkillPreview,
  getSkills,
  getTools,
  previewSkill,
  setSkillEnabled,
  uploadSkill,
} from '../api/cowApi';
import {Icon} from '../components/Icon';
import {
  ChoiceSheet,
  ConfirmSheet,
  FieldSheet,
  MONO,
  Notice,
  StatusTag,
  Toggle,
  type Choice,
} from '../components/settings';
import {SHEET_DISMISS_MS} from '../components/Sheet';
import {McpIcon, SkillIcon, ToolIcon} from '../components/SkillIcon';
import {SkillInstallSheet} from '../components/SkillInstallSheet';
import {showToast, ToastHost} from '../components/Toast';
import {SwipeTabs} from '../components/SwipeTabs';
import {EmptyState, GroupLabel, IconButton, PageHeader, Segmented} from '../components/ui';
import {tr, trf, type MessageKey} from '../i18n';
import {pickDocuments} from '../media/picker';
import {openWebPage} from '../navigation/openWeb';
import type {RootStackParamList} from '../navigation/types';
import type {Skill, SkillMarketSource, SkillPreview, ToolInfo} from '../protocol/resources';
import {MCP_STATUS, MCP_TRANSPORT_LABEL, mcpTarget, mcpTransport, useMcpStore} from '../store/mcpStore';
import {describeConnectError, useLocalServer} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {compareSkills, SKILL_SOURCE_LABEL, skillDescription, skillName, skillRefusal} from '../utils/skills';

type Props = StackScreenProps<RootStackParamList, 'Skills'>;
type Tab = 'skills' | 'tools' | 'mcp';
const TABS: readonly Tab[] = ['skills', 'tools', 'mcp'];

/** The tools the app runs on the phone, named and explained in the user's language. */
const PHONE_TOOL: Record<string, [MessageKey, MessageKey]> = {
  phone_open: ['phone_tool_open', 'phone_tool_open_desc'],
  phone_location: ['phone_tool_location', 'phone_tool_location_desc'],
  phone_calendar: ['phone_tool_calendar', 'phone_tool_calendar_desc'],
  phone_contacts: ['phone_tool_contacts', 'phone_tool_contacts_desc'],
  phone_photos: ['phone_tool_photos', 'phone_tool_photos_desc'],
  phone_share: ['phone_tool_share', 'phone_tool_share_desc'],
  phone_device: ['phone_tool_device', 'phone_tool_device_desc'],
};

const PLATFORM_NAME: Record<string, MessageKey> = {
  android: 'phone_platform_android',
  ios: 'phone_platform_ios',
  harmony: 'phone_platform_harmony',
};

const platformName = (p: string) => (PLATFORM_NAME[p] ? tr(PLATFORM_NAME[p]) : p);

/** Phone tools first; without any, one unlabelled list as before. */
function toolGroups(tools: ToolInfo[]) {
  const phone = tools.filter(t => t.group === 'phone');
  const rest = tools.filter(t => t.group !== 'phone');
  if (!phone.length) {
    return [{key: 'all', label: null, items: tools}];
  }
  return [
    {key: 'phone', label: tr('phone_group'), items: phone},
    ...(rest.length ? [{key: 'builtin', label: tr('skill_tools_builtin'), items: rest}] : []),
  ];
}

type SheetState =
  | {kind: 'add'}
  | {kind: 'market'; source: SkillMarketSource}
  | {kind: 'skill'; skill: Skill}
  | {kind: 'delete'; skill: Skill};
type AddKey = 'create' | SkillMarketSource | 'upload' | 'browse';

export const SKILL_HUB_URL = 'https://skills.cowagent.ai/';
const MCP_POLL_MS = 1500;
const MCP_POLL_MAX_MS = 120_000;
const UPLOAD_MAX_BYTES = 50 * 1024 * 1024;

const market = (source: SkillMarketSource): {title: string; placeholder: string; hint: string} =>
  ({
    hub: {
      title: tr('skill_market_hub_title'),
      placeholder: tr('skill_market_hub_ph'),
      hint: tr('skill_market_hub_hint'),
    },
    github: {
      title: tr('skill_market_github_title'),
      placeholder: 'https://github.com/owner/repo',
      hint: tr('skill_market_github_hint'),
    },
    clawhub: {
      title: tr('skill_market_clawhub_title'),
      placeholder: tr('skill_market_clawhub_ph'),
      hint: tr('skill_market_clawhub_hint'),
    },
  })[source];

const addOptions = (): Choice<AddKey>[] => [
  {key: 'create', label: tr('skill_create'), desc: tr('skill_create_desc'), icon: faPenToSquare},
  {key: 'hub', label: 'Cow Skill Hub', desc: tr('skill_hub_desc'), icon: faStore},
  {key: 'github', label: 'GitHub', desc: tr('skill_github_desc'), icon: faCodeBranch},
  {key: 'clawhub', label: 'ClawHub', desc: tr('skill_clawhub_desc'), icon: faPaw},
  {key: 'upload', label: tr('skill_upload'), desc: tr('skill_upload_desc'), icon: faFileArrowUp},
  {key: 'browse', label: tr('skill_browse_hub'), desc: tr('skill_browse_hub_desc'), icon: faCompass},
];

export function skillErrorText(e: unknown): string {
  const message = describeConnectError(e);
  return skillRefusal(message) ?? message;
}

export function SkillsScreen({navigation}: Props) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const local = useLocalServer();
  const [tab, setTab] = useState<Tab>('skills');
  const [skills, setSkills] = useState<Skill[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tools, setTools] = useState<ToolInfo[] | null>(null);
  const [toolsError, setToolsError] = useState<string | null>(null);
  const [mcpError, setMcpError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [openTool, setOpenTool] = useState<string | null>(null);
  const [sheet, setSheet] = useState<SheetState | null>(null);
  const [preview, setPreview] = useState<SkillPreview | null>(null);
  const servers = useMcpStore(s => s.servers);
  const loadMcp = useMcpStore(s => s.load);
  const pollDeadline = useRef(0);

  const loadSkills = useCallback(async () => {
    try {
      setSkills((await getSkills()).skills);
      setError(null);
    } catch (e) {
      setError(describeConnectError(e));
    }
  }, []);

  const loadTools = useCallback(async () => {
    try {
      setTools((await getTools()).tools);
      setToolsError(null);
    } catch (e) {
      setToolsError(describeConnectError(e));
    }
  }, []);

  // A broken mcp.json must not take the skills and tools down with it.
  const reloadMcp = useCallback(async () => {
    try {
      await loadMcp();
      setMcpError(null);
    } catch (e) {
      setMcpError(describeConnectError(e));
    }
  }, [loadMcp]);

  useFocusEffect(
    useCallback(() => {
      loadSkills();
      reloadMcp();
    }, [loadSkills, reloadMcp]),
  );

  useEffect(() => {
    loadTools();
  }, [loadTools]);

  // Saved servers connect in the background; keep refreshing while any is still on its way.
  useEffect(() => {
    if (!servers?.some(s => s.status === 'pending')) {
      pollDeadline.current = 0;
      return;
    }
    if (!pollDeadline.current) {
      pollDeadline.current = Date.now() + MCP_POLL_MAX_MS;
    }
    if (Date.now() > pollDeadline.current) {
      return;
    }
    const timer = setTimeout(() => loadMcp().catch(() => undefined), MCP_POLL_MS);
    return () => clearTimeout(timer);
  }, [servers, loadMcp]);

  const refresh = async () => {
    setRefreshing(true);
    await (tab === 'skills' ? loadSkills() : tab === 'tools' ? loadTools() : reloadMcp());
    setRefreshing(false);
  };

  const next = (s: SheetState | null) => {
    setSheet(null);
    if (s) {
      setTimeout(() => setSheet(s), SHEET_DISMISS_MS);
    }
  };

  const sorted = useMemo(() => (skills ? [...skills].sort(compareSkills) : []), [skills]);
  const enabledCount = sorted.filter(s => s.enabled).length;

  const toggle = async (skill: Skill, enabled: boolean) => {
    const flip = (on: boolean) => setSkills(prev => prev?.map(s => (s.name === skill.name ? {...s, enabled: on} : s)) ?? prev);
    flip(enabled);
    try {
      await setSkillEnabled(skill.name, enabled);
    } catch (e) {
      flip(!enabled);
      showToast(trf(enabled ? 'skill_enable_failed' : 'skill_disable_failed', {error: skillErrorText(e)}));
    }
  };

  const fetchPreview = async (source: SkillMarketSource, value: string) => {
    let res: SkillPreview;
    try {
      res = await previewSkill(source, value);
    } catch (e) {
      throw new Error(skillErrorText(e));
    }
    setTimeout(() => setPreview(res), SHEET_DISMISS_MS);
  };

  const runUpload = async () => {
    setSheet(null);
    let files;
    try {
      files = await pickDocuments();
    } catch (e) {
      showToast(e instanceof Error ? e.message : String(e));
      return;
    }
    if (!files.length) {
      return;
    }
    if (files.reduce((n, f) => n + (f.size ?? 0), 0) > UPLOAD_MAX_BYTES) {
      showToast(tr('skill_err_too_large'));
      return;
    }
    showToast(tr('skill_uploading'));
    try {
      setPreview(await uploadSkill(files));
    } catch (e) {
      showToast(trf('skill_upload_failed', {error: skillErrorText(e)}));
    }
  };

  const install = async (names: string[]) => {
    if (!preview) {
      return;
    }
    let installed: string[];
    try {
      installed = (await confirmSkillInstall(preview.token, names)).installed ?? [];
    } catch (e) {
      throw new Error(skillErrorText(e));
    }
    setPreview(null);
    showToast(
      installed.length ? trf('skill_installed_names', {names: installed.join(tr('skill_list_sep'))}) : tr('skill_installed'),
    );
    await loadSkills();
  };

  const closePreview = () => {
    if (preview) {
      discardSkillPreview(preview.token);
    }
    setPreview(null);
  };

  const remove = async (skill: Skill) => {
    try {
      await deleteSkill(skill.name);
      setSheet(null);
      showToast(tr('common_deleted'));
      await loadSkills();
    } catch (e) {
      setSheet(null);
      showToast(trf('common_delete_failed', {error: skillErrorText(e)}));
    }
  };

  const onAdd = (key: AddKey) => {
    if (key === 'create') {
      setSheet(null);
      navigation.navigate('SkillCreate');
    } else if (key === 'upload') {
      runUpload();
    } else if (key === 'browse') {
      setSheet(null);
      openWebPage(SKILL_HUB_URL);
    } else {
      next({kind: 'market', source: key});
    }
  };

  const openSkill = (skill: Skill) => navigation.navigate('SkillDetail', {name: skill.name});

  const renderSkill = ({item}: {item: Skill}) => {
    const tag = item.ships_with_install
      ? tr('skill_src_builtin')
      : item.source && item.source !== 'custom'
        ? SKILL_SOURCE_LABEL[item.source] ?? item.source
        : null;
    const desc = skillDescription(item);
    return (
      <Pressable
        accessibilityRole="button"
        accessibilityHint={tr('skill_long_press_hint')}
        onPress={() => openSkill(item)}
        onLongPress={() => setSheet({kind: 'skill', skill: item})}
        style={({pressed}) => [styles.card, pressed && styles.cardPressed]}>
        <SkillIcon skill={item} />
        <View style={styles.cardText}>
          <View style={styles.cardHead}>
            <Text style={[styles.cardName, !item.enabled && styles.dim]} numberOfLines={1}>
              {skillName(item)}
            </Text>
            {!!tag && <Text style={styles.tag}>{tag}</Text>}
            {!!item.version && <Text style={styles.version}>v{item.version}</Text>}
          </View>
          <Text style={[styles.cardDesc, !desc && styles.dim]} numberOfLines={2}>
            {desc || tr('skill_no_desc')}
          </Text>
        </View>
        <Toggle value={item.enabled} onValueChange={v => toggle(item, v)} label={trf('skill_enable_label', {name: skillName(item)})} />
      </Pressable>
    );
  };

  const mcpList = servers ?? [];
  const refreshControl = <RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={t.t3} colors={[t.green]} />;

  const skillSheet = sheet?.kind === 'skill' ? sheet.skill : null;
  const skillOptions: Choice<'open' | 'edit' | 'delete'>[] = skillSheet
    ? [
        {key: 'open', label: tr('skill_opt_open'), icon: faFileLines},
        ...(skillSheet.ships_with_install ? [] : [{key: 'edit' as const, label: tr('skill_edit_md'), icon: faPenToSquare}]),
        ...(skillSheet.deletable !== false && !skillSheet.ships_with_install
          ? [{key: 'delete' as const, label: tr('common_delete'), icon: faTrashCan}]
          : []),
      ]
    : [];

  return (
    <View style={styles.root}>
      <PageHeader
        title={tr('menu_skills')}
        onBack={navigation.goBack}
        right={
          tab === 'tools' ? undefined : (
            <IconButton
              icon={faPlus}
              label={tab === 'skills' ? tr('skill_add') : tr('mcp_add')}
              filled
              size={13}
              color={t.t1}
              onPress={() => (tab === 'skills' ? setSheet({kind: 'add'}) : navigation.navigate('McpEdit'))}
            />
          )
        }
      />
      <Segmented
        value={tab}
        onChange={setTab}
        options={[
          {key: 'skills', label: tr('skill_title'), count: skills?.length || undefined},
          {key: 'tools', label: tr('skill_tab_tools'), count: tools?.length || undefined},
          {key: 'mcp', label: tr('skill_tab_mcp'), count: servers?.length || undefined},
        ]}
      />

      <SwipeTabs tabs={TABS} value={tab} onChange={setTab}>
        {tab === 'skills' ? (
          <FlatList
            data={sorted}
            keyExtractor={s => s.name}
            renderItem={renderSkill}
            contentContainerStyle={[styles.list, {paddingBottom: insets.bottom + 24}]}
            ListHeaderComponent={
              sorted.length ? (
                <>
                  {local && <Notice style={styles.localNote}>{tr('skill_local_note')}</Notice>}
                  <Text style={styles.summary}>{trf('skill_summary', {enabled: enabledCount, total: sorted.length})}</Text>
                </>
              ) : null
            }
            ListFooterComponent={
              sorted.length ? (
                <Pressable
                  accessibilityRole="link"
                  onPress={() => openWebPage(SKILL_HUB_URL)}
                  style={({pressed}) => [styles.hubLink, pressed && styles.cardPressed]}>
                  <Icon icon={faCompass} size={12} color={t.t3} />
                  <Text style={styles.hubText}>{tr('skill_hub_link')}</Text>
                  <Icon icon={faArrowUpRightFromSquare} size={10} color={t.t4} />
                </Pressable>
              ) : null
            }
            ListEmptyComponent={
              <EmptyState
                loading={!skills && !error}
                title={error ? tr('common_load_failed') : tr('skill_empty')}
                hint={error ?? tr('skill_empty_hint')}
              />
            }
            refreshControl={refreshControl}
          />
        ) : tab === 'tools' ? (
          <ScrollView contentContainerStyle={[styles.list, {paddingBottom: insets.bottom + 32}]} refreshControl={refreshControl}>
            {!tools ? (
              <Text style={styles.sectionNote}>
                {toolsError ? trf('common_load_failed_detail', {error: toolsError}) : tr('common_loading')}
              </Text>
            ) : !tools.length ? (
              <Text style={styles.sectionNote}>{tr('skill_no_tools')}</Text>
            ) : (
              toolGroups(tools).map(({key, label, items}, g) => (
                <View key={key}>
                  {label && <GroupLabel style={g ? styles.toolGroupLabel : styles.toolGroupFirst}>{label}</GroupLabel>}
                  <View style={[styles.group, !label && styles.groupTop]}>
                    {items.map((tool, i) => {
                      const open = openTool === tool.name;
                      const phone = PHONE_TOOL[tool.name];
                      return (
                        <Pressable
                          key={tool.name}
                          accessibilityRole="button"
                          accessibilityState={{expanded: open}}
                          onPress={() => setOpenTool(open ? null : tool.name)}
                          style={({pressed}) => [styles.groupRow, i > 0 && styles.groupDivider, pressed && styles.rowPressed]}>
                          <ToolIcon name={tool.name} />
                          <View style={styles.rowText}>
                            <Text style={phone ? styles.toolTitle : styles.monoName} numberOfLines={1}>
                              {phone ? tr(phone[0]) : tool.name}
                            </Text>
                            <Text style={styles.rowDesc} numberOfLines={open ? undefined : 2}>
                              {phone ? tr(phone[1]) : tool.description || tr('skill_no_desc')}
                            </Text>
                            {!!tool.platforms?.length && (
                              <Text style={styles.platforms}>
                                {trf('phone_platforms', {platforms: tool.platforms.map(platformName).join(' · ')})}
                              </Text>
                            )}
                          </View>
                        </Pressable>
                      );
                    })}
                  </View>
                </View>
              ))
            )}
          </ScrollView>
        ) : (
          <ScrollView contentContainerStyle={[styles.list, {paddingBottom: insets.bottom + 32}]} refreshControl={refreshControl}>
            {local && <Notice style={styles.localNote}>{tr('mcp_local_note')}</Notice>}
            {!!mcpError && (
              <Text style={[styles.sectionNote, styles.errorText]}>{trf('common_load_failed_detail', {error: mcpError})}</Text>
            )}
            {!servers ? (
              !mcpError && <Text style={styles.sectionNote}>{tr('common_loading')}</Text>
            ) : !mcpList.length ? (
              <Pressable
                onPress={() => navigation.navigate('McpEdit')}
                style={({pressed}) => [styles.emptyBox, styles.groupTop, pressed && styles.rowPressed]}>
                <McpIcon />
                <Text style={styles.emptyTitle}>{tr('mcp_empty')}</Text>
                <Text style={styles.emptyHint}>{tr('mcp_empty_hint_tools')}</Text>
              </Pressable>
            ) : (
              <View style={[styles.group, styles.groupTop]}>
                {mcpList.map((s, i) => {
                  const status = MCP_STATUS[s.status ?? 'idle'] ?? MCP_STATUS.idle;
                  const transport = mcpTransport(s);
                  return (
                    <Pressable
                      key={s.name}
                      accessibilityRole="button"
                      accessibilityLabel={trf('mcp_row_a11y', {name: s.name, status: status.label})}
                      onPress={() => navigation.navigate('McpDetail', {name: s.name})}
                      style={({pressed}) => [styles.groupRow, styles.center, i > 0 && styles.groupDivider, pressed && styles.rowPressed]}>
                      <McpIcon off={s.status === 'disabled'} />
                      <View style={styles.rowText}>
                        <View style={styles.cardHead}>
                          <Text style={[styles.monoName, styles.shrink, s.status === 'disabled' && styles.dim]} numberOfLines={1}>
                            {s.name}
                          </Text>
                          <Text style={styles.tag}>{transport === 'stdio' ? 'stdio' : MCP_TRANSPORT_LABEL[transport] ?? transport}</Text>
                        </View>
                        <Text style={styles.target} numberOfLines={1}>
                          {mcpTarget(s) || '-'}
                        </Text>
                      </View>
                      <StatusTag label={status.label} on={status.on} />
                      <Icon icon={faChevronRight} size={10} color={t.t4} />
                    </Pressable>
                  );
                })}
              </View>
            )}
            <Text style={styles.footnote}>{tr('mcp_tools_footnote')}</Text>
          </ScrollView>
        )}
      </SwipeTabs>

      <ChoiceSheet
        visible={sheet?.kind === 'add'}
        title={tr('skill_add')}
        options={addOptions()}
        onSelect={onAdd}
        onClose={() => setSheet(null)}
      />
      <FieldSheet
        visible={sheet?.kind === 'market'}
        title={sheet?.kind === 'market' ? market(sheet.source).title : ''}
        placeholder={sheet?.kind === 'market' ? market(sheet.source).placeholder : ''}
        hint={sheet?.kind === 'market' ? market(sheet.source).hint : undefined}
        mono
        allowEmpty={false}
        submitLabel={tr('skill_fetch')}
        onSubmit={v => (sheet?.kind === 'market' ? fetchPreview(sheet.source, v) : undefined)}
        onClose={() => setSheet(null)}
      />
      <ChoiceSheet
        visible={sheet?.kind === 'skill'}
        title={skillSheet ? skillName(skillSheet) : tr('skill_title')}
        options={skillOptions}
        onSelect={key => {
          if (!skillSheet) {
            return;
          }
          if (key === 'open') {
            setSheet(null);
            openSkill(skillSheet);
          } else if (key === 'edit') {
            setSheet(null);
            navigation.navigate('SkillFile', {name: skillSheet.name, title: 'SKILL.md', edit: true});
          } else {
            next({kind: 'delete', skill: skillSheet});
          }
        }}
        onClose={() => setSheet(null)}
      />
      <ConfirmSheet
        visible={sheet?.kind === 'delete'}
        title={tr('skill_delete_title')}
        message={sheet?.kind === 'delete' ? trf('skill_delete_message', {name: skillName(sheet.skill)}) : ''}
        confirmLabel={tr('common_delete')}
        danger
        onConfirm={() => (sheet?.kind === 'delete' ? remove(sheet.skill) : undefined)}
        onClose={() => setSheet(null)}
      />
      <SkillInstallSheet preview={preview} onInstall={install} onClose={closePreview} />
      <ToastHost bottom={insets.bottom + 28} />
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  localNote: {marginTop: 4, marginBottom: 8},
  list: {paddingTop: 4, flexGrow: 1},
  summary: {fontSize: 12, color: t.t4, paddingHorizontal: 18, paddingTop: 4, paddingBottom: 10, fontVariant: ['tabular-nums']},
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    marginHorizontal: 14,
    marginBottom: 8,
    paddingHorizontal: 14,
    paddingVertical: 13,
    borderRadius: radius.md,
    backgroundColor: t.bg1,
    borderWidth: 1,
    borderColor: t.line1,
  },
  cardPressed: {opacity: 0.7},
  cardText: {flex: 1, minWidth: 0},
  cardHead: {flexDirection: 'row', alignItems: 'center', gap: 6},
  cardName: {flexShrink: 1, fontSize: 15, fontWeight: '600', color: t.t1, letterSpacing: -0.1},
  cardDesc: {fontSize: 12.5, lineHeight: 18, color: t.t3, marginTop: 4},
  dim: {color: t.t3},
  tag: {
    fontSize: 10.5,
    color: t.t3,
    paddingHorizontal: 5,
    paddingVertical: 1,
    borderRadius: 5,
    overflow: 'hidden',
    backgroundColor: t.bg2,
  },
  version: {fontSize: 10.5, color: t.t4, fontVariant: ['tabular-nums']},
  hubLink: {flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 7, paddingVertical: 16},
  hubText: {fontSize: 13, color: t.t3},
  sectionNote: {fontSize: 13, color: t.t3, paddingHorizontal: 18, paddingVertical: 6},
  errorText: {color: t.danger},
  groupTop: {marginTop: 8},
  group: {
    marginHorizontal: 14,
    borderRadius: radius.md,
    backgroundColor: t.bg1,
    borderWidth: 1,
    borderColor: t.line1,
    overflow: 'hidden',
  },
  groupRow: {flexDirection: 'row', alignItems: 'flex-start', gap: 12, paddingHorizontal: 14, paddingVertical: 12},
  center: {alignItems: 'center'},
  groupDivider: {borderTopWidth: 1, borderTopColor: t.line1},
  rowPressed: {backgroundColor: t.bg2},
  rowText: {flex: 1, minWidth: 0},
  monoName: {fontFamily: MONO, fontSize: 13.5, fontWeight: '500', color: t.t1},
  toolTitle: {fontSize: 14.5, fontWeight: '500', color: t.t1},
  toolGroupLabel: {marginTop: 22},
  toolGroupFirst: {marginTop: 10},
  platforms: {fontSize: 11.5, color: t.t4, marginTop: 5},
  shrink: {flexShrink: 1},
  rowDesc: {fontSize: 12.5, lineHeight: 18, color: t.t3, marginTop: 3},
  target: {fontFamily: MONO, fontSize: 11.5, color: t.t3, marginTop: 4},
  emptyBox: {
    marginHorizontal: 14,
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 24,
    paddingVertical: 22,
    borderRadius: radius.md,
    borderWidth: 1,
    borderStyle: 'dashed',
    borderColor: t.line2,
  },
  emptyTitle: {fontSize: 14, fontWeight: '500', color: t.t2, marginTop: 4},
  emptyHint: {fontSize: 12, lineHeight: 18, color: t.t3, textAlign: 'center'},
  footnote: {fontSize: 12, lineHeight: 18, color: t.t4, paddingHorizontal: 18, paddingTop: 12},
}));
