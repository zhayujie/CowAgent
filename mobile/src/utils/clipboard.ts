/** Core Clipboard is deprecated but still ships on iOS, Android and RNOH; read it lazily so the warning fires only on use. */
export async function copyText(text: string): Promise<boolean> {
  try {
    const {Clipboard} = require('react-native') as typeof import('react-native');
    Clipboard.setString(text);
    return true;
  } catch {
    return false;
  }
}
