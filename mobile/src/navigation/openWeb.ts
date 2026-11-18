import {Linking, Platform} from 'react-native';
import {showToast} from '../components/Toast';
import {tr} from '../i18n';
import {navigationRef} from './ref';

const WEB = /^https?:/i;

/**
 * Opens a link in the app's own web page. Other schemes (mailto:, tel:, an
 * app's own like lark://) go to the system, which hands them to that app.
 */
export function openWebPage(url: string, title?: string) {
  const target = url.trim();
  if (!target) {
    showToast(tr('file_no_url'));
    return;
  }
  // Signed out there is no web page screen; the web preview is a browser already.
  const routes = navigationRef.isReady() ? navigationRef.getRootState()?.routeNames ?? [] : [];
  if (WEB.test(target) && Platform.OS !== 'web' && routes.includes('WebPage')) {
    navigationRef.navigate('WebPage', {url: target, title});
    return;
  }
  Linking.openURL(target).catch(() => showToast(tr('file_link_unsupported')));
}

/** Whether the app's web page loads this itself rather than handing it to the system. */
export const loadsInPage = (url: string) => /^(https?:|about:|data:|blob:)/i.test(url);
