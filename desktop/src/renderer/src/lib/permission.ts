import { t } from '../i18n'

export type PermissionMode = 'read-only' | 'workspace-write' | 'full-access'

/** UI order: least alarming first, matching the web console. */
export const PERMISSION_MODE_ORDER: PermissionMode[] = [
  'full-access',
  'workspace-write',
  'read-only',
]

export const PERMISSION_META: Record<PermissionMode, { key: string; descKey: string }> = {
  'full-access': { key: 'perm_full_access', descKey: 'perm_full_access_desc' },
  'workspace-write': { key: 'perm_workspace_write', descKey: 'perm_workspace_write_desc' },
  'read-only': { key: 'perm_read_only', descKey: 'perm_read_only_desc' },
}

export function asPermissionMode(value: string | undefined | null): PermissionMode {
  if (value === 'read-only' || value === 'workspace-write' || value === 'full-access') return value
  return 'full-access'
}

export function permLabel(mode: string | undefined | null): string {
  const m = asPermissionMode(mode)
  return t(PERMISSION_META[m].key)
}
