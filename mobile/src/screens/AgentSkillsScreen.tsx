import type {StackScreenProps} from '@react-navigation/stack';
import {faCheck} from '@fortawesome/free-solid-svg-icons';
import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {Pressable, RefreshControl, ScrollView, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {getSkills} from '../api/cowApi';
import {Icon} from '../components/Icon';
import {SwitchRow} from '../components/settings';
import {showToast, ToastHost} from '../components/Toast';
import {EmptyState, PageHeader} from '../components/ui';
import {tr, trf} from '../i18n';
import type {RootStackParamList} from '../navigation/types';
import type {Skill} from '../protocol/resources';
import {useAgentStore} from '../store/agentStore';
import {describeConnectError} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {skillDescription, skillName} from '../utils/skills';

type Props = StackScreenProps<RootStackParamList, 'AgentSkills'>;

/**
 * Per-Agent skill subset, matching the desktop Agents › Skills tab.
 * `skills == null` means all installed skills; an array is the explicit set
 * (`[]` means none). The picker lists the shared library, not this Agent's folder.
 */
export function AgentSkillsScreen({route, navigation}: Props) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const {agentId} = route.params;
  const agent = useAgentStore(s => s.roster.find(a => a.id === agentId));
  const update = useAgentStore(s => s.update);
  const [library, setLibrary] = useState<Skill[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setLibrary((await getSkills()).skills);
      setError(null);
    } catch (e) {
      setError(describeConnectError(e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Taps outrun the save-and-reload round trip, so the screen shows the latest
  // pick and saves run one after another; the server copy returns once all land.
  const [draft, setDraft] = useState<string[] | null | undefined>(undefined);
  const queue = useRef(Promise.resolve());
  const pending = useRef(0);
  const selection = draft !== undefined ? draft : agent?.skills ?? null;
  const useAll = selection == null;
  const picked = useMemo(() => new Set(selection ?? []), [selection]);

  const apply = (skills: string[] | null) => {
    setDraft(skills);
    pending.current += 1;
    queue.current = queue.current
      .then(() => update(agentId, {skills}))
      .catch(e => showToast(trf('common_save_failed_detail', {error: describeConnectError(e)})))
      .finally(() => {
        pending.current -= 1;
        if (!pending.current) {
          setDraft(undefined);
        }
      });
  };

  const refresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  if (!agent) {
    return (
      <View style={styles.root}>
        <PageHeader title={tr('agent_skills')} onBack={navigation.goBack} />
        <EmptyState title={tr('agent_gone')} hint={tr('agent_gone_hint')} />
      </View>
    );
  }

  return (
    <View style={styles.root}>
      <PageHeader title={tr('agent_skills')} subtitle={agent.name || agent.id} onBack={navigation.goBack} />
      <ScrollView
        contentContainerStyle={{paddingBottom: insets.bottom + 32}}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={t.t3} colors={[t.green]} />}>
        <SwitchRow
          title={tr('agent_skills_use_all')}
          detail={tr('agent_skills_pick')}
          fullDetail
          value={useAll}
          onValueChange={v => apply(v ? null : [])}
          last
        />

        {!library ? (
          <EmptyState loading={!error} title={tr('common_load_failed')} hint={error ?? undefined} />
        ) : !library.length ? (
          <Text style={styles.empty}>{tr('skill_empty')}</Text>
        ) : (
          <View style={styles.list}>
            {library.map((skill, i) => {
              const on = useAll || picked.has(skill.name);
              const desc = skillDescription(skill);
              return (
                <Pressable
                  key={skill.name}
                  accessibilityRole="checkbox"
                  accessibilityState={{checked: on, disabled: useAll}}
                  disabled={useAll}
                  onPress={() => {
                    const next = new Set(picked);
                    if (next.has(skill.name)) {
                      next.delete(skill.name);
                    } else {
                      next.add(skill.name);
                    }
                    apply(Array.from(next));
                  }}
                  style={({pressed}) => [
                    styles.row,
                    i > 0 && styles.divider,
                    on && !useAll && styles.rowOn,
                    useAll && styles.rowDim,
                    pressed && !useAll && styles.rowPressed,
                  ]}>
                  <View style={[styles.check, on && styles.checkOn]}>
                    {on && <Icon icon={faCheck} size={10} color={t.onAccent} />}
                  </View>
                  <View style={styles.rowText}>
                    <Text style={styles.name} numberOfLines={1}>
                      {skillName(skill)}
                    </Text>
                    {!!desc && (
                      <Text style={styles.desc} numberOfLines={2}>
                        {desc}
                      </Text>
                    )}
                  </View>
                </Pressable>
              );
            })}
          </View>
        )}
      </ScrollView>
      <ToastHost bottom={insets.bottom + 28} />
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  empty: {fontSize: 13, color: t.t3, paddingHorizontal: 18, paddingTop: 16},
  list: {
    marginTop: 16,
    marginHorizontal: 14,
    borderRadius: radius.md,
    backgroundColor: t.bg1,
    borderWidth: 1,
    borderColor: t.line1,
    overflow: 'hidden',
  },
  row: {flexDirection: 'row', alignItems: 'flex-start', gap: 12, paddingHorizontal: 14, paddingVertical: 12},
  rowOn: {backgroundColor: t.accentSoft},
  rowDim: {opacity: 0.6},
  rowPressed: {backgroundColor: t.bg2},
  divider: {borderTopWidth: 1, borderTopColor: t.line1},
  check: {
    width: 18,
    height: 18,
    marginTop: 1,
    borderRadius: 4,
    borderWidth: 1.5,
    borderColor: t.line2,
    alignItems: 'center',
    justifyContent: 'center',
  },
  checkOn: {backgroundColor: t.accent, borderColor: t.accent},
  rowText: {flex: 1, minWidth: 0},
  name: {fontSize: 14, fontWeight: '500', color: t.t1},
  desc: {fontSize: 12.5, lineHeight: 18, color: t.t3, marginTop: 3},
}));
