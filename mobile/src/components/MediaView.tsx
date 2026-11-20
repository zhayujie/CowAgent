import React, {useMemo} from 'react';
import {Platform, StyleSheet} from 'react-native';
import {WebView, type WebViewMessageEvent} from 'react-native-webview';
import {fileHttpError} from '../files/chatFile';
import {tr} from '../i18n';
import {useTheme} from '../theme/theme';

export type MediaKind = 'pdf' | 'video' | 'audio';

// The same files on both CDNs; the second is the one reachable from mainland China.
// Pinned by hash, since the page runs as the CowAgent server's origin.
const PDFJS_BASES = [
  'https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/legacy/build',
  'https://registry.npmmirror.com/pdfjs-dist/3.11.174/files/legacy/build',
];
const PDFJS_LIB = {name: 'pdf.min.js', sri: 'sha384-OemFRmhjDZwhIKuUld0HJozkF2YErsgDaCL41trxGQZt4/WgnopJQqQl2DvDZ07Z'};
const PDFJS_WORKER = {
  name: 'pdf.worker.min.js',
  sri: 'sha384-sS8B4COeBqzQV9DaPpp5cbpF+xz2jPcFbN3L8FL3/dx0RMC6WLUwTUOFm0iFb1lw',
};

const originOf = (url: string) => /^(https?:\/\/[^/]+)/i.exec(url)?.[1] ?? undefined;

/** A value safe to drop into an inline script. */
const literal = (v: unknown) => JSON.stringify(v).replace(/</g, '\\u003c');

const PAGE_HEAD =
  '<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=5">' +
  '<style>html,body{margin:0;height:100%;-webkit-touch-callout:none;-webkit-user-select:none;user-select:none}</style>';

/** A finger held still on the page posts `longpress`; the web view hides touches from React Native. */
const LONG_PRESS_SCRIPT = `<script>(function(){var timer=null,x=0,y=0;
function clear(){if(timer){clearTimeout(timer);timer=null;}}
document.addEventListener('touchstart',function(e){clear();if(e.touches.length!==1)return;x=e.touches[0].clientX;y=e.touches[0].clientY;
timer=setTimeout(function(){timer=null;window.ReactNativeWebView.postMessage('longpress');},500);},{passive:true});
document.addEventListener('touchmove',function(e){var p=e.touches[0];if(p&&(Math.abs(p.clientX-x)>10||Math.abs(p.clientY-y)>10))clear();},{passive:true});
document.addEventListener('touchend',clear);document.addEventListener('touchcancel',clear);
document.addEventListener('contextmenu',function(e){e.preventDefault();});})();</script>`;

function mediaPage(uri: string, kind: 'video' | 'audio', dark: boolean): string {
  const bg = kind === 'video' || dark ? '#000' : '#fff';
  const tag =
    kind === 'video'
      ? `<video src=${literal(uri)} controls playsinline webkit-playsinline preload="metadata" style="width:100%;height:100%;object-fit:contain"></video>`
      : `<audio src=${literal(uri)} controls preload="metadata" style="width:86%"></audio>`;
  return `<!doctype html><html><head>${PAGE_HEAD}<style>body{display:flex;align-items:center;justify-content:center;background:${bg}}</style></head><body>${tag}
<script>(function(){var el=document.querySelector('video,audio'),post=function(m){window.ReactNativeWebView.postMessage(m);};
el.addEventListener('loadedmetadata',function(){post('ready');});el.addEventListener('error',function(){post('error');});})();</script>${LONG_PRESS_SCRIPT}</body></html>`;
}

/**
 * Android's WebView has no PDF viewer, so pages are drawn with pdf.js.
 *
 * Both scripts load with SRI. With the worker script already on the page pdf.js
 * parses on the main thread instead of fetching it unchecked into a Worker.
 * `isEvalSupported: false` closes CVE-2024-4367 (script in a crafted font).
 */
