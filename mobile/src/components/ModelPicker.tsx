import {faCheck, faMagnifyingGlass} from '@fortawesome/free-solid-svg-icons';
import React, {useMemo, useState} from 'react';
import {Pressable, ScrollView, Text, TextInput, View} from 'react-native';
import {localizedLabel, tr, trf} from '../i18n';
import type {CatalogModel, ProviderEntry} from '../protocol/resources';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {formatTokens} from '../utils/format';
import {Icon} from './Icon';
import {Sheet} from './Sheet';
import {GroupLabel} from './ui';

const SEARCH_THRESHOLD = 10;

export const labelText = (label: string | {zh?: string; en?: string} | undefined, fallback: string) =>
  localizedLabel(label, fallback);

export function modelsOf(p: ProviderEntry): CatalogModel[] {
  return p.effective?.length ? p.effective : p.models.map(name => ({name}));
}

export function describeModel(m: CatalogModel): string {
  const parts: string[] = [];
  if (m.context_window) {
    parts.push(trf('settings_model_context', {n: formatTokens(m.context_window)}));
  }
  const caps = m.capabilities ?? [];
  if (caps.includes('vision')) {
    parts.push(tr('settings_model_vision'));
  }
  if (caps.includes('video')) {
    parts.push(tr('settings_model_video'));
  }
  return parts.join(' · ');
}

export interface ModelPick {
  provider: string;
  model: string;
}

/** Configured vendors only: a model whose vendor has no key cannot answer. */
export function ModelPicker({
  visible,
  title,
  providers,
  selected,
  exclude,
  lead,
  onSelect,
  onClose,
}: {
  visible: boolean;
  title: string;
  providers: ProviderEntry[];
  selected?: ModelPick | null;
  exclude?: ModelPick[];
  /** An extra first row, e.g. "follow the global model". */
  lead?: {label: string; desc?: string; active: boolean; onPress: () => void};
  onSelect: (pick: ModelPick) => void;
  onClose: () => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  const [query, setQuery] = useState('');
  const usable = useMemo(() => providers.filter(p => p.configured), [providers]);
  const total = usable.reduce((n, p) => n + modelsOf(p).length, 0);

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const skip = new Set((exclude ?? []).map(x => `${x.provider}/${x.model}`));
    return usable
      .map(p => ({
        provider: p,
        models: modelsOf(p).filter(
          m => !skip.has(`${p.id}/${m.name}`) && (!q || m.name.toLowerCase().includes(q)),
        ),
      }))
      .filter(g => g.models.length);
  }, [usable, query, exclude]);

  const close = () => {
    setQuery('');
    onClose();
  };

  return (
    <Sheet visible={visible} onClose={close} title={title}>
      {lead && (
        <Pressable
          accessibilityRole="button"
          accessibilityState={{selected: lead.active}}
          onPress={lead.onPress}
          style={({pressed}) => [styles.lead, pressed && styles.pressed]}>
          <View style={styles.leadText}>
            <Text style={styles.leadName}>{lead.label}</Text>
            {!!lead.desc && <Text style={styles.leadDesc}>{lead.desc}</Text>}
          </View>
          {lead.active && <Icon icon={faCheck} size={13} color={t.accent} />}
        </Pressable>
      )}
      {total > SEARCH_THRESHOLD && (
        <View style={styles.search}>
          <Icon icon={faMagnifyingGlass} size={12} color={t.t3} />
          <TextInput
            value={query}
            onChangeText={setQuery}
            placeholder={tr('settings_search_models')}
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
        {!usable.length && <Text style={styles.empty}>{tr('settings_no_ready_vendor')}</Text>}
        {!!usable.length && !groups.length && <Text style={styles.empty}>{tr('settings_no_matching_model')}</Text>}
        {groups.map(({provider, models}) => (
          <View key={provider.id} style={styles.group}>
            <GroupLabel style={styles.groupLabel} small>{labelText(provider.label, provider.id)}</GroupLabel>
            {models.map(m => {
              const active = selected?.provider === provider.id && selected?.model === m.name;
              const desc = describeModel(m);
              return (
                <Pressable
                  key={m.name}
                  accessibilityRole="button"
                  accessibilityState={{selected: active}}
                  onPress={() => {
                    setQuery('');
                    onSelect({provider: provider.id, model: m.name});
                  }}
                  style={({pressed}) => [styles.row, pressed && styles.pressed]}>
                  <View style={styles.leadText}>
                    <Text style={[styles.name, active && styles.nameActive]} numberOfLines={1}>
                      {m.name}
                    </Text>
                    {!!desc && <Text style={styles.desc}>{desc}</Text>}
                  </View>
                  {active && <Icon icon={faCheck} size={13} color={t.accent} />}
                </Pressable>
              );
            })}
          </View>
        ))}
      </ScrollView>
    </Sheet>
  );
}

const useStyles = makeStyles(t => ({
  lead: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 12,
    paddingVertical: 12,
    borderRadius: radius.md,
  },
  leadText: {flex: 1, minWidth: 0},
  leadName: {fontSize: 15, fontWeight: '500', color: t.t1},
  leadDesc: {fontSize: 12, color: t.t3, marginTop: 3},
  pressed: {backgroundColor: t.bg2},
  search: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    height: 38,
    marginHorizontal: 12,
    marginTop: 4,
    marginBottom: 4,
    paddingHorizontal: 12,
    borderRadius: radius.sm,
    backgroundColor: t.bg2,
  },
  searchInput: {flex: 1, padding: 0, fontSize: 14, color: t.t1},
  scroll: {flexGrow: 0, flexShrink: 1},
  group: {paddingTop: 12},
  groupLabel: {paddingHorizontal: 12, marginBottom: 4},
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: radius.sm,
  },
  name: {fontSize: 14, color: t.t1},
  nameActive: {color: t.accent, fontWeight: '600'},
  desc: {fontSize: 11, color: t.t3, marginTop: 2},
  empty: {fontSize: 13, lineHeight: 20, color: t.t3, paddingHorizontal: 12, paddingVertical: 20},
}));
