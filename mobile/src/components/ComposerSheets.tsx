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
    name: '全部可访问',
    short: '全部访问',
    desc: '不加限制，可修改任意位置',
  },
  'workspace-write': {
    icon: faShieldHalved,
    name: '工作区可写',
    short: '工作区',
    desc: '在当前工作空间内自由读写，空间之外的写入会被拒绝',
  },
  'read-only': {
    icon: faEye,
    name: '只读',
    short: '只读',
    desc: '只能查看和分析，不修改任何文件',
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
    {key: 'photos', icon: faImage, label: '相册'},
    ...(canTakePhoto ? [{key: 'camera' as const, icon: faCamera, label: '拍照'}] : []),
    {key: 'files', icon: faFolderOpen, label: '文件'},
  ];
  return (
    <Sheet visible={visible} onClose={onClose} title="添加">
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
        {full ? '附件已满，先移除一些再添加' : `单条消息最多 9 个附件，还可以添加 ${remaining} 个`}
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
          <Text style={styles.rowName}>优化输入</Text>
          <Text style={styles.rowDesc}>
            {canOptimize ? '把口语化的描述整理成清晰、完整的指令' : '先输入一些内容再来优化'}
          </Text>
        </View>
        {optimizing && <Dots />}
      </Pressable>
    </Sheet>
  );
}

const providerLabel = (p: ModelProvider) =>
  typeof p.label === 'string' ? p.label : p.label?.zh || p.label?.en || p.id;

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
      title="本次会话模型">
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
              <Text style={styles.rowName}>跟随默认</Text>
              <Text style={styles.rowDesc} numberOfLines={1}>
                {state.agent ? 'Agent 默认' : '全局默认'} · {fallback?.model || '未配置'}
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
                placeholder="搜索模型"
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
            {!total && <Text style={styles.empty}>还没有可选的模型，请先在 Web 控制台配置模型厂商</Text>}
            {!!total && !filtered.length && <Text style={styles.empty}>没有匹配的模型</Text>}
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
                      {current && !pinned && <Text style={styles.tag}>默认</Text>}
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
    <Sheet visible={visible} onClose={onClose} title="本次会话权限">
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
              ? `已为本次会话单独设置。再点一次当前项可恢复跟随全局（${PERMISSION_META[state.global]?.name ?? state.global}）`
              : '当前跟随全局设置，选择后只对本次会话生效'}
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
