import React, {useEffect, useState} from 'react';
import {Pressable, ScrollView, Text, View} from 'react-native';
import {tr} from '../i18n';
import {useAgentStore} from '../store/agentStore';
import {radius} from '../theme/palette';
import {makeStyles} from '../theme/theme';
import {AgentAvatar} from './AgentAvatar';
import {ActionButton} from './settings';
import {Sheet} from './Sheet';

/**
 * Ordered multi-select: the first pick receives the channel's messages, later
 * picks are teammates it can hand work to. No pick follows the default Agent.
 */
export function ChannelAgentsSheet({
  visible,
  initial,
  onSave,
  onClose,
}: {
  visible: boolean;
  initial: string[];
  onSave: (ids: string[]) => Promise<void>;
  onClose: () => void;
}) {
  const styles = useStyles();
  const agents = useAgentStore(s => s.agents);
  const defaultId = useAgentStore(s => s.defaultId);
  const [picked, setPicked] = useState<string[]>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (visible) {
      setPicked(initial);
      setError(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  const toggle = (id: string) => setPicked(p => (p.includes(id) ? p.filter(x => x !== id) : [...p, id]));

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await onSave(picked);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet visible={visible} onClose={onClose} title={tr('channel_who_replies')}>
      <Text style={styles.note}>{tr('channel_agents_note')}</Text>
      <ScrollView style={styles.list} bounces={false}>
        {agents.map(agent => {
          const order = picked.indexOf(agent.id);
          const role =
            order === 0
              ? tr('channel_role_receiver')
              : order > 0
                ? tr('channel_role_member')
                : agent.id === defaultId
                  ? tr('channel_role_default')
                  : '';
          return (
            <Pressable
              key={agent.id}
              accessibilityRole="checkbox"
              accessibilityState={{checked: order >= 0}}
              onPress={() => toggle(agent.id)}
              style={({pressed}) => [styles.row, pressed && styles.pressed]}>
              <AgentAvatar agent={agent} isDefault={agent.id === defaultId} size={34} />
              <View style={styles.text}>
                <Text style={styles.name} numberOfLines={1}>
                  {agent.name}
                </Text>
                {!!role && <Text style={[styles.role, order === 0 && styles.roleLead]}>{role}</Text>}
              </View>
              <View style={[styles.check, order >= 0 && styles.checkOn]}>
                {order >= 0 && <Text style={styles.checkText}>{order + 1}</Text>}
              </View>
            </Pressable>
          );
        })}
        {!agents.length && <Text style={styles.note}>{tr('channel_agents_empty')}</Text>}
      </ScrollView>
      {!!error && <Text style={styles.error}>{error}</Text>}
      <View style={styles.footer}>
        <ActionButton label={tr('common_save')} tone="primary" loading={busy} onPress={save} />
      </View>
    </Sheet>
  );
}

const useStyles = makeStyles(t => ({
  note: {fontSize: 12.5, lineHeight: 19, color: t.t3, paddingHorizontal: 12, paddingBottom: 8},
  list: {maxHeight: 380},
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: radius.md,
  },
  pressed: {backgroundColor: t.bg2},
  text: {flex: 1, minWidth: 0},
  name: {fontSize: 15.5, fontWeight: '500', color: t.t1, letterSpacing: -0.2},
  role: {fontSize: 12, color: t.t3, marginTop: 3},
  roleLead: {color: t.accent},
  check: {
    width: 22,
    height: 22,
    borderRadius: 11,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1.5,
    borderColor: t.line2,
  },
  checkOn: {backgroundColor: t.green, borderColor: t.green},
  checkText: {fontSize: 11.5, fontWeight: '700', color: t.onAccent, fontVariant: ['tabular-nums']},
  error: {fontSize: 12, color: t.danger, paddingHorizontal: 12, paddingTop: 8},
  footer: {paddingHorizontal: 12, paddingTop: 12, paddingBottom: 4},
}));
