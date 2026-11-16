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
  read: '读取文件',
  ls: '浏览目录',
  search_files: '搜索文件',
  write: '写入文件',
  edit: '编辑文件',
  send: '发送文件',
  web_search: '联网搜索',
  web_fetch: '读取网页',
  vision: '图片理解',
  time: '当前时间',
};

export const SHARE_LANGUAGES: {value: string; label: string}[] = [
  {value: '', label: '跟随访客浏览器'},
  {value: 'zh', label: '简体中文'},
  {value: 'zh-Hant', label: '繁體中文'},
  {value: 'en', label: 'English'},
];

export const STATUS_LABEL: Record<GuestShareStatus, string> = {
  active: '运行中',
  unconfirmed: '待确认',
  password_missing: '缺少密码',
  disabled: '已停用',
  expired: '已过期',
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
    cfg.access?.password_required ? '需要密码' : '公开访问',
    quota ? `每人每日 ${quota} 次` : '提问不限次数',
    `${(cfg.tools ?? []).length} 个工具`,
    ...(refs.length ? [`${refs.length} 份参考资料`] : []),
    ...(cfg.expires_at ? [`有效期至 ${cfg.expires_at.slice(0, 10)}`] : []),
    ...(origins.length ? [`${origins.length} 个嵌入网站`] : []),
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

/** A new page starts in Chinese with two starter questions, like the console. */
export function draftFromConfig(share: GuestShare | null, cfg: GuestShareConfig, rules: string): ShareDraft {
  const brand = cfg.branding ?? {};
  const quota = cfg.limits?.daily_messages;
  const language = share ? cfg.language ?? '' : 'zh';
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
  draftFromConfig(null, {suggested_questions: ['你能帮我做什么？', '怎么快速上手？']}, '');

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
    return '请填写名称';
  }
  if (d.passwordRequired && d.password && d.password.length < SHARE_PASSWORD_MIN) {
    return `访问密码至少 ${SHARE_PASSWORD_MIN} 位`;
  }
  if (d.passwordRequired && !d.password && !passwordSet) {
    return '请设置访问密码';
  }
  const q = d.quota.trim();
  if (q && (!/^\d+$/.test(q) || !Number.isSafeInteger(Number(q)))) {
    return '提问次数需要是不小于 0 的整数';
  }
  if (d.expires.trim() && !validDate(d.expires.trim())) {
    return '有效期请按 2026-12-31 的格式填写';
  }
  const url = d.footerUrl.trim();
  if (url && !/^https?:\/\/[^\s<>"']+$/i.test(url)) {
    return '页脚链接需要以 http:// 或 https:// 开头';
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
  console_password: '访客页面的密码不能与「设置 › 访问密码」相同',
  'Password must be at least 6 characters.': `访问密码至少 ${SHARE_PASSWORD_MIN} 位`,
  'A profile with this id already exists.': '已有同名的访客页面，换个名称试试',
  'Not found': '这个访客页面不存在或已被删除',
};

export const shareFailure = (reason: string | undefined, message: string) =>
  (reason && FAILURES[reason]) || FAILURES[message] || message;

export const toggleIn = (list: string[], item: string) =>
  list.includes(item) ? list.filter(x => x !== item) : [...list, item];
