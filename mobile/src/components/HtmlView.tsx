import React, {useEffect, useRef} from 'react';
import {StyleSheet} from 'react-native';
import {WebView, type WebViewNavigation} from 'react-native-webview';
import {fileHttpError} from '../files/chatFile';
import {tr} from '../i18n';
import {openWebPage} from '../navigation/openWeb';
import {useTheme} from '../theme/theme';

const originOf = (url: string) => /^(https?:\/\/[^/]+)/i.exec(url)?.[1]?.toLowerCase() ?? '';

// Load end waits for every subresource, and a blocked CDN (Google Fonts in mainland China)
// can hold it for minutes; the page is readable once its own document is parsed.
const READY_SIGNAL = 'cow:html-ready';
const READY_SCRIPT = `(function(){
  function ready(){ window.ReactNativeWebView && window.ReactNativeWebView.postMessage('${READY_SIGNAL}'); }
  if (document.readyState !== 'loading') { ready(); } else { document.addEventListener('DOMContentLoaded', ready); }
})(); true;`;
const READY_TIMEOUT_MS = 6000;

/**
 * A generated page, live; links that leave its server open on a web page of their own.
 * The page's own swipe-back is left off so the edge swipe always closes the preview.
 */
export function HtmlView({
  uri,
  onError,
  onProgress,
  onReady,
}: {
  uri: string;
  onError?: (message: string) => void;
  onProgress?: (fraction: number) => void;
  onReady?: () => void;
}) {
  const t = useTheme();
  const home = originOf(uri);
  const readyRef = useRef(onReady);
  readyRef.current = onReady;
  useEffect(() => {
    // A synchronous CDN script can stall parsing as well; never leave the skeleton up for good.
    const timer = setTimeout(() => readyRef.current?.(), READY_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [uri]);
  const allow = (req: WebViewNavigation & {isTopFrame?: boolean}) => {
    // iOS asks for iframes too; an embedded map or video must load in place.
    if (req.isTopFrame === false || !/^https?:/i.test(req.url) || originOf(req.url) === home) {
      return true;
    }
    openWebPage(req.url);
    return false;
  };
  return (
    <WebView
      source={{uri}}
      originWhitelist={['http://*', 'https://*']}
      onShouldStartLoadWithRequest={allow}
      setSupportMultipleWindows={false}
      injectedJavaScriptBeforeContentLoaded={READY_SCRIPT}
      onMessage={e => e.nativeEvent.data === READY_SIGNAL && onReady?.()}
      onLoadProgress={e => onProgress?.(e.nativeEvent.progress)}
      onLoadEnd={() => onReady?.()}
      onError={e => onError?.(e.nativeEvent.description || tr('media_page_failed'))}
      onHttpError={e => onError?.(fileHttpError(e.nativeEvent.statusCode))}
      style={[styles.web, {backgroundColor: t.bg0}]}
    />
  );
}

const styles = StyleSheet.create({
  web: {flex: 1},
});
