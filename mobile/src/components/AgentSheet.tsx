import {faCheck, faUserGroup} from '@fortawesome/free-solid-svg-icons';
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
  onTeamChat,
  title = tr('chat_agent_sheet_title'),
  selectedId,
}: {
  visible: boolean;
  onClose: () => void;
  onSelect: (agentId: string) => void;
  onManage?: () => void;
  /** Offered below the Agents once there are at least two to bring together. */
  onTeamChat?: () => void;
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
    <Sheet
      visible={visible}
      onClose={onClose}
      title={title}
      action={onManage ? {label: tr('chat_agent_manage'), onPress: onManage} : undefined}>
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
      {!!onTeamChat && agents.length > 1 && (
        <Pressable
          accessibilityRole="button"
          onPress={onTeamChat}
          style={({pressed}) => [styles.row, styles.team, pressed && styles.pressed]}>
          <View style={styles.teamIcon}>
            <Icon icon={faUserGroup} size={14} color={t.accent} />
          </View>
          <View style={styles.text}>
            <Text style={styles.name} numberOfLines={1}>
              {tr('menu_new_team_chat')}
            </Text>
            <Text style={styles.meta} numberOfLines={1}>
              {tr('menu_new_team_chat_desc')}
            </Text>
          </View>
        </Pressable>
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
  team: {marginTop: 4, borderTopWidth: 1, borderTopColor: t.line1, borderRadius: 0},
  teamIcon: {
    width: 34,
    height: 34,
    borderRadius: 17,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: t.accentSoft,
  },
  text: {flex: 1},
  name: {fontSize: 16, fontWeight: '500', color: t.t1, letterSpacing: -0.2},
  meta: {fontSize: 12, color: t.t2, marginTop: 3},
}));
