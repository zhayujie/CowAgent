import React, { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  Eye,
  EyeOff,
  FolderPlus,
  FileText,
  Globe,
  GripVertical,
  Laptop,
  Loader2,
  Plus,
  RotateCcw,
  Search,
  Trash2,
  X,
} from 'lucide-react'
import { t } from '../i18n'
import apiClient from '../api/client'
import { Btn } from '../pages/settings/primitives'
import { useMenuStore } from '../store/menuStore'
import { useInstanceStore } from '../store/instanceStore'
import { askConfirm, useConfirmStore } from '../store/confirmStore'
import { colorFor, iconFor } from '../lib/fileKind'
import {
  MENU_BUILTINS,
  MENU_DEFAULT_VIEWS,
  MENU_GROUP_LABELS,
  MENU_ICONS,
  MENU_REQUIRED,
  MENU_TITLE_MAX,
  builtinItem,
  findItem,
  isFooterItem,
  itemIcon,
  itemLabel,
  newMenuId,
} from '../lib/menu'
import type { ArtifactListItem, MenuDoc, MenuItem } from '../types'

type Pop =
  | { kind: 'add' | 'artifact'; anchor: HTMLElement; groupId: string }
  | { kind: 'icon'; anchor: HTMLElement; itemId: string }

/** `grab` is where the pointer holds the row or group, measured from its top edge. */
type Drag = { type: 'item' | 'group'; id: string; y: number; grab: number }

/** How close to the list's top or bottom edge the pointer scrolls it while sorting. */
const SCROLL_EDGE = 36
/** How long the rows the dragged one passes take to slide into their new places. */
const SORT_MS = 180

const clone = (doc: MenuDoc): MenuDoc => JSON.parse(JSON.stringify(doc))

/** Move an entry in front of `beforeId` in the group `groupId` (to its end when null). */
function moveItem(doc: MenuDoc, id: string, groupId: string, beforeId: string | null): MenuDoc {
  const found = findItem(doc, id)
  if (!found) return doc
  const at = found.group.items.indexOf(found.item)
  const next = found.group.items[at + 1]?.id ?? null
  if (found.group.id === groupId && next === beforeId) return doc
  const groups = doc.groups.map((g) => ({ ...g, items: g.items.filter((i) => i.id !== id) }))
  const target = groups.find((g) => g.id === groupId)
  if (!target) return doc
  const index = beforeId ? target.items.findIndex((i) => i.id === beforeId) : -1
  target.items.splice(index < 0 ? target.items.length : index, 0, found.item)
  return { ...doc, groups }
}

function moveGroup(doc: MenuDoc, id: string, beforeId: string | null): MenuDoc {
  const at = doc.groups.findIndex((g) => g.id === id)
  if (at < 0 || (doc.groups[at + 1]?.id ?? null) === beforeId) return doc
  const group = doc.groups[at]
  const groups = doc.groups.filter((g) => g.id !== id)
  const index = beforeId ? groups.findIndex((g) => g.id === beforeId) : -1
  groups.splice(index < 0 ? groups.length : index, 0, group)
  return { ...doc, groups }
}

/** Where an element's top sits once the slide it may be in the middle of settles. */
function restingTop(el: HTMLElement): number {
  const shift = getComputedStyle(el).transform
  return el.getBoundingClientRect().top - (shift && shift !== 'none' ? new DOMMatrixReadOnly(shift).m42 : 0)
}

/** The first element whose vertical middle lies below `y`. */
function firstBelow(elements: HTMLElement[], y: number): HTMLElement | undefined {
  return elements.find((el) => y < restingTop(el) + el.offsetHeight / 2)
}

/** The rows, or the groups, a drag of this kind reorders. */
function sortables(body: HTMLElement, type: Drag['type']): HTMLElement[] {
  return Array.from(body.querySelectorAll<HTMLElement>(type === 'item' ? '[data-iid]' : ':scope > [data-gid]'))
}