export function pdfPage(uri: string): string {
  return `<!doctype html><html><head>${PAGE_HEAD}<meta name="referrer" content="no-referrer"><style>body{background:#f2f3f5}canvas{display:block;width:100%;margin:0 0 8px;background:#fff}</style>
</head><body><div id="pages"></div>
<script>(function(){var post=function(m){window.ReactNativeWebView.postMessage(m);};
var bases=${literal(PDFJS_BASES)};
function load(src,sri){return new Promise(function(ok,fail){var s=document.createElement('script');
s.src=src;s.integrity=sri;s.crossOrigin='anonymous';s.onload=ok;s.onerror=fail;document.head.appendChild(s);});}
function pick(file,i){i=i||0;if(i>=bases.length)return Promise.reject(new Error(file.name));
return load(bases[i]+'/'+file.name,file.sri).catch(function(){return pick(file,i+1);});}
pick(${literal(PDFJS_LIB)}).then(function(){return pick(${literal(PDFJS_WORKER)});}).then(function(){
if(!window.pdfjsLib||!window.pdfjsWorker)throw new Error('pdf.js');
return pdfjsLib.getDocument({url:${literal(uri)},isEvalSupported:false}).promise;}).then(function(doc){
var box=document.getElementById('pages'),scale=window.devicePixelRatio||2,n=0;
function next(){n+=1;if(n>doc.numPages)return;doc.getPage(n).then(function(page){
var base=page.getViewport({scale:1}),vp=page.getViewport({scale:document.body.clientWidth/base.width*scale});
var c=document.createElement('canvas');c.width=vp.width;c.height=vp.height;box.appendChild(c);
return page.render({canvasContext:c.getContext('2d'),viewport:vp}).promise;}).then(function(){if(n===1)post('ready');next();});}
next();}).catch(function(){post('error');});})();</script>${LONG_PRESS_SCRIPT}</body></html>`;
}

/** A PDF, video or audio file played inside the app instead of handed to the system. */
export function MediaView({
  uri,
  kind,
  onError,
  onProgress,
  onReady,
  onLongPress,
}: {
  uri: string;
  kind: MediaKind;
  onError?: (message: string) => void;
  onProgress?: (fraction: number) => void;
  onReady?: () => void;
  /** Not on iOS PDFs, which load as the file itself rather than a page of ours. */
  onLongPress?: () => void;
}) {
  const t = useTheme();
  const source = useMemo(() => {
    if (kind === 'pdf' && Platform.OS === 'ios') {
      return {uri};
    }
    const html = kind === 'pdf' ? pdfPage(uri) : mediaPage(uri, kind, t.isDark);
    return {html, baseUrl: originOf(uri)};
  }, [uri, kind, t.isDark]);

  const onMessage = (e: WebViewMessageEvent) => {
    if (e.nativeEvent.data === 'ready') {
      onReady?.();
    } else if (e.nativeEvent.data === 'longpress') {
      onLongPress?.();
    } else if (e.nativeEvent.data === 'error') {
      onError?.(kind === 'pdf' ? tr('media_pdf_failed') : tr('media_load_failed'));
    }
  };

  return (
    <WebView
      source={source}
      originWhitelist={['*']}
      allowsInlineMediaPlayback
      // Without this Android ignores the player's fullscreen button.
      allowsFullscreenVideo
      setSupportMultipleWindows={false}
      onMessage={onMessage}
      onLoadProgress={e => onProgress?.(e.nativeEvent.progress)}
      onLoadEnd={() => 'uri' in source && onReady?.()}
      onError={e => onError?.(e.nativeEvent.description || tr('media_page_failed'))}
      onHttpError={e => onError?.(fileHttpError(e.nativeEvent.statusCode))}
      style={[styles.web, {backgroundColor: kind === 'video' ? '#000' : t.bg0}]}
    />
  );
}

const styles = StyleSheet.create({
  web: {flex: 1},
});
