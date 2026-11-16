import {faFolderOpen, faImage} from '@fortawesome/free-regular-svg-icons';
import {
  faCamera,
  faCheck,
  faEye,
  faLockOpen,
  faMagnifyingGlass,
  faMicrochip,
  faShieldHalved,
  faWandMagicSparkles,
} from '@fortawesome/free-solid-svg-icons';
import type {IconDefinition} from '@fortawesome/fontawesome-svg-core';
import React, {useMemo, useState} from 'react';
import {ActivityIndicator, Pressable, ScrollView, Text, TextInput, View} from 'react-native';
import {localizedLabel, tr, trf} from '../i18n';
import type {ModelProvider, PermissionMode, SessionSettings} from '../protocol/resources';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {Dots} from './Dots';
import {Icon} from './Icon';
import {Sheet} from './Sheet';
import {GroupLabel} from './ui';

/** Most open first, the order the web console lists them in. */
export const PERMISSION_META: Record<
  PermissionMode,
  {icon: IconDefinition; name: string; short: string; desc: string}
> = {
  'full-access': {
    icon: faLockOpen,
    get name() {
      return tr('composer_perm_full_access');
    },
    get short() {
      return tr('composer_perm_full_access_short');
    },
    get desc() {
      return tr('composer_perm_full_access_desc');
    },
  },
  'workspace-write': {
    icon: faShieldHalved,
    get name() {
      return tr('composer_perm_workspace_write');
    },
    get short() {
      return tr('composer_perm_workspace_write_short');
    },
    get desc() {
      return tr('composer_perm_workspace_write_desc');
    },
  },
  'read-only': {
    icon: faEye,
    get name() {
      return tr('composer_perm_read_only');
    },
    get short() {
      return tr('composer_perm_read_only_short');
    },
    get desc() {
      return tr('composer_perm_read_only_desc');
    },
  },
};

const PERMISSION_ORDER = Object.keys(PERMISSION_META) as PermissionMode[];
const SEARCH_THRESHOLD = 10;

export type AttachSource = 'photos' | 'camera' | 'files';

