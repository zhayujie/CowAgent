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

/** The system share sheet with the file's link; where there is none, the link is copied instead. */
export async function shareFile(f: ChatFile) {
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
type SavedTo = 'downloads' | 'photos' | 'files' | 'other' | null;

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
const systemDownloads: {save(url: string, fileName: string): Promise<SavedTo>} | undefined =
  NativeModules.CowDownloads ??
  (cowNative
    ? {
        save: (url, fileName) =>
          cowNative!.saveDownload(url, fileName || nameFromUrl(url)).then(
            () => 'downloads' as const,
            (e: unknown) => {
              throw nativeError(e);
            },
          ),
      }
    : undefined);

const savesNatively = (url: string) => !!systemDownloads && /^https?:/i.test(url);

const SAVED_TOAST: Partial<Record<NonNullable<SavedTo>, MessageKey>> = {
  downloads: 'file_saved_downloads',
  photos: 'file_saved_photos',
  files: 'file_saved_files',
};

/** An empty `fileName` leaves the name to the native side, which can read the server's on iOS. */
async function saveToDownloads(url: string, name: string, fileName = name) {
  if (!(await canWriteDownloads())) {
    showToast(tr('file_download_no_permission'));
    return;
  }
  showToast(trf('file_download_started', {name}));
  try {
    const savedTo = await systemDownloads!.save(url, fileName);
    const key = savedTo ? SAVED_TOAST[savedTo] : undefined;
    if (key) {
      showToast(tr(key));
    }
  } catch {
    showToast(tr('file_download_failed'));
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
    saveToDownloads(url, f.name);
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
