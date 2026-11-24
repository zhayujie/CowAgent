import React from 'react';
import {ActivityIndicator, Pressable, Text, View} from 'react-native';
import Animated, {FadeIn, FadeOut} from 'react-native-reanimated';
import {tr, trf} from '../i18n';
import {checkLinkNow, useLinkStore} from '../store/linkStore';
import {activeServer} from '../store/serverStore';
import {CHAT_WIDTH} from '../theme/layout';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {hostOf} from './ServerPicker';

/** Says the remote device is out of reach, under the chat header, with a way to try again now. */
export function LinkBanner() {
  const t = useTheme();
  const styles = useStyles();
  const down = useLinkStore(s => s.down);
  const checking = useLinkStore(s => s.checking);

  if (!down) {
    return null;
  }
  const server = activeServer();
  const name = server?.name || (server ? hostOf(server.baseUrl) : '');
  return (
    <Animated.View entering={FadeIn.duration(160)} exiting={FadeOut.duration(120)} style={styles.wrap}>
      <View style={styles.card} accessibilityLiveRegion="polite">
        <View style={styles.dot} />
        <View style={styles.text}>
          <Text style={styles.title} numberOfLines={1}>
            {trf('link_down', {name})}
          </Text>
          <Text style={styles.hint}>{tr('link_down_hint')}</Text>
        </View>
        {checking ? (
          <View style={styles.retry}>
            <ActivityIndicator size="small" color={t.t3} />
          </View>
        ) : (
          <Pressable
            accessibilityRole="button"
            hitSlop={8}
            onPress={checkLinkNow}
            style={({pressed}) => [styles.retry, pressed && styles.pressed]}>
            <Text style={styles.retryText}>{tr('common_retry')}</Text>
          </Pressable>
        )}
      </View>
    </Animated.View>
  );
}

const useStyles = makeStyles(t => ({
  wrap: {width: '100%', maxWidth: CHAT_WIDTH, alignSelf: 'center', paddingHorizontal: 12, paddingBottom: 8},
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingLeft: 14,
    paddingRight: 6,
    paddingVertical: 10,
    borderRadius: radius.md,
    backgroundColor: t.dangerSoft,
  },
  dot: {width: 6, height: 6, borderRadius: 3, backgroundColor: t.danger},
  text: {flex: 1, gap: 2},
  title: {fontSize: 14, fontWeight: '600', color: t.t1},
  hint: {fontSize: 12, lineHeight: 17, color: t.t2},
  retry: {minWidth: 52, height: 32, paddingHorizontal: 10, alignItems: 'center', justifyContent: 'center'},
  retryText: {fontSize: 14, fontWeight: '600', color: t.t1},
  pressed: {opacity: 0.6},
}));
