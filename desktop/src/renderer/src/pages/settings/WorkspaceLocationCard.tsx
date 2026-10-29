import React, { useCallback, useEffect, useState } from 'react'
import { HardDrive, FolderOpen, Loader2, AlertTriangle, CheckCircle2 } from 'lucide-react'
import { t, tf } from '../../i18n'
import type {
  WorkspaceApplyResult,
  WorkspaceCheck,
  WorkspaceInfo,
  WorkspaceMigrationProgress,
} from '../../types'
import { Card, Modal, Btn } from './primitives'

const formatBytes = (n: number): string => {
  if (n < 1024) return `${n} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let v = n / 1024
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i += 1
  }
  return `${v.toFixed(v >= 100 ? 0 : 1)} ${units[i]}`
}

const errorText = (code?: string, detail?: string): string => {
  const msg = t(`workspace_location_error_${code || 'copy_failed'}`)
  return detail ? `${msg}\n${detail}` : msg
}

const warningText = (warning: string): string => {
  const at = warning.indexOf(':')
  const kind = warning.slice(0, at)
  const p = warning.slice(at + 1)
  return tf(kind === 'link' ? 'workspace_location_warning_link' : 'workspace_location_warning_cleanup', { path: p })
}

const PathRow: React.FC<{
  label: string
  path: string
  size?: number | null
  onOpen?: () => void
  onChange?: () => void
}> = ({ label, path, size, onOpen, onChange }) => (
  <div className="flex items-center gap-3 py-1.5">
    <div className="w-20 flex-shrink-0 text-xs text-content-tertiary">{label}</div>
    <div className="flex-1 min-w-0 font-mono text-xs text-content truncate" title={path}>
      {path}
    </div>
    {size !== undefined && (
      <div className="flex-shrink-0 text-xs text-content-tertiary tabular-nums">
        {size === null ? <Loader2 size={12} className="animate-spin" /> : formatBytes(size)}
      </div>
    )}
    {onChange ? (
      <button
        type="button"
        onClick={onChange}
        className="flex-shrink-0 text-xs font-medium text-accent hover:opacity-80 cursor-pointer"
      >
        {t('workspace_location_change')}
      </button>
    ) : (
      onOpen && (
        <button
          type="button"
          onClick={onOpen}
          title={t('workspace_location_open')}
          className="flex-shrink-0 p-1 text-content-tertiary hover:text-content-secondary cursor-pointer"
        >
          <FolderOpen size={14} />
        </button>
      )
    )}
  </div>
)

type Stage =
  | { kind: 'closed' }
  | { kind: 'checking' }
  | { kind: 'confirm'; parent: string; check: WorkspaceCheck }
  | { kind: 'running'; progress: WorkspaceMigrationProgress | null }
  | { kind: 'done'; result: WorkspaceApplyResult }
  | { kind: 'failed'; message: string }

const WorkspaceLocationCard: React.FC = () => {
  const api = window.electronAPI
  const [info, setInfo] = useState<WorkspaceInfo | null>(null)
  const [usage, setUsage] = useState<number | null>(null)
  const [stage, setStage] = useState<Stage>({ kind: 'closed' })

  useEffect(() => {
    if (!api?.getWorkspaceLocation) return
    api.getWorkspaceLocation().then(setInfo).catch(() => {})
    api.getWorkspaceUsage?.().then(setUsage).catch(() => {})
  }, [api])

  useEffect(() => {
    if (!api?.onWorkspaceMigrationProgress) return
    return api.onWorkspaceMigrationProgress((progress) =>
      setStage((s) => (s.kind === 'running' ? { ...s, progress } : s)),
    )
  }, [api])

  const open = useCallback((p: string) => void api?.openPath(p), [api])

  const choose = async () => {
    const parent = await api?.pickWorkspaceLocation?.(t('workspace_location_pick_title'))
    if (!parent) return
    setStage({ kind: 'checking' })
    try {
      const check = await api!.checkWorkspaceLocation!(parent)
      setStage(
        check.ok
          ? { kind: 'confirm', parent, check }
          : { kind: 'failed', message: errorText(check.code, check.detail) },
      )
    } catch (e) {
      setStage({ kind: 'failed', message: errorText('copy_failed', e instanceof Error ? e.message : String(e)) })
    }
  }

  const apply = async (parent: string) => {
    setStage({ kind: 'running', progress: null })
    try {
      const result = await api!.applyWorkspaceLocation!({ parent, keepLink: true })
      setStage(result.ok ? { kind: 'done', result } : { kind: 'failed', message: errorText(result.code, result.detail) })
    } catch (e) {
      setStage({ kind: 'failed', message: errorText('copy_failed', e instanceof Error ? e.message : String(e)) })
    }
  }

  if (!api?.getWorkspaceLocation || !info) return null

  const busy = stage.kind === 'running'
  const closeModal = () => {
    if (!busy && stage.kind !== 'done') setStage({ kind: 'closed' })
  }

  const progressPercent =
    stage.kind === 'running' && stage.progress && stage.progress.totalBytes > 0
      ? Math.min(100, Math.round((stage.progress.doneBytes / stage.progress.totalBytes) * 100))
      : null

  let body: React.ReactNode = null
  let footer: React.ReactNode = null
  if (stage.kind === 'checking') {
    body = (
      <div className="flex items-center gap-2 text-sm text-content-secondary">
        <Loader2 size={14} className="animate-spin" />
        {t('workspace_location_checking')}
      </div>
    )
  } else if (stage.kind === 'confirm') {
    const { parent, check } = stage
    body = (
      <>
        <div className="rounded-btn border border-default p-3 space-y-1">
          <PathRow label={t('workspace_location_current')} path={info.realWorkspace} />
          <PathRow label={t('workspace_location_target')} path={check.target} />
        </div>
        <p className="text-xs text-content-tertiary">
          {check.requiredBytes > 0
            ? tf('workspace_location_space', {
                required: formatBytes(check.requiredBytes),
                free: check.freeBytes === null ? '—' : formatBytes(check.freeBytes),
              })
            : t('workspace_location_space_rename')}
        </p>
        <p className="text-xs text-content-tertiary">{t('workspace_location_move_hint')}</p>
      </>
    )
    footer = (
      <>
        <Btn onClick={closeModal}>{t('workspace_location_cancel')}</Btn>
        <Btn variant="primary" onClick={() => apply(parent)}>
          {t('workspace_location_start_move')}
        </Btn>
      </>
    )
  } else if (stage.kind === 'running') {
    const p = stage.progress
    body = (
      <div className="space-y-3">
        <div className="flex items-center gap-2 text-sm text-content-secondary">
          <Loader2 size={14} className="animate-spin" />
          {t(`workspace_location_phase_${p?.phase || 'stopping'}`)}
        </div>
        <div className="h-2 rounded-full bg-surface-2 overflow-hidden">
          <div className="h-full bg-accent transition-all" style={{ width: `${progressPercent ?? 0}%` }} />
        </div>
        {p && p.totalBytes > 0 && (
          <div className="text-xs text-content-tertiary tabular-nums">
            {formatBytes(p.doneBytes)} / {formatBytes(p.totalBytes)} · {p.doneFiles} / {p.totalFiles}
          </div>
        )}
        <p className="text-xs text-content-tertiary">{t('workspace_location_running_hint')}</p>
      </div>
    )
  } else if (stage.kind === 'done') {
    body = (
      <div className="space-y-3">
        <div className="flex items-center gap-2 text-sm text-content">
          <CheckCircle2 size={16} className="text-accent" />
          {t('workspace_location_done_move')}
        </div>
        {stage.result.warnings.map((w) => (
          <div key={w} className="flex gap-2 text-xs text-content-secondary">
            <AlertTriangle size={13} className="flex-shrink-0 text-danger mt-0.5" />
            <span className="break-all">{warningText(w)}</span>
          </div>
        ))}
      </div>
    )
    footer = (
      <Btn variant="primary" onClick={() => void api.relaunchForWorkspaceLocation?.()}>
        {t('workspace_location_relaunch')}
      </Btn>
    )
  } else if (stage.kind === 'failed') {
    body = <p className="text-sm text-danger whitespace-pre-line break-all">{stage.message}</p>
    footer = <Btn onClick={closeModal}>{t('workspace_location_close')}</Btn>
  }

  return (
    <Card icon={<HardDrive size={16} />} title={t('workspace_location_title')} subtitle={t('workspace_location_subtitle')}>
      <div className="space-y-3">
        <div className="rounded-btn border border-default bg-inset-2 px-3 py-1.5">
          <PathRow
            label={t('workspace_location_current')}
            path={info.realWorkspace}
            size={usage}
            onOpen={() => open(info.realWorkspace)}
            onChange={info.managedByEnv ? undefined : choose}
          />
        </div>
        {info.managedByEnv && (
          <p className="text-xs text-content-tertiary">{t('workspace_location_managed_by_env')}</p>
        )}
      </div>

      <Modal open={stage.kind !== 'closed'} title={t('workspace_location_modal_title')} onClose={closeModal} footer={footer}>
        {body}
      </Modal>
    </Card>
  )
}

export default WorkspaceLocationCard
