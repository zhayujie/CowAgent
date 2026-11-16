import {tr, trf} from '../i18n';

export type PasswordStrength = 'short' | 'weak' | 'medium' | 'strong';

export const PASSWORD_MIN_LENGTH = 6;

const COMMON = new Set([
  'password', 'passw0rd', 'password1', 'admin', 'admin123', 'administrator', 'root123',
  'qwerty', 'qwerty123', 'iloveyou', '1q2w3e4r', 'a123456', '123456a', 'abc123456', 'woaini1314',
]);
const SEQUENCES = ['01234567890', '9876543210', 'abcdefghijklmnopqrstuvwxyz', 'qwertyuiopasdfghjklzxcvbnm'];

/** A rough hint while typing, same rules as the desktop client: common and keyboard-run passwords are always weak. */
export function passwordStrength(pwd: string): PasswordStrength {
  if (pwd.length < PASSWORD_MIN_LENGTH) {
    return 'short';
  }
  const lower = pwd.toLowerCase();
  if (COMMON.has(lower) || /^(.)\1+$/.test(pwd) || SEQUENCES.some(s => s.includes(lower))) {
    return 'weak';
  }
  const kinds = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter(re => re.test(pwd)).length;
  if ((pwd.length >= 10 && kinds >= 3) || (pwd.length >= 14 && kinds >= 2)) {
    return 'strong';
  }
  if (pwd.length >= 8 && kinds >= 2) {
    return 'medium';
  }
  return 'weak';
}

export const PASSWORD_STRENGTH_TEXT: Record<PasswordStrength, string> = {
  get short() {
    return trf('settings_pwd_short', {min: PASSWORD_MIN_LENGTH});
  },
  get weak() {
    return tr('settings_pwd_weak');
  },
  get medium() {
    return tr('settings_pwd_medium');
  },
  get strong() {
    return tr('settings_pwd_strong');
  },
};
