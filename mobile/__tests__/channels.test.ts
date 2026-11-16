import type {ChannelField, ChannelInfo, ChannelsResponse} from '../src/protocol/resources';
import {
  bindingSummary,
  blankChannel,
  buildChannelConfig,
  changedFields,
  channelPending,
  channelStatusLabel,
  initialValues,
  missingFields,
  splitChannels,
} from '../src/utils/channels';

const feishuFields: ChannelField[] = [
  {key: 'feishu_app_id', label: 'App ID', type: 'text', value: 'cli_123'},
  {key: 'feishu_app_secret', label: 'App Secret', type: 'secret', value: 'abcd****wxyz'},
];

const ch = (name: string, active: boolean, extra: Partial<ChannelInfo> = {}): ChannelInfo => ({name, active, fields: [], ...extra});

describe('splitChannels', () => {
  it('lists active channels as connected, WeChat first', () => {
    const data: ChannelsResponse = {channels: [ch('feishu', true), ch('weixin', true), ch('dingtalk', false)]};
    const {connected, available} = splitChannels(data);
    expect(connected.map(c => c.name)).toEqual(['weixin', 'feishu']);
    expect(available.map(c => c.name)).toEqual(['dingtalk']);
  });

  it('shows per-bot cards for multi-instance types in multi-Agent mode and keeps the type addable', () => {
    const data: ChannelsResponse = {
      channels: [ch('feishu', true), ch('wechatmp', true)],
      multi_agent: true,
      multi_instance_types: ['feishu'],
      instances: [ch('feishu', true, {instance_id: 'feishu'}), ch('feishu', true, {instance_id: 'feishu_2'})],
    };
    const {connected, available} = splitChannels(data);
    expect(connected.map(c => c.instance_id ?? c.name)).toEqual(['wechatmp', 'feishu', 'feishu_2']);
    expect(available.map(c => c.name)).toEqual(['feishu']);
  });
});

describe('channelPending', () => {
  it('only treats an active WeChat that is not logged in as pending', () => {
    expect(channelPending(ch('weixin', true, {login_status: 'waiting_scan'}))).toBe('scanning');
    expect(channelPending(ch('weixin', true, {login_status: 'idle'}))).toBe('starting');
    expect(channelPending(ch('weixin', true, {login_status: 'logged_in'}))).toBe('none');
    expect(channelPending(ch('feishu', true, {login_status: 'idle'}))).toBe('none');
    expect(channelStatusLabel(ch('weixin', true, {login_status: 'scanned'}))).toBe('已扫码，等待确认');
  });
});

describe('credential form', () => {
  it('starts masked secrets empty and leaves them out unless retyped', () => {
    const values = initialValues(feishuFields);
    expect(values).toEqual({feishu_app_id: 'cli_123', feishu_app_secret: ''});
    expect(buildChannelConfig(feishuFields, values)).toEqual({feishu_app_id: 'cli_123'});
    expect(changedFields(feishuFields, values)).toBe(false);
    expect(changedFields(feishuFields, {...values, feishu_app_secret: 'new'})).toBe(true);
  });

  it('counts stored secrets and defaults as filled', () => {
    expect(missingFields(feishuFields, initialValues(feishuFields))).toEqual([]);
    const port: ChannelField = {key: 'port', label: 'Port', type: 'number', value: '', default: 9898};
    const token: ChannelField = {key: 'token', label: 'Token', type: 'secret', value: ''};
    expect(missingFields([port, token], {port: '', token: ''}).map(f => f.key)).toEqual(['token']);
    expect(buildChannelConfig([port], {port: '8080'})).toEqual({port: 8080});
  });

  it('blanks a template so a new bot never inherits stored credentials', () => {
    const blank = blankChannel(ch('feishu', true, {instance_id: 'feishu', agent_id: 'a', fields: feishuFields}));
    expect(blank.active).toBe(false);
    expect(blank.instance_id).toBeUndefined();
    expect(blank.fields?.map(f => f.value)).toEqual(['', '']);
  });
});

describe('bindingSummary', () => {
  const names: Record<string, string> = {a: '助理', b: '研究员'};
  it('names the owner and counts the team', () => {
    expect(bindingSummary(ch('feishu', true), id => names[id])).toBe('跟随默认');
    expect(bindingSummary(ch('feishu', true, {agent_id: 'a'}), id => names[id])).toBe('助理');
    expect(bindingSummary(ch('feishu', true, {agent_id: 'a', members: ['b']}), id => names[id])).toBe('助理 等 2 个');
  });
});
