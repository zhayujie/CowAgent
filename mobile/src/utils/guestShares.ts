import {getLang, tr, trf} from '../i18n';
import type {GuestShare, GuestShareConfig, GuestShareStatus} from '../protocol/resources';

export const SHARE_TOOLS = ['read', 'ls', 'search_files', 'write', 'edit', 'send', 'web_search', 'web_fetch', 'vision', 'time'];
export const SHARE_DEFAULT_TOOLS = ['read', 'ls', 'search_files', 'web_fetch', 'vision', 'time'];
const NETWORK_TOOLS = ['web_search', 'web_fetch'];
export const SHARE_MAX_QUESTIONS = 6;
export const SHARE_DEFAULT_QUOTA = 100;
export const SHARE_PASSWORD_MIN = 6;
export const SHARE_DEFAULT_COLOR = '#4abe6e';
export const SHARE_COLORS = ['#14b8a6', '#3b82f6', '#6366f1', '#8b5cf6', '#ec4899', '#f97316', '#475569'];
const FOOTER_TEXT = 'Powered by CowAgent';
const FOOTER_URL = 'https://cowagent.ai';

export const TOOL_LABEL: Record<string, string> = {
  get read() {
    return tr('share_tool_read');
  },
  get ls() {
    return tr('share_tool_ls');
  },
  get search_files() {
    return tr('share_tool_search_files');
  },
  get write() {
    return tr('share_tool_write');
  },
  get edit() {
    return tr('share_tool_edit');
  },
  get send() {
    return tr('share_tool_send');
  },
  get web_search() {
    return tr('share_tool_web_search');
  },
  get web_fetch() {
    return tr('share_tool_web_fetch');
  },
  get vision() {
    return tr('share_tool_vision');
  },
  get time() {
    return tr('share_tool_time');
  },
};

// Language names stay in their own language.
export const SHARE_LANGUAGES: {value: string; label: string}[] = [
  {
    value: '',
    get label() {
      return tr('share_language_auto');
    },
  },
  {value: 'zh', label: '简体中文'},
  {value: 'zh-Hant', label: '繁體中文'},
  {value: 'en', label: 'English'},
];

export const STATUS_LABEL: Record<GuestShareStatus, string> = {
  get active() {
    return tr('share_status_active');
  },
  get unconfirmed() {
    return tr('share_status_unconfirmed');
  },
  get password_missing() {
    return tr('share_status_password_missing');
  },
  get disabled() {
    return tr('share_status_disabled');
  },
  get expired() {
    return tr('share_status_expired');
  },
};

export const shareConfig = (share: GuestShare): GuestShareConfig => share.effective_config || share.file_config || {};

export const shareUrl = (share: GuestShare, base: string): string =>
  share.share_token ? `${base.replace(/\/+$/, '')}/share/${share.share_token}` : '';

export function shareChips(share: GuestShare): string[] {
  const cfg = shareConfig(share);
  const quota = cfg.limits?.daily_messages ?? SHARE_DEFAULT_QUOTA;
  const refs = cfg.references ?? [];
  const origins = cfg.access?.allowed_origins ?? [];
  return [
    tr(cfg.access?.password_required ? 'share_chip_password' : 'share_chip_public'),
    quota ? trf('share_chip_quota', {n: quota}) : tr('share_chip_unlimited'),
    trf('share_chip_tools', {n: (cfg.tools ?? []).length}),
    ...(refs.length ? [trf('share_chip_refs', {n: refs.length})] : []),
    ...(cfg.expires_at ? [trf('share_chip_expires', {date: cfg.expires_at.slice(0, 10)})] : []),
    ...(origins.length ? [trf('share_chip_embed', {n: origins.length})] : []),
  ];
}

export interface ShareDraft {
  name: string;
  language: string;
  welcome: string;
  questions: string[];
  /** `provider|model`, or '' to follow the default model. */
  model: string;
  color: string;
  passwordRequired: boolean;
  password: string;
  quota: string;
  expires: string;
  tools: string[];
  skills: string[];
  references: {path: string; note: string}[];
  rules: string;
  footerText: string;
  footerUrl: string;
}

