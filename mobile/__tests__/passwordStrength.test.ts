import {passwordStrength} from '../src/utils/passwordStrength';

describe('passwordStrength', () => {
  it('rates like the desktop client', () => {
    expect(passwordStrength('abc12')).toBe('short');
    expect(passwordStrength('123456')).toBe('weak');
    expect(passwordStrength('password')).toBe('weak');
    expect(passwordStrength('aaaaaaaa')).toBe('weak');
    expect(passwordStrength('cow2026x')).toBe('medium');
    expect(passwordStrength('Cow-agent2026')).toBe('strong');
  });
});
