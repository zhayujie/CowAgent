import {
  faArrowUpRightFromSquare,
  faChevronDown,
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
import React, {useCallback, useEffect, useMemo, useRef, useState, type ReactNode} from 'react';
import {FlatList, Linking, Pressable, RefreshControl, ScrollView, Text, View} from 'react-native';
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
import {AgentSheet} from '../components/AgentSheet';
import {Icon} from '../components/Icon';
import {ChoiceSheet, ConfirmSheet, FieldSheet, MONO, StatusTag, Toggle, type Choice} from '../components/settings';
import {SHEET_DISMISS_MS} from '../components/Sheet';
import {McpIcon, SkillIcon, ToolIcon} from '../components/SkillIcon';
import {SkillInstallSheet} from '../components/SkillInstallSheet';
import {showToast, ToastHost} from '../components/Toast';
import {SwipeTabs} from '../components/SwipeTabs';
import {EmptyState, IconButton, PageHeader, Segmented} from '../components/ui';
import {pickDocuments} from '../media/picker';
import type {RootStackParamList} from '../navigation/types';
import type {Skill, SkillMarketSource, SkillPreview, ToolInfo} from '../protocol/resources';
import {agentParam, useViewedAgent} from '../store/agentStore';
import {MCP_STATUS, MCP_TRANSPORT_LABEL, mcpTarget, mcpTransport, useMcpStore} from '../store/mcpStore';
import {describeConnectError} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {compareSkills, SKILL_SOURCE_LABEL, skillDescription, skillName, skillRefusal} from '../utils/skills';

type Props = StackScreenProps<RootStackParamList, 'Skills'>;
type Tab = 'skills' | 'tools';
const TABS: readonly Tab[] = ['skills', 'tools'];
type SheetState =
  | {kind: 'add'}
  | {kind: 'market'; source: SkillMarketSource}
  | {kind: 'skill'; skill: Skill}
  | {kind: 'delete'; skill: Skill}
  | {kind: 'agent'};
type AddKey = 'create' | SkillMarketSource | 'upload' | 'browse';

export const SKILL_HUB_URL = 'https://skills.cowagent.ai/';
const TOOLS_COLLAPSED = 6;
const MCP_POLL_MS = 1500;
const MCP_POLL_MAX_MS = 120_000;
const UPLOAD_MAX_BYTES = 50 * 1024 * 1024;

const MARKET: Record<SkillMarketSource, {title: string; placeholder: string; hint: string}> = {
  hub: {
    title: '从 Cow Skill Hub 安装',
    placeholder: '技能名，如 weather',
    hint: '在 skills.cowagent.ai 找到技能后填它的名称，安装前会先列出内容供确认',
  },
  github: {
    title: '从 GitHub 安装',
    placeholder: 'https://github.com/owner/repo',
    hint: '仓库、子目录链接或 owner/repo；仓库里有多个技能时可以挑着装',
  },
  clawhub: {
    title: '从 ClawHub 安装',
    placeholder: '技能名，如 owner/skill',
    hint: '填 ClawHub 上的技能名，安装前会先列出内容供确认',
  },
};

const ADD_OPTIONS: Choice<AddKey>[] = [
  {key: 'create', label: '新建技能', desc: '填写名称、描述和说明，直接写一个', icon: faPenToSquare},
  {key: 'hub', label: 'Cow Skill Hub', desc: '按名称安装技能广场里的技能', icon: faStore},
  {key: 'github', label: 'GitHub', desc: '仓库或子目录链接，也可以写 owner/repo', icon: faCodeBranch},
  {key: 'clawhub', label: 'ClawHub', desc: '按名称安装 ClawHub 上的技能', icon: faPaw},
  {key: 'upload', label: '上传文件', desc: '从手机选择 .zip 压缩包或 SKILL.md', icon: faFileArrowUp},
  {key: 'browse', label: '浏览技能广场', desc: '在浏览器里打开 skills.cowagent.ai', icon: faCompass},
];

export function skillErrorText(e: unknown): string {
  const message = describeConnectError(e);
  return skillRefusal(message) ?? message;
}

export function SkillsScreen({navigation}: Props) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const viewed = useViewedAgent('skills');
  const scope = agentParam(viewed.agentId);
  const [tab, setTab] = useState<Tab>('skills');
  const [skills, setSkills] = useState<Skill[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tools, setTools] = useState<ToolInfo[] | null>(null);
  const [toolsError, setToolsError] = useState<string | null>(null);
  const [mcpError, setMcpError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [toolsOpen, setToolsOpen] = useState(false);
  const [openTool, setOpenTool] = useState<string | null>(null);
  const [sheet, setSheet] = useState<SheetState | null>(null);
  const [preview, setPreview] = useState<SkillPreview | null>(null);
  const storeServers = useMcpStore(s => s.servers);
  const storeScope = useMcpStore(s => s.agentId);
  const loadMcp = useMcpStore(s => s.load);
  const servers = storeScope === scope ? storeServers : null;
  const generation = useRef(0);
  const pollDeadline = useRef(0);

  const loadSkills = useCallback(async () => {
    const gen = generation.current;
    try {
      const res = await getSkills(scope);
      if (gen === generation.current) {
        setSkills(res.skills);
        setError(null);
      }
    } catch (e) {
      if (gen === generation.current) {
        setError(describeConnectError(e));
      }
    }
  }, [scope]);

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
      await loadMcp(scope);
      setMcpError(null);
    } catch (e) {
      setMcpError(describeConnectError(e));
    }
  }, [loadMcp, scope]);

  useFocusEffect(
    useCallback(() => {
      if (viewed.ready) {
        loadSkills();
        reloadMcp();
      }
    }, [viewed.ready, loadSkills, reloadMcp]),
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
    const timer = setTimeout(() => loadMcp(scope).catch(() => undefined), MCP_POLL_MS);
    return () => clearTimeout(timer);
  }, [servers, loadMcp, scope]);

  const refresh = async () => {
    setRefreshing(true);
    await Promise.all(tab === 'skills' ? [loadSkills()] : [loadTools(), reloadMcp()]);
    setRefreshing(false);
  };

  const next = (s: SheetState | null) => {
    setSheet(null);
    if (s) {
      setTimeout(() => setSheet(s), SHEET_DISMISS_MS);
    }
  };

  const switchAgent = (id: string) => {
    setSheet(null);
    generation.current += 1;
    setSkills(null);
    setError(null);
    viewed.select(id);
  };

  const sorted = useMemo(() => (skills ? [...skills].sort(compareSkills) : []), [skills]);
  const enabledCount = sorted.filter(s => s.enabled).length;

  const toggle = async (skill: Skill, enabled: boolean) => {
    const flip = (on: boolean) => setSkills(prev => prev?.map(s => (s.name === skill.name ? {...s, enabled: on} : s)) ?? prev);
    flip(enabled);
    try {
      await setSkillEnabled(skill.name, enabled, scope);
    } catch (e) {
      flip(!enabled);
      showToast(`${enabled ? '启用' : '停用'}失败：${skillErrorText(e)}`);
    }
  };

  const fetchPreview = async (source: SkillMarketSource, value: string) => {
    let res: SkillPreview;
    try {
      res = await previewSkill(source, value, scope);
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
      showToast('文件太大，上限 50 MB');
      return;
    }
    showToast('正在上传…');
    try {
      setPreview(await uploadSkill(files, scope));
    } catch (e) {
      showToast(`上传失败：${skillErrorText(e)}`);
    }
  };

  const install = async (names: string[]) => {
    if (!preview) {
      return;
    }
    let installed: string[];
    try {
      installed = (await confirmSkillInstall(preview.token, names, scope)).installed ?? [];
    } catch (e) {
      throw new Error(skillErrorText(e));
    }
    setPreview(null);
    showToast(installed.length ? `已安装 ${installed.join('、')}` : '已安装');
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
      await deleteSkill(skill.name, scope);
      setSheet(null);
      showToast('已删除');
      await loadSkills();
    } catch (e) {
      setSheet(null);
      showToast(`删除失败：${skillErrorText(e)}`);
    }
  };

  const onAdd = (key: AddKey) => {
    if (key === 'create') {
      setSheet(null);
      navigation.navigate('SkillCreate', {agentId: scope});
    } else if (key === 'upload') {
      runUpload();
    } else if (key === 'browse') {
      setSheet(null);
      Linking.openURL(SKILL_HUB_URL).catch(() => showToast('无法打开浏览器'));
    } else {
      next({kind: 'market', source: key});
    }
  };

  const openSkill = (skill: Skill) => navigation.navigate('SkillDetail', {name: skill.name, agentId: scope});

  const renderSkill = ({item}: {item: Skill}) => {
    const tag = item.ships_with_install ? '内置' : item.source && item.source !== 'custom' ? SKILL_SOURCE_LABEL[item.source] ?? item.source : null;
    const desc = skillDescription(item);
    return (
      <Pressable
        accessibilityRole="button"
        accessibilityHint="长按查看更多操作"
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
            {desc || '没有描述'}
          </Text>
        </View>
        <Toggle value={item.enabled} onValueChange={v => toggle(item, v)} label={`启用 ${skillName(item)}`} />
      </Pressable>
    );
  };

  const mcpList = servers ?? [];
  const visibleTools = toolsOpen ? tools ?? [] : (tools ?? []).slice(0, TOOLS_COLLAPSED);
  const toolCount = (tools?.length ?? 0) + mcpList.length;
  const refreshControl = <RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={t.t3} colors={[t.green]} />;

  const skillSheet = sheet?.kind === 'skill' ? sheet.skill : null;
  const skillOptions: Choice<'open' | 'edit' | 'delete'>[] = skillSheet
    ? [
        {key: 'open', label: '查看详情和文件', icon: faFileLines},
        ...(skillSheet.ships_with_install ? [] : [{key: 'edit' as const, label: '编辑 SKILL.md', icon: faPenToSquare}]),
        ...(skillSheet.deletable !== false && !skillSheet.ships_with_install
          ? [{key: 'delete' as const, label: '删除', icon: faTrashCan}]
          : []),
      ]
    : [];

  return (
    <View style={styles.root}>
      <PageHeader
        title="技能"
        subtitle={viewed.multi ? viewed.agent?.name ?? viewed.agentId ?? undefined : undefined}
        onTitlePress={viewed.multi ? () => setSheet({kind: 'agent'}) : undefined}
        onBack={navigation.goBack}
        right={
          <IconButton
            icon={faPlus}
            label={tab === 'skills' ? '添加技能' : '添加 MCP 服务'}
            filled
            size={13}
            color={t.t1}
            onPress={() => (tab === 'skills' ? setSheet({kind: 'add'}) : navigation.navigate('McpEdit'))}
          />
        }
      />
      <Segmented
        value={tab}
        onChange={setTab}
        options={[
          {key: 'skills', label: '技能', count: skills?.length || undefined},
          {key: 'tools', label: '工具', count: toolCount || undefined},
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
                <Text style={styles.summary}>
                  已启用 {enabledCount} / {sorted.length}，停用的技能 Agent 不会使用
                </Text>
              ) : null
            }
            ListFooterComponent={
              sorted.length ? (
                <Pressable
                  accessibilityRole="link"
                  onPress={() => Linking.openURL(SKILL_HUB_URL).catch(() => undefined)}
                  style={({pressed}) => [styles.hubLink, pressed && styles.cardPressed]}>
                  <Icon icon={faCompass} size={12} color={t.t3} />
                  <Text style={styles.hubText}>去 Cow Skill Hub 发现更多技能</Text>
                  <Icon icon={faArrowUpRightFromSquare} size={10} color={t.t4} />
                </Pressable>
              ) : null
            }
            ListEmptyComponent={
              <EmptyState
                loading={!skills && !error}
                title={error ? '加载失败' : '还没有技能'}
                hint={error ?? '点右上角 + 新建一个，或者从 Skill Hub、GitHub 安装'}
              />
            }
            refreshControl={refreshControl}
          />
        ) : (
          <ScrollView contentContainerStyle={[styles.list, {paddingBottom: insets.bottom + 32}]} refreshControl={refreshControl}>
            <SectionHead
              title="内置工具"
              count={tools?.length}
              action={
                (tools?.length ?? 0) > TOOLS_COLLAPSED ? (
                  <Pressable hitSlop={8} onPress={() => setToolsOpen(v => !v)} style={styles.headLink}>
                    <Text style={styles.headLinkText}>{toolsOpen ? '收起' : `全部 ${tools?.length}`}</Text>
                    <View style={toolsOpen && styles.flipped}>
                      <Icon icon={faChevronDown} size={9} color={t.t3} />
                    </View>
                  </Pressable>
                ) : null
              }
            />
            {!tools ? (
              <Text style={styles.sectionNote}>{toolsError ? `加载失败：${toolsError}` : '加载中…'}</Text>
            ) : !tools.length ? (
              <Text style={styles.sectionNote}>没有可用的内置工具</Text>
            ) : (
              <View style={styles.group}>
                {visibleTools.map((tool, i) => {
                  const open = openTool === tool.name;
                  return (
                    <Pressable
                      key={tool.name}
                      accessibilityRole="button"
                      accessibilityState={{expanded: open}}
                      onPress={() => setOpenTool(open ? null : tool.name)}
                      style={({pressed}) => [styles.groupRow, i > 0 && styles.groupDivider, pressed && styles.rowPressed]}>
                      <ToolIcon name={tool.name} />
                      <View style={styles.rowText}>
                        <Text style={styles.monoName} numberOfLines={1}>
                          {tool.name}
                        </Text>
                        <Text style={styles.rowDesc} numberOfLines={open ? undefined : 2}>
                          {tool.description || '没有描述'}
                        </Text>
                      </View>
                    </Pressable>
                  );
                })}
              </View>
            )}

            <SectionHead
              title="MCP 服务"
              count={servers ? mcpList.length : undefined}
              action={
                <Pressable hitSlop={8} onPress={() => navigation.navigate('McpEdit')} style={styles.addButton}>
                  <Icon icon={faPlus} size={10} color={t.accent} />
                  <Text style={styles.addText}>添加</Text>
                </Pressable>
              }
            />
            {!!mcpError && <Text style={[styles.sectionNote, styles.errorText]}>加载失败：{mcpError}</Text>}
            {!servers ? (
              !mcpError && <Text style={styles.sectionNote}>加载中…</Text>
            ) : !mcpList.length ? (
              <Pressable onPress={() => navigation.navigate('McpEdit')} style={({pressed}) => [styles.emptyBox, pressed && styles.rowPressed]}>
                <McpIcon />
                <Text style={styles.emptyTitle}>还没有 MCP 服务</Text>
                <Text style={styles.emptyHint}>接入数据库、内网文档、浏览器等外部系统，Agent 就能调用它们提供的工具</Text>
              </Pressable>
            ) : (
              <View style={styles.group}>
                {mcpList.map((s, i) => {
                  const status = MCP_STATUS[s.status ?? 'idle'] ?? MCP_STATUS.idle;
                  const transport = mcpTransport(s);
                  return (
                    <Pressable
                      key={s.name}
                      accessibilityRole="button"
                      accessibilityLabel={`${s.name}，${status.label}`}
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
            <Text style={styles.footnote}>
              MCP 服务保存后从下一条消息开始生效，不需要重启。每个服务单独连接，一个连不上不影响其他服务和内置工具。
            </Text>
          </ScrollView>
        )}
      </SwipeTabs>

      <ChoiceSheet visible={sheet?.kind === 'add'} title="添加技能" options={ADD_OPTIONS} onSelect={onAdd} onClose={() => setSheet(null)} />
      <FieldSheet
        visible={sheet?.kind === 'market'}
        title={sheet?.kind === 'market' ? MARKET[sheet.source].title : ''}
        placeholder={sheet?.kind === 'market' ? MARKET[sheet.source].placeholder : ''}
        hint={sheet?.kind === 'market' ? MARKET[sheet.source].hint : undefined}
        mono
        allowEmpty={false}
        submitLabel="获取"
        onSubmit={v => (sheet?.kind === 'market' ? fetchPreview(sheet.source, v) : undefined)}
        onClose={() => setSheet(null)}
      />
      <ChoiceSheet
        visible={sheet?.kind === 'skill'}
        title={skillSheet ? skillName(skillSheet) : '技能'}
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
            navigation.navigate('SkillFile', {name: skillSheet.name, title: 'SKILL.md', agentId: scope, edit: true});
          } else {
            next({kind: 'delete', skill: skillSheet});
          }
        }}
        onClose={() => setSheet(null)}
      />
      <ConfirmSheet
        visible={sheet?.kind === 'delete'}
        title="删除技能"
        message={sheet?.kind === 'delete' ? `「${skillName(sheet.skill)}」和它目录里的所有文件都会被删除，Agent 也不能再使用它。` : ''}
        confirmLabel="删除"
        danger
        onConfirm={() => (sheet?.kind === 'delete' ? remove(sheet.skill) : undefined)}
        onClose={() => setSheet(null)}
      />
      <SkillInstallSheet preview={preview} onInstall={install} onClose={closePreview} />
      <AgentSheet
        visible={sheet?.kind === 'agent'}
        title="查看哪个 Agent 的技能"
        selectedId={viewed.agentId}
        onSelect={switchAgent}
        onClose={() => setSheet(null)}
      />
      <ToastHost bottom={insets.bottom + 28} />
    </View>
  );
}

