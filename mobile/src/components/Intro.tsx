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
import type {SessionItem} from '../protocol/events';
import {makeStyles, useTheme} from '../theme/theme';
import {greeting, shortTime} from '../utils/format';
import {Icon} from './Icon';

const EXAMPLES: {icon: IconDefinition; text: string}[] = [
  {icon: faFolderOpen, text: '看看工作空间里有哪些文件'},
  {icon: faClock, text: '一分钟后提醒我检查服务器'},
  {icon: faWindowMaximize, text: '搜索本周 AI 新闻，整理成一页网页报告'},
  {icon: faBookmark, text: '知识库里现在都有什么'},
  {icon: faLightbulb, text: '你会哪些技能'},
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
      <Text style={styles.eyebrow}>{firstRun ? '首次使用' : greeting()}</Text>
      <Text style={styles.title}>
        {firstRun ? '说说你想让它\n帮你做什么' : '接着上次的，\n还是开始新的？'}
      </Text>
      <Text style={styles.lead}>
        {firstRun
          ? '用平常说话的方式就行。它会自己找工具、调技能，把结果整理进产物中心。'
          : '直接说新的需求，或者回到最近的对话。'}
      </Text>

      <View style={styles.picks}>
        {showRecent
          ? recent.slice(0, RECENT_LIMIT).map(s => (
              <Pick
                key={s.session_id}
                icon={faMessage}
                text={s.title || '未命名对话'}
                aside={shortTime(s.last_active)}
                onPress={() => onOpenSession(s)}
              />
            ))
          : EXAMPLES.map(e => (
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
