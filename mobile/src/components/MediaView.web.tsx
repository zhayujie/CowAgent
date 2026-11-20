import React from 'react';
import {StyleSheet, View} from 'react-native';
import {tr} from '../i18n';

export type MediaKind = 'pdf' | 'video' | 'audio';

/** Browser preview: the browser's own PDF viewer and media players, inside the page. */
export function MediaView({
  uri,
  kind,
  onError,
  onReady,
}: {
  uri: string;
  kind: MediaKind;
  onError?: (message: string) => void;
  onReady?: () => void;
}) {
  const failed = () => onError?.(tr('media_load_failed'));
  if (kind === 'pdf') {
    // No sandbox: a sandboxed frame keeps Chrome's PDF viewer from loading.
    return (
      <View style={styles.root}>
        <iframe src={uri} title="preview" onLoad={onReady} style={FRAME} />
      </View>
    );
  }
  if (kind === 'video') {
    return (
      <View style={[styles.root, styles.dark]}>
        <video src={uri} controls playsInline onLoadedData={onReady} onError={failed} style={VIDEO} />
      </View>
    );
  }
  return (
    <View style={[styles.root, styles.center]}>
      <audio src={uri} controls onLoadedData={onReady} onError={failed} style={AUDIO} />
    </View>
  );
}

const FRAME = {border: 0, width: '100%', height: '100%', background: '#fff'};
const VIDEO = {width: '100%', height: '100%', objectFit: 'contain' as const, background: '#000'};
const AUDIO = {width: '86%'};

const styles = StyleSheet.create({
  root: {flex: 1},
  dark: {backgroundColor: '#000'},
  center: {alignItems: 'center', justifyContent: 'center'},
});
