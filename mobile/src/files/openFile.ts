import {Linking, NativeModules, Platform, Share} from 'react-native';
import {create} from 'zustand';
import {showToast} from '../components/Toast';
import {serverUrl} from '../api/cowApi';
import {tr, trf, type MessageKey} from '../i18n';
import {openWebPage, withoutLoginToken} from '../navigation/openWeb';
import {navigationRef} from '../navigation/ref';
import {useAgentStore} from '../store/agentStore';
import {useChatStore} from '../store/chatStore';
import {copyText} from '../utils/clipboard';
import {
  type ChatFile,
  fileKeyOf,
  isUnsandboxedPage,
  outsideLinkOf,
  rawUrlOf,
  resolveFile,
  serverFileRef,
  viewUrlOf,
  withPreview,
} from './chatFile';
import {cowNative, nativeError} from '../media/cowNative';
import {canWriteDownloads} from './downloadPermission';
import {downloadKey, listenForDownloadProgress, useDownloadStore} from './downloadStore';

/** Read as text or rendered as a page on the preview screen. */
const IN_APP = new Set(['markdown', 'text', 'csv', 'code', 'html']);

/** Played or paged through on the preview screen. */
export const MEDIA_KINDS = new Set(['pdf', 'video', 'audio']);

export const canPreviewInApp = (f: ChatFile) => f.kind === 'image' || IN_APP.has(f.kind) || MEDIA_KINDS.has(f.kind);

/** The picture shown full screen. */
export const useImageViewer = create<{
  file: ChatFile | null;
  show: (file: ChatFile) => void;
  close: () => void;
}>(set => ({
  file: null,
  show: file => set({file}),
  close: () => set({file: null}),
}));

/** Only where nothing native can save: the system keeps the file. */
function saveWithSystem(url: string) {
  if (!url) {
    showToast(tr('file_no_url'));
    return;
  }
  Linking.openURL(url).catch(() => showToast(tr('file_cannot_open')));
}

/** Runs `then` with a page that is safe to render, once its preview link is known. */
function sandboxed(f: ChatFile, then: (page: ChatFile) => void) {
  withPreview(f).then(page => (page ? then(page) : showToast(tr('file_page_unsafe'))));
}

/** The file as the web view shows it, which handles formats the preview screen does not. */
export function openAsWebPage(f: ChatFile) {
  if (isUnsandboxedPage(f)) {
    sandboxed(f, openAsWebPage);
    return;
  }
  // Asked from the full-screen picture, which would otherwise stay over the page.
  useImageViewer.getState().close();
  openWebPage(viewUrlOf(f), f.name);
}

/**
 * The file in the system browser. Without a link that works outside the app the
 * app's own web page shows it, so the login token never reaches the browser.
 */
export async function openInBrowser(f: ChatFile) {
  const url = withoutLoginToken(await outsideLinkOf(f));
  if (!url) {
    openAsWebPage(f);
    return;
  }
  Linking.openURL(url).catch(() => showToast(tr('file_cannot_open')));
}

const nativeShare: {share(source: string, fileName: string, mime: string): Promise<unknown>} | undefined =
  NativeModules.CowDownloads?.share ? NativeModules.CowDownloads : undefined;

/**
 * The system share sheet with the file itself on Android and iOS, so a chat app receives the file
 * rather than a link that only opens where the server is reachable. Elsewhere, its link.
 */

export async function shareFile(f: ChatFile) {
  const raw = rawUrlOf(f);
  if (nativeShare && /^https?:/i.test(raw)) {
    const slow = setTimeout(() => showToast(tr('file_share_preparing')), 500);
    try {
      await nativeShare.share(raw, f.name, '');
      return;
    } catch {
      // Falls back to the link below.
    } finally {
      clearTimeout(slow);
    }
  }
  const url = withoutLoginToken(await outsideLinkOf(f));
  if (!url) {
    showToast(tr('file_share_no_link'));
    return;
  }
  try {
    // Android shares only the message; iOS, HarmonyOS and the web take the link itself.
    await Share.share(
      Platform.OS === 'android' ? {title: f.name, message: `${f.name}\n${url}`} : {title: f.name, url},
      {dialogTitle: f.name, subject: f.name},
    );
  } catch (e) {
    if (e instanceof Error && e.name === 'AbortError') {
      return;
    }
    const ok = await copyText(url);
    showToast(ok ? tr('share_link_copied') : tr('file_share_failed'));
  }
}

