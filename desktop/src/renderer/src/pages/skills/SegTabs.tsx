import React from 'react'
import type { LucideIcon } from 'lucide-react'

interface SegTab<T extends string> {
  value: T
  label: string
  icon?: LucideIcon
}

/** A compact segmented switch, styled like the Memory page's tabs. */
export function SegTabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: SegTab<T>[]
  value: T
  onChange: (value: T) => void
}): React.ReactElement {
  return (
    <div className="inline-flex items-center gap-1 bg-inset-2 rounded-btn p-0.5">
      {tabs.map(({ value: v, label, icon: Icon }) => (
        <button
          key={v}
          type="button"
          onClick={() => onChange(v)}
          className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-[6px] text-[13px] font-medium cursor-pointer transition-colors ${
            v === value
              ? 'bg-elevated dark:bg-white/10 text-content shadow-sm'
              : 'text-content-tertiary hover:text-content-secondary'
          }`}
        >
          {Icon && <Icon size={13} />}
          {label}
        </button>
      ))}
    </div>
  )
}
