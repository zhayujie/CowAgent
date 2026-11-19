// ============================================================
// Theme Contract — single source of truth for themes.
//
// A "theme" is pure data: it overrides semantic design tokens
// (colors, radius, shadow, font) and an optional background
// wallpaper. It never touches component code or DOM structure,
// so themes stay stable across UI refactors — as long as
// components keep consuming these tokens, old themes keep working.
//
// Contract rule: themes may ONLY set fields defined here. Adding a
// new token is an additive, versioned change (bump THEME_SPEC_VERSION).
//
// Built-in themes are pure color data defined below ('default' plus a few
// palettes); they ship no images. Everything else lives in
// <workspace>/system/themes/<id>/ (theme.json + images) and is loaded at runtime via the
// main process, which inlines images as data URLs.
// ============================================================

// ---- Color tokens (per-appearance) -------------------------
export const COLOR_KEYS = [
  'accent',
  'accentHover',
  'accentActive',
  'accentSoft',
  'accentContrast',
  'bubbleUserBg',
  'bubbleUserText',
  'bgBase',
  'bgSurface',
  'bgSurface2',
  'bgElevated',
  'bgInset',
  'bgInset2',
  'textPrimary',
  'textSecondary',
  'textTertiary',
  'textDisabled',
  'borderDefault',
  'borderStrong',
  'borderSubtle',
  'shadowSm',
  'shadowMd',
  'shadowLg',
] as const
export type ColorKey = (typeof COLOR_KEYS)[number]

// ---- Shape tokens (appearance-independent) -----------------
// Radius / font apply regardless of light or dark.
export const SHAPE_KEYS = ['radiusCard', 'radiusBtn', 'radiusSm', 'fontSans', 'fontMono'] as const
export type ShapeKey = (typeof SHAPE_KEYS)[number]

// camelCase token -> --kebab-case CSS variable
export function tokenToCssVar(key: string): string {
  return '--' + key.replace(/[A-Z0-9]/g, (m) => '-' + m.toLowerCase())
}

// ---- Wallpaper (Codex-style ambient background) ------------
export interface Wallpaper {
  // Image URL (bundled asset path or data/file URL). Empty = solid color.
  image?: string
  focusX?: number // 0..1 horizontal focal point, default 0.5
  focusY?: number // 0..1 vertical focal point, default 0.5
  overlayOpacity?: number // 0..1 scrim strength over the image, default per-appearance
  // Panels become translucent + blurred (frosted glass) so the wallpaper
  // shows through. When false, panels stay solid (wallpaper only behind base).
  glass?: boolean
}

export interface ThemeAppearance {
  colors?: Partial<Record<ColorKey, string>>
  wallpaper?: Wallpaper
}

// Optional per-theme identity: a logo shown on the new-chat home page.
export interface ThemeIdentity {
  logo?: string // data URL (inlined by main)
}

export interface Theme {
  id: string
  name: string
  specVersion?: number
  // Optional preview swatch; when absent it's derived from colors.
  preview?: { accent: string; bg: string; surface: string }
  identity?: ThemeIdentity
  // Appearance-independent shape tokens.
  shape?: Partial<Record<ShapeKey, string>>
  // Per-appearance colors + wallpaper. A theme.json may instead set one
  // top-level `wallpaper` for both; loading folds it into each appearance.
  light?: ThemeAppearance
  dark?: ThemeAppearance
}

// Bump when the contract changes in a breaking way. theme.json files declare
// which version they target so imports can be validated.
export const THEME_SPEC_VERSION = 1

// 'default' uses the built-in :root / .dark values in index.css and
// applies no data-theme attribute nor overrides.
export const DEFAULT_THEME_ID = 'default'

// 'default' maps to the base :root / .dark values in index.css (no overrides).
export const DEFAULT_THEME: Theme = {
  id: DEFAULT_THEME_ID,
  name: 'Meadow',
  preview: { accent: '#4abe6e', bg: '#f9fafb', surface: '#ffffff' },
}

// Dark-mode borders are shared: translucent white reads well on any tint.
const DARK_BORDERS = {
  borderDefault: 'rgba(255, 255, 255, 0.08)',
  borderStrong: 'rgba(255, 255, 255, 0.14)',
  borderSubtle: 'rgba(255, 255, 255, 0.04)',
}

