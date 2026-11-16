import type {GuestShare} from '../src/protocol/resources';
import {
  buildShareConfig,
  draftFromConfig,
  newShareDraft,
  SHARE_DEFAULT_TOOLS,
  shareChips,
  shareFailure,
  shareUrl,
  validateDraft,
} from '../src/utils/guestShares';

const share = (over: Partial<GuestShare> = {}): GuestShare => ({
  slug: 'help',
  name: '产品咨询',
  status: 'active',
  share_token: 'tok',
  password_set: false,
  disabled: false,
  pending: [],
  notices: [],
  file_config: {},
  effective_config: {},
  ...over,
});

describe('draftFromConfig', () => {
  it('gives a new page Chinese, default tools and two starter questions', () => {
    const d = newShareDraft();
    expect(d.language).toBe('zh');
    expect(d.tools).toEqual(SHARE_DEFAULT_TOOLS);
    expect(d.questions).toHaveLength(2);
    expect(d.quota).toBe('100');
    expect(d.footerText).toBe('Powered by CowAgent');
  });

  it('reads an existing page, keeping an explicit empty tool list', () => {
    const cfg = {
      name: 'A',
      provider: 'openai',
      model: 'gpt-a',
      tools: [],
      limits: {daily_messages: 0},
      expires_at: '2026-12-31T00:00:00',
      branding: {footer_text: ''},
    };
    const d = draftFromConfig(share(), cfg, 'rules');
    expect(d.model).toBe('openai|gpt-a');
    expect(d.tools).toEqual([]);
    expect(d.quota).toBe('0');
    expect(d.expires).toBe('2026-12-31');
    expect(d.footerText).toBe('');
    expect(d.language).toBe('');
    expect(d.rules).toBe('rules');
  });
});

describe('validateDraft', () => {
  const ok = {...newShareDraft(), name: 'A'};

  it('accepts a complete draft', () => {
    expect(validateDraft(ok, false)).toBeNull();
  });

  it('flags each problem', () => {
    expect(validateDraft({...ok, name: ' '}, false)).toBe('请填写名称');
    expect(validateDraft({...ok, passwordRequired: true}, false)).toBe('请设置访问密码');
    expect(validateDraft({...ok, passwordRequired: true}, true)).toBeNull();
    expect(validateDraft({...ok, passwordRequired: true, password: '123'}, true)).toContain('至少 6 位');
    expect(validateDraft({...ok, quota: '1.5'}, false)).toContain('整数');
    expect(validateDraft({...ok, expires: '2026-02-30'}, false)).toContain('格式');
    expect(validateDraft({...ok, expires: '2026-02-28'}, false)).toBeNull();
    expect(validateDraft({...ok, footerUrl: 'cowagent.ai'}, false)).toContain('页脚链接');
  });
});

describe('buildShareConfig', () => {
  it('keeps unknown stored fields and derives network access from tools', () => {
    const raw = {embed: {allowed_origins: ['https://a.com']}, limits: {daily_messages: 5, burst: 2}, custom_flag: true};
    const d = {...newShareDraft(), name: ' A ', model: 'openai|gpt-a', tools: ['read', 'web_search'], quota: ''};
    const cfg = buildShareConfig(d, raw);
    expect(cfg.custom_flag).toBe(true);
    expect(cfg.embed).toEqual({allowed_origins: ['https://a.com']});
    expect(cfg.limits).toEqual({daily_messages: 100, burst: 2});
    expect(cfg.network).toEqual({enabled: true});
    expect(cfg.name).toBe('A');
    expect(cfg.provider).toBe('openai');
    expect(cfg.model).toBe('gpt-a');
    expect(raw.limits.daily_messages).toBe(5);
  });

  it('follows the default model when none is picked', () => {
    const cfg = buildShareConfig({...newShareDraft(), name: 'A', tools: ['read']}, undefined);
    expect(cfg.provider).toBe('');
    expect(cfg.model).toBe('');
    expect(cfg.network).toEqual({enabled: false});
    expect(cfg.suggested_questions).toHaveLength(2);
  });
});

it('shareUrl needs a token', () => {
  expect(shareUrl(share(), 'http://h:9899/')).toBe('http://h:9899/share/tok');
  expect(shareUrl(share({share_token: ''}), 'http://h')).toBe('');
});

it('shareChips summarises access, quota, tools and extras', () => {
  const s = share({
    effective_config: {
      access: {password_required: true, allowed_origins: ['https://a.com', 'https://b.com']},
      limits: {daily_messages: 0},
      tools: ['read', 'ls'],
      references: [{path: '/a'}],
      expires_at: '2026-12-31',
    },
  });
  expect(shareChips(s)).toEqual(['需要密码', '提问不限次数', '2 个工具', '1 份参考资料', '有效期至 2026-12-31', '2 个嵌入网站']);
  expect(shareChips(share())).toEqual(['公开访问', '每人每日 100 次', '0 个工具']);
});

it('shareFailure translates known reasons and messages', () => {
  expect(shareFailure('console_password', 'x')).toContain('不能与');
  expect(shareFailure(undefined, 'Not found')).toContain('不存在');
  expect(shareFailure(undefined, 'Something else')).toBe('Something else');
});
