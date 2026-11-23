import React, {useCallback, useEffect, useRef, useState} from 'react';
import {Dimensions, Platform, StyleSheet, Text, View} from 'react-native';
import Svg, {Defs, LinearGradient, Rect, Stop} from 'react-native-svg';
import {WebView, type WebViewNavigation} from 'react-native-webview';
import {serverUrl} from '../api/cowApi';
import type {Artifact} from '../protocol/events';
import {usePaneWidth} from '../theme/layout';
import {makeStyles, useTheme} from '../theme/theme';
import {Markdown} from './Markdown';

/** Pages lay out at a desktop width and are scaled down to the card, as the web console does. */
const PAGE_WIDTH = 1024;
/** Documents are set at a reading width and scaled, so the card shows the shape of the page. */
const PAPER_WIDTH = 360;
const PAPER_PAD_X = 22;
const PAPER_PAD_Y = 20;
const TEXT_KINDS = new Set(['markdown', 'code', 'text', 'csv']);
/** The body is read whole, so a large file is left as an icon. */
const TEXT_MAX_BYTES = 512 * 1024;
/** About what a card has room to show; more only costs layout. */
const TEXT_HEAD_CHARS = 1200;
const TEXT_HEAD_LINES = 24;
const TEXT_CACHE_MAX = 80;
const MONO = Platform.select({ios: 'Menlo', default: 'monospace'});
/** Starting a web view is the costly part, so only a few pages load at once. */
const PAGE_SLOTS = 2;
const PAGE_SLOT_TIMEOUT_MS = 8000;
/** Once painted, a thumbnail page stops its animations, timers and media so idle cards cost nothing. */
const FREEZE_PAGE = `setTimeout(function () {
  try {
    if (document.getAnimations) document.getAnimations().forEach(function (a) { a.pause(); });
    window.requestAnimationFrame = function () { return 0; };
    var id = setTimeout(function () {}, 0);
    while (id--) { clearTimeout(id); clearInterval(id); }
    document.querySelectorAll('video, audio').forEach(function (m) { m.pause(); });
  } catch (e) {}
}, 1500);
true;`;
/** Idle time after a drag before thumbnails near the screen start loading. */
const SETTLE_MS = 120;

const originOf = (url: string) => /^(https?:\/\/[^/]+)/i.exec(url)?.[1]?.toLowerCase() ?? '';

let slotsBusy = 0;
const slotQueue: Array<() => void> = [];

/** Waits for a free page slot, then calls `grant`; the returned function gives the slot back or leaves the queue. */
function takePageSlot(grant: () => void): () => void {
  let held = false;
  const run = () => {
    held = true;
    slotsBusy++;
    grant();
  };
  if (slotsBusy < PAGE_SLOTS) {
    run();
  } else {
    slotQueue.push(run);
  }
  return () => {
    const queued = slotQueue.indexOf(run);
    if (queued >= 0) {
      slotQueue.splice(queued, 1);
    }
    if (held) {
      held = false;
      slotsBusy--;
      slotQueue.shift()?.();
    }
  };
}

/** Whether the artifact can show its own content in place of a kind icon. */
export function hasThumb(a: Artifact): boolean {
  if (a.exists === false || !a.preview_url) {
    return false;
  }
  if (a.kind === 'html') {
    return true;
  }
  return TEXT_KINDS.has(a.kind) && (a.size ?? 0) <= TEXT_MAX_BYTES;
}

type Listener = () => void;

/**
 * Lets thumbnails re-check whether they are near the screen. Checks run only
 * once scrolling rests, so nothing is measured or started mid-fling.
 */
export function createThumbViewport() {
  const listeners = new Set<Listener>();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const notify = () => {
    clearTimeout(timer);
    listeners.forEach(fn => fn());
  };
  return {
    subscribe(fn: Listener) {
      listeners.add(fn);
      return () => {
        listeners.delete(fn);
      };
    },
    notify,
    /** A drag ended: check soon, unless a fling carries the list on. */
    settle() {
      clearTimeout(timer);
      timer = setTimeout(notify, SETTLE_MS);
    },
    cancel() {
      clearTimeout(timer);
    },
  };
}

export type ThumbViewport = ReturnType<typeof createThumbViewport>;

/**
 * True while the view is on or just beyond the screen. `sticky` keeps it
 * true once reached, for content that is cheap to keep around.
 */
function useNearScreen(viewport: ThumbViewport, sticky: boolean) {
  const ref = useRef<View>(null);
  const [near, setNear] = useState(false);
  const check = useCallback(() => {
    ref.current?.measureInWindow((_x, y, _w, h) => {
      if (!h) {
        return;
      }
      const screen = Dimensions.get('window').height;
      const inRange = y + h > -screen / 2 && y < screen * 1.5;
      setNear(prev => (sticky && prev) || inRange);
    });
  }, [sticky]);
  useEffect(() => viewport.subscribe(check), [viewport, check]);
  return {ref, near, onLayout: check};
}

/** A card's preview: the page or the head of the document, drawn once the card nears the screen. */
export function ArtifactThumb({
  artifact: a,
  height,
  viewport,
}: {
  artifact: Artifact;
  height: number;
  viewport: ThumbViewport;
}) {
  const [width, setWidth] = useState(0);
  const page = a.kind === 'html';
  // Pages each hold a live web view, so they let go once scrolled far away.
  const {ref, near, onLayout} = useNearScreen(viewport, !page);
  return (
    <View
      ref={ref}
      pointerEvents="none"
      style={StyleSheet.absoluteFill}
      onLayout={e => {
        setWidth(e.nativeEvent.layout.width);
        onLayout();
      }}>
      {near && width > 0 && a.preview_url ? (
        page ? (
          <PageThumb uri={serverUrl(a.preview_url)} width={width} height={height} />
        ) : (
          <PaperThumb uri={serverUrl(a.preview_url)} kind={a.kind} width={width} height={height} />
        )
      ) : null}
    </View>
  );
}

