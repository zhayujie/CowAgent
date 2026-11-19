import { useState, useEffect, useCallback, useRef } from 'react'
import {
  BUILTIN_THEME_IDS,
  COLOR_KEYS,
  DEFAULT_THEME_ID,
  getAllThemes,
  getTheme,
  registerRuntimeThemes,
  setHiddenThemes,
  SHAPE_KEYS,
  tokenToCssVar,
  type Theme,
  type Wallpaper,
} from '../theme/themes'
import type { ThemeImportResult } from '../types'
import { askConfirm } from '../store/confirmStore'
import { t } from '../i18n'

export type ThemePref = 'light' | 'dark' | 'system'
export type ResolvedTheme = 'light' | 'dark'

// Appearance preference (light/dark/system).
const PREF_KEY = 'cow_theme'
// Selected theme id (which visual theme is active).
const THEME_ID_KEY = 'cow_theme_id'

function getSystemTheme(): ResolvedTheme {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function readStoredPref(): ThemePref {
  const saved = localStorage.getItem(PREF_KEY)
  if (saved === 'dark' || saved === 'light' || saved === 'system') return saved
  // First run: follow the OS appearance rather than forcing a fixed theme.
  return 'system'
}

function readStoredThemeId(): string {
  return localStorage.getItem(THEME_ID_KEY) || DEFAULT_THEME_ID
}

// Whether the user has ever explicitly chosen a theme. Used so a bundled
// first-run default only applies when the user hasn't made a choice yet.
function hasStoredThemeId(): boolean {
  return localStorage.getItem(THEME_ID_KEY) != null
}

// All CSS variables a theme may inject, so we can fully reset before
// applying one (prevents stale overrides from leaking across switches).
const ASSET_VARS = [
  '--theme-logo',
  '--wallpaper-image',
  '--wallpaper-position',
  '--wallpaper-overlay',
  '--glass-fill',
  '--glass-blur',
  '--surface-alpha',
] as const

function hexToRgb(hex: string): [number, number, number] | null {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim())
  if (!m) return null
  const n = parseInt(m[1], 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

// Apply the resolved appearance (light/dark) as the .dark class, plus the
// active theme's overrides. Themes are pure data: we only write contract
// tokens as inline CSS variables on <html> (and toggle a wallpaper flag on
// <body>), so components restyle without any code change.
//
// A theme must never leave the app unusable: if applying it fails, or its
// text would be unreadable against its own backgrounds, fall back to the
// default theme (the user can still pick another one from the menu).
function applyAppearanceAndTheme(resolved: ResolvedTheme, themeId: string) {
  const theme = getTheme(themeId)
  try {
    applyTheme(resolved, theme)
    if (theme.id === DEFAULT_THEME_ID || isReadable()) return
    console.warn(`[theme] "${theme.id}" has unreadable text colors, using the default theme`)
  } catch (e) {
    console.warn(`[theme] failed to apply "${theme.id}", using the default theme:`, e)
  }
  try {
    applyTheme(resolved, getTheme(DEFAULT_THEME_ID))
  } catch {
    // The base stylesheet still applies.
  }
}

// Text/background pairs that must stay legible for the app to be usable.
const READABLE_PAIRS = [
  ['--text-primary', '--bg-base'],
  ['--text-primary', '--bg-surface'],
  ['--text-secondary', '--bg-elevated'],
] as const
const MIN_CONTRAST = 3

function isReadable(): boolean {
  const css = getComputedStyle(document.documentElement)
  for (const [fg, bg] of READABLE_PAIRS) {
    const a = parseColor(css.getPropertyValue(fg))
    const b = parseColor(css.getPropertyValue(bg))
    // Only judge colors we can parse (hex / rgb[a]); others pass.
    if (a && b && contrastRatio(a, b) < MIN_CONTRAST) return false
  }
  return true
}

function parseColor(value: string): [number, number, number] | null {
  const v = value.trim()
  const short = /^#([0-9a-f]{3})$/i.exec(v)
  if (short) return hexToRgb('#' + short[1].replace(/./g, (c) => c + c))
  if (/^#[0-9a-f]{6}$/i.test(v)) return hexToRgb(v)
  const rgb = /^rgba?\(\s*(\d+(?:\.\d+)?)[\s,]+(\d+(?:\.\d+)?)[\s,]+(\d+(?:\.\d+)?)/i.exec(v)
  return rgb ? [Number(rgb[1]), Number(rgb[2]), Number(rgb[3])] : null
}

function contrastRatio(a: [number, number, number], b: [number, number, number]): number {
  const lum = ([r, g, bl]: [number, number, number]) => {
    const ch = (c: number) => {
      const s = Math.min(255, Math.max(0, c)) / 255
      return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
    }
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(bl)
  }
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

function applyTheme(resolved: ResolvedTheme, theme: Theme) {
  const root = document.documentElement
  root.classList.toggle('dark', resolved === 'dark')

  if (theme.id === DEFAULT_THEME_ID) root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', theme.id)

  activeSurface = {
    light: theme.light?.colors?.bgSurface,
    dark: theme.dark?.colors?.bgSurface,
  }

  // Reset everything a theme can touch, then re-apply the active one.
  for (const key of COLOR_KEYS) root.style.removeProperty(tokenToCssVar(key))
  for (const key of SHAPE_KEYS) root.style.removeProperty(tokenToCssVar(key))
  for (const v of ASSET_VARS) root.style.removeProperty(v)

  // Shape tokens are appearance-independent.
  if (theme.shape) {
    for (const [k, v] of Object.entries(theme.shape)) {
      if (v) root.style.setProperty(tokenToCssVar(k), v)
    }
  }

  const appearance = resolved === 'dark' ? theme.dark : theme.light
  if (appearance?.colors) {
    for (const [k, v] of Object.entries(appearance.colors)) {
      if (v) root.style.setProperty(tokenToCssVar(k), v)
    }
  }

  applyWallpaper(resolved, appearance?.wallpaper)

  const logo = theme.identity?.logo
  if (logo) {
    root.style.setProperty('--theme-logo', `url("${logo}")`)
    root.setAttribute('data-theme-logo', '')
  } else {
    root.removeAttribute('data-theme-logo')
  }
}

// Render (or clear) the ambient wallpaper + frosted-glass panels.
function applyWallpaper(resolved: ResolvedTheme, wp?: Wallpaper) {
  const root = document.documentElement
  const body = document.body
  if (!wp?.image) {
    body.removeAttribute('data-wallpaper')
    return
  }
  body.setAttribute('data-wallpaper', 'on')
  root.style.setProperty('--wallpaper-image', `url("${wp.image}")`)

  const fx = clamp01(wp.focusX ?? 0.5) * 100
  const fy = clamp01(wp.focusY ?? 0.5) * 100
  root.style.setProperty('--wallpaper-position', `${fx}% ${fy}%`)

  // Default scrim: darker in dark mode, lighter in light mode.
  const opacity = clamp01(wp.overlayOpacity ?? (resolved === 'dark' ? 0.3 : 0.4))
  const scrim = resolved === 'dark' ? '0, 0, 0' : '255, 255, 255'
  root.style.setProperty('--wallpaper-overlay', `rgba(${scrim}, ${opacity})`)

  if (wp.glass) {
    // Frosted glass: surfaces become translucent (so the wallpaper shows
    // through) + blurred. We derive the tint from the theme's own surface
    // color so it stays on-palette, then drive alpha via --surface-alpha.
    const themeSurface =
      (resolved === 'dark' ? getThemeSurface('dark') : getThemeSurface('light')) ??
      (resolved === 'dark' ? '#141416' : '#ffffff')
    const rgb = hexToRgb(themeSurface) ?? (resolved === 'dark' ? [20, 20, 22] : [255, 255, 255])
    const alpha = resolved === 'dark' ? 0.55 : 0.62
    root.style.setProperty('--glass-fill', `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${alpha})`)
    root.style.setProperty('--glass-blur', '20px')
    // Also make the generic surface tokens translucent so existing cards
    // (bg-surface) read as glass without touching component code.
    root.style.setProperty('--surface-alpha', String(alpha))
  }
}

// Cache of the active theme's surface color for glass tinting.
let activeSurface: { light?: string; dark?: string } = {}
function getThemeSurface(mode: 'light' | 'dark'): string | undefined {
  return activeSurface[mode]
}

function clamp01(n: number): number {
  return Math.min(1, Math.max(0, n))
}

// Apply the persisted appearance + theme once, before React renders, so the
// first paint already has the right colors (no flash of the default theme).
export function initThemeEarly() {
  const pref = readStoredPref()
  const resolved: ResolvedTheme = pref === 'system' ? getSystemTheme() : pref
  applyAppearanceAndTheme(resolved, readStoredThemeId())
}

export function useTheme() {
  const [pref, setPref] = useState<ThemePref>(readStoredPref)
  const [themeId, setThemeIdState] = useState<string>(readStoredThemeId)
  const [themes, setThemes] = useState<Theme[]>(getAllThemes)
  const [resolved, setResolved] = useState<ResolvedTheme>(() =>
    readStoredPref() === 'system' ? getSystemTheme() : (readStoredPref() as ResolvedTheme)
  )
  // Display name; a bundled app config may override the default.
  const [appName, setAppName] = useState<string>('CowAgent')
  // Snapshot before any effect persists a value, so we can tell a genuine
  // first run (no prior choice) from a user who explicitly picked a theme.
  const [firstRun] = useState(() => !hasStoredThemeId())

  // Load themes (bundled + user) and the optional app config once on mount.
  // On a genuine first run, apply the config's default theme if one is set;
  // otherwise just re-apply the current selection now its definition is loaded.
  useEffect(() => {
    let cancelled = false
    Promise.all([
      window.electronAPI?.listThemes?.() ?? Promise.resolve([]),
      window.electronAPI?.getAppConfig?.() ?? Promise.resolve(null),
    ])
      .then(([remote, config]) => {
        if (cancelled) return
        setHiddenThemes(config?.hiddenThemes)
        registerRuntimeThemes(remote)
        setThemes(getAllThemes())
        if (config?.appName) setAppName(config.appName)

        // First-run default from the app config (if the theme exists).
        if (firstRun && config?.defaultTheme && getTheme(config.defaultTheme).id === config.defaultTheme) {
          setThemeIdState(config.defaultTheme) // triggers the apply effect below
          return
        }
        // Re-apply the current selection now that its definition is loaded.
        const next: ResolvedTheme = readStoredPref() === 'system' ? getSystemTheme() : (readStoredPref() as ResolvedTheme)
        applyAppearanceAndTheme(next, readStoredThemeId())
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [firstRun])

  // Re-apply whenever the appearance preference or theme changes.
  useEffect(() => {
    const next: ResolvedTheme = pref === 'system' ? getSystemTheme() : pref
    setResolved(next)
    applyAppearanceAndTheme(next, themeId)
    localStorage.setItem(PREF_KEY, pref)
    localStorage.setItem(THEME_ID_KEY, themeId)
  }, [pref, themeId])

  // Follow system changes only when preference is "system".
  useEffect(() => {
    if (pref !== 'system') return
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = () => {
      const next = getSystemTheme()
      setResolved(next)
      applyAppearanceAndTheme(next, themeId)
    }
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [pref, themeId])

  const toggleTheme = useCallback(() => {
    setPref(resolved === 'dark' ? 'light' : 'dark')
  }, [resolved])

  const setTheme = useCallback((next: ThemePref) => setPref(next), [])
  const setThemeId = useCallback((next: string) => setThemeIdState(next), [])

  // Re-scan the themes folder so themes added since launch (imported, copied
  // in by hand, or written by the agent) show up without a restart. The
  // active theme is re-applied in case its files changed.
  const lastReload = useRef(0)
  const reloadThemes = useCallback(async (force = false) => {
    const api = window.electronAPI
    if (!api?.listThemes) return
    if (!force && Date.now() - lastReload.current < 1500) return
    lastReload.current = Date.now()
    try {
      registerRuntimeThemes(await api.listThemes())
      setThemes(getAllThemes())
      const p = readStoredPref()
      applyAppearanceAndTheme(p === 'system' ? getSystemTheme() : p, readStoredThemeId())
    } catch {
      // Keep the current list.
    }
  }, [])

  // Import a theme package from `path` (a dropped file / folder) or, without
  // one, from a picker. Asks before replacing a theme with the same id; a
  // successful import becomes the active theme.
  const importTheme = useCallback(async (path?: string): Promise<ThemeImportResult> => {
    const api = window.electronAPI
    if (!api?.importTheme) return { status: 'error', code: 'failed' }
    const reserved = BUILTIN_THEME_IDS
    let res = await api.importTheme({ path, title: t('theme_import_dialog_title'), reserved })
    if (res.status === 'exists') {
      const ok = await askConfirm({
        titleKey: 'theme_import_replace_title',
        msgKey: 'theme_import_replace_msg',
        vars: { name: res.name },
        okKey: 'theme_import_replace_ok',
        tone: 'primary',
      })
      if (!ok) return { status: 'canceled' }
      res = await api.importTheme({ path: res.path, overwrite: true, reserved })
    }
    if (res.status === 'ok') {
      await reloadThemes(true)
      setThemeIdState(res.id)
    }
    return res
  }, [reloadThemes])

  const openThemesDir = useCallback(async () => {
    const api = window.electronAPI
    const dir = await api?.getThemesDir?.()
    if (dir) await api?.openPath(dir)
  }, [])

  return {
    theme: resolved,
    pref,
    themeId,
    themes,
    appName,
    toggleTheme,
    setTheme,
    setThemeId,
    reloadThemes,
    importTheme,
    openThemesDir,
  }
}
