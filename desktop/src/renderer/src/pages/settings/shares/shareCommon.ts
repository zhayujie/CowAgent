import type { GuestShare, GuestShareConfig } from '../../../api/client'
import { getLang } from '../../../i18n'

export const SHARE_TOOLS = ['read', 'ls', 'search_files', 'write', 'edit', 'send', 'web_search', 'web_fetch', 'vision', 'time']
export const SHARE_DEFAULT_TOOLS = ['read', 'ls', 'search_files', 'web_fetch', 'vision', 'time']
export const SHARE_NETWORK_TOOLS = ['web_search', 'web_fetch']
export const SHARE_MAX_QUESTIONS = 6
export const SHARE_DEFAULT_QUOTA = 100
export const SHARE_ORIGIN_RE = /^https?:\/\/[a-z0-9.-]+(:\d{1,5})?$/i
export const SHARE_DEFAULT_COLOR = '#4abe6e'
export const SHARE_COLORS = ['#14b8a6', '#3b82f6', '#6366f1', '#8b5cf6', '#ec4899', '#f97316', '#475569']
export const SHARE_LOGO_TYPES = ['image/png', 'image/jpeg', 'image/webp']
export const SHARE_LOGO_MAX = 2 * 1024 * 1024
export const SHARE_FOOTER_TEXT = 'Powered by CowAgent'
export const shareFooterUrl = () => (getLang() === 'zh' ? 'https://cowagent.cn' : 'https://cowagent.ai')
/** '' follows the visitor's browser. */
export const SHARE_LANGUAGES = ['', 'zh', 'zh-Hant', 'en']
export const SHARE_LANGUAGE_NAMES: Record<string, string> = { zh: '简体中文', 'zh-Hant': '繁體中文', en: 'English' }

export const shareConfig = (share: GuestShare): GuestShareConfig =>
  share.effective_config || share.file_config || {}

export const shareUrl = (share: GuestShare, base: string): string =>
  share.share_token ? `${base}/share/${share.share_token}` : ''

export function embedSnippet(share: GuestShare, base: string): string {
  const title = (share.name || share.slug).replace(/"/g, '&quot;')
  const color = (share.file_config || share.effective_config || {}).branding?.color
  return [
    `<script src="${base}/assets/guest/embed.js"`,
    `  data-share-url="${shareUrl(share, base)}"`,
    `  data-title="${title}"`,
    ...(color ? [`  data-color="${color}"`] : []),
    '  defer>',
    '</script>',
  ].join('\n')
}

export function isLightColor(hex: string): boolean {
  const [r, g, b] = [1, 3, 5]
    .map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.45
}

export const shareTime = (ts?: number): string => (ts ? new Date(ts * 1000).toLocaleString() : '')
