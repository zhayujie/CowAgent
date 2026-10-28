import React, { useId, useState } from 'react'
import { ChevronDown, ChevronUp, Circle, CircleCheck, ListTodo, Loader2 } from 'lucide-react'
import { t } from '../i18n'
import type { TodoSnapshot, TodoItem } from '../types'

const STORAGE_KEY = 'cow_todo_panel_expanded'
const icons = { pending: Circle, in_progress: Loader2, completed: CircleCheck }
const rowClasses: Record<TodoItem['status'], string> = {
  pending: 'text-content-secondary',
  in_progress: 'font-medium text-content',
  completed: 'text-content-tertiary',
}

function progressLabel(counts: Record<TodoItem['status'], number>) {
  return [
    counts.completed > 0 ? `${counts.completed} ${t('todo_completed')}` : '',
    counts.in_progress > 0 ? `${counts.in_progress} ${t('todo_in_progress')}` : '',
    counts.pending > 0 ? `${counts.pending} ${t('todo_pending')}` : '',
  ].filter(Boolean).join(' \u2002·\u2002 ')
}

const TodoPanel: React.FC<{ snapshot?: TodoSnapshot }> = ({ snapshot }) => {
  const [expanded, setExpanded] = useState(() => {
    try { return localStorage.getItem(STORAGE_KEY) === '1' } catch { return false }
  })
  const listId = useId()
  if (!snapshot?.todos.length) return null

  const counts = { pending: 0, in_progress: 0, completed: 0 }
  snapshot.todos.forEach(item => counts[item.status]++)
  const progress = progressLabel(counts)

  const toggle = () => {
    setExpanded(value => {
      const next = !value
      try { localStorage.setItem(STORAGE_KEY, next ? '1' : '0') } catch { /* Storage can be unavailable. */ }
      return next
    })
  }

  return (
    <section className="pointer-events-auto mx-auto w-full overflow-hidden rounded-2xl border border-default bg-surface text-content shadow-sm transition-colors" aria-label={t('todo_title')}>
      <button type="button" onClick={toggle} aria-expanded={expanded} aria-controls={listId}
        className="flex w-full cursor-pointer items-center gap-2.5 px-3 py-1.5 text-left hover:bg-surface-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-[-2px]">
        <ListTodo size={14} aria-hidden="true" className="shrink-0 text-content-tertiary" />
        <span className="shrink-0 text-[13px] font-medium leading-6">{t('todo_title')}</span>
        <span className="min-w-0 flex-1 truncate text-[13px] leading-5 text-content-tertiary" title={progress}>{progress}</span>
        {expanded ? <ChevronDown size={14} aria-hidden="true" className="shrink-0 text-content-tertiary" /> : <ChevronUp size={14} aria-hidden="true" className="shrink-0 text-content-tertiary" />}
      </button>
      <div id={listId} hidden={!expanded} className="max-h-[180px] overflow-y-auto px-3 pb-2.5 pt-0.5 [scrollbar-width:thin]">
        <ul>
          {snapshot.todos.map(item => {
            const Icon = icons[item.status]
            return (
              <li key={item.content} className={`flex items-start gap-2.5 rounded-md px-1 py-[5px] text-[12.5px] leading-[1.45] transition-colors hover:bg-surface-2 ${rowClasses[item.status]}`}>
                <Icon size={13} aria-hidden="true" className={`mt-0.5 shrink-0 ${item.status === 'pending' ? 'text-content-tertiary' : 'text-success'} ${item.status === 'in_progress' ? 'animate-spin' : ''}`} />
                <span className={`min-w-0 whitespace-pre-wrap break-words [overflow-wrap:anywhere] ${item.status === 'completed' ? 'line-through opacity-[0.85]' : ''}`}>
                  <span className="sr-only">{t(`todo_${item.status}`)}: </span>
                  {item.content}
                </span>
              </li>
            )
          })}
        </ul>
        {snapshot.explanation && (
          <p className="mt-2 whitespace-pre-wrap break-words border-t border-default px-1 pt-1.5 text-[11px] leading-[1.4] text-content-secondary [overflow-wrap:anywhere]">{snapshot.explanation}</p>
        )}
      </div>
    </section>
  )
}

export default TodoPanel
