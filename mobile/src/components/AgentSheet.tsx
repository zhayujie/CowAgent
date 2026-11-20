import {faCheck} from '@fortawesome/free-solid-svg-icons';
import React from 'react';
import {Pressable, Text, View} from 'react-native';
import {tr} from '../i18n';
import {useAgentStore} from '../store/agentStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {AgentAvatar} from './AgentAvatar';
import {Icon} from './Icon';
import {Sheet} from './Sheet';

export function AgentSheet({
  visible,
  onClose,
  onSelect,
  onManage,
  title = tr('chat_agent_sheet_title'),
  selectedId,
}: {
  visible: boolean;
  onClose: () => void;
  onSelect: (agentId: string) => void;
  onManage?: () => void;
  title?: string;
  /** Defaults to the Agent new chats go to. */
  selectedId?: string | null;
}) {
  const t = useTheme();
  const styles = useStyles();
  const agents = useAgentStore(s => s.agents);
  const currentId = useAgentStore(s => s.currentId);
  const defaultId = useAgentStore(s => s.defaultId);
  const checkedId = selectedId === undefined ? currentId : selectedId;

  return (
    <Sheet visible={visible} onClose={onClose} title={title}>
      {agents.map(agent => {
        const selected = agent.id === checkedId;
        const isDefault = agent.id === defaultId;
        return (
          <Pressable
            key={agent.id}
            accessibilityRole="button"
            accessibilityState={{selected}}
            onPress={() => onSelect(agent.id)}
            style={({pressed}) => [styles.row, pressed && styles.pressed]}>
            <AgentAvatar agent={agent} isDefault={isDefault} size={34} />
            <View style={styles.text}>
              <Text style={styles.name} numberOfLines={1}>
                {agent.name}
              </Text>
              {(isDefault || !!agent.description) && (
                <Text style={styles.meta} numberOfLines={1}>
                  {[isDefault ? tr('chat_default') : null, agent.description].filter(Boolean).join(' · ')}
                </Text>
              )}
            </View>
            {selected && <Icon icon={faCheck} size={13} color={t.accent} />}
          </Pressable>
        );
      })}
      {!!onManage && (
        <View style={styles.footer}>
          <Pressable accessibilityRole="button" hitSlop={8} onPress={onManage}>
            <Text style={styles.manage}>{tr('chat_agent_manage')}</Text>
          </Pressable>
        </View>
      )}
    </Sheet>
  );
}

const useStyles = makeStyles(t => ({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 12,
    paddingVertical: 11,
    borderRadius: radius.md,
  },
  pressed: {backgroundColor: t.bg2},
  text: {flex: 1},
  name: {fontSize: 16, fontWeight: '500', color: t.t1, letterSpacing: -0.2},
  meta: {fontSize: 12, color: t.t3, marginTop: 3},
  footer: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'flex-end',
    paddingHorizontal: 12,
    paddingTop: 10,
    paddingBottom: 4,
  },
  manage: {fontSize: 13, color: t.accent},
}));
