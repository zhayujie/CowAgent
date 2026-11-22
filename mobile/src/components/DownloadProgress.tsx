import React from 'react';
import {Text, View, type DimensionValue} from 'react-native';
import {rawUrlOf, type ChatFile} from '../files/chatFile';
import {downloadKey, useDownloadStore} from '../files/downloadStore';
import {trf} from '../i18n';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {formatBytes} from '../utils/format';

/** A live native download, including the bytes retained for a failed download's next resume. */
export function DownloadProgressBar({file, wide = false}: {file: ChatFile; wide?: boolean}) {
  const t = useTheme();
  const styles = useStyles();
  const item = useDownloadStore(s => s.byId[downloadKey(rawUrlOf(file), file.name)]);
  if (!item || item.status === 'done') {
    return null;
  }
  const failed = item.status === 'failed';
  const percent = item.total && item.total > 0 ? Math.min(1, item.loaded / item.total) : null;
  const size = item.total
    ? `${formatBytes(item.loaded)} / ${formatBytes(item.total)}`
    : formatBytes(item.loaded);
  const label = failed
    ? trf('file_download_resume_at', {size})
    : percent !== null
      ? trf('file_download_progress', {size, pct: Math.floor(percent * 100)})
      : trf('file_download_received', {size});
  const width = `${(percent ?? 0.08) * 100}%` as DimensionValue;
  return (
    <View
      style={[styles.box, wide && styles.boxWide]}
      accessibilityLabel={label}
      accessibilityRole={failed ? 'button' : undefined}
      accessibilityLiveRegion="polite">
      <View style={styles.track}>
        <View style={[styles.fill, failed && styles.failed, {width}]} />
      </View>
      <Text style={[styles.text, failed && {color: t.danger}]} numberOfLines={1}>
        {label}
      </Text>
    </View>
  );
}

const useStyles = makeStyles(t => ({
  box: {gap: 5, marginTop: 5},
  boxWide: {width: '100%', marginTop: 16},
  track: {height: 4, borderRadius: radius.xs, backgroundColor: t.bg3, overflow: 'hidden'},
  fill: {height: 4, borderRadius: radius.xs, backgroundColor: t.green},
  failed: {backgroundColor: t.danger},
  text: {fontSize: 11, color: t.t3, fontVariant: ['tabular-nums']},
}));