// Color-only palettes shipped with the app. Accents stay dark enough in both
// appearances for the white text some accent buttons use.
const BUILTIN_PALETTES: Theme[] = [
  {
    id: 'ocean',
    name: 'Ocean',
    preview: { accent: '#3370ff', bg: '#f7f9fc', surface: '#ffffff' },
    light: {
      colors: {
        accent: '#3370ff',
        accentHover: '#2f68ee',
        accentActive: '#2559d6',
        accentSoft: 'rgba(51, 112, 255, 0.10)',
        accentContrast: '#ffffff',
        bubbleUserBg: '#e6efff',
        bubbleUserText: '#1a3a7a',
        bgBase: '#f7f9fc',
        bgSurface: '#ffffff',
        bgSurface2: '#eef2f9',
        bgElevated: '#ffffff',
        bgInset: '#eef2f9',
        bgInset2: '#eef2f9',
        textPrimary: '#1a2233',
        textSecondary: '#48536b',
        textTertiary: '#6b7488',
        textDisabled: '#9aa3b5',
        borderDefault: '#e3e8f0',
        borderStrong: '#cbd4e2',
        borderSubtle: '#eef2f9',
      },
    },
    dark: {
      colors: {
        accent: '#4a83ff',
        accentHover: '#5e91ff',
        accentActive: '#3a72f0',
        accentSoft: 'rgba(74, 131, 255, 0.16)',
        accentContrast: '#0e0e10',
        bubbleUserBg: 'rgba(74, 131, 255, 0.20)',
        bubbleUserText: '#dce8ff',
        bgBase: '#0e0e10',
        bgSurface: '#161618',
        bgSurface2: '#1c1c1f',
        bgElevated: '#1f1f23',
        bgInset: '#161618',
        bgInset2: '#161618',
        textPrimary: '#f4f4f5',
        textSecondary: '#c4c4cc',
        textTertiary: '#8e8e96',
        textDisabled: '#5a5a62',
        ...DARK_BORDERS,
      },
    },
  },
  {
    id: 'clay',
    name: 'Clay',
    preview: { accent: '#c96442', bg: '#faf9f5', surface: '#ffffff' },
    light: {
      colors: {
        accent: '#c96442',
        accentHover: '#b8583a',
        accentActive: '#a24d33',
        accentSoft: 'rgba(201, 100, 66, 0.10)',
        accentContrast: '#ffffff',
        bubbleUserBg: '#f1ebe2',
        bubbleUserText: '#3d3424',
        bgBase: '#faf9f5',
        bgSurface: '#ffffff',
        bgSurface2: '#f2f0e9',
        bgElevated: '#ffffff',
        bgInset: '#faf9f5',
        bgInset2: '#f2f0e9',
        textPrimary: '#2b2925',
        textSecondary: '#55524b',
        textTertiary: '#7a766c',
        textDisabled: '#aba79c',
        borderDefault: '#e8e5dc',
        borderStrong: '#d7d3c7',
        borderSubtle: '#f2f0e9',
      },
    },
    dark: {
      colors: {
        accent: '#d97757',
        accentHover: '#e08a6d',
        accentActive: '#c96442',
        accentSoft: 'rgba(217, 119, 87, 0.16)',
        accentContrast: '#ffffff',
        bubbleUserBg: 'rgba(217, 119, 87, 0.18)',
        bubbleUserText: '#f7e1d7',
        bgBase: '#1f1e1c',
        bgSurface: '#262624',
        bgSurface2: '#302f2c',
        bgElevated: '#2c2b29',
        bgInset: '#262624',
        bgInset2: '#2a2927',
        textPrimary: '#f5f4ef',
        textSecondary: '#cdcac0',
        textTertiary: '#9b978d',
        textDisabled: '#67645d',
        ...DARK_BORDERS,
      },
    },
  },
  {
    id: 'sakura',
    name: 'Sakura',
    preview: { accent: '#e16b8c', bg: '#fcf8f9', surface: '#ffffff' },
    light: {
      colors: {
        accent: '#e16b8c',
        accentHover: '#d65c7e',
        accentActive: '#c24f70',
        accentSoft: 'rgba(225, 107, 140, 0.10)',
        accentContrast: '#ffffff',
        bubbleUserBg: '#fce8ee',
        bubbleUserText: '#7a2e47',
        bgBase: '#fcf8f9',
        bgSurface: '#ffffff',
        bgSurface2: '#f8eef1',
        bgElevated: '#ffffff',
        bgInset: '#fcf8f9',
        bgInset2: '#f6ecef',
        textPrimary: '#2f2529',
        textSecondary: '#5f5157',
        textTertiary: '#887a80',
        textDisabled: '#bcb0b5',
        borderDefault: '#f0e3e8',
        borderStrong: '#e3d1d8',
        borderSubtle: '#f8eef1',
      },
    },
    dark: {
      colors: {
        accent: '#e8799a',
        accentHover: '#ee8eab',
        accentActive: '#da6a8b',
        accentSoft: 'rgba(232, 121, 154, 0.16)',
        accentContrast: '#ffffff',
        bubbleUserBg: 'rgba(232, 121, 154, 0.18)',
        bubbleUserText: '#ffe4ec',
        bgBase: '#131113',
        bgSurface: '#1a181a',
        bgSurface2: '#221f22',
        bgElevated: '#242124',
        bgInset: '#1a181a',
        bgInset2: '#1a181a',
        textPrimary: '#f6eff2',
        textSecondary: '#d4c8cd',
        textTertiary: '#9e9197',
        textDisabled: '#675b60',
        ...DARK_BORDERS,
      },
    },
  },
  {
    id: 'lavender',
    name: 'Lavender',
    preview: { accent: '#8467d8', bg: '#f9f8fc', surface: '#ffffff' },
    light: {
      colors: {
        accent: '#8467d8',
        accentHover: '#7659cb',
        accentActive: '#684cb8',
        accentSoft: 'rgba(132, 103, 216, 0.10)',
        accentContrast: '#ffffff',
        bubbleUserBg: '#efebfb',
        bubbleUserText: '#3f3075',
        bgBase: '#f9f8fc',
        bgSurface: '#ffffff',
        bgSurface2: '#f1eff8',
        bgElevated: '#ffffff',
        bgInset: '#f9f8fc',
        bgInset2: '#efedf6',
        textPrimary: '#25222f',
        textSecondary: '#524d62',
        textTertiary: '#787388',
        textDisabled: '#aca8ba',
        borderDefault: '#e8e5f0',
        borderStrong: '#d8d4e5',
        borderSubtle: '#f1eff8',
      },
    },
    dark: {
      colors: {
        accent: '#9c86ee',
        accentHover: '#ac99f2',
        accentActive: '#8d76e3',
        accentSoft: 'rgba(156, 134, 238, 0.16)',
        accentContrast: '#ffffff',
        bubbleUserBg: 'rgba(156, 134, 238, 0.18)',
        bubbleUserText: '#ece7ff',
        bgBase: '#111014',
        bgSurface: '#18171c',
        bgSurface2: '#1f1e24',
        bgElevated: '#222127',
        bgInset: '#18171c',
        bgInset2: '#18171c',
        textPrimary: '#f3f2f7',
        textSecondary: '#cbc8d6',
        textTertiary: '#928ea1',
        textDisabled: '#5f5c6b',
        ...DARK_BORDERS,
      },
    },
  },
]

