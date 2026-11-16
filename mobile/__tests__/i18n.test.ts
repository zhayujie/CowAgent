import {getLang, localizedLabel, tr, trf, useLangStore} from '../src/i18n';
import {MESSAGE_MODULES} from '../src/i18n/messages';

const placeholders = (s: string) => (s.match(/\{\w+\}/g) ?? []).sort();

describe('message modules', () => {
  it('never define the same key twice', () => {
    const seen = new Map<string, string>();
    for (const [name, mod] of Object.entries(MESSAGE_MODULES)) {
      for (const key of Object.keys(mod.zh)) {
        expect([key, seen.get(key)]).toEqual([key, undefined]);
        seen.set(key, name);
      }
    }
  });

  it('carry the same keys in both languages', () => {
    for (const mod of Object.values(MESSAGE_MODULES)) {
      expect(Object.keys(mod.en).sort()).toEqual(Object.keys(mod.zh).sort());
    }
  });

  it('use the same placeholders in both languages', () => {
    for (const mod of Object.values(MESSAGE_MODULES)) {
      const zh = mod.zh as Record<string, string>;
      const en = mod.en as Record<string, string>;
      for (const key of Object.keys(zh)) {
        // English dates name the month instead of numbering it.
        const zhVars = placeholders(zh[key]).filter(v => v !== '{month}');
        const enVars = placeholders(en[key]).filter(v => v !== '{monthName}');
        expect([key, enVars]).toEqual([key, zhVars]);
      }
    }
  });
});

describe('translation', () => {
  afterEach(() => useLangStore.getState().setLang('zh'));

  it('follows the selected language', () => {
    expect(tr('common_cancel')).toBe('取消');
    useLangStore.getState().setLang('en');
    expect(getLang()).toBe('en');
    expect(tr('common_cancel')).toBe('Cancel');
  });

  it('fills every placeholder', () => {
    expect(trf('common_today_at', {time: '09:30'})).toBe('今天 09:30');
  });

  it('picks the matching side of a server label', () => {
    const label = {zh: '通道', en: 'Channels'};
    expect(localizedLabel(label)).toBe('通道');
    useLangStore.getState().setLang('en');
    expect(localizedLabel(label)).toBe('Channels');
    expect(localizedLabel({zh: '仅中文'})).toBe('仅中文');
    expect(localizedLabel(undefined, 'fallback')).toBe('fallback');
  });
});
