import {
  faBookmark,
  faClock,
  faFolderOpen,
  faLightbulb,
  faMessage,
  faWindowMaximize,
} from '@fortawesome/free-regular-svg-icons';
import {faChevronRight} from '@fortawesome/free-solid-svg-icons';
import type {IconDefinition} from '@fortawesome/fontawesome-svg-core';
import React from 'react';
import {Pressable, ScrollView, Text, View} from 'react-native';
import {tr} from '../i18n';
import type {SessionItem} from '../protocol/events';
import {makeStyles, useTheme} from '../theme/theme';
import {greeting, shortTime} from '../utils/format';
import {Icon} from './Icon';

const examples = (): {icon: IconDefinition; text: string}[] => [
  {icon: faFolderOpen, text: tr('chat_intro_example_files')},
  {icon: faClock, text: tr('chat_intro_example_reminder')},
  {icon: faWindowMaximize, text: tr('chat_intro_example_news')},
  {icon: faBookmark, text: tr('chat_intro_example_knowledge')},
  {icon: faLightbulb, text: tr('chat_intro_example_skills')},
];

const RECENT_LIMIT = 4;

export function Intro({
  firstRun,
  recent,
  onPick,
  onOpenSession,
}: {
  firstRun: boolean;
  recent: SessionItem[];
  onPick: (text: string) => void;
  onOpenSession: (session: SessionItem) => void;
}) {
  const styles = useStyles();
  const showRecent = !firstRun && recent.length > 0;

  return (
    <ScrollView
      style={styles.scroll}
      contentContainerStyle={styles.body}
      keyboardShouldPersistTaps="handled">
      <Text style={styles.eyebrow}>{firstRun ? tr('chat_intro_first_run') : greeting()}</Text>
      <Text style={styles.title}>
        {firstRun ? tr('chat_intro_title_first') : tr('chat_intro_title_back')}
      </Text>
      <Text style={styles.lead}>
        {firstRun ? tr('chat_intro_lead_first') : tr('chat_intro_lead_back')}
      </Text>

      <View style={styles.picks}>
        {showRecent
          ? recent.slice(0, RECENT_LIMIT).map(s => (
              <Pick
                key={s.session_id}
                icon={faMessage}
                text={s.title || tr('session_untitled')}
                aside={shortTime(s.last_active)}
                onPress={() => onOpenSession(s)}
              />
            ))
          : examples().map(e => (
              <Pick key={e.text} icon={e.icon} text={e.text} onPress={() => onPick(e.text)} />
            ))}
      </View>
    </ScrollView>
  );
}

function Pick({
  icon,
  text,
  aside,
  onPress,
}: {
  icon: IconDefinition;
  text: string;
  aside?: string;
  onPress: () => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      style={({pressed}) => [styles.pick, pressed && styles.pickPressed]}>
      <View style={styles.pickIcon}>
        <Icon icon={icon} size={13} color={t.t3} />
      </View>
      <Text style={styles.pickText} numberOfLines={1}>
        {text}
      </Text>
      {aside ? (
        <Text style={styles.pickAside}>{aside}</Text>
      ) : (
        <Icon icon={faChevronRight} size={10} color={t.t4} />
      )}
    </Pressable>
  );
}

const useStyles = makeStyles(t => ({
  scroll: {flex: 1},
  body: {paddingHorizontal: 22, paddingTop: 28, paddingBottom: 24},
  eyebrow: {fontSize: 12, fontWeight: '600', letterSpacing: 1.6, color: t.accent, marginBottom: 12},
  title: {fontSize: 26, lineHeight: 36, fontWeight: '600', letterSpacing: -0.7, color: t.t1},
  lead: {fontSize: 14, lineHeight: 23, color: t.t2, marginTop: 10, letterSpacing: 0.1},
  picks: {marginTop: 26, borderBottomWidth: 1, borderBottomColor: t.line1},
  pick: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingVertical: 14,
    paddingHorizontal: 2,
    borderTopWidth: 1,
    borderTopColor: t.line1,
  },
  pickPressed: {opacity: 0.55},
  pickIcon: {width: 18, alignItems: 'center'},
  pickText: {flex: 1, fontSize: 15, color: t.t1, letterSpacing: -0.1},
  pickAside: {fontSize: 12, color: t.t4, fontVariant: ['tabular-nums']},
}));