export const BUILTIN_THEMES: Theme[] = [DEFAULT_THEME, ...BUILTIN_PALETTES]
// Ids a theme loaded from disk can't take (built-ins always win).
export const BUILTIN_THEME_IDS = BUILTIN_THEMES.map((t) => t.id)

// Built-ins a build opts out of (app config `hiddenThemes`), e.g. when it
// ships its own theme in a similar color. 'default' can't be hidden.
let hiddenBuiltins: string[] = []

export function setHiddenThemes(ids: string[] | undefined): void {
  hiddenBuiltins = (ids ?? []).filter((id) => id !== DEFAULT_THEME_ID)
}

// Runtime registry: built-ins first, then whatever was loaded from ~/.cow.
let runtimeThemes: Theme[] = BUILTIN_THEMES

// ---- Normalizing loaded themes -----------------------------
// theme.json files come from users and the agent, written against whatever
// contract version they knew. Rebuild each one from the fields this contract
// defines, with the right types, so unknown or retired keys are ignored and a
// malformed value can only drop that one field, never break rendering.

const isRecord = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v)

// A CSS value for a token. Resource references are refused so a theme can't
// make the app fetch remote content.
const isCssValue = (v: unknown): v is string =>
  typeof v === 'string' && v.trim() !== '' && v.length <= 300 && !/url\s*\(|@import|expression\s*\(/i.test(v)

const finite = (v: unknown): number | undefined => (typeof v === 'number' && Number.isFinite(v) ? v : undefined)

function pickTokens<K extends string>(src: unknown, keys: readonly K[]): Partial<Record<K, string>> | undefined {
  if (!isRecord(src)) return undefined
  const out: Partial<Record<K, string>> = {}
  for (const key of keys) {
    const v = src[key]
    if (isCssValue(v)) out[key] = v
  }
  return Object.keys(out).length ? out : undefined
}

// Images arrive as data URLs inlined by the main process and end up inside a
// CSS url("..."), so anything else (or anything that could close it) is dropped.
const isImageUrl = (v: unknown): v is string =>
  typeof v === 'string' && v.startsWith('data:image/') && !/["'\\()\s]/.test(v)

function normalizeWallpaper(wp: unknown): Wallpaper | undefined {
  if (!isRecord(wp) || !isImageUrl(wp.image)) return undefined
  return {
    image: wp.image,
    focusX: finite(wp.focusX),
    focusY: finite(wp.focusY),
    overlayOpacity: finite(wp.overlayOpacity),
    glass: wp.glass === true,
  }
}

function normalizeAppearance(src: unknown): ThemeAppearance | undefined {
  if (!isRecord(src)) return undefined
  const out: ThemeAppearance = {}
  const colors = pickTokens(src.colors, COLOR_KEYS)
  if (colors) out.colors = colors
  const wallpaper = normalizeWallpaper(src.wallpaper)
  if (wallpaper) out.wallpaper = wallpaper
  return out.colors || out.wallpaper ? out : undefined
}

function normalizeTheme(raw: unknown): Theme | null {
  if (!isRecord(raw) || typeof raw.id !== 'string' || !raw.id.trim()) return null
  const theme: Theme = {
    id: raw.id,
    name: typeof raw.name === 'string' && raw.name.trim() ? raw.name.slice(0, 64) : raw.id,
  }
  if (finite(raw.specVersion) !== undefined) theme.specVersion = raw.specVersion as number
  const shape = pickTokens(raw.shape, SHAPE_KEYS)
  if (shape) theme.shape = shape
  const light = normalizeAppearance(raw.light)
  const dark = normalizeAppearance(raw.dark)
  // One wallpaper serves both appearances: an appearance's own wins, then the
  // top-level shared one, then the other appearance's.
  const shared = normalizeWallpaper(raw.wallpaper)
  const lightWp = light?.wallpaper ?? shared ?? dark?.wallpaper
  const darkWp = dark?.wallpaper ?? shared ?? light?.wallpaper
  if (light || lightWp) theme.light = { ...light, wallpaper: lightWp }
  if (dark || darkWp) theme.dark = { ...dark, wallpaper: darkWp }
  const logo = isRecord(raw.identity) ? raw.identity.logo : undefined
  if (isImageUrl(logo)) theme.identity = { logo }
  const p = raw.preview
  theme.preview =
    isRecord(p) && isCssValue(p.accent) && isCssValue(p.bg) && isCssValue(p.surface)
      ? { accent: p.accent, bg: p.bg, surface: p.surface }
      : derivePreview(theme)
  return theme
}

// Derive a preview swatch from a theme's colors when it didn't ship one.
function derivePreview(theme: Theme): { accent: string; bg: string; surface: string } {
  const c = theme.dark?.colors ?? theme.light?.colors ?? {}
  return {
    accent: c.accent ?? '#4abe6e',
    bg: c.bgBase ?? '#111111',
    surface: c.bgSurface ?? '#1c1c1f',
  }
}

// Replace the runtime theme list with built-ins + validated loaded themes.
export function registerRuntimeThemes(themes: unknown[]): void {
  const loaded: Theme[] = []
  const taken = new Set(BUILTIN_THEME_IDS)
  for (const raw of Array.isArray(themes) ? themes : []) {
    const theme = normalizeTheme(raw)
    if (!theme) continue
    // A theme written straight into the folder may reuse a built-in (or
    // another theme's) id; suffix it so it still shows up.
    let id = theme.id
    for (let n = 2; taken.has(id); n++) id = `${theme.id}-${n}`
    taken.add(id)
    loaded.push(id === theme.id ? theme : { ...theme, id })
  }
  runtimeThemes = [...BUILTIN_THEMES.filter((t) => !hiddenBuiltins.includes(t.id)), ...loaded]
}

export function getAllThemes(): Theme[] {
  return runtimeThemes
}

export function getTheme(id: string): Theme {
  return runtimeThemes.find((t) => t.id === id) ?? runtimeThemes[0]
}
