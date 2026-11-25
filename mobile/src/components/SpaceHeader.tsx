import {faFolder} from '@fortawesome/free-regular-svg-icons';
import {faChevronDown, faChevronRight, faHouse} from '@fortawesome/free-solid-svg-icons';
import React from 'react';
import {Pressable, Text, View, type StyleProp, type ViewStyle} from 'react-native';
import {trf} from '../i18n';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import type {SessionGroup} from '../utils/sessionGroups';
import {Icon} from './Icon';

/** The heading of the chats in one workspace: a tap folds them, a long press offers more. */
export function SpaceHeader({
  group,
  collapsed,
  onToggle,
  onLongPress,
  style,
}: {
  group: SessionGroup;
  collapsed: boolean;
  onToggle: () => void;
  onLongPress: () => void;
  style?: StyleProp<ViewStyle>;
}) {
  const t = useTheme();
  const styles = useStyles();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{expanded: !collapsed}}
      accessibilityLabel={trf('space_header_a11y', {name: group.title, n: group.data.length})}
      onPress={onToggle}
      onLongPress={onLongPress}
      delayLongPress={350}
      style={({pressed}) => [styles.head, style, pressed && styles.pressed]}>
      <View style={styles.icon}>
        <Icon icon={group.space?.path ? faFolder : faHouse} size={13} color={t.t2} />
      </View>
      <Text style={styles.name} numberOfLines={1}>
        {group.title}
      </Text>
      <Text style={styles.count}>{group.data.length}</Text>
      <View style={styles.chevron}>
        <Icon icon={collapsed ? faChevronRight : faChevronDown} size={10} color={t.t3} />
      </View>
    </Pressable>
  );
}

const useStyles = makeStyles(t => ({
  head: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    minHeight: 38,
    paddingHorizontal: 12,
    borderRadius: radius.sm,
  },
  pressed: {backgroundColor: t.bg2},
  icon: {width: 18, alignItems: 'center'},
  name: {flex: 1, fontSize: 14, fontWeight: '600', color: t.t1, letterSpacing: -0.1},
  count: {fontSize: 12, color: t.t3, fontVariant: ['tabular-nums']},
  chevron: {width: 12, alignItems: 'center'},
}));
