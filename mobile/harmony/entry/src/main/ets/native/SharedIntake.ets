import type { Want } from '@kit.AbilityKit';

export const SHARE_ACTION = 'ohos.want.action.sendData';
/** Set on the want of a tapped notification or reminder: the chat it is about. */
export const SESSION_PARAM = 'cowSession';

/** The chat of the notification the app was last opened from, until JS takes it. */
export class NotificationTap {
  private static session: string | null = null;

  static offer(want: Want): void {
    const session = want.parameters?.[SESSION_PARAM];
    if (typeof session === 'string' && session) {
      NotificationTap.session = session;
    }
  }

  static take(): string | null {
    const session = NotificationTap.session;
    NotificationTap.session = null;
    return session;
  }
}

/**
 * What another app shared here, from the ability's launch or a later want, held until
 * the React side takes it. `onArrive` tells a running React instance to come and take it.
 */
export class SharedIntake {
  private static pending: Want | null = null;
  static onArrive: (() => void) | null = null;

  static offer(want: Want): void {
    if (want.action !== SHARE_ACTION) {
      return;
    }
    SharedIntake.pending = want;
    SharedIntake.onArrive?.();
  }

  static take(): Want | null {
    const want = SharedIntake.pending;
    SharedIntake.pending = null;
    return want;
  }
}
