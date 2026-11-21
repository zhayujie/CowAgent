import {faPenToSquare, faTrashCan} from '@fortawesome/free-regular-svg-icons';
import {faPlus, faThumbtack} from '@fortawesome/free-solid-svg-icons';
import React, {useCallback, useEffect, useState} from 'react';
import {ActivityIndicator, Pressable, ScrollView, Text, View} from 'react-native';
import {clearContext, compactContext, getContextUsage} from '../api/cowApi';
import {tr, trf} from '../i18n';
import type {AgentBadge, ContextUsage} from '../protocol/resources';
import {agentParam, useAgentStore} from '../store/agentStore';
import {useSessionSettingsStore} from '../store/sessionSettingsStore';
import {describeConnectError} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {formatTokens} from '../utils/format';
import {AgentAvatar} from './AgentAvatar';
import {Icon} from './Icon';
import {SessionAction} from './SessionActions';
import {Sheet} from './Sheet';
import {showToast} from './Toast';

type Busy = 'compact' | 'clear' | null;

/** Enough to see the choices at a glance without pushing the rest of the sheet off screen. */
const CANDIDATE_PREVIEW = 4;

/** Context budget, teammates and housekeeping for the open conversation. */
export function SessionSheet({
  visible,
  onClose,
  title,
  contextOnly,
  sessionId,
  agentId,
  isNew,
  replying,
  pinned,
  onTogglePin,
  onRename,
  onDelete,
}: {
  visible: boolean;
  onClose: () => void;
  title: string;
  /** Only the context budget, as opened from a reply's token count. */
  contextOnly?: boolean;
  sessionId: string;
  agentId: string | null;
  /** Nothing is stored yet, so there is no context and nothing to rename. */
  isNew: boolean;
  replying: boolean;
  pinned: boolean;
  onTogglePin: () => void;
  onRename: () => void;
  onDelete: () => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  const team = useSessionSettingsStore(s => s.bySession[sessionId]?.team);
  const setMembers = useSessionSettingsStore(s => s.setMembers);
  const defaultId = useAgentStore(s => s.defaultId);
  const multiAgent = useAgentStore(s => s.agents.length > 1);
  const [usage, setUsage] = useState<ContextUsage | null>(null);
  const [usageError, setUsageError] = useState(false);
  const [busy, setBusy] = useState<Busy>(null);
  const [showAll, setShowAll] = useState(false);
  const [teamError, setTeamError] = useState(false);

  const loadUsage = useCallback(async () => {
    try {
      setUsage(await getContextUsage(sessionId, agentParam(agentId)));
      setUsageError(false);
    } catch {
      setUsageError(true);
    }
  }, [sessionId, agentId]);

  useEffect(() => {
    if (visible) {
      setShowAll(false);
      setTeamError(false);
      if (!isNew) {
        loadUsage();
      }
      useSessionSettingsStore
        .getState()
        .load(sessionId, agentId)
        .catch(() => setTeamError(true));
    }
  }, [visible, isNew, loadUsage, sessionId, agentId]);

  const act = async (kind: Exclude<Busy, null>) => {
    if (replying) {
      showToast(tr('chat_busy_wait'));
      return;
    }
    setBusy(kind);
    try {
      if (kind === 'compact') {
        const res = await compactContext(sessionId, agentParam(agentId));
        if (res.usage) {
          setUsage(res.usage);
        }
        showToast(
          res.ok && res.compacted_turns > 0
            ? trf('session_compacted', {n: res.compacted_turns})
            : tr('session_compact_noop'),
        );
      } else {
        await clearContext(sessionId, agentParam(agentId));
        showToast(tr('session_context_cleared'));
        await loadUsage();
      }
    } catch (e) {
      showToast(
        trf(kind === 'compact' ? 'session_compact_failed' : 'session_clear_failed', {error: describeConnectError(e)}),
      );
    } finally {
      setBusy(null);
    }
  };

  const memberIds = team?.members.map(m => m.id) ?? [];
  const changeMembers = (ids: string[]) =>
    setMembers(sessionId, agentId, ids).catch(e =>
      showToast(trf('common_save_failed_detail', {error: describeConnectError(e)})),
    );
  const addable = team?.candidates.filter(c => !memberIds.includes(c.id)) ?? [];
  const shownAddable = showAll ? addable : addable.slice(0, CANDIDATE_PREVIEW);

  const limit = usage?.limit || usage?.window || 0;
  const used = usage?.used ?? 0;
  const pct = limit ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  const parts = usage?.breakdown
    ? [
        {key: 'system', label: tr('session_ctx_system'), value: usage.breakdown.system, color: t.t3},
        {key: 'tools', label: tr('session_ctx_tools'), value: usage.breakdown.tools, color: t.t2},
        {key: 'history', label: tr('session_ctx_history'), value: usage.breakdown.history, color: t.accent},
      ]
    : [];

  return (
    <Sheet visible={visible} onClose={onClose} title={title}>
      <ScrollView style={styles.scroll} contentContainerStyle={styles.body} bounces={false}>
        {!isNew && (
          <View style={styles.block}>
            <View style={styles.blockHead}>
              <Text style={styles.blockTitle}>{tr('session_ctx_title')}</Text>
              {usage?.available && (
                <Text style={styles.blockValue}>
                  {formatTokens(used)} / {formatTokens(limit)}
                  <Text style={styles.pct}> · {pct}%</Text>
                </Text>
              )}
            </View>
            {!usage && !usageError ? (
              <ActivityIndicator style={styles.loading} color={t.t3} />
            ) : !usage?.available ? (
              <Text style={styles.muted}>{usageError ? tr('session_ctx_error') : tr('session_ctx_empty')}</Text>
            ) : (
              <>
                <View style={styles.bar}>
                  {parts.map(p =>
                    p.value > 0 ? (
                      <View key={p.key} style={{flex: p.value, backgroundColor: p.color}} />
                    ) : null,
                  )}
                  <View style={{flex: Math.max(0, limit - used) || 0.0001}} />
                </View>
                <View style={styles.legend}>
                  {parts.map(p => (
                    <View key={p.key} style={styles.legendItem}>
                      <View style={[styles.swatch, {backgroundColor: p.color}]} />
                      <Text style={styles.legendText}>
                        {p.label} {formatTokens(p.value)}
                      </Text>
                    </View>
                  ))}
                </View>
                {(usage.estimated || usage.restored) && (
                  <Text style={styles.note}>
                    {usage.restored ? tr('session_ctx_restored') : tr('session_ctx_estimated')}
                  </Text>
                )}
              </>
            )}
            <View style={styles.actions}>
              <ActionChip
                label={tr('session_compact')}
                hint={tr('session_compact_hint')}
                loading={busy === 'compact'}
                disabled={!!busy}
                onPress={() => act('compact')}
              />
              <ActionChip
                label={tr('session_clear')}
                hint={tr('session_clear_hint')}
                loading={busy === 'clear'}
                disabled={!!busy}
                onPress={() => act('clear')}
              />
            </View>
          </View>
        )}

        {!contextOnly && !team && multiAgent && (
          <View style={styles.block}>
            <Text style={styles.blockTitle}>{tr('session_members')}</Text>
            {teamError ? (
              <Text style={styles.note}>{tr('session_members_failed')}</Text>
            ) : (
              <ActivityIndicator style={styles.loading} color={t.t3} />
            )}
          </View>
        )}
        {!contextOnly && !!team && (team.candidates.length > 0 || team.members.length > 0) && (
          <View style={styles.block}>
            <View style={styles.blockHead}>
              <Text style={styles.blockTitle}>{tr('session_members')}</Text>
              <Text style={styles.blockValue}>{trf('session_member_count', {n: 1 + team.members.length})}</Text>
            </View>
            <MemberRow agent={team.owner} isDefault={team.owner.id === defaultId} tag={tr('chat_main_agent')} />
            {team.members.map(m => (
              <MemberRow
                key={m.id}
                agent={m}
                isDefault={m.id === defaultId}
                tag={m.available === false ? tr('session_member_unavailable') : undefined}
                onRemove={() => changeMembers(memberIds.filter(id => id !== m.id))}
              />
            ))}
            {addable.length > 0 && (
              <>
                <Text style={styles.subLabel}>{tr('session_can_add')}</Text>
                {shownAddable.map(c => (
                  <Pressable
                    key={c.id}
                    accessibilityRole="button"
                    accessibilityLabel={trf('session_add_member_a11y', {name: c.name})}
                    onPress={() => changeMembers([...memberIds, c.id])}
                    style={({pressed}) => [styles.member, pressed && styles.pressed]}>
                    <AgentAvatar agent={c} isDefault={c.id === defaultId} size={28} />
                    <Text style={[styles.memberName, styles.candidateName]} numberOfLines={1}>
                      {c.name}
                    </Text>
                    <View style={styles.addButton}>
                      <Icon icon={faPlus} size={9} color={t.accent} />
                      <Text style={styles.add}>{tr('common_add')}</Text>
                    </View>
                  </Pressable>
                ))}
                {addable.length > shownAddable.length && (
                  <Pressable accessibilityRole="button" hitSlop={6} onPress={() => setShowAll(true)} style={styles.more}>
                    <Text style={styles.moreText}>
                      {trf('session_more_agents', {n: addable.length - shownAddable.length})}
                    </Text>
                  </Pressable>
                )}
              </>
            )}
            <Text style={styles.note}>{tr('session_members_note')}</Text>
          </View>
        )}

        {!isNew && !contextOnly && (
          <View>
            <SessionAction
              icon={faThumbtack}
              label={pinned ? tr('session_unpin') : tr('session_pin')}
              onPress={onTogglePin}
            />
            <SessionAction icon={faPenToSquare} label={tr('common_rename')} onPress={onRename} />
            <SessionAction icon={faTrashCan} label={tr('session_delete')} danger onPress={onDelete} />
          </View>
        )}
      </ScrollView>
    </Sheet>
  );
}

function MemberRow({
  agent,
  isDefault,
  tag,
  onRemove,
}: {
  agent: AgentBadge;
  isDefault: boolean;
  tag?: string;
  onRemove?: () => void;
}) {
  const styles = useStyles();
  return (
    <View style={styles.member}>
      <AgentAvatar agent={agent} isDefault={isDefault} size={28} />
      <Text style={styles.memberName} numberOfLines={1}>
        {agent.name}
      </Text>
      {!!tag && <Text style={styles.memberTag}>{tag}</Text>}
      {!!onRemove && (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={trf('session_remove_member_a11y', {name: agent.name})}
          hitSlop={8}
          onPress={onRemove}>
          <Text style={styles.remove}>{tr('session_remove_member')}</Text>
        </Pressable>
      )}
    </View>
  );
}

function ActionChip({
  label,
  hint,
  loading,
  disabled,
  onPress,
}: {
  label: string;
  hint: string;
  loading: boolean;
  disabled: boolean;
  onPress: () => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      disabled={disabled}
      style={({pressed}) => [styles.chip, pressed && styles.pressed, disabled && !loading && styles.disabled]}>
      {loading ? <ActivityIndicator size="small" color={t.t2} /> : <Text style={styles.chipLabel}>{label}</Text>}
      <Text style={styles.chipHint}>{hint}</Text>
    </Pressable>
  );
}

const useStyles = makeStyles(t => ({
  scroll: {flexGrow: 0, flexShrink: 1},
  body: {paddingHorizontal: 4, paddingBottom: 4, gap: 10},
  block: {
    padding: 14,
    borderRadius: radius.md,
    backgroundColor: t.isDark ? t.bg2 : t.bg1,
    borderWidth: 1,
    borderColor: t.line1,
  },
  blockHead: {flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 12},
  blockTitle: {fontSize: 14, fontWeight: '600', color: t.t1},
  blockValue: {fontSize: 13, color: t.t2, fontVariant: ['tabular-nums']},
  pct: {color: t.t4},
  loading: {paddingVertical: 10},
  muted: {fontSize: 13, color: t.t3, paddingVertical: 4},
  bar: {
    flexDirection: 'row',
    height: 8,
    borderRadius: 4,
    overflow: 'hidden',
    backgroundColor: t.isDark ? t.bg3 : t.bg2,
  },
  legend: {flexDirection: 'row', flexWrap: 'wrap', columnGap: 14, rowGap: 6, marginTop: 10},
  legendItem: {flexDirection: 'row', alignItems: 'center', gap: 6},
  swatch: {width: 7, height: 7, borderRadius: 2},
  legendText: {fontSize: 12, color: t.t3, fontVariant: ['tabular-nums']},
  note: {fontSize: 12, lineHeight: 18, color: t.t4, marginTop: 10},
  actions: {flexDirection: 'row', gap: 8, marginTop: 14},
  chip: {
    flex: 1,
    minHeight: 54,
    justifyContent: 'center',
    paddingHorizontal: 12,
    paddingVertical: 9,
    borderRadius: radius.sm,
    backgroundColor: t.isDark ? t.bg3 : t.bg0,
    borderWidth: 1,
    borderColor: t.line1,
  },
  chipLabel: {fontSize: 14, fontWeight: '500', color: t.t1},
  chipHint: {fontSize: 11, color: t.t3, marginTop: 3},
  disabled: {opacity: 0.5},
  pressed: {opacity: 0.6},
  member: {flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 7},
  memberName: {flex: 1, fontSize: 14, color: t.t1},
  memberTag: {fontSize: 11, color: t.t3},
  remove: {fontSize: 13, color: t.t3},
  subLabel: {fontSize: 13, fontWeight: '600', color: t.t2, marginTop: 10, marginBottom: 2},
  candidateName: {color: t.t2},
  addButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 999,
    backgroundColor: t.accentSoft,
  },
  add: {fontSize: 12, fontWeight: '500', color: t.accent},
  more: {paddingVertical: 8},
  moreText: {fontSize: 13, color: t.accent},
}));