export function AttachSheet({
  visible,
  onClose,
  onPick,
  canTakePhoto,
  remaining,
  canOptimize,
  optimizing,
  onOptimize,
}: {
  visible: boolean;
  onClose: () => void;
  onPick: (source: AttachSource) => void;
  canTakePhoto: boolean;
  remaining: number;
  canOptimize: boolean;
  optimizing: boolean;
  onOptimize: () => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  const full = remaining <= 0;
  const tiles: {key: AttachSource; icon: IconDefinition; label: string}[] = [
    {key: 'photos', icon: faImage, label: tr('composer_attach_photos')},
    ...(canTakePhoto ? [{key: 'camera' as const, icon: faCamera, label: tr('composer_attach_camera')}] : []),
    {key: 'files', icon: faFolderOpen, label: tr('composer_attach_files')},
  ];
  return (
    <Sheet visible={visible} onClose={onClose} title={tr('common_add')}>
      <View style={styles.tiles}>
        {tiles.map(tile => (
          <Pressable
            key={tile.key}
            accessibilityRole="button"
            accessibilityLabel={tile.label}
            disabled={full}
            onPress={() => onPick(tile.key)}
            style={({pressed}) => [styles.tile, pressed && styles.tilePressed, full && styles.dim]}>
            <View style={styles.tileIcon}>
              <Icon icon={tile.icon} size={19} color={t.t1} />
            </View>
            <Text style={styles.tileLabel}>{tile.label}</Text>
          </Pressable>
        ))}
      </View>
      <Text style={styles.note}>
        {full ? tr('composer_attach_full') : trf('composer_attach_remaining', {n: remaining})}
      </Text>

      <View style={styles.divider} />

      <Pressable
        accessibilityRole="button"
        disabled={!canOptimize || optimizing}
        onPress={onOptimize}
        style={({pressed}) => [styles.row, pressed && styles.rowPressed, !canOptimize && styles.dim]}>
        <View style={styles.rowIcon}>
          <Icon icon={faWandMagicSparkles} size={14} color={t.accent} />
        </View>
        <View style={styles.rowBody}>
          <Text style={styles.rowName}>{tr('composer_optimize')}</Text>
          <Text style={styles.rowDesc}>
            {canOptimize ? tr('composer_optimize_desc') : tr('composer_optimize_empty')}
          </Text>
        </View>
        {optimizing && <Dots />}
      </Pressable>
    </Sheet>
  );
}

const providerLabel = (p: ModelProvider) => localizedLabel(p.label, p.id);

export function ModelSheet({
  visible,
  onClose,
  settings,
  onSelect,
}: {
  visible: boolean;
  onClose: () => void;
  settings?: SessionSettings;
  onSelect: (pick: {provider: string; model: string} | null) => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  const [query, setQuery] = useState('');
  const state = settings?.model;
  const providers = useMemo(() => state?.providers ?? [], [state]);
  const total = providers.reduce((n, p) => n + p.models.length, 0);
  const pinned = state?.source === 'session';
  const fallback = state?.agent ?? state?.global;

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) {
      return providers;
    }
    return providers
      .map(p => ({...p, models: p.models.filter(m => m.toLowerCase().includes(q))}))
      .filter(p => p.models.length || providerLabel(p).toLowerCase().includes(q));
  }, [providers, query]);

  return (
    <Sheet
      visible={visible}
      onClose={() => {
        setQuery('');
        onClose();
      }}
      title={tr('composer_model_title')}>
      {!state ? (
        <View style={styles.loading}>
          <ActivityIndicator color={t.t3} />
        </View>
      ) : (
        <>
          <Pressable
            accessibilityRole="button"
            accessibilityState={{selected: !pinned}}
            onPress={() => onSelect(null)}
            style={({pressed}) => [styles.row, pressed && styles.rowPressed]}>
            <View style={styles.rowIcon}>
              <Icon icon={faMicrochip} size={13} color={t.t2} />
            </View>
            <View style={styles.rowBody}>
              <Text style={styles.rowName}>{tr('composer_model_follow_default')}</Text>
              <Text style={styles.rowDesc} numberOfLines={1}>
                {state.agent ? tr('composer_model_agent_default') : tr('composer_model_global_default')} ·{' '}
                {fallback?.model || tr('common_not_configured')}
              </Text>
            </View>
            {!pinned && <Icon icon={faCheck} size={13} color={t.accent} />}
          </Pressable>

          {total > SEARCH_THRESHOLD && (
            <View style={styles.search}>
              <Icon icon={faMagnifyingGlass} size={12} color={t.t3} />
              <TextInput
                value={query}
                onChangeText={setQuery}
                placeholder={tr('composer_model_search')}
                placeholderTextColor={t.t3}
                selectionColor={t.accent}
                cursorColor={t.accent}
                autoCapitalize="none"
                autoCorrect={false}
                style={styles.searchInput}
              />
            </View>
          )}

          <ScrollView style={styles.scroll} keyboardShouldPersistTaps="handled">
            {!total && <Text style={styles.empty}>{tr('composer_model_none')}</Text>}
            {!!total && !filtered.length && <Text style={styles.empty}>{tr('composer_model_no_match')}</Text>}
            {filtered.map(p => (
              <View key={p.id} style={styles.group}>
                <GroupLabel style={styles.groupLabel}>{providerLabel(p)}</GroupLabel>
                {p.models.map(m => {
                  const current = m === state.model && p.id === state.provider;
                  const active = pinned && current;
                  return (
                    <Pressable
                      key={m}
                      accessibilityRole="button"
                      accessibilityState={{selected: active}}
                      onPress={() => onSelect({provider: p.id, model: m})}
                      style={({pressed}) => [styles.modelRow, pressed && styles.rowPressed]}>
                      <Text style={[styles.modelName, active && styles.modelActive]} numberOfLines={1}>
                        {m}
                      </Text>
                      {current && !pinned && <Text style={styles.tag}>{tr('chat_default')}</Text>}
                      {active && <Icon icon={faCheck} size={13} color={t.accent} />}
                    </Pressable>
                  );
                })}
              </View>
            ))}
          </ScrollView>
        </>
      )}
    </Sheet>
  );
}

