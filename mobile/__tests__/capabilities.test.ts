import type {CapabilityPick, ModelsState, SearchProviderMeta} from '../src/protocol/resources';
import {
  capabilityProviders,
  capabilitySummary,
  moveItem,
  needsTypedModel,
  resolveModels,
  resolveVoices,
  searchEditor,
} from '../src/utils/capabilities';

const data: ModelsState = {
  providers: [
    {id: 'openai', label: 'OpenAI', configured: true, models: ['gpt-a', 'gpt-b']},
    {id: 'zhipu', label: {zh: '智谱'}, configured: false, models: ['glm']},
    {id: 'custom:abc', label: 'Gateway', configured: true, is_custom: true, custom_name: 'Gateway', models: []},
    {id: 'custom:empty', label: '', configured: false, is_custom: true, models: []},
  ],
  capabilities: {
    chat: {current_provider: 'openai', current_model: 'gpt-a'},
    chat_fallback: {enabled: false, chain: []},
    vision: {current_provider: '', current_model: '', fallback_provider: 'openai', fallback_model: 'gpt-b'},
    tts: {current_provider: 'openai', current_model: 'tts-1', reply_mode: 'off'},
  },
};

describe('capabilityProviders', () => {
  const pick: CapabilityPick = {providers: ['openai', 'zhipu', 'custom:abc', 'custom:empty']};

  it('offers configured and named custom vendors', () => {
    expect(capabilityProviders(data, pick, '')).toEqual(['openai', 'custom:abc']);
  });

  it('keeps the current pick visible even when unconfigured', () => {
    expect(capabilityProviders(data, pick, 'zhipu')).toEqual(['openai', 'zhipu', 'custom:abc']);
  });
});

describe('resolveModels', () => {
  it('prefers the capability-scoped list', () => {
    const pick: CapabilityPick = {provider_models: {openai: ['whisper', {value: 'gpt-4o-transcribe', hint: '新'}]}};
    expect(resolveModels(data, pick, 'openai')).toEqual([{value: 'whisper'}, {value: 'gpt-4o-transcribe', hint: '新'}]);
  });

  it('uses the shared custom list for custom:<id>', () => {
    expect(resolveModels(data, {provider_models: {custom: ['m1']}}, 'custom:abc')).toEqual([{value: 'm1'}]);
  });

  it('falls back to the vendor catalog', () => {
    expect(resolveModels(data, {}, 'openai').map(o => o.value)).toEqual(['gpt-a', 'gpt-b']);
    expect(resolveModels(data, {}, '')).toEqual([]);
  });
});

describe('resolveVoices', () => {
  it('reads flat and per-model voice maps', () => {
    const pick: CapabilityPick = {
      provider_voices: {openai: ['alloy'], linkai: {'tts-x': [{value: 'v1', hint: '女声'}]}},
    };
    expect(resolveVoices(pick, 'openai', 'any')).toEqual([{value: 'alloy'}]);
    expect(resolveVoices(pick, 'linkai', 'tts-x')).toEqual([{value: 'v1', hint: '女声'}]);
    expect(resolveVoices(pick, 'linkai', 'other')).toEqual([]);
  });
});

it('needsTypedModel only for catalog-less custom vendors', () => {
  expect(needsTypedModel(data.providers[2], 'custom:abc')).toBe(true);
  expect(needsTypedModel({...data.providers[2], catalog: [{name: 'm'}]}, 'custom:abc')).toBe(false);
  expect(needsTypedModel(data.providers[0], 'openai')).toBe(false);
});

it('capabilitySummary describes auto, off and explicit picks', () => {
  expect(capabilitySummary(data, 'vision')).toBe('自动');
  expect(capabilitySummary(data, 'tts')).toBe('关闭');
  expect(
    capabilitySummary(
      {...data, capabilities: {...data.capabilities, asr: {current_provider: 'zhipu', current_model: 'glm-asr'}}},
      'asr',
    ),
  ).toBe('智谱 · glm-asr');
});

it('searchEditor routes each vendor to the right credential editor', () => {
  const meta = (p: Partial<SearchProviderMeta>): SearchProviderMeta => ({
    id: 'x',
    label: 'x',
    configured: false,
    needs_dedicated_key: false,
    ...p,
  });
  expect(searchEditor(meta({id: 'deepseek'}))).toBe('deepseek');
  expect(searchEditor(meta({id: 'searxng', needs_url: true}))).toBe('url');
  expect(searchEditor(meta({id: 'outcrawl', needs_dedicated_key: true}))).toBe('key');
  expect(searchEditor(meta({id: 'zhipu'}))).toBe('vendor');
});

it('moveItem swaps neighbours and ignores out-of-range moves', () => {
  expect(moveItem(['a', 'b', 'c'], 1, -1)).toEqual(['b', 'a', 'c']);
  expect(moveItem(['a', 'b', 'c'], 1, 1)).toEqual(['a', 'c', 'b']);
  const list = ['a', 'b'];
  expect(moveItem(list, 0, -1)).toBe(list);
  expect(moveItem(list, 1, 1)).toBe(list);
});