function dragged(body: HTMLElement, drag: Drag): HTMLElement | null {
  const attr = drag.type === 'item' ? 'data-iid' : 'data-gid'
  return body.querySelector<HTMLElement>(`[${attr}="${CSS.escape(drag.id)}"]`)
}

/** Keep the dragged row or group under the pointer, wherever its slot is now. */
function follow(body: HTMLElement, drag: Drag, y: number) {
  const el = dragged(body, drag)
  if (!el) return
  el.style.transition = 'none'
  el.style.transform = ''
  el.style.transform = `translateY(${y - drag.grab - el.getBoundingClientRect().top}px)`
}

const inputClass = (invalid: boolean) =>
  `w-full min-w-0 h-7 px-1.5 rounded-md border bg-transparent text-[13px] text-content placeholder:text-content-tertiary focus:outline-none focus:bg-surface transition-colors ${
    invalid ? 'border-danger' : 'border-transparent hover:border-default focus:border-accent'
  }`

const iconBtn =
  'inline-flex items-center justify-center w-7 h-7 rounded-md text-content-tertiary hover:text-content hover:bg-surface-2 cursor-pointer transition-colors flex-shrink-0 disabled:opacity-35 disabled:cursor-default disabled:hover:bg-transparent disabled:hover:text-content-tertiary'

const popRow =
  'w-full flex items-center gap-2.5 px-3 h-8 text-[13px] text-content-secondary hover:bg-surface-2 hover:text-content cursor-pointer transition-colors text-left disabled:opacity-50 disabled:cursor-default disabled:hover:bg-transparent'

/**
 * The dialog behind the nav rail's edit button. It edits a copy of the menu
 * in force and saves the whole of it; entries this app has no page for (a
 * web-console-only page) stay in the copy as they are, so saving from here
 * never drops them. Mirrors the web console's views/menu-editor.js.
 */
const MenuEditor: React.FC = () => {
  const open = useMenuStore((s) => s.editorOpen)
  return open ? <EditorDialog /> : null
}