/** Where a native save put the file; null when the user backed out of the iOS share sheet. */
type SavedTo = 'downloads' | 'photos' | 'files' | 'other' | 'present' | null;

/** The file name at the end of a URL, decoded; empty when there is none. */
function nameFromUrl(url: string): string {
  const name = url.split(/[?#]/)[0].split('/').pop() || '';
  try {
    return decodeURIComponent(name);
  } catch {
    return name;
  }
}

/**
 * Native saving, http(s) only: Android queues the system downloader into Downloads,
 * iOS downloads first and then offers the share sheet, HarmonyOS streams into
 * Downloads/<app name>. All settle once the file is kept.
 */
const nativeDownloads = NativeModules.CowDownloads;
const systemDownloads:
  | {
      save(url: string, fileName: string, id: string): Promise<SavedTo>;
      open?(url: string, fileName: string, id: string): Promise<'opened' | 'downloads' | 'present'>;
    }
  | undefined =
  Platform.OS === 'android'
    ? nativeDownloads
    : nativeDownloads
      ? {
          // iOS predates progress ids and still exports the original two-argument method.
          save: (url: string, fileName: string) => nativeDownloads.save(url, fileName),
        }
      : cowNative
        ? {
            save: (url, fileName) =>
              cowNative!.saveDownload(url, fileName || nameFromUrl(url)).then(
                () => 'downloads' as const,
                (e: unknown) => {
                  throw nativeError(e);
                },
              ),
          }
        : undefined;

const savesNatively = (url: string) => !!systemDownloads && /^https?:/i.test(url);

const SAVED_TOAST: Partial<Record<NonNullable<SavedTo>, MessageKey>> = {
  downloads: 'file_saved_downloads',
  photos: 'file_saved_photos',
  files: 'file_saved_files',
  present: 'file_saved_already',
};

/**
 * The status the server or the socket gave, when it named one. Telling a reader "HTTP 403"
 * instead of "failed" is the difference between a retry and a bug report.
 */
function failureReason(e: unknown): string {
  const message = e instanceof Error ? e.message : String(e ?? '');
  const code = /HTTP\s+(\d{3})/i.exec(message);
  if (code) {
    return `HTTP ${code[1]}`;
  }
  if (/timeout|timed out|ETIMEDOUT/i.test(message)) {
    return tr('file_download_timeout');
  }
  return '';
}

const activeDownloads = new Map<string, Promise<SavedTo>>();
const activeOpens = new Map<string, Promise<'opened' | 'downloads' | 'present'>>();

/**
 * An empty `fileName` leaves the name to the native side, which can read the server's on iOS.
 * `key` and `expected` come from the file itself when there is one; a bare link has neither.
 */
async function saveToDownloads(url: string, name: string, fileName = name, key?: string, expected?: number) {
  const id = key || downloadKey(url, fileName || name);
  const running = activeDownloads.get(id);
  if (running) {
    // Repeated taps join the same request instead of creating another Downloads entry.
    return running;
  }
  if (!(await canWriteDownloads())) {
    showToast(tr('file_download_no_permission'));
    return;
  }
  listenForDownloadProgress();
  useDownloadStore.getState().start(id, url, name, expected);
  const work = systemDownloads!.save(url, fileName, id);
  activeDownloads.set(id, work);
  try {
    const savedTo = await work;
    if (savedTo === null) {
      useDownloadStore.getState().clear(id);
      return;
    }
    useDownloadStore.getState().finish(id);
    const message = savedTo ? SAVED_TOAST[savedTo] : undefined;
    if (message) {
      showToast(tr(message));
    }
  } catch (e) {
    useDownloadStore.getState().fail(id);
    const reason = failureReason(e);
    showToast(reason ? trf('file_download_failed_reason', {reason}) : tr('file_download_failed'));
  } finally {
    activeDownloads.delete(id);
  }
}

/** A link the server answers with a file, such as the full log or a download inside a web page. */
export function downloadUrl(url: string, name?: string) {
  if (!savesNatively(url)) {
    saveWithSystem(url);
    return;
  }
  if (name) {
    saveToDownloads(url, name);
    return;
  }
  saveToDownloads(url, nameFromUrl(url) || tr('file_download'), '');
}

/** Saved natively on Android and iOS, through an anchor on the web, and by the system elsewhere. */
export function downloadFile(f: ChatFile) {
  const url = rawUrlOf(f);
  if (savesNatively(url)) {
    saveToDownloads(url, f.name, f.name, fileKeyOf(f), f.size);
    return;
  }
  if (Platform.OS === 'web' && url && typeof document !== 'undefined') {
    const a = document.createElement('a');
    a.href = url;
    a.download = f.name;
    // Cross-origin the browser ignores `download` and navigates; keep the app.
    a.target = '_blank';
    a.rel = 'noopener';
    document.body.appendChild(a);
    a.click();
    a.remove();
    return;
  }
  // A browser renders HTML rather than saving it.
  if (f.kind === 'html') {
    openAsWebPage(f);
    return;
  }
  saveWithSystem(url);
}

/**
 * Android only: downloads the file and lets the system "open with" chooser hand it to
 * Word/WPS. Elsewhere the browser takes the link, since no such chooser exists.
 */
export async function openWithSystem(f: ChatFile) {
  const url = rawUrlOf(f);
  if (Platform.OS !== 'android' || !systemDownloads?.open || !savesNatively(url)) {
    openInBrowser(f);
    return;
  }
  if (!(await canWriteDownloads())) {
    showToast(tr('file_download_no_permission'));
    return;
  }
  const id = fileKeyOf(f);
  const running = activeOpens.get(id);
  if (running) {
    return running;
  }
  listenForDownloadProgress();
  useDownloadStore.getState().start(id, url, f.name, f.size);
  const work = systemDownloads.open(url, f.name, id);
  activeOpens.set(id, work);
  try {
    const result = await work;
    useDownloadStore.getState().finish(id);
    // Nothing took the file, so say where it went instead of implying it opened.
    if (result === 'present') {
      showToast(tr('file_saved_already'));
    } else if (result === 'downloads') {
      showToast(tr('file_open_no_app'));
    } else if (result !== 'opened') {
      showToast(tr('file_saved_files'));
    }
  } catch (e) {
    useDownloadStore.getState().fail(id);
    const reason = failureReason(e);
    showToast(reason ? trf('file_download_failed_reason', {reason}) : tr('file_download_failed'));
  } finally {
    activeOpens.delete(id);
  }
}

/** One tap on a file: it always opens in the app; formats it cannot render get a page to save them from. */
export function openFile(f: ChatFile) {
  if (isUnsandboxedPage(f)) {
    sandboxed(f, openFile);
    return;
  }
  if (f.kind === 'image') {
    useImageViewer.getState().show(f);
    return;
  }
  if (navigationRef.isReady()) {
    navigationRef.navigate('FilePreview', {file: f});
    return;
  }
  downloadFile(f);
}

/** The artifacts page, narrowed to this one file. */
export function viewInArtifacts(f: ChatFile) {
  if (f.path && navigationRef.isReady()) {
    // Asked from the full-screen picture, which would otherwise stay over the page.
    useImageViewer.getState().close();
    navigationRef.navigate('Artifacts', {focusPath: f.path, focusName: f.name});
  }
}

/** Reply text is model output; other schemes could launch apps or run `javascript:` on web. */
const SAFE_LINK = /^(https?:|mailto:|tel:)/i;

/** A link inside a reply: a file on the server opens like a file card, the web in the app's web page. */
export function openLink(href: string) {
  const ref = serverFileRef(href);
  if (ref) {
    openFileRef(ref);
    return;
  }
  const url = href.startsWith('/') ? serverUrl(href) : href.trim();
  if (!SAFE_LINK.test(url)) {
    showToast(tr('file_link_unsupported'));
    return;
  }
  openWebPage(url);
}

/** A file a reply only names: find it on the server, then open it like any other. */
export async function openFileRef(ref: string) {
  const sessionId = useChatStore.getState().currentSessionId ?? undefined;
  const agentId = useAgentStore.getState().currentId ?? undefined;
  const slow = setTimeout(() => showToast(tr('file_finding')), 400);
  try {
    const f = await resolveFile(ref, sessionId, agentId);
    if (f) {
      openFile(f);
      return;
    }
  } catch {
    // Falls through to the notice below.
  } finally {
    clearTimeout(slow);
  }
  showToast(tr('file_not_found'));
}
