import {faCalendar, faClock, faFolderOpen} from '@fortawesome/free-regular-svg-icons';
import {
  faBook,
  faLocationDot,
  faMagnifyingGlassChart,
  faMicrochip,
  faPuzzlePiece,
  faTerminal,
} from '@fortawesome/free-solid-svg-icons';
import type {IconDefinition} from '@fortawesome/fontawesome-svg-core';
import React, {useEffect, useRef} from 'react';
import {Pressable, ScrollView, Text, View} from 'react-native';
import {tr, trf, type MessageKey} from '../i18n';
import {LOCAL_SERVER_ID} from '../kernel/localKernel';
import type {AgentProfile} from '../protocol/resources';
import {useServerStore} from '../store/serverStore';
import type {Palette} from '../theme/palette';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {greeting} from '../utils/format';
import {AgentAvatar} from './AgentAvatar';
import {Icon} from './Icon';

type Example = {
  key: string;
  icon: IconDefinition;
  tint: (t: Palette) => [string, string];
  send?: string;
};

const FILES: Example = {key: 'sys', icon: faFolderOpen, tint: t => t.kind.web};
const TASK: Example = {key: 'task', icon: faClock, tint: t => t.kind.image};
/** Only the agent on the phone itself reaches the phone's calendar and location. */
const CALENDAR: Example = {key: 'calendar', icon: faCalendar, tint: t => t.kind.web};
const NEARBY: Example = {key: 'nearby', icon: faLocationDot, tint: t => t.kind.image};

/** The web console's starter cards; the last one sends a command rather than prose. */
const examples = (onPhone: boolean): Example[] => [
  {key: 'research', icon: faMagnifyingGlassChart, tint: t => t.kind.doc},
  onPhone ? CALENDAR : FILES,
  onPhone ? NEARBY : TASK,
  {key: 'knowledge', icon: faBook, tint: t => t.kind.media},
  {key: 'skill', icon: faPuzzlePiece, tint: t => [t.dangerSoft, t.danger]},
  {key: 'cmd', icon: faTerminal, tint: t => t.kind.other, send: '/help'},
];

export function Intro({
  agent,
  isDefault,
  onPick,
  onSetupModel,
  onCardsBand,
}: {
  agent?: AgentProfile;
  isDefault: boolean;
  /** Puts the text in the composer for the user to send or edit. */
  onPick: (text: string) => void;
  /** Set while chat has no usable model; shows the card leading to model setup. */
  onSetupModel?: () => void;
  /** Where the sideways cards sit on screen, so a swipe over them scrolls them instead of opening the drawer. */
  onCardsBand?: (band: {top: number; bottom: number} | null) => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  const cardsRef = useRef<View>(null);
  const measureCards = () =>
    cardsRef.current?.measureInWindow((_x, y, _w, h) => onCardsBand?.({top: y, bottom: y + h}));
  useEffect(() => () => onCardsBand?.(null), [onCardsBand]);
  const custom = !isDefault && agent?.description?.trim();
  const onPhone = useServerStore(s => s.activeId === LOCAL_SERVER_ID);

  return (
    <View style={styles.root}>
      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.hero}
        keyboardShouldPersistTaps="handled"
        bounces={false}>
        <AgentAvatar agent={agent} isDefault={isDefault} size={52} />
        <Text style={styles.title}>{trf('chat_intro_title', {greeting: greeting()})}</Text>
        <Text style={styles.lead}>{custom || tr('chat_intro_lead')}</Text>

        {onSetupModel && (
          <Pressable
            accessibilityRole="button"
            onPress={onSetupModel}
            style={({pressed}) => [styles.setup, pressed && styles.pressed]}>
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
      </ScrollView>

      <View ref={cardsRef} onLayout={measureCards} collapsable={false}>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          keyboardShouldPersistTaps="handled"
          style={styles.cardsScroll}
          contentContainerStyle={styles.cards}>
          {examples(onPhone).map(e => {
            const [bg, fg] = e.tint(t);
            const text = tr(`chat_example_${e.key}_text` as MessageKey);
            return (
              <Pressable
                key={e.key}
                accessibilityRole="button"
                onPress={() => onPick(e.send ?? text)}
                style={({pressed}) => [styles.card, pressed && styles.cardPressed]}>
                <View style={styles.cardHead}>
                  <View style={[styles.cardIcon, {backgroundColor: bg}]}>
                    <Icon icon={e.icon} size={12} color={fg} />
                  </View>
                  <Text style={styles.cardTitle} numberOfLines={1}>
                    {tr(`chat_example_${e.key}_title` as MessageKey)}
                  </Text>
                </View>
                <Text style={styles.cardText} numberOfLines={2}>
                  {text}
                </Text>
              </Pressable>
            );
          })}
        </ScrollView>
      </View>
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1},
  scroll: {flex: 1},
  hero: {flexGrow: 1, justifyContent: 'center', alignItems: 'center', paddingHorizontal: 32, paddingVertical: 24},
  title: {
    fontSize: 22,
    lineHeight: 30,
    fontWeight: '600',
    letterSpacing: -0.4,
    color: t.t1,
    textAlign: 'center',
    marginTop: 18,
  },
  lead: {fontSize: 14, lineHeight: 22, color: t.t3, textAlign: 'center', marginTop: 8, maxWidth: 300},
  setup: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    alignSelf: 'stretch',
    marginTop: 28,
    padding: 14,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: t.accentLine,
    backgroundColor: t.accentSoft,
  },
  pressed: {opacity: 0.6},
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
  cardsScroll: {flexGrow: 0},
  cards: {gap: 10, paddingHorizontal: 12, paddingTop: 4, paddingBottom: 6},
  card: {
    width: 164,
    paddingHorizontal: 14,
    paddingVertical: 12,
    borderRadius: 18,
    backgroundColor: t.bg1,
    borderWidth: 1,
    borderColor: t.line1,
  },
  cardPressed: {backgroundColor: t.bg2},
  cardHead: {flexDirection: 'row', alignItems: 'center', gap: 8},
  cardIcon: {width: 22, height: 22, borderRadius: 7, alignItems: 'center', justifyContent: 'center'},
  cardTitle: {flexShrink: 1, fontSize: 14, fontWeight: '600', color: t.t1},
  cardText: {fontSize: 13, lineHeight: 19, color: t.t3, marginTop: 8, minHeight: 38},
}));
