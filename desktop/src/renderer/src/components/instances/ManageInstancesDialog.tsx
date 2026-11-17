import React, { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ArrowLeftRight, Check, Laptop, Pencil, Plus, Server, Trash2, X } from 'lucide-react'
import { t } from '../../i18n'
import { instanceHost, type Instance } from '../../api/instances'
import { askConfirm } from '../../store/confirmStore'
import { guardDocEditors } from '../../store/docEditorStore'
import { useInstanceStore, type InstanceStatus } from '../../store/instanceStore'
import { Btn } from '../../pages/settings/primitives'
import Tooltip from '../Tooltip'
import { StatusDot } from './InstanceSwitcher'

const SEP = <span className="mx-1.5 text-[color-mix(in_srgb,var(--text-tertiary)_50%,transparent)]">·</span>

/** The instances this app can switch to: switch, rename, pair again or remove. */
const ManageInstancesDialog: React.FC = () => {
  const { manageOpen, closeManage, items, activeId, status, refreshStatus, openAdd, switchTo, forget, rename } =
    useInstanceStore()
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null)
  const renamingRef = useRef(renaming)
  renamingRef.current = renaming

  useEffect(() => {
    if (!manageOpen) return
    setRenaming(null)
    void refreshStatus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !renamingRef.current) closeManage()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [manageOpen, refreshStatus, closeManage])

  if (!manageOpen) return null

  const commitRename = () => {
    const r = renamingRef.current
    renamingRef.current = null
    setRenaming(null)
    if (r) rename(r.id, r.name)
  }

  const pick = async (id: string) => {
    if (!(await guardDocEditors())) return
    closeManage()
    switchTo(id)
  }

  const remove = async (item: Instance) => {
    const ok = await askConfirm({
      titleKey: 'instances_remove',
      msgKey: 'instances_remove_confirm',
      okKey: 'instances_remove',
      vars: { name: item.name },
    })
    if (ok) await forget(item.id)
  }

  const row = (item: Instance | null) => {
    const id = item ? item.id : ''
    const on = id === activeId
    const st: InstanceStatus = item ? (item.token ? status[id] || 'checking' : 'offline') : 'online'
    const statusText = !item
      ? ''
      : !item.token
        ? t('instances_needs_pairing')
        : t(st === 'online' ? 'instances_online' : st === 'offline' ? 'instances_offline' : 'instances_checking')
    const meta = (item ? [instanceHost(item.url), item.version && `v${item.version}`, statusText] : [t('instances_this_desc')])
      .filter(Boolean)
      .flatMap((p, i) => (i ? [<React.Fragment key={i}>{SEP}</React.Fragment>, p] : [p]))
    const editing = !!item && renaming?.id === id
    return (
      <div
        key={id || 'local'}
        className={`group flex items-center gap-3 px-2 py-2.5 rounded-lg transition-colors hover:bg-[color-mix(in_srgb,var(--bg-surface-2)_60%,transparent)] ${
          on ? 'bg-[color-mix(in_srgb,var(--accent-soft)_40%,transparent)]' : ''
        }`}
      >
        <div className="relative w-9 h-9 rounded-lg bg-surface-2 text-content-secondary flex items-center justify-center flex-shrink-0">
          {item ? <Server size={15} /> : <Laptop size={15} />}
          <StatusDot status={st} className="absolute -right-0.5 -bottom-0.5" />
        </div>
        <div className="min-w-0 flex-1">
          {editing ? (
            <input
              autoFocus
              value={renaming.name}
              maxLength={60}
              onChange={(e) => setRenaming({ id, name: e.target.value })}
              onFocus={(e) => e.target.select()}
              onBlur={commitRename}
              onKeyDown={(e) => {
                if (e.key === 'Enter') commitRename()
                if (e.key === 'Escape') {
                  renamingRef.current = null
                  setRenaming(null)
                }
              }}
              className="w-full max-w-xs px-2 py-0.5 -ml-2 rounded-md border border-accent bg-inset text-sm text-content focus:outline-none"
            />
          ) : (
            <div className="text-sm font-medium text-content truncate">{item ? item.name : t('instances_this')}</div>
          )}
          <div className="mt-0.5 text-xs text-content-tertiary truncate">{meta}</div>
        </div>
        {item && (
          <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
            <Tooltip label={t('instances_rename')}>
              <button
                type="button"
                aria-label={t('instances_rename')}
                onClick={() => setRenaming({ id, name: item.name })}
                className="w-7 h-7 inline-flex items-center justify-center rounded-md text-content-tertiary hover:text-content hover:bg-surface-2 cursor-pointer"
              >
                <Pencil size={13} />
              </button>
            </Tooltip>
            <Tooltip label={t('instances_remove')}>
              <button
                type="button"
                aria-label={t('instances_remove')}
                onClick={() => void remove(item)}
                className="w-7 h-7 inline-flex items-center justify-center rounded-md text-content-tertiary hover:text-danger hover:bg-surface-2 cursor-pointer"
              >
                <Trash2 size={13} />
              </button>
            </Tooltip>
          </div>
        )}
        <div className="flex-shrink-0">
          {on ? (
            <span className="inline-flex items-center gap-1 h-5 px-2 rounded-full text-[11px] font-medium bg-accent-soft text-accent">
              <Check size={10} />
              {t('instances_current')}
            </span>
          ) : item && !item.token ? (
            <Btn onClick={() => openAdd({ url: item.url, replaceId: id })} className="!px-3 !py-1 text-xs">
              {t('instances_repair')}
            </Btn>
          ) : (
            <Btn onClick={() => void pick(id)} className="!px-3 !py-1 text-xs hover:!border-accent hover:!text-accent">
              {t('instances_switch')}
            </Btn>
          )}
        </div>
      </div>
    )
  }

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) closeManage()
      }}
    >
      <div className="w-full max-w-[560px] max-h-[85vh] flex flex-col rounded-card border border-default bg-elevated shadow-xl overflow-hidden">
        <div className="flex items-start gap-3 px-5 pt-5 pb-3">
          <div className="w-9 h-9 rounded-xl bg-accent-soft text-accent flex items-center justify-center flex-shrink-0">
            <ArrowLeftRight size={17} />
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="font-semibold text-content">{t('instances_manage_title')}</h3>
            <p className="text-xs text-content-tertiary mt-0.5">{t('instances_manage_desc')}</p>
          </div>
          <button
            type="button"
            onClick={closeManage}
            className="p-1 -mr-1 rounded-md text-content-tertiary hover:text-content hover:bg-surface-2 cursor-pointer"
          >
            <X size={16} />
          </button>
        </div>
        <div className="px-3 pb-3 overflow-y-auto">
          <div className="divide-y divide-subtle">{[null, ...items].map(row)}</div>
          {!items.length && (
            <div className="mx-2 mt-2 rounded-xl border border-dashed border-default px-4 py-5 text-center">
              <p className="text-sm text-content-secondary">{t('instances_empty_title')}</p>
              <p className="mt-1 text-xs leading-relaxed text-content-tertiary">{t('instances_empty')}</p>
            </div>
          )}
        </div>
        <div className="flex items-center justify-between gap-3 px-5 py-3.5 border-t border-default bg-[color-mix(in_srgb,var(--bg-surface)_40%,transparent)]">
          <p className="text-xs text-content-tertiary min-w-0">{t('instances_manage_foot')}</p>
          <Btn variant="primary" onClick={() => openAdd()} className="flex-shrink-0">
            <span className="inline-flex items-center gap-1.5">
              <Plus size={14} />
              {t('instances_add')}
            </span>
          </Btn>
        </div>
      </div>
    </div>,
    document.body,
  )
}

export default ManageInstancesDialog
