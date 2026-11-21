import {faChevronLeft, faEllipsis, faXmark} from '@fortawesome/free-solid-svg-icons';
import {useFocusEffect} from '@react-navigation/native';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useRef, useState} from 'react';
import {BackHandler, Linking, StyleSheet, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {WebView, type WebViewNavigation} from 'react-native-webview';
import {LoadBar} from '../components/LoadBar';
import {ChoiceSheet} from '../components/settings';
import {showToast, ToastHost} from '../components/Toast';
import {Chip, IconButton} from '../components/ui';
import {downloadUrl} from '../files/openFile';
import {tr} from '../i18n';
import {EDGE_ONLY} from '../navigation/gestures';
import {loadsInPage, withoutLoginToken} from '../navigation/openWeb';
import type {RootStackParamList} from '../navigation/types';
import {makeStyles, useTheme} from '../theme/theme';
import {copyText} from '../utils/clipboard';

type Props = StackScreenProps<RootStackParamList, 'WebPage'>;

const hostOf = (url: string) => /^https?:\/\/([^/?#]+)/i.exec(url)?.[1] ?? url;

/** Pages can redirect on their own, so only these leave for another app; others could launch anything installed. */
const HANDED_OUT = /^(mailto:|tel:|sms:)/i;

/** Any web page, inside the app: links stay in it, its own back steps through its history. */
export function WebPageScreen({route, navigation}: Props) {
  const {url, title} = route.params;
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const web = useRef<WebView>(null);
  const [page, setPage] = useState({url, title: '', canGoBack: false});
  const [loading, setLoading] = useState(true);
  const [progress, setProgress] = useState<number>();
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [acting, setActing] = useState(false);

  // After a failed load the web view is gone, and its history with it.
  const canGoBack = page.canGoBack && !error;
  const back = useCallback(() => {
    if (canGoBack && web.current) {
      web.current.goBack();
      return true;
    }
    return false;
  }, [canGoBack]);

  useFocusEffect(
    useCallback(() => {
      const sub = BackHandler.addEventListener('hardwareBackPress', back);
      return () => sub.remove();
    }, [back]),
  );

  const onNavigation = (nav: WebViewNavigation) => {
    setPage({url: nav.url || url, title: nav.title && nav.title !== nav.url ? nav.title : '', canGoBack: nav.canGoBack});
  };

  const allow = (req: WebViewNavigation & {isTopFrame?: boolean}) => {
    if (req.isTopFrame === false || loadsInPage(req.url)) {
      return true;
    }
    if (HANDED_OUT.test(req.url)) {
      Linking.openURL(req.url).catch(() => showToast(tr('file_link_unsupported')));
    } else {
      showToast(tr('file_link_unsupported'));
    }
    return false;
  };

  const retry = () => {
    setPage(p => ({...p, url, canGoBack: false}));
    setError(null);
    setLoading(true);
    setProgress(undefined);
    setAttempt(a => a + 1);
  };

  const act = async (key: 'reload' | 'copy') => {
    setActing(false);
    if (key === 'reload') {
      if (error) {
        retry();
      } else {
        web.current?.reload();
      }
      return;
    }
    const ok = await copyText(withoutLoginToken(page.url));
    showToast(ok ? tr('share_link_copied') : tr('file_copy_failed'));
  };

  return (
    <View style={styles.root}>
      <View style={[styles.top, {paddingTop: insets.top + 6}]}>
        <IconButton
          icon={faChevronLeft}
          label={tr('common_back')}
          onPress={() => back() || navigation.goBack()}
          filled
          size={13}
          color={t.t1}
        />
        {canGoBack && (
          <IconButton icon={faXmark} label={tr('common_close')} onPress={() => navigation.goBack()} size={15} color={t.t1} />
        )}
        <View style={styles.heading} accessibilityRole="header">
          <Text style={styles.title} numberOfLines={1}>
            {page.title || title || hostOf(page.url)}
          </Text>
          <Text style={styles.meta} numberOfLines={1}>
            {hostOf(page.url)}
          </Text>
        </View>
        <IconButton icon={faEllipsis} label={tr('ui_more_actions')} onPress={() => setActing(true)} size={15} />
        <LoadBar active={loading && !error} progress={progress} />
      </View>
      {error ? (
        <View style={styles.failed}>
          <Text style={styles.failedTitle}>{tr('media_page_failed')}</Text>
          <Text style={styles.failedHint}>{error}</Text>
          <View style={styles.failedActions}>
            <Chip label={tr('common_retry')} active onPress={retry} />
          </View>
        </View>
      ) : (
        <View style={[styles.page, {paddingBottom: insets.bottom}]}>
          <WebView
            key={attempt}
            ref={web}
            source={{uri: url}}
            originWhitelist={['*']}
            onShouldStartLoadWithRequest={allow}
            setSupportMultipleWindows={false}
            allowsInlineMediaPlayback
            allowsFullscreenVideo
            onNavigationStateChange={onNavigation}
            onLoadStart={() => setLoading(true)}
            onLoadProgress={e => setProgress(e.nativeEvent.progress)}
            onLoadEnd={() => setLoading(false)}
            onError={e => setError(e.nativeEvent.description || tr('media_page_failed'))}
            onFileDownload={e => downloadUrl(e.nativeEvent.downloadUrl)}
            style={[styles.web, {backgroundColor: t.bg0}]}
          />
          <View style={styles.backEdge} />
        </View>
      )}
      <ChoiceSheet
        visible={acting}
        title={page.title || hostOf(page.url)}
        options={[
          {key: 'reload' as const, label: tr('common_refresh')},
          {key: 'copy' as const, label: tr('share_copy_link')},
        ]}
        onSelect={act}
        onClose={() => setActing(false)}
      />
      <ToastHost bottom={insets.bottom + 28} />
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  top: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 12,
    paddingBottom: 8,
    backgroundColor: t.bg0,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: t.line2,
    zIndex: 1,
  },
  heading: {flex: 1, minWidth: 0},
  title: {fontSize: 16, fontWeight: '600', letterSpacing: -0.3, color: t.t1},
  meta: {fontSize: 11.5, color: t.t3, marginTop: 2, letterSpacing: 0.2},
  page: {flex: 1},
  web: {flex: 1},
  // A web view claims every touch that lands on it, which cancels the swipe
  // back; this strip keeps the screen edge for it.
  backEdge: {position: 'absolute', left: 0, top: 0, bottom: 0, width: EDGE_ONLY},
  failed: {flex: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 40, paddingBottom: 60},
  failedTitle: {fontSize: 15, fontWeight: '500', color: t.t2},
  failedHint: {fontSize: 13, lineHeight: 20, color: t.t3, marginTop: 8, textAlign: 'center'},
  failedActions: {flexDirection: 'row', gap: 8, marginTop: 20},
}));
