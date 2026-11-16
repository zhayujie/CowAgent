import React from 'react';
import {StyleSheet, View} from 'react-native';

/** Browser preview: the same sandbox the web console gives a generated page. */
export function HtmlView({
  uri,
  onReady,
}: {
  uri: string;
  onError?: (message: string) => void;
  onProgress?: (fraction: number) => void;
  onReady?: () => void;
}) {
  return (
    <View style={styles.root}>
      <iframe
        src={uri}
        title="preview"
        sandbox="allow-scripts allow-popups allow-forms allow-modals"
        onLoad={onReady}
        style={FRAME}
      />
    </View>
  );
}

const FRAME = {border: 0, width: '100%', height: '100%', background: '#fff'};

const styles = StyleSheet.create({
  root: {flex: 1},
});