function SectionHead({title, count, action}: {title: string; count?: number; action?: ReactNode}) {
  const styles = useStyles();
  return (
    <View style={styles.sectionHead}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {!!count && <Text style={styles.sectionCount}>{count}</Text>}
      <View style={styles.flex} />
      {action}
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  flex: {flex: 1},
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
  sectionHead: {flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 18, marginTop: 14, marginBottom: 10, minHeight: 24},
  sectionTitle: {fontSize: 12, fontWeight: '600', letterSpacing: 0.6, color: t.t3},
  sectionCount: {
    minWidth: 20,
    paddingHorizontal: 6,
    paddingVertical: 1,
    borderRadius: 999,
    overflow: 'hidden',
    textAlign: 'center',
    fontSize: 11,
    color: t.t3,
    backgroundColor: t.bg2,
    fontVariant: ['tabular-nums'],
  },
  sectionNote: {fontSize: 13, color: t.t3, paddingHorizontal: 18, paddingVertical: 6},
  errorText: {color: t.danger},
  headLink: {flexDirection: 'row', alignItems: 'center', gap: 5, paddingVertical: 2},
  headLinkText: {fontSize: 12, color: t.t3},
  flipped: {transform: [{rotate: '180deg'}]},
  addButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: radius.sm,
    backgroundColor: t.accentSoft,
  },
  addText: {fontSize: 12, fontWeight: '600', color: t.accent},
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
