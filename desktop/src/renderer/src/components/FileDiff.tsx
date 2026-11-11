import { useState } from 'react'
import type { FileChange, MessageStep } from '../types'

/** How many diff lines stay visible before "Show full diff". */
const PREVIEW_LINES = 40

interface DiffRow {
  kind: 'meta' | 'hunk' | 'add' | 'del' | 'ctx'
  text: string
  no?: number
}

export function fileChangeFromStored(result?: string): FileChange | null {
  if (!result) return null
  const text = result.trim()
  if (!text.startsWith('{')) return null
  let payload: Record<string, unknown>
  try {
    payload = JSON.parse(text) as Record<string, unknown>
  } catch {
    return null
  }
  if (typeof payload.diff !== 'string' || typeof payload.path !== 'string' || !payload.path) return null
  if (!/^(---|\+\+\+|@@|\+|-)/m.test(payload.diff)) return null
  return {
    path: payload.path,
    diff: payload.diff,
    first_changed_line: typeof payload.first_changed_line === 'number' ? payload.first_changed_line : null,
    message: typeof payload.message === 'string' ? payload.message : '',
    truncated: false,
  }
}

export function fileChangeOf(step: MessageStep): FileChange | null {
  const live = step.file_change
  if (live && live.path && live.diff && /^(---|\+\+\+|@@|\+|-)/m.test(live.diff)) return live
  return fileChangeFromStored(step.result)
}

function parseDiff(diff: string): DiffRow[] {
  const rows: DiffRow[] = []
  let oldNo = 0
  let newNo = 0
  for (const line of diff.split('\n')) {
    if (line.startsWith('@@')) {
      const match = /@@ -(\d+)(?:,\d*)? \+(\d+)/.exec(line)
      oldNo = match ? parseInt(match[1], 10) : 0
      newNo = match ? parseInt(match[2], 10) : 0
      rows.push({ kind: 'hunk', text: line })
      continue
    }
    if (line.startsWith('---') || line.startsWith('+++') || line.startsWith('\\')) {
      rows.push({ kind: 'meta', text: line })
      continue
    }
    if (line.startsWith('+')) {
      rows.push({ kind: 'add', text: line.slice(1), no: newNo })
      newNo += 1
      continue
    }
    if (line.startsWith('-')) {
      rows.push({ kind: 'del', text: line.slice(1), no: oldNo })
      oldNo += 1
      continue
    }
    const text = line.startsWith(' ') ? line.slice(1) : line
    rows.push({ kind: 'ctx', text, no: newNo || oldNo || undefined })
    if (oldNo) oldNo += 1
    if (newNo) newNo += 1
  }
  return rows
}

const rowClass: Record<DiffRow['kind'], string> = {
  add: 'bg-emerald-500/15',
  del: 'bg-red-500/15',
  hunk: 'opacity-60',
  meta: 'opacity-50',
  ctx: '',
}

const FileDiff: React.FC<{ change: FileChange }> = ({ change }) => {
  const rows = parseDiff(change.diff)
  const [open, setOpen] = useState(false)
  const shown = open ? rows : rows.slice(0, PREVIEW_LINES)
  const where = change.first_changed_line ? `${change.path}:${change.first_changed_line}` : change.path
  return (
    <div className="rounded-md border border-subtle overflow-hidden font-mono text-[11px] leading-relaxed">
      <div className="px-2 py-1 font-semibold break-all bg-black/5 dark:bg-white/5">{where}</div>
      <div className="max-h-[320px] overflow-auto">
        {shown.map((row, i) => (
          <div key={i} className={`flex whitespace-pre-wrap break-all ${rowClass[row.kind]}`}>
            <span className="w-10 flex-shrink-0 text-right pr-2 opacity-40 select-none">{row.no ?? ''}</span>
            <span className="flex-1 min-w-0">{row.text}</span>
          </div>
        ))}
      </div>
      {rows.length > PREVIEW_LINES && (
        <button
          type="button"
          className="w-full text-left px-2 py-1 opacity-70 hover:opacity-100"
          onClick={() => setOpen((v) => !v)}
        >
          {open ? 'Show less' : 'Show full diff'}
        </button>
      )}
      {change.truncated && <div className="px-2 py-1 opacity-60">Diff truncated</div>}
    </div>
  )
}

export default FileDiff
