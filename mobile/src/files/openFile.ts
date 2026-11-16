import {Linking, Platform} from 'react-native';
import {create} from 'zustand';
import {showToast} from '../components/Toast';
import {serverUrl} from '../api/cowApi';
import {tr} from '../i18n';
import {navigationRef} from '../navigation/ref';
import {useAgentStore} from '../store/agentStore';
import {useChatStore} from '../store/chatStore';
import {
  type ChatFile,
  isUnsandboxedPage,
  rawUrlOf,
  resolveFile,
  serverFileRef,
  viewUrlOf,
  withPreview,
} from './chatFile';

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

function openUrl(url: string) {
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

export function openInBrowser(f: ChatFile) {
  if (isUnsandboxedPage(f)) {
    sandboxed(f, openInBrowser);
    return;
  }
  openUrl(viewUrlOf(f));
}

/** Saves through the browser: a phone hands the link to the system, which keeps the file. */
export function downloadFile(f: ChatFile) {
  const url = rawUrlOf(f);
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
  // The system browser renders HTML rather than saving it.
  if (f.kind === 'html') {
    openInBrowser(f);
    return;
  }
  openUrl(url);
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
    navigationRef.navigate('Artifacts', {focusPath: f.path, focusName: f.name});
  }
}

/** Reply text is model output; other schemes could launch apps or run `javascript:` on web. */
const SAFE_LINK = /^(https?:|mailto:|tel:)/i;

/** A link inside a reply: a file on the server opens like a file card, the web in the browser. */
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
  openUrl(url);
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