export function PermissionSheet({
  visible,
  onClose,
  settings,
  onSelect,
}: {
  visible: boolean;
  onClose: () => void;
  settings?: SessionSettings;
  onSelect: (mode: PermissionMode | null) => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  const state = settings?.permission;
  const modes = state?.modes?.length ? state.modes : PERMISSION_ORDER;
  const pinned = state?.source === 'session';
  return (
    <Sheet visible={visible} onClose={onClose} title={tr('composer_perm_title')}>
      {!state ? (
        <View style={styles.loading}>
          <ActivityIndicator color={t.t3} />
        </View>
      ) : (
        <>
          {PERMISSION_ORDER.filter(m => modes.includes(m)).map(mode => {
            const meta = PERMISSION_META[mode];
            const active = mode === state.mode;
            return (
              <Pressable
                key={mode}
                accessibilityRole="button"
                accessibilityState={{selected: active}}
                // Tapping the pinned mode again drops the pin and follows global.
                onPress={() => onSelect(active && pinned ? null : mode)}
                style={({pressed}) => [styles.row, pressed && styles.rowPressed]}>
                <View style={[styles.rowIcon, active && styles.rowIconActive]}>
                  <Icon icon={meta.icon} size={13} color={active ? t.accent : t.t2} />
                </View>
                <View style={styles.rowBody}>
                  <Text style={styles.rowName}>{meta.name}</Text>
                  <Text style={styles.rowDesc}>{meta.desc}</Text>
                </View>
                {active && <Icon icon={faCheck} size={13} color={t.accent} />}
              </Pressable>
            );
          })}
          <Text style={styles.note}>
            {pinned
              ? trf('composer_perm_pinned_note', {name: PERMISSION_META[state.global]?.name ?? state.global})
              : tr('composer_perm_follow_note')}
          </Text>
        </>
      )}
    </Sheet>
  );
}

const useStyles = makeStyles(t => ({
  tiles: {flexDirection: 'row', gap: 10, paddingHorizontal: 12, paddingTop: 2},
  tile: {
    flex: 1,
    alignItems: 'center',
    gap: 8,
    paddingVertical: 14,
    borderRadius: radius.md,
    backgroundColor: t.bg2,
  },
  tilePressed: {backgroundColor: t.bg3},
  tileIcon: {height: 22, alignItems: 'center', justifyContent: 'center'},
  tileLabel: {fontSize: 13, color: t.t1},
  dim: {opacity: 0.45},
  note: {fontSize: 12, lineHeight: 18, color: t.t4, paddingHorizontal: 12, paddingTop: 10, paddingBottom: 4},
  divider: {height: 1, backgroundColor: t.line1, marginHorizontal: 12, marginVertical: 8},
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 12,
    paddingVertical: 11,
    borderRadius: radius.md,
  },
  rowPressed: {backgroundColor: t.bg2},
  rowIcon: {
    width: 34,
    height: 34,
    borderRadius: radius.sm,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: t.bg2,
  },
  rowIconActive: {backgroundColor: t.accentSoft},
  rowBody: {flex: 1, minWidth: 0},
  rowName: {fontSize: 15, fontWeight: '500', color: t.t1, letterSpacing: -0.1},
  rowDesc: {fontSize: 12, lineHeight: 17, color: t.t3, marginTop: 3},
  loading: {paddingVertical: 48, alignItems: 'center'},
  search: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    height: 38,
    marginHorizontal: 12,
    marginTop: 6,
    marginBottom: 4,
    paddingHorizontal: 12,
    borderRadius: radius.sm,
    backgroundColor: t.bg2,
  },
  searchInput: {flex: 1, padding: 0, fontSize: 14, color: t.t1},
  scroll: {flexGrow: 0, flexShrink: 1},
  group: {paddingTop: 12},
  groupLabel: {paddingHorizontal: 12, marginBottom: 4},
  modelRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingHorizontal: 12,
    paddingVertical: 11,
    borderRadius: radius.sm,
  },
  modelName: {flex: 1, fontSize: 14, color: t.t1},
  modelActive: {color: t.accent, fontWeight: '600'},
  tag: {
    fontSize: 11,
    color: t.t3,
    paddingHorizontal: 6,
    paddingVertical: 1,
    borderRadius: 4,
    backgroundColor: t.bg2,
    overflow: 'hidden',
  },
  empty: {fontSize: 13, lineHeight: 20, color: t.t3, paddingHorizontal: 12, paddingVertical: 20},
}));
