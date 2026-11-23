import {faChevronLeft, faDownload, faEllipsis} from '@fortawesome/free-solid-svg-icons';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useEffect, useLayoutEffect, useState} from 'react';
import {Platform, ScrollView, StyleSheet, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {KIND_LABEL, kindGroup} from '../components/ArtifactStrip';
import {CodeText} from '../components/CodeText';
import {DownloadProgressBar} from '../components/DownloadProgress';
import {FileSheet} from '../components/FileViews';
import {HtmlView} from '../components/HtmlView';
import {LoadBar} from '../components/LoadBar';
import {Markdown} from '../components/Markdown';
import {MediaView, type MediaKind} from '../components/MediaView';
import {PreviewSkeleton} from '../components/Skeleton';
import {ToastHost} from '../components/Toast';
import {Chip, IconButton} from '../components/ui';
import {type ChatFile, fileHttpError, fileKeyOf, viewUrlOf} from '../files/chatFile';
import {useDownloadStore} from '../files/downloadStore';
import {downloadFile, MEDIA_KINDS, openAsWebPage, openWithSystem} from '../files/openFile';
import {tr, trf} from '../i18n';
import {EDGE_ONLY, useFullBackSwipe} from '../navigation/gestures';
import type {RootStackParamList} from '../navigation/types';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {formatBytes} from '../utils/format';
import {languageOf} from '../utils/highlight';

type Props = StackScreenProps<RootStackParamList, 'FilePreview'>;

const MONO = Platform.select({ios: 'Menlo', default: 'monospace'});
/** Kinds read as text; anything else that is neither a page nor media only gets a save option. */
const TEXT_KINDS = new Set(['markdown', 'text', 'csv', 'code']);
/** Past this the phone would stall laying the text out; the browser copes better. */
const MAX_PREVIEW_CHARS = 200_000;
/** The body is read whole before it is cut, so a huge log is not fetched at all. */
const MAX_FETCH_BYTES = 5 * 1024 * 1024;

/** `HTML · 86.4 KB`: the extension says more than the broad kind when there is one. */
function fileMeta(f: ChatFile): string {
  const ext = /\.([a-z0-9]{1,6})$/i.exec(f.name)?.[1];
  return [ext ? ext.toUpperCase() : KIND_LABEL[kindGroup(f.kind)], formatBytes(f.size)].filter(Boolean).join(' · ');
}

export function FilePreviewScreen({route, navigation}: Props) {
  const {file} = route.params;
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const isPage = file.kind === 'html';
  const media = MEDIA_KINDS.has(file.kind) ? (file.kind as MediaKind) : null;
  const unsupported = !isPage && !media && !TEXT_KINDS.has(file.kind);
  // Pages and media load themselves in a view; only text is fetched here.
  const live = isPage || !!media;
  const [attempt, setAttempt] = useState(0);
  const [text, setText] = useState<string | null>(null);
  const [pageReady, setPageReady] = useState(false);
  const [progress, setProgress] = useState<number>();
  const [error, setError] = useState<string | null>(null);
  const [scrolled, setScrolled] = useState(false);
  const [acting, setActing] = useState(false);
  const fullBackSwipe = useFullBackSwipe();
  const download = useDownloadStore(s => s.byId[fileKeyOf(file)]);
  const downloadLabel =
    download?.status === 'downloading'
      ? tr('file_downloading')
      : download?.status === 'failed'
        ? tr('file_download_resume')
        : tr('file_download');
  // Code and tables scroll sideways, so they keep back to the screen edge.
  const sideways = live || file.kind === 'code' || file.kind === 'csv';

  useLayoutEffect(() => {
    navigation.setOptions({gestureResponseDistance: sideways ? EDGE_ONLY : fullBackSwipe});
  }, [navigation, sideways, fullBackSwipe]);

  useEffect(() => {
    if (unsupported) {
      return;
    }
    if (live) {
      if (!viewUrlOf(file)) {
        setError(isPage ? tr('file_page_no_preview') : tr('file_no_url'));
      }
      return;
    }
    if ((file.size ?? 0) > MAX_FETCH_BYTES) {
      setError(trf('file_too_large', {size: formatBytes(file.size)}));
      return;
    }
    let alive = true;
    fetch(viewUrlOf(file))
      .then(res => {
        if (!res.ok) {
          throw new Error(fileHttpError(res.status));
        }
        return res.text();
      })
      .then(body => alive && setText(body))
      .catch(e => {
        if (alive) {
          const message = e instanceof Error ? e.message : String(e);
          setError(/network request failed|failed to fetch/i.test(message) ? tr('file_network_error') : message);
        }
      });
    return () => {
      alive = false;
    };
  }, [file, isPage, live, unsupported, attempt]);

  const retry = () => {
    setError(null);
    setText(null);
    setPageReady(false);
    setProgress(undefined);
    setScrolled(false);
    setAttempt(a => a + 1);
  };

  const loading = !error && !unsupported && (live ? !pageReady : text === null);
  const tooLong = text !== null && text.length > MAX_PREVIEW_CHARS;
  const shown = tooLong ? text.slice(0, MAX_PREVIEW_CHARS) : text;
  const meta = fileMeta(file);

  let body: React.ReactNode;
  if (unsupported) {
    body = (
      <View style={styles.failed}>
        <Text style={styles.failedTitle}>{tr('file_unsupported_title')}</Text>
        <Text style={styles.failedHint}>{[file.name, meta].filter(Boolean).join('\n')}</Text>
        <DownloadProgressBar file={file} wide />
        <View style={styles.failedActions}>
          <Chip label={downloadLabel} active onPress={() => downloadFile(file)} />
          {Platform.OS === 'android' && <Chip label={tr('file_open_with')} onPress={() => openWithSystem(file)} />}
        </View>
      </View>
    );
  } else if (error) {
    body = (
      <View style={styles.failed}>
        <Text style={styles.failedTitle}>{tr('file_open_failed_title')}</Text>
        <Text style={styles.failedHint}>{error}</Text>
        <View style={styles.failedActions}>
          <Chip label={tr('common_retry')} active onPress={retry} />
          <Chip label={tr('file_open_in_browser')} onPress={() => openAsWebPage(file)} />
        </View>
      </View>
    );
  } else if (isPage) {
    body = (
      <View style={[styles.page, {paddingBottom: insets.bottom}]}>
        <HtmlView
          key={attempt}
          uri={viewUrlOf(file)}
          onError={setError}
          onProgress={setProgress}
          onReady={() => setPageReady(true)}
        />
        <PreviewSkeleton visible={!pageReady} overlay />
        <View style={styles.backEdge} />
      </View>
    );
  } else if (media) {
    body = (
      <View style={[styles.page, {paddingBottom: insets.bottom}]}>
        <MediaView
          key={attempt}
          uri={viewUrlOf(file)}
          kind={media}
          onError={setError}
          onProgress={setProgress}
          onReady={() => setPageReady(true)}
          onLongPress={() => setActing(true)}
        />
        {media === 'pdf' && <PreviewSkeleton visible={!pageReady} overlay />}
        <View style={styles.backEdge} />
      </View>
    );
  } else if (shown === null) {
    body = <PreviewSkeleton visible />;
  } else {
    body = (
      <ScrollView
        onScroll={e => setScrolled(e.nativeEvent.contentOffset.y > 2)}
        scrollEventThrottle={32}
        contentContainerStyle={[styles.body, {paddingBottom: insets.bottom + 32}]}>
        {file.kind === 'markdown' ? (
          <Markdown value={shown || `_${tr('file_empty')}_`} />
        ) : (
          <ScrollView horizontal={file.kind === 'csv' || file.kind === 'code'} showsHorizontalScrollIndicator={false}>
            {file.kind === 'code' && shown ? (
              <CodeText code={shown} lang={languageOf(file.name)} style={styles.code} />
            ) : (
              <Text selectable style={styles.code}>
                {shown || tr('file_empty')}
              </Text>
            )}
          </ScrollView>
        )}
        {tooLong && (
          <Text style={styles.note}>{trf('file_truncated_note', {count: MAX_PREVIEW_CHARS.toLocaleString()})}</Text>
        )}
      </ScrollView>
    );
  }

  return (
    <View style={styles.root}>
      <View style={[styles.top, {paddingTop: insets.top + 6}]}>
        <IconButton
          icon={faChevronLeft}
          label={tr('common_back')}
          onPress={navigation.goBack}
          filled
          size={13}
          color={t.t1}
        />
        <View style={styles.heading} accessibilityRole="header">
          <Text style={styles.title} numberOfLines={1} ellipsizeMode="middle">
            {file.name}
          </Text>
          {!!meta && (
            <Text style={styles.meta} numberOfLines={1}>
              {meta}
            </Text>
          )}
        </View>
        <View style={styles.panes}>
          <IconButton icon={faDownload} label={downloadLabel} onPress={() => downloadFile(file)} size={14} />
          <View style={styles.panesDivider} />
          <IconButton icon={faEllipsis} label={tr('ui_more_actions')} onPress={() => setActing(true)} size={15} />
        </View>
        <View style={[styles.edge, (live || scrolled) && !error && styles.edgeShown]} />
        <LoadBar active={loading} progress={live ? progress : undefined} />
      </View>
      {body}
      <FileSheet file={file} visible={acting} onClose={() => setActing(false)} inPreview />
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
    zIndex: 1,
  },
  heading: {flex: 1, minWidth: 0},
  title: {fontSize: 16, fontWeight: '600', letterSpacing: -0.3, color: t.t1},
  meta: {fontSize: 11.5, color: t.t3, marginTop: 2, letterSpacing: 0.2, fontVariant: ['tabular-nums']},
  panes: {
    flexDirection: 'row',
    alignItems: 'center',
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: t.line1,
  },
  panesDivider: {width: 1, height: 16, backgroundColor: t.line1},
  edge: {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 0,
    height: StyleSheet.hairlineWidth,
    backgroundColor: t.line2,
    opacity: 0,
  },
  edgeShown: {opacity: 1},
  page: {flex: 1},
  // A web view claims every touch that lands on it, which cancels the swipe
  // back; this strip keeps the screen edge for it.
  backEdge: {position: 'absolute', left: 0, top: 0, bottom: 0, width: EDGE_ONLY},
  body: {paddingHorizontal: 18, paddingTop: 12},
  code: {fontFamily: MONO, fontSize: 12, lineHeight: 18.5, color: t.t1},
  note: {marginTop: 14, fontSize: 12, color: t.t3},
  failed: {flex: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 40, paddingBottom: 60},
  failedTitle: {fontSize: 15, fontWeight: '500', color: t.t2},
  failedHint: {fontSize: 13, lineHeight: 20, color: t.t3, marginTop: 8, textAlign: 'center'},
  failedActions: {flexDirection: 'row', gap: 8, marginTop: 20},
}));
