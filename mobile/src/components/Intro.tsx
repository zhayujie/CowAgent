import {
  faBookmark,
  faClock,
  faFolderOpen,
  faLightbulb,
  faMessage,
  faWindowMaximize,
} from '@fortawesome/free-regular-svg-icons';
import {faChevronRight, faMicrochip} from '@fortawesome/free-solid-svg-icons';
import type {IconDefinition} from '@fortawesome/fontawesome-svg-core';
import React from 'react';
import {Pressable, ScrollView, Text, View} from 'react-native';
import {tr} from '../i18n';
import type {SessionItem} from '../protocol/events';
import {radius} from '../theme/palette';
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
  onSetupModel,
}: {
  firstRun: boolean;
  recent: SessionItem[];
  onPick: (text: string) => void;
  onOpenSession: (session: SessionItem) => void;
  /** Set while chat has no usable model; shows the card leading to model setup. */
  onSetupModel?: () => void;
}) {
  const t = useTheme();
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

      {onSetupModel && (
        <Pressable
          accessibilityRole="button"
          onPress={onSetupModel}
          style={({pressed}) => [styles.setup, pressed && styles.pickPressed]}>
          <View style={styles.setupIcon}>
            <Icon icon={faMicrochip} size={15} color={t.onAccent} />
          </View>
          <View style={styles.setupText}>
            <Text style={styles.setupTitle}>{tr('connect_setup_model_title')}</Text>
            <Text style={styles.setupDesc}>{tr('connect_setup_model_desc')}</Text>
          </View>
          <View style={styles.setupAction}>
            <Text style={styles.setupActionText}>{tr('connect_setup_model_action')}</Text>
          </View>
        </Pressable>
      )}

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
  setup: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    marginTop: 24,
    padding: 14,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: t.accentLine,
    backgroundColor: t.accentSoft,
  },
  setupIcon: {
    width: 36,
    height: 36,
    borderRadius: radius.sm,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: t.green,
  },
  setupText: {flex: 1},
  setupTitle: {fontSize: 15, fontWeight: '600', color: t.t1},
  setupDesc: {fontSize: 12, lineHeight: 18, color: t.t2, marginTop: 3},
  setupAction: {paddingHorizontal: 12, paddingVertical: 7, borderRadius: 999, backgroundColor: t.green},
  setupActionText: {fontSize: 13, fontWeight: '600', color: t.onAccent},
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
