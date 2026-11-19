import type {PairedDevice} from '../src/protocol/resources';
import {countdown, deviceMeta, seenLabel, sortDevices} from '../src/utils/devices';

const NOW = 1_800_000_000_000;
const sec = NOW / 1000;

const device = (over: Partial<PairedDevice>): PairedDevice => ({
  id: 'd_1',
  name: 'Phone',
  platform: 'android',
  app_version: '',
  created_at: sec - 86_400 * 30,
  last_seen_at: 0,
  ...over,
});

describe('device list', () => {
  it('puts this device first, then the online ones, then the most recently seen', () => {
    const list = [
      device({id: 'd_old', last_seen_at: sec - 7200}),
      device({id: 'd_recent', last_seen_at: sec - 60}),
      device({id: 'd_online', online: true, last_seen_at: sec - 9000}),
      device({id: 'd_me', last_seen_at: sec - 99_999}),
    ];
    expect(sortDevices(list, 'd_me').map(d => d.id)).toEqual(['d_me', 'd_online', 'd_recent', 'd_old']);
  });

  it('falls back to the sign-in time for a device never seen since', () => {
    const list = [device({id: 'd_a', created_at: sec - 500}), device({id: 'd_b', created_at: sec - 50})];
    expect(sortDevices(list, '').map(d => d.id)).toEqual(['d_b', 'd_a']);
  });

  it('says when a device was last active', () => {
    expect(seenLabel(device({online: true}), NOW)).toBe('在线');
    expect(seenLabel(device({last_seen_at: sec - 120}), NOW)).toBe('刚刚活跃');
    expect(seenLabel(device({last_seen_at: sec - 25 * 60}), NOW)).toBe('25 分钟前活跃');
    expect(seenLabel(device({last_seen_at: sec - 5 * 3600}), NOW)).toBe('5 小时前活跃');
    expect(seenLabel(device({last_seen_at: sec - 3 * 86_400}), NOW)).toBe('3 天前活跃');
    expect(seenLabel(device({created_at: 0, last_seen_at: 0}), NOW)).toBe('');
  });

  it('describes how a device signed in and where from', () => {
    expect(
      deviceMeta(
        device({via: 'password', app_version: '1.2.0', origin: 'https://console.example.com', last_ip: '10.0.0.8'}),
      ),
    ).toBe('密码登录 · v1.2.0 · 来自 console.example.com · 10.0.0.8');
    expect(deviceMeta(device({}))).toBe('配对连接');
  });

  it('counts a pairing code down in minutes and seconds', () => {
    expect(countdown(300_000)).toBe('5:00');
    expect(countdown(61_400)).toBe('1:01');
    expect(countdown(-5)).toBe('0:00');
  });
});