const EditorDialog: React.FC = () => {
  const doc = useMenuStore((s) => s.doc)
  const save = useMenuStore((s) => s.save)
  const close = useMenuStore((s) => s.closeEditor)
  const confirmPending = useConfirmStore((s) => !!s.pending)
  const navigate = useNavigate()
  const location = useLocation()

  const intent = useMenuStore((s) => s.editorIntent)
  const [draft, setDraft] = useState<MenuDoc>(() => {
    const copy = clone(doc)
    if (intent?.add && copy.groups.length) copy.groups[0].items.push(intent.add)
    return copy
  })
  const [error, setError] = useState('')
  const [invalid, setInvalid] = useState('')
  const [saving, setSaving] = useState(false)
  const [pop, setPop] = useState<Pop | null>(null)
  const [drag, setDrag] = useState<Drag | null>(null)
  const [fresh, setFresh] = useState(() => intent?.add?.id || intent?.focus || '')
  // Kept on this computer only, unlike the menu itself.
  const [switcherHidden, setSwitcherHidden] = useState(() => useInstanceStore.getState().switcherHidden)

  const panelRef = useRef<HTMLDivElement>(null)
  const bodyRef = useRef<HTMLDivElement>(null)
  const popRef = useRef<HTMLDivElement>(null)
  const draftRef = useRef(draft)
  draftRef.current = draft
  const pointerY = useRef(0)
  // Where the other rows were on screen just before a move, to slide them from.
  const lastTops = useRef<Map<HTMLElement, number> | null>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || confirmPending) return
      e.stopPropagation()
      if (pop) setPop(null)
      else close()
    }
    document.addEventListener('keydown', onKey, true)
    return () => document.removeEventListener('keydown', onKey, true)
  }, [pop, confirmPending, close])

  // Place the popover under its anchor, or above it when there is no room below.
  useLayoutEffect(() => {
    const el = popRef.current
    const panel = panelRef.current
    if (!pop || !el || !panel) return
    const box = panel.getBoundingClientRect()
    const at = pop.anchor.getBoundingClientRect()
    const left = Math.min(at.left - box.left, box.width - el.offsetWidth - 12)
    const below = at.bottom - box.top + 6
    const top = below + el.offsetHeight > box.height - 8 ? at.top - box.top - el.offsetHeight - 6 : below
    el.style.left = `${Math.max(12, left)}px`
    el.style.top = `${Math.max(8, top)}px`
  }, [pop])

  // A new entry is pointed out and its name selected, ready to type over.
  useEffect(() => {
    if (!fresh) return
    const row = panelRef.current?.querySelector<HTMLElement>(`[data-iid="${CSS.escape(fresh)}"]`)
    row?.scrollIntoView({ block: 'nearest' })
    const input = row?.querySelector<HTMLInputElement>('input[data-field="title"]')
    input?.focus()
    input?.select()
  }, [fresh])

  const edit = (fn: (d: MenuDoc) => MenuDoc) => {
    setError('')
    setDraft(fn)
  }
  const updateItem = (id: string, patch: Partial<MenuItem>) =>
    edit((d) => ({
      ...d,
      groups: d.groups.map((g) => ({ ...g, items: g.items.map((i) => (i.id === id ? { ...i, ...patch } : i)) })),
    }))
  const addItem = (groupId: string, item: MenuItem) => {
    edit((d) => ({ ...d, groups: d.groups.map((g) => (g.id === groupId ? { ...g, items: [...g.items, item] } : g)) }))
    setPop(null)
    setFresh(item.id)
  }
  const addGroup = () => {
    const id = newMenuId('g_')
    edit((d) => ({ ...d, groups: [...d.groups, { id, title: '', items: [] }] }))
    requestAnimationFrame(() => {
      const input = panelRef.current?.querySelector<HTMLInputElement>(`[data-key="${id}:group-title"]`)
      input?.scrollIntoView({ block: 'center' })
      input?.focus()
    })
  }
  const togglePop = (next: Pop) => setPop((cur) => (cur && cur.anchor === next.anchor ? null : next))

  // -------------------------------------------------------------------
  // Sorting: rows between and within groups, and the groups themselves.
  // It follows the pointer directly instead of going through HTML5 drag
  // and drop, which hands the gesture to the system's drag session.
  // -------------------------------------------------------------------

  const beginDrag = (e: React.PointerEvent, type: Drag['type'], id: string) => {
    if (e.button !== 0) return
    e.preventDefault()
    const el = (e.currentTarget as HTMLElement).closest<HTMLElement>(type === 'item' ? '[data-iid]' : '[data-gid]')
    if (!el) return
    setPop(null)
    pointerY.current = e.clientY
    setDrag({ type, id, y: e.clientY, grab: e.clientY - el.getBoundingClientRect().top })
  }

  // After a move: put the dragged one back under the pointer from its new
  // slot, and slide the rest from where they were to where they now sit.
  useLayoutEffect(() => {
    const body = bodyRef.current
    const tops = lastTops.current
    lastTops.current = null
    if (!drag || !body) return
    follow(body, drag, pointerY.current)
    tops?.forEach((before, el) => {
      if (!el.isConnected) return
      el.style.transition = 'none'
      el.style.transform = ''
      const delta = before - el.getBoundingClientRect().top
      if (!delta) return
      el.style.transform = `translateY(${delta}px)`
      void el.offsetHeight
      el.style.transition = `transform ${SORT_MS}ms ease`
      el.style.transform = ''
    })
  }, [draft, drag])

  useEffect(() => {
    const body = bodyRef.current
    if (!drag || !body) return
    let y = drag.y
    const place = () => {
      const sections = Array.from(body.querySelectorAll<HTMLElement>(':scope > [data-gid]'))
      let next = draftRef.current
      if (drag.type === 'item') {
        const section = sections.find((s) => y < s.getBoundingClientRect().bottom) ?? sections[sections.length - 1]
        const gid = section?.dataset.gid
        if (!gid) return
        const rows = Array.from(section.querySelectorAll<HTMLElement>('[data-iid]')).filter((r) => r.dataset.iid !== drag.id)
        next = moveItem(next, drag.id, gid, firstBelow(rows, y)?.dataset.iid ?? null)
      } else {
        const others = sections.filter((s) => s.dataset.gid !== drag.id)
        next = moveGroup(next, drag.id, firstBelow(others, y)?.dataset.gid ?? null)
      }
      if (next === draftRef.current) return
      const self = dragged(body, drag)
      lastTops.current = new Map(
        sortables(body, drag.type)
          .filter((el) => el !== self)
          .map((el) => [el, el.getBoundingClientRect().top]),
      )
      draftRef.current = next
      setDraft(next)
    }
    let frame = 0
    const scroll = () => {
      const box = body.getBoundingClientRect()
      const step = y < box.top + SCROLL_EDGE ? -8 : y > box.bottom - SCROLL_EDGE ? 8 : 0
      if (step) {
        body.scrollTop += step
        follow(body, drag, y)
        place()
      }
      frame = requestAnimationFrame(scroll)
    }
    const onMove = (e: PointerEvent) => {
      y = e.clientY
      pointerY.current = y
      follow(body, drag, y)
      place()
    }
    const onUp = () => {
      const el = dragged(body, drag)
      if (el) {
        el.style.transition = `transform ${SORT_MS}ms ease`
        el.style.transform = ''
      }
      setDrag(null)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    window.addEventListener('pointercancel', onUp)
    document.documentElement.classList.add('menu-sorting')
    frame = requestAnimationFrame(scroll)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('pointercancel', onUp)
      document.documentElement.classList.remove('menu-sorting')
      cancelAnimationFrame(frame)
    }
  }, [drag])

  // -------------------------------------------------------------------
  // Saving
  // -------------------------------------------------------------------

  const fail = (key: string, message: string): null => {
    setInvalid(key)
    setError(t(message))
    const input = panelRef.current?.querySelector<HTMLInputElement>(`[data-key="${CSS.escape(key)}"]`)
    input?.scrollIntoView({ block: 'center' })
    input?.focus()
    return null
  }

  /** The draft as the backend stores it, or null after pointing at the first thing to fix. */
  const validated = (): MenuDoc | null => {
    const out = clone(draft)
    for (const group of out.groups) {
      group.title = (group.title || '').trim()
      if (!group.title && !MENU_GROUP_LABELS[group.id]) return fail(`${group.id}:group-title`, 'menu_need_group_title')
      for (const item of group.items) {
        item.title = (item.title || '').trim()
        if (item.type !== 'builtin' && !item.title) return fail(`${item.id}:title`, 'menu_need_title')
        if (item.type === 'url') {
          item.url = (item.url || '').trim()
          if (!/^https?:\/\/[^\s/?#]+/i.test(item.url)) return fail(`${item.id}:url`, 'menu_need_url')
        }
        delete item.file
      }
    }
    return { groups: out.groups }
  }

  const submit = async (menu: MenuDoc | null) => {
    setSaving(true)
    try {
      await save(menu)
      useInstanceStore.getState().setSwitcherHidden(menu ? switcherHidden : false)
      setSaving(false)
      close()
      // The page on screen may be the entry just removed.
      const custom = location.pathname.match(/^\/m\/(.+)$/)
      if (custom && !findItem(useMenuStore.getState().doc, decodeURIComponent(custom[1]))) navigate('/')
    } catch (e) {
      setSaving(false)
      setError((e as Error).message || t('menu_save_failed'))
    }
  }

  const onSave = () => {
    const menu = validated()
    if (menu) void submit(menu)
  }

  const onReset = async () => {
    if (await askConfirm({ titleKey: 'menu_reset', msgKey: 'menu_reset_confirm', okKey: 'menu_reset' })) void submit(null)
  }

  // -------------------------------------------------------------------
  // Drawing
  // -------------------------------------------------------------------

  const handle = (type: Drag['type'], id: string) => (
    <span
      onPointerDown={(e) => beginDrag(e, type, id)}
      title={t('menu_drag')}
      className="inline-flex items-center justify-center w-5 h-7 flex-shrink-0 text-content-tertiary cursor-grab touch-none"
    >
      <GripVertical size={14} />
    </span>
  )

  const renderItem = (item: MenuItem) => {
    const builtin = item.type === 'builtin'
    const known = !builtin || !!(item.view && MENU_BUILTINS[item.view])
    const removable = !builtin || !MENU_DEFAULT_VIEWS.has(item.view || '')
    const required = builtin && MENU_REQUIRED.has(item.view || '')
    const Icon = itemIcon(item)
    const placeholder = builtin ? itemLabel({ ...item, title: '' }) : t('menu_item_title_ph')
    const mode = item.open === 'tab' ? 'tab' : 'embed'

    return (
      <div
        key={item.id}
        data-iid={item.id}
        className={`flex items-center gap-1.5 pl-1 pr-1.5 py-1.5 rounded-lg border bg-surface transition-opacity ${
          fresh === item.id || drag?.id === item.id ? 'border-accent' : 'border-default'
        } ${drag?.id === item.id ? 'relative z-10 shadow-lg' : item.hidden || !known ? 'opacity-55' : ''}`}
      >
        {handle('item', item.id)}
        <button
          onClick={(e) => togglePop({ kind: 'icon', anchor: e.currentTarget, itemId: item.id })}
          title={t('menu_icon')}
          className="inline-flex items-center justify-center w-7 h-7 flex-shrink-0 rounded-md border border-default text-content-secondary hover:border-accent hover:text-accent cursor-pointer transition-colors"
        >
          <Icon size={14} />
        </button>
        <div className="flex-1 min-w-0">
          <input
            data-key={`${item.id}:title`}
            data-field="title"
            value={item.title}
            maxLength={MENU_TITLE_MAX}
            placeholder={placeholder}
            onChange={(e) => {
              setInvalid('')
              updateItem(item.id, { title: e.target.value })
            }}
            className={`${inputClass(invalid === `${item.id}:title`)} ${builtin ? 'placeholder:text-content' : ''}`}
          />
          {item.type === 'url' ? (
            <input
              data-key={`${item.id}:url`}
              value={item.url || ''}
              maxLength={2048}
              spellCheck={false}
              placeholder="https://"
              onChange={(e) => {
                setInvalid('')
                updateItem(item.id, { url: e.target.value })
              }}
              className={`${inputClass(invalid === `${item.id}:url`)} !h-6 !text-[11.5px] font-mono !text-content-secondary`}
            />
          ) : (
            <div className="px-1.5 text-[11.5px] text-content-tertiary truncate" title={item.path}>
              {item.type === 'artifact' ? item.path : t(known ? 'menu_builtin_page' : 'menu_unsupported')}
            </div>
          )}
        </div>
        {item.type === 'url' && (
          <div className="flex flex-shrink-0 rounded-md border border-default p-0.5 text-[11.5px]">
            {(['embed', 'tab'] as const).map((value) => (
              <button
                key={value}
                onClick={() => updateItem(item.id, { open: value })}
                className={`px-2 h-6 rounded cursor-pointer transition-colors ${
                  mode === value ? 'bg-accent-soft text-accent' : 'text-content-tertiary hover:text-content'
                }`}
              >
                {t(value === 'embed' ? 'menu_open_embed' : 'menu_open_tab')}
              </button>
            ))}
          </div>
        )}
        {builtin && (
          <button
            disabled={required}
            onClick={() => updateItem(item.id, { hidden: !item.hidden })}
            title={t(required ? 'menu_required' : item.hidden ? 'menu_show' : 'menu_hide')}
            className={iconBtn}
          >
            {item.hidden ? <EyeOff size={14} /> : <Eye size={14} />}
          </button>
        )}
        {removable && (
          <button
            onClick={() =>
              edit((d) => ({ ...d, groups: d.groups.map((g) => ({ ...g, items: g.items.filter((i) => i.id !== item.id) })) }))
            }
            title={t('menu_remove')}
            className={iconBtn}
          >
            <X size={14} />
          </button>
        )}
      </div>
    )
  }

  const renderPop = () => {
    if (!pop) return null
    if (pop.kind === 'icon') {
      const found = findItem(draft, pop.itemId)
      if (!found) return null
      const current = found.item.icon
      const pick = (icon: string) => {
        updateItem(pop.itemId, { icon })
        setPop(null)
      }
      return (
        <div className="w-[248px] p-2">
          <button
            onClick={() => pick('')}
            className={`w-full h-7 mb-1.5 rounded-md text-[12px] cursor-pointer transition-colors ${
              current ? 'text-content-secondary hover:bg-surface-2' : 'bg-accent-soft text-accent'
            }`}
          >
            {t('menu_icon_default')}
          </button>
          <div className="grid grid-cols-8 gap-0.5">
            {Object.entries(MENU_ICONS).map(([key, Icon]) => (
              <button
                key={key}
                title={key}
                onClick={() => pick(key)}
                className={`inline-flex items-center justify-center h-7 rounded-md cursor-pointer transition-colors ${
                  current === key ? 'bg-accent-soft text-accent' : 'text-content-secondary hover:bg-surface-2 hover:text-content'
                }`}
              >
                <Icon size={14} />
              </button>
            ))}
          </div>
        </div>
      )
    }
    if (pop.kind === 'add') {
      const { anchor, groupId } = pop
      // Pages the menu does not carry yet, listed by name rather than behind a
      // submenu of their own.
      const present = new Set<string>()
      draft.groups.forEach((g) => g.items.forEach((i) => i.type === 'builtin' && i.view && present.add(i.view)))
      const pages = Object.keys(MENU_BUILTINS).filter((view) => !present.has(view))
      return (
        <div className="w-[220px] py-1">
          <button className={popRow} onClick={() => setPop({ kind: 'artifact', anchor, groupId })}>
            <FileText size={14} className="text-content-tertiary" />
            {t('menu_add_artifact')}
          </button>
          <button
            className={popRow}
            onClick={() => addItem(groupId, { id: newMenuId('m_'), type: 'url', title: '', icon: '', url: '', open: 'embed' })}
          >
            <Globe size={14} className="text-content-tertiary" />
            {t('menu_add_url')}
          </button>
          {pages.length > 0 && (
            <>
              <div className="my-1 mx-2 border-t border-subtle" />
              <div className="px-3 pt-1 pb-0.5 text-[11px] text-content-tertiary">{t('menu_add_builtin')}</div>
              {pages.map((view) => {
                const Icon = MENU_BUILTINS[view].icon
                return (
                  <button key={view} className={popRow} onClick={() => addItem(groupId, builtinItem(view))}>
                    <Icon size={14} className="text-content-tertiary" />
                    {t(MENU_BUILTINS[view].labelKey)}
                  </button>
                )
              })}
            </>
          )}
        </div>
      )
    }
    const inMenu = new Set<string>()
    draft.groups.forEach((g) => g.items.forEach((i) => i.type === 'artifact' && i.path && inMenu.add(i.path)))
    return (
      <ArtifactPicker
        inMenu={inMenu}
        onPick={(a) =>
          addItem(pop.groupId, {
            id: newMenuId('m_'),
            type: 'artifact',
            path: a.abs_path,
            icon: '',
            title: (a.title || a.file_name || '').slice(0, MENU_TITLE_MAX),
            file: { kind: a.kind, exists: true, file_name: a.file_name, preview_url: a.preview_url, raw_url: a.raw_url },
          })
        }
      />
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        ref={panelRef}
        className="relative w-full max-w-[600px] max-h-[86vh] flex flex-col rounded-card border border-default bg-elevated shadow-xl"
        onMouseDown={(e) => {
          if (pop && !popRef.current?.contains(e.target as Node) && !pop.anchor.contains(e.target as Node)) setPop(null)
        }}
      >
        <div className="flex items-start gap-3 px-5 pt-4 pb-3 border-b border-default">
          <div className="flex-1 min-w-0">
            <h3 className="font-semibold text-content">{t('menu_edit')}</h3>
            <p className="mt-0.5 text-[12px] text-content-tertiary leading-relaxed">{t('menu_edit_desc')}</p>
          </div>
          <button onClick={close} className={iconBtn}>
            <X size={16} />
          </button>
        </div>

        <div
          ref={bodyRef}
          className="flex-1 min-h-0 overflow-y-auto px-4 py-3 space-y-3"
          onScroll={() => pop && setPop(null)}
        >
          <div
            className={`flex items-center gap-1.5 pl-1 pr-1.5 py-1.5 rounded-lg border border-default bg-surface transition-opacity ${
              switcherHidden ? 'opacity-55' : ''
            }`}
          >
            <span className="w-5 flex-shrink-0" />
            <span className="inline-flex items-center justify-center w-7 h-7 flex-shrink-0 rounded-md border border-default text-content-secondary">
              <Laptop size={14} />
            </span>
            <div className="flex-1 min-w-0 px-1.5">
              <div className="text-[13px] text-content truncate">{t('devices_switcher')}</div>
              <div className="text-[11.5px] text-content-tertiary truncate">{t('devices_switcher_desc')}</div>
            </div>
            <button
              onClick={() => setSwitcherHidden((v) => !v)}
              title={t(switcherHidden ? 'menu_show' : 'menu_hide')}
              className={iconBtn}
            >
              {switcherHidden ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
          </div>
          {draft.groups.map((group) => {
            // Footer pages stay in the document for the web console but have no
            // row here, and a group holding nothing else has nothing to edit.
            const rows = group.items.filter((i) => !isFooterItem(i))
            if (group.items.length && !rows.length) return null
            const keeps = group.items.some((i) => i.type === 'builtin' && MENU_DEFAULT_VIEWS.has(i.view || ''))
            return (
              <section
                key={group.id}
                data-gid={group.id}
                className={`rounded-xl border bg-inset p-2 ${drag?.id === group.id ? 'relative z-10 border-accent shadow-lg' : 'border-default'}`}
              >
                <div className="flex items-center gap-1 pb-1.5 pl-1">
                  {handle('group', group.id)}
                  <input
                    data-key={`${group.id}:group-title`}
                    value={group.title}
                    maxLength={MENU_TITLE_MAX}
                    placeholder={MENU_GROUP_LABELS[group.id] ? t(MENU_GROUP_LABELS[group.id]) : t('menu_group_title_ph')}
                    onChange={(e) => {
                      setInvalid('')
                      const title = e.target.value
                      edit((d) => ({ ...d, groups: d.groups.map((g) => (g.id === group.id ? { ...g, title } : g)) }))
                    }}
                    className={`${inputClass(invalid === `${group.id}:group-title`)} !text-[12px] font-semibold ${
                      MENU_GROUP_LABELS[group.id] ? 'placeholder:text-content-secondary' : ''
                    }`}
                  />
                  <button
                    onClick={(e) => togglePop({ kind: 'add', anchor: e.currentTarget, groupId: group.id })}
                    className="inline-flex items-center gap-1 h-7 px-2 rounded-md text-[12px] text-content-secondary hover:bg-surface-2 hover:text-content cursor-pointer transition-colors flex-shrink-0"
                  >
                    <Plus size={13} />
                    {t('menu_add')}
                  </button>
                  <button
                    disabled={keeps}
                    onClick={() => edit((d) => ({ ...d, groups: d.groups.filter((g) => g.id !== group.id) }))}
                    title={t(keeps ? 'menu_group_keeps_pages' : 'menu_remove')}
                    className={iconBtn}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
                <div className="space-y-1.5 min-h-[6px]">{rows.map(renderItem)}</div>
              </section>
            )
          })}
        </div>

        <div className="flex items-center gap-2 px-5 py-3 border-t border-default">
          <button
            onClick={addGroup}
            className="inline-flex items-center gap-1.5 h-8 px-2 rounded-btn text-[12.5px] text-content-secondary hover:bg-surface-2 hover:text-content cursor-pointer transition-colors"
          >
            <FolderPlus size={14} />
            {t('menu_add_group')}
          </button>
          <button
            onClick={() => void onReset()}
            className="inline-flex items-center gap-1.5 h-8 px-2 rounded-btn text-[12.5px] text-content-secondary hover:bg-surface-2 hover:text-content cursor-pointer transition-colors"
          >
            <RotateCcw size={14} />
            {t('menu_reset')}
          </button>
          <span className="flex-1 min-w-0 text-right text-[12px] text-danger truncate">{error}</span>
          <Btn onClick={close}>{t('config_cancel')}</Btn>
          <Btn variant="primary" disabled={saving} onClick={onSave}>
            {t('config_save')}
          </Btn>
        </div>

        {pop && (
          <div
            ref={popRef}
            className="absolute z-10 rounded-lg border border-default bg-elevated shadow-lg overflow-hidden"
            style={{ left: -9999, top: 0 }}
          >
            {renderPop()}
          </div>
        )}
      </div>
    </div>
  )
}

/** Recent artifacts across every Agent, searchable; those already in the menu are greyed out. */
const ArtifactPicker: React.FC<{ inMenu: Set<string>; onPick: (a: ArtifactListItem) => void }> = ({ inMenu, onPick }) => {
  const [query, setQuery] = useState('')
  const [state, setState] = useState<{ items: ArtifactListItem[]; loading: boolean; failed: boolean }>({
    items: [],
    loading: true,
    failed: false,
  })

  useEffect(() => {
    let cancelled = false
    setState((s) => ({ ...s, loading: true }))
    const timer = setTimeout(
      () => {
        apiClient
          .listPageArtifacts(query.trim())
          .then((res) => {
            if (cancelled) return
            setState({ items: (res.items || []).filter((a) => a.exists), loading: false, failed: res.status !== 'success' })
          })
          .catch(() => !cancelled && setState({ items: [], loading: false, failed: true }))
      },
      query ? 220 : 0,
    )
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [query])

  return (
    <div className="w-[300px] h-[320px] flex flex-col">
      <label className="flex items-center gap-2 m-2 mb-1 px-2.5 h-8 rounded-md bg-inset text-content-tertiary">
        <Search size={13} />
        <input
          autoFocus
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          spellCheck={false}
          placeholder={t('menu_artifact_search')}
          className="flex-1 min-w-0 bg-transparent text-[13px] text-content placeholder:text-content-tertiary focus:outline-none"
        />
      </label>
      <div className="flex-1 min-h-0 overflow-y-auto py-1">
        {state.loading && !state.items.length ? (
          <div className="flex justify-center py-6 text-content-tertiary">
            <Loader2 size={16} className="animate-spin" />
          </div>
        ) : state.items.length ? (
          state.items.map((a) => {
            const Icon = iconFor(a.kind)
            const added = inMenu.has(a.abs_path)
            return (
              <button
                key={a.id}
                disabled={added}
                onClick={() => onPick(a)}
                className="w-full flex items-start gap-2.5 px-3 py-1.5 text-left hover:bg-surface-2 cursor-pointer transition-colors disabled:opacity-50 disabled:cursor-default disabled:hover:bg-transparent"
              >
                <Icon size={15} className={`flex-shrink-0 mt-0.5 ${colorFor(a.kind)}`} />
                <span className="flex-1 min-w-0">
                  <span className="block text-[13px] text-content truncate">{a.title || a.file_name}</span>
                  <span className="block text-[11px] text-content-tertiary truncate">
                    {added ? t('menu_already_added') : a.rel_path}
                  </span>
                </span>
              </button>
            )
          })
        ) : (
          <div className="px-3 py-6 text-center text-[12px] text-content-tertiary">
            {t(state.failed ? 'menu_artifact_failed' : 'menu_artifact_empty')}
          </div>
        )}
      </div>
    </div>
  )
}

export default MenuEditor
