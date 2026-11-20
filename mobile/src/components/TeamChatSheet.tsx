import {faCircle} from '@fortawesome/free-regular-svg-icons';
import {faCircleCheck} from '@fortawesome/free-solid-svg-icons';
import React, {useEffect, useState} from 'react';
import {Pressable, ScrollView, Text, View} from 'react-native';
import {tr, trf} from '../i18n';
import {useAgentStore} from '../store/agentStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {AgentAvatar} from './AgentAvatar';
import {Icon} from './Icon';
import {ActionButton} from './settings';
import {Sheet} from './Sheet';

/** Pick the Agents for a group chat; the first one picked owns the conversation. */
export function TeamChatSheet({
  visible,
  onClose,
  onStart,
}: {
  visible: boolean;
  onClose: () => void;
  onStart: (owner: string, members: string[]) => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  const agents = useAgentStore(s => s.agents);
  const defaultId = useAgentStore(s => s.defaultId);
  const [picks, setPicks] = useState<string[]>([]);
  const [tried, setTried] = useState(false);

  useEffect(() => {
    if (visible) {
      const {currentId, defaultId: fallback} = useAgentStore.getState();
      const first = currentId ?? fallback;
      setPicks(first ? [first] : []);
      setTried(false);
    }
  }, [visible]);

  const toggle = (id: string) => setPicks(p => (p.includes(id) ? p.filter(x => x !== id) : [...p, id]));
  // The remembered current Agent may have been deleted since.
  const chosen = picks.filter(id => agents.some(a => a.id === id));

  const start = () => {
    if (chosen.length < 2) {
      setTried(true);
      return;
    }
    const [owner, ...members] = chosen;
    onStart(owner, members);
  };

  return (
    <Sheet visible={visible} onClose={onClose} title={tr('chat_team_title')}>
      {agents.length < 2 ? (
        <Text style={styles.hint}>{tr('chat_team_need_two')}</Text>
      ) : (
        <>
          <Text style={styles.hint}>{tr('chat_team_hint')}</Text>
          <ScrollView style={styles.list} bounces={false}>
            {agents.map(agent => {
              const rank = chosen.indexOf(agent.id);
              const on = rank !== -1;
              return (
                <Pressable
                  key={agent.id}
                  accessibilityRole="checkbox"
                  accessibilityState={{checked: on}}
                  accessibilityLabel={rank === 0 ? trf('chat_team_owner_a11y', {name: agent.name}) : agent.name}
                  onPress={() => toggle(agent.id)}
                  style={({pressed}) => [styles.row, on && styles.rowOn, pressed && styles.pressed]}>
                  <AgentAvatar agent={agent} isDefault={agent.id === defaultId} size={32} />
                  <View style={styles.text}>
                    <Text style={styles.name} numberOfLines={1}>
                      {agent.name}
                    </Text>
                    {!!agent.description && (
                      <Text style={styles.desc} numberOfLines={1}>
                        {agent.description}
                      </Text>
                    )}
                  </View>
                  {rank === 0 && <Text style={styles.owner}>{tr('chat_main_agent')}</Text>}
                  <Icon icon={on ? faCircleCheck : faCircle} size={18} color={on ? t.accent : t.t4} />
                </Pressable>
              );
            })}
          </ScrollView>
          <Text style={[styles.status, tried && chosen.length < 2 && styles.statusBad]}>
            {chosen.length < 2 ? tr('chat_team_min') : trf('chat_team_selected', {n: chosen.length})}
          </Text>
          <ActionButton label={tr('chat_team_start')} tone="primary" disabled={chosen.length < 2} onPress={start} />
        </>
      )}
    </Sheet>
  );
}

const useStyles = makeStyles(t => ({
  hint: {fontSize: 13, lineHeight: 20, color: t.t3, paddingHorizontal: 11, marginBottom: 12},
  list: {flexGrow: 0, flexShrink: 1},
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 12,
    paddingVertical: 10,
    marginBottom: 6,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: t.line1,
  },
  rowOn: {borderColor: t.accentLine, backgroundColor: t.accentSoft},
  pressed: {opacity: 0.7},
  text: {flex: 1},
  name: {fontSize: 15, fontWeight: '500', color: t.t1, letterSpacing: -0.2},
  desc: {fontSize: 12, color: t.t3, marginTop: 2},
  owner: {fontSize: 11, color: t.accent, fontWeight: '500'},
  status: {fontSize: 12, color: t.t4, textAlign: 'center', marginTop: 6, marginBottom: 10},
  statusBad: {color: t.danger},
}));
