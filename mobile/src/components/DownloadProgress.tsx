import React, {useEffect, useRef} from 'react';
import {Animated, Easing, Text, View} from 'react-native';
import {fileKeyOf, type ChatFile} from '../files/chatFile';
import {useDownloadStore} from '../files/downloadStore';
import {trf} from '../i18n';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {formatBytes} from '../utils/format';

/** A live native download, including the bytes retained for a failed download's next resume. */
export function DownloadProgressBar({file, wide = false}: {file: ChatFile; wide?: boolean}) {
  const t = useTheme();
  const styles = useStyles();
  const item = useDownloadStore(s => s.byId[fileKeyOf(file)]);
  if (!item || item.status === 'done') {
    return null;
  }
  const failed = item.status === 'failed';
  // A chunked response carries no length; the size the server reported stands in for it.
  const total = item.total ?? item.expected ?? 0;
  const percent = total > 0 ? Math.min(1, item.loaded / total) : null;
  const size = total > 0 ? `${formatBytes(item.loaded)} / ${formatBytes(total)}` : formatBytes(item.loaded);
  const label = failed
    ? trf('file_download_resume_at', {size})
    : percent !== null
      ? trf('file_download_progress', {size, pct: Math.floor(percent * 100)})
      : trf('file_download_received', {size});
  return (
    <View
      style={[styles.box, wide && styles.boxWide]}
      accessibilityLabel={label}
      accessibilityRole={failed ? 'button' : undefined}
      accessibilityLiveRegion="polite">
      <View style={styles.track}>
        {percent !== null ? (
          <View style={[styles.fill, failed && styles.failed, {width: `${percent * 100}%` as unknown as number}]} />
        ) : (
          // No length at all: show that bytes are arriving, never a made-up ratio.
          <Sweep failed={failed} />
        )}
      </View>
      <Text style={[styles.text, failed && {color: t.danger}]} numberOfLines={1}>
        {label}
      </Text>
    </View>
  );
}

function Sweep({failed}: {failed: boolean}) {
  const styles = useStyles();
  const shift = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    const loop = Animated.loop(
      Animated.timing(shift, {toValue: 1, duration: 1100, easing: Easing.linear, useNativeDriver: true}),
    );
    loop.start();
    return () => loop.stop();
  }, [shift]);
  return (
    <Animated.View
      style={[
        styles.fill,
        styles.sweep,
        failed && styles.failed,
        {transform: [{translateX: shift.interpolate({inputRange: [0, 1], outputRange: [-48, 320]})}]},
      ]}
    />
  );
}

const useStyles = makeStyles(t => ({
  box: {gap: 5, marginTop: 5},
  boxWide: {width: '100%', marginTop: 16},
  track: {height: 4, borderRadius: radius.xs, backgroundColor: t.bg3, overflow: 'hidden'},
  fill: {height: 4, borderRadius: radius.xs, backgroundColor: t.green},
  sweep: {width: 48},
  failed: {backgroundColor: t.danger},
  text: {fontSize: 11, color: t.t3, fontVariant: ['tabular-nums']},
}));
