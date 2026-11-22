import {describeSpan, formatLocal, nextDay, parseLocal} from '../src/phone/time';

describe('phone calendar times', () => {
  it('reads local times and whole days', () => {
    expect(parseLocal('2026-11-25T15:30')).toEqual({ms: new Date(2026, 10, 25, 15, 30).getTime(), dateOnly: false});
    expect(parseLocal('2026-11-25')).toEqual({ms: new Date(2026, 10, 25).getTime(), dateOnly: true});
  });

  it('refuses what is no such time', () => {
    for (const text of ['2026-02-30', '2026-11-25T24:00', 'tomorrow', '2026-11-25T15:00Z', '']) {
      expect(parseLocal(text)).toBeNull();
    }
  });

  it('writes back what it reads', () => {
    expect(formatLocal(parseLocal('2026-01-05T08:05')!.ms)).toBe('2026-01-05T08:05');
    expect(formatLocal(nextDay(new Date(2026, 11, 31, 18).getTime()), true)).toBe('2027-01-01');
  });

  it('describes a span for the user to allow', () => {
    const at = (h: number, d = 25) => new Date(2026, 10, d, h).getTime();
    expect(describeSpan(at(15), at(16), false)).toBe('2026-11-25 15:00 – 16:00');
    expect(describeSpan(at(22), at(1, 26), false)).toBe('2026-11-25 22:00 – 2026-11-26 01:00');
    expect(describeSpan(at(0), at(0, 26), true)).toBe('2026-11-25');
    expect(describeSpan(at(0), at(0, 28), true)).toBe('2026-11-25 – 2026-11-27');
  });
});