/** A new page starts in the app's language with two starter questions, like the console. */
export function draftFromConfig(share: GuestShare | null, cfg: GuestShareConfig, rules: string): ShareDraft {
  const brand = cfg.branding ?? {};
  const quota = cfg.limits?.daily_messages;
  const language = share ? cfg.language ?? '' : getLang();
  return {
    name: cfg.name ?? '',
    language: SHARE_LANGUAGES.some(l => l.value === language) ? language : '',
    welcome: cfg.welcome ?? '',
    questions: (cfg.suggested_questions ?? []).slice(0, SHARE_MAX_QUESTIONS),
    model: cfg.model ? `${cfg.provider ?? ''}|${cfg.model}` : '',
    color: brand.color ?? '',
    passwordRequired: !!cfg.access?.password_required,
    password: '',
    quota: String(quota === undefined ? SHARE_DEFAULT_QUOTA : quota),
    expires: (cfg.expires_at ?? '').slice(0, 10),
    tools: Array.isArray(cfg.tools) ? cfg.tools.slice() : SHARE_DEFAULT_TOOLS.slice(),
    skills: Array.isArray(cfg.skills) ? cfg.skills.slice() : [],
    references: (cfg.references ?? []).map(r => ({path: r.path ?? '', note: r.note ?? ''})),
    rules,
    footerText: brand.footer_text === undefined ? FOOTER_TEXT : brand.footer_text,
    footerUrl: brand.footer_url === undefined ? FOOTER_URL : brand.footer_url,
  };
}

export const newShareDraft = () =>
  draftFromConfig(null, {suggested_questions: [tr('share_default_q1'), tr('share_default_q2')]}, '');

function validDate(s: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) {
    return false;
  }
  const d = new Date(`${s}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === s;
}

/** The first problem that blocks saving, or null. */
export function validateDraft(d: ShareDraft, passwordSet: boolean): string | null {
  if (!d.name.trim()) {
    return tr('share_name_required');
  }
  if (d.passwordRequired && d.password && d.password.length < SHARE_PASSWORD_MIN) {
    return trf('share_password_short', {min: SHARE_PASSWORD_MIN});
  }
  if (d.passwordRequired && !d.password && !passwordSet) {
    return tr('share_password_required');
  }
  const q = d.quota.trim();
  if (q && (!/^\d+$/.test(q) || !Number.isSafeInteger(Number(q)))) {
    return tr('share_quota_invalid');
  }
  if (d.expires.trim() && !validDate(d.expires.trim())) {
    return tr('share_expires_invalid');
  }
  const url = d.footerUrl.trim();
  if (url && !/^https?:\/\/[^\s<>"']+$/i.test(url)) {
    return tr('share_footer_url_invalid');
  }
  return null;
}

/** Starts from the stored config so fields this form does not show survive a save. */
export function buildShareConfig(d: ShareDraft, raw: GuestShareConfig | undefined): GuestShareConfig {
  const base: GuestShareConfig = raw ? JSON.parse(JSON.stringify(raw)) : {};
  const cut = d.model.indexOf('|');
  const q = d.quota.trim();
  return {
    ...base,
    name: d.name.trim(),
    language: d.language,
    welcome: d.welcome.trim(),
    suggested_questions: d.questions.map(s => s.trim()).filter(Boolean),
    provider: d.model ? d.model.slice(0, cut) : '',
    model: d.model ? d.model.slice(cut + 1) : '',
    tools: d.tools.slice(),
    skills: d.skills.slice(),
    references: d.references.map(r => ({path: r.path.trim(), note: r.note.trim()})).filter(r => r.path),
    expires_at: d.expires.trim(),
    limits: {...(base.limits ?? {}), daily_messages: q === '' ? SHARE_DEFAULT_QUOTA : Number(q)},
    access: {...(base.access ?? {}), password_required: d.passwordRequired},
    network: {...(base.network ?? {}), enabled: d.tools.some(id => NETWORK_TOOLS.includes(id))},
    branding: {...(base.branding ?? {}), color: d.color, footer_text: d.footerText.trim(), footer_url: d.footerUrl.trim()},
  };
}

/** The share API answers in English; keyed by reason code, else by message. */
const FAILURES: Record<string, string> = {
  get console_password() {
    return tr('share_err_console_password');
  },
  get 'Password must be at least 6 characters.'() {
    return trf('share_password_short', {min: SHARE_PASSWORD_MIN});
  },
  get 'A profile with this id already exists.'() {
    return tr('share_err_exists');
  },
  get 'Not found'() {
    return tr('share_err_not_found');
  },
};

export const shareFailure = (reason: string | undefined, message: string) =>
  (reason && FAILURES[reason]) || FAILURES[message] || message;

export const toggleIn = (list: string[], item: string) =>
  list.includes(item) ? list.filter(x => x !== item) : [...list, item];
