import React, { useEffect, useRef, useState } from 'react'
import { Check, ChevronsUpDown, Laptop, Plus, Server, SlidersHorizontal } from 'lucide-react'
import { t } from '../../i18n'
import { instanceHost } from '../../api/instances'
import { useInstanceStore, type InstanceStatus } from '../../store/instanceStore'
import { guardDocEditors } from '../../store/docEditorStore'
import Tooltip from '../Tooltip'

const DOT: Record<InstanceStatus, string> = {
  online: 'bg-success',
  offline: 'bg-danger',
  checking: 'bg-[color-mix(in_srgb,var(--text-tertiary)_50%,transparent)]',
}

export const StatusDot: React.FC<{ status: InstanceStatus; className?: string }> = ({ status, className }) => (
  <span className={`block w-2 h-2 rounded-full ring-2 ring-elevated ${DOT[status]} ${className || ''}`} />
)

/** Which instance the app drives, at the top of the nav rail. */
const InstanceSwitcher: React.FC<{ collapsed: boolean }> = ({ collapsed }) => {
  const { items, activeId, status, refreshStatus, openAdd, openManage, switchTo } = useInstanceStore()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  const active = items.find((i) => i.id === activeId) || null
  const activeStatus: InstanceStatus = active ? status[active.id] || 'online' : 'online'

  useEffect(() => {
    if (!open) return
    void refreshStatus()
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, refreshStatus])

  const pick = async (id: string) => {
    setOpen(false)
    if (id === activeId) return
    if (!(await guardDocEditors())) return
    switchTo(id)
  }

  const manage = () => {
    setOpen(false)
    openManage()
  }

  const Icon = active ? Server : Laptop
  const label = active ? active.name : t('instances_this')

  const trigger = (
    <button
      type="button"
      onClick={() => setOpen((o) => !o)}
      className={`group w-full flex items-center rounded-btn cursor-pointer transition-colors ${
        open ? 'bg-surface-2' : 'hover:bg-surface-2'
      } ${collapsed ? 'h-10 justify-center' : 'h-11 gap-2.5 px-2'}`}
    >
      <span
        className={`relative w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 ${
          active ? 'bg-accent text-accent-contrast' : 'bg-accent-soft text-accent'
        }`}
      >
        <Icon size={15} strokeWidth={2} />
        {active && <StatusDot status={activeStatus} className="absolute -right-0.5 -bottom-0.5" />}
      </span>
      {!collapsed && (
        <>
          <span className="min-w-0 flex-1 text-left leading-tight">
            <span className="block text-[13px] font-medium text-content truncate">{label}</span>
            <span className="block text-[11px] text-content-tertiary truncate">
              {active ? instanceHost(active.url) : t('instances_this_desc')}
            </span>
          </span>
          <ChevronsUpDown size={14} className="flex-shrink-0 text-content-tertiary group-hover:text-content-secondary" />
        </>
      )}
    </button>
  )

  return (
    <div ref={ref} className="relative px-2 pt-2">
      {collapsed ? (
        <Tooltip label={label} placement="right">
          {trigger}
        </Tooltip>
      ) : (
        trigger
      )}

      {open && (
        <div
          className={`absolute z-50 rounded-card border border-default bg-elevated shadow-xl p-1.5 ${
            collapsed ? 'left-full top-2 ml-2 w-64' : 'left-2 right-2 top-full mt-1 min-w-[240px]'
          }`}
        >
          <div className="px-2.5 pt-1.5 pb-1 text-[11px] font-medium text-content-tertiary">{t('instances_title')}</div>
          <div className="max-h-[50vh] overflow-y-auto">
            {[null, ...items].map((item) => {
              const id = item ? item.id : ''
              const on = id === activeId
              const st: InstanceStatus = item ? (item.token ? status[id] || 'checking' : 'offline') : 'online'
              const sub = item
                ? item.token
                  ? instanceHost(item.url)
                  : t('instances_needs_pairing')
                : t('instances_this_desc')
              return (
                <button
                  key={id || 'local'}
                  type="button"
                  onClick={() => (item && !item.token ? (setOpen(false), openAdd({ url: item.url, replaceId: id })) : void pick(id))}
                  className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left cursor-pointer transition-colors ${
                    on ? 'bg-accent-soft' : 'hover:bg-surface-2'
                  }`}
                >
                  <span className="relative w-7 h-7 rounded-lg bg-surface-2 text-content-secondary flex items-center justify-center flex-shrink-0">
                    {item ? <Server size={14} /> : <Laptop size={14} />}
                    <StatusDot status={st} className="absolute -right-0.5 -bottom-0.5" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className={`block text-[13px] truncate ${on ? 'text-accent font-medium' : 'text-content'}`}>
                      {item ? item.name : t('instances_this')}
                    </span>
                    <span className="block text-[11px] text-content-tertiary truncate">{sub}</span>
                  </span>
                  {on && <Check size={14} className="flex-shrink-0 text-accent" />}
                </button>
              )
            })}
          </div>
          <div className="my-1 border-t border-subtle" />
          <button
            type="button"
            onClick={() => {
              setOpen(false)
              openAdd()
            }}
            className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-[13px] text-content-secondary hover:bg-surface-2 hover:text-content cursor-pointer"
          >
            <Plus size={15} className="flex-shrink-0" />
            {t('instances_add_ellipsis')}
          </button>
          <button
            type="button"
            onClick={manage}
            className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-[13px] text-content-secondary hover:bg-surface-2 hover:text-content cursor-pointer"
          >
            <SlidersHorizontal size={15} className="flex-shrink-0" />
            {t('instances_manage_ellipsis')}
          </button>
        </div>
      )}
    </div>
  )
}

export default InstanceSwitcher
