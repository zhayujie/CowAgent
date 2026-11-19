import { tf } from '../../i18n'
import { InstanceError } from '../../api/instances'

const KNOWN = new Set([
  'self',
  'code_invalid',
  'unreachable',
  'timeout',
  'blocked',
  'login',
  'outdated',
  'not_cowagent',
  'wrong_device',
])

/** What went wrong reaching or pairing with another device, in words. */
export function failureText(e: unknown): string {
  const err = e instanceof InstanceError ? e : new InstanceError('unreachable')
  if (err.reason === 'locked') {
    return tf('devices_err_locked', { n: Math.max(1, Math.ceil(err.retryAfter / 60)) })
  }
  const reason = KNOWN.has(err.reason) ? err.reason : 'unreachable'
  return tf(`devices_err_${reason}`, { host: err.host || '?', status: err.status || '?' })
}