function PageThumb({uri, width, height}: {uri: string; width: number; height: number}) {
  const styles = useStyles();
  const [granted, setGranted] = useState(false);
  const [ready, setReady] = useState(false);
  const release = useRef<(() => void) | null>(null);
  useEffect(() => {
    release.current = takePageSlot(() => setGranted(true));
    // A page that never finishes must not hold up the rest.
    const timer = setTimeout(() => release.current?.(), PAGE_SLOT_TIMEOUT_MS);
    return () => {
      clearTimeout(timer);
      release.current?.();
    };
  }, []);
  const scale = width / PAGE_WIDTH;
  const home = originOf(uri);
  // A thumbnail only paints: nothing it does may take it elsewhere.
  const allow = (req: WebViewNavigation & {isTopFrame?: boolean}) =>
    req.isTopFrame === false || originOf(req.url) === home;
  if (!granted) {
    return null;
  }
  return (
    <View style={[styles.frame, !ready && styles.hidden]}>
      <View style={[styles.scaled, {width: PAGE_WIDTH, height: Math.ceil(height / scale), transform: [{scale}]}]}>
        <WebView
          source={{uri}}
          originWhitelist={['http://*', 'https://*']}
          onShouldStartLoadWithRequest={allow}
          setSupportMultipleWindows={false}
          mediaPlaybackRequiresUserAction
          allowsInlineMediaPlayback={false}
          allowFileAccess={false}
          geolocationEnabled={false}
          scrollEnabled={false}
          showsVerticalScrollIndicator={false}
          showsHorizontalScrollIndicator={false}
          overScrollMode="never"
          textZoom={100}
          injectedJavaScript={FREEZE_PAGE}
          onLoadEnd={() => {
            setReady(true);
            release.current?.();
          }}
          style={styles.page}
        />
      </View>
    </View>
  );
}

const textCache = new Map<string, string>();

function useTextHead(uri: string) {
  const [text, setText] = useState(() => textCache.get(uri) ?? null);
  useEffect(() => {
    if (textCache.has(uri)) {
      setText(textCache.get(uri)!);
      return;
    }
    let alive = true;
    fetch(uri)
      .then(res => (res.ok ? res.text() : Promise.reject(new Error(String(res.status)))))
      .then(body => {
        const head = body.slice(0, TEXT_HEAD_CHARS);
        if (textCache.size >= TEXT_CACHE_MAX) {
          textCache.delete(textCache.keys().next().value!);
        }
        textCache.set(uri, head);
        if (alive) {
          setText(head);
        }
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [uri]);
  return text;
}

/** Nothing in a thumbnail should load: pictures and embeds are dropped. */
const stripMedia = (md: string) =>
  md.replace(/!\[[^\]]*\]\([^)]*\)/g, '').replace(/<(img|video|audio|iframe)\b[^>]*>/gi, '');

function PaperThumb({uri, kind, width, height}: {uri: string; kind: string; width: number; height: number}) {
  const t = useTheme();
  const styles = useStyles();
  const paneWidth = usePaneWidth();
  const text = useTextHead(uri);
  if (!text?.trim()) {
    return null;
  }
  const scale = width / PAPER_WIDTH;
  const paper = t.isDark ? t.bg1 : '#ffffff';
  return (
    <View style={[styles.frame, {backgroundColor: paper}]}>
      <View
        style={[styles.paper, styles.scaled, {height: Math.ceil(height / scale), transform: [{scale}]}]}>
        {kind === 'markdown' ? (
          <Markdown value={stripMedia(text)} inset={Math.max(0, paneWidth - (PAPER_WIDTH - PAPER_PAD_X * 2))} />
        ) : (
          // Wider than the paper, so lines are cut at the edge instead of wrapping.
          <View style={styles.monoBox}>
            <Text style={styles.mono}>{text.split('\n').slice(0, TEXT_HEAD_LINES).join('\n')}</Text>
          </View>
        )}
      </View>
      <Svg style={StyleSheet.absoluteFill}>
        <Defs>
          <LinearGradient id="fade" x1="0" y1="0" x2="0" y2="1">
            <Stop offset="0.6" stopColor={paper} stopOpacity="0" />
            <Stop offset="1" stopColor={paper} stopOpacity="1" />
          </LinearGradient>
        </Defs>
        <Rect width="100%" height="100%" fill="url(#fade)" />
      </Svg>
    </View>
  );
}

const useStyles = makeStyles(t => ({
  frame: {...StyleSheet.absoluteFillObject, overflow: 'hidden', backgroundColor: '#ffffff'},
  hidden: {opacity: 0},
  scaled: {transformOrigin: 'top left'},
  page: {flex: 1, backgroundColor: '#ffffff'},
  paper: {
    width: PAPER_WIDTH,
    paddingHorizontal: PAPER_PAD_X,
    paddingVertical: PAPER_PAD_Y,
    overflow: 'hidden',
  },
  monoBox: {width: PAPER_WIDTH * 3},
  mono: {fontFamily: MONO, fontSize: 12.5, lineHeight: 19, color: t.t2},
}));
