import React, { useState, useRef, useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  MessageSquare,
  BookOpen,
  Brain,
  Zap,
  Radio,
  Clock,
  Users,
  Settings,
  PanelLeftClose,
  PanelLeftOpen,
  Sun,
  Moon,
  ScrollText,
  MoreHorizontal,
  Download,
  Loader2,
  Globe,
  FileText,
  Store,
  MessageSquareWarning,
  Palette,
  Check,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { Theme } from '../theme/themes'
// The desktop app's own brand icon (transparent PNG), bundled by Vite.
import brandLogo from '../assets/logo.png'
import { t } from '../i18n'
import { useUIStore } from '../store/uiStore'
import { guardDocEditors } from '../store/docEditorStore'
import { useTheme } from '../hooks/useTheme'
import { usePlatform } from '../hooks/usePlatform'
import { useUpdateStore, hasPendingUpdate, hasAvailableUpdate } from '../store/updateStore'
import UpdateBanner from '../components/UpdateBanner'
import { product } from '@product'

// Fallback shown when app.getVersion() is unavailable (dev/web preview). Keep
// in sync with desktop/package.json "version"; the packaged app overrides this
// with the real value via IPC, so it only matters outside a packaged build.
const FALLBACK_VERSION = '2.1.9'

// External links opened in the user's default browser. The window-open handler
// in the main process routes window.open() through shell.openExternal.
// English is the default (no suffix); Chinese gets a /zh suffix. Skill hub is
// language-agnostic.
const SKILL_HUB_URL = 'https://skills.cowagent.ai/'
// GitHub issues — where users report bugs / request features.
const FEEDBACK_URL = 'https://github.com/zhayujie/CowAgent/issues'

const websiteUrl = () => 'https://cowagent.ai'
const docsUrl = () => 'https://docs.cowagent.ai'

const openExternal = (url: string) => {
  window.open(url, '_blank', 'noopener,noreferrer')
}

interface NavItem {
  path: string
  labelKey: string
  icon: LucideIcon
}

const NAV_ITEMS: NavItem[] = [
  { path: '/', labelKey: 'menu_chat', icon: MessageSquare },
  { path: '/knowledge', labelKey: 'menu_knowledge', icon: BookOpen },
  { path: '/memory', labelKey: 'menu_memory', icon: Brain },
  { path: '/skills', labelKey: 'menu_skills', icon: Zap },
  { path: '/channels', labelKey: 'menu_channels', icon: Radio },
  { path: '/tasks', labelKey: 'menu_tasks', icon: Clock },
  { path: '/settings', labelKey: 'menu_settings', icon: Settings },
]

// The Team entry only exists once the install runs more than one Agent, so a
// single-Agent client shows exactly the original menu. Inserted after Chat.
const AGENTS_ITEM: NavItem = { path: '/agents', labelKey: 'menu_agents', icon: Users }

// Language switching (and its onLangChange callback) was removed along with
// the Chinese locales — the desktop app is English-only.
const NavRail: React.FC = () => {
  const location = useLocation()
  const navigate = useNavigate()
  const { navCollapsed, toggleNav } = useUIStore()
  const { theme, toggleTheme, themeId, themes, appName, setThemeId } = useTheme()
  // On macOS the top-left is occupied by the native traffic lights, so the
  // brand mark is only shown on Windows/Linux where that corner is otherwise
  // empty (mirrors the web console's sidebar logo).
  const { isMac } = usePlatform()

  const collapsed = navCollapsed
  const width = collapsed ? 'w-[56px]' : 'w-[208px]'

  // Leaving a page unmounts its document editor, so settle any unsaved work
  // first - here, while declining can still stop the navigation.
  const go = async (path: string) => {
    if (!(await guardDocEditors())) return
    navigate(path)
  }

  // Always surface the Team entry: it is the only way to add a second Agent,
  // so gating it on multi-Agent mode created a chicken-and-egg trap where a
  // single-Agent install could never opt into a team. Inserted after Chat.
  const navItems = [NAV_ITEMS[0], AGENTS_ITEM, ...NAV_ITEMS.slice(1)]

  const updateState = useUpdateStore()
  // Footer dot: hidden once dismissed for this version (user asked for this).
  const pendingUpdate = hasPendingUpdate(updateState)
  // Menu "check for update" dot: stays as long as an update actually exists,
  // even after dismissing the footer badge.
  const availableUpdate = hasAvailableUpdate(updateState)
  const checking = updateState.status?.state === 'checking'

  const [menuOpen, setMenuOpen] = useState(false)
  // Local fallback so a version always shows even if the main-process IPC is
  // unavailable (e.g. dev/web preview). The real value comes from
  // app.getVersion() (packaged package.json), never from a remote service.
  const [version, setVersion] = useState(FALLBACK_VERSION)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    window.electronAPI
      ?.getAppVersion?.()
      .then((v) => v && setVersion(v))
      .catch(() => {})
  }, [])

  // Close the popover on any outside click / Escape.
  useEffect(() => {
    if (!menuOpen) return
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenuOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [menuOpen])

  // Track a user-initiated check so we can show "up to date" feedback in the
  // menu when the result comes back as not-available (the auto poll stays
  // silent). Cleared shortly after, and whenever the menu closes.
  const [checkedManually, setCheckedManually] = useState(false)
  const updateStatusState = updateState.status?.state

  useEffect(() => {
    if (!checkedManually) return
    if (updateStatusState === 'not-available') {
      const id = setTimeout(() => setCheckedManually(false), 4000)
      return () => clearTimeout(id)
    }
    // A pending update opens its own panel; no need for the inline hint.
    if (updateStatusState === 'available' || updateStatusState === 'downloaded') {
      setCheckedManually(false)
    }
    return
  }, [checkedManually, updateStatusState])

  useEffect(() => {
    if (!menuOpen) setCheckedManually(false)
  }, [menuOpen])

  const checkUpdate = () => {
    setCheckedManually(true)
    // If an update is already known, recheck() re-opens its panel, so close the
    // menu to reveal it. Otherwise keep the menu OPEN: the "up to date" result
    // shows inline as the menu label — closing it (which resets checkedManually)
    // is exactly what made the box flash and never show "up to date".
    if (availableUpdate) setMenuOpen(false)
    updateState.recheck()
  }

  return (
    <aside className={`${width} flex flex-col flex-shrink-0 h-full bg-base transition-[width] duration-200`}>
      {/* Top: full-width drag strip; bottom border continues the header divider
          across the whole window. No right border so it doesn't cut the lights.
          On Windows/Linux the top-left corner is empty (no traffic lights), so
          we surface the brand mark here like the web console's sidebar. */}
      <div
        className={`titlebar-drag h-[44px] flex-shrink-0 border-b border-default flex items-center ${
          collapsed ? 'justify-center px-0' : 'px-3'
        }`}
      >
        {!isMac &&
          (product.slots?.NavRailBrand ? (
            // A build may render its own wordmark in the brand area.
            <product.slots.NavRailBrand collapsed={collapsed} />
          ) : (
            <div className="flex items-center gap-2 min-w-0 select-none">
              <BrandLogo />
              {!collapsed && (
                <span className="text-[14px] font-semibold text-content truncate">{appName}</span>
              )}
            </div>
          ))}
      </div>

      {/* Content area carries the right divider, starting below the titlebar */}
      <div className="flex-1 flex flex-col min-h-0 border-r border-default">
      {/* Nav items */}
      <nav className="flex-1 overflow-y-auto px-2 py-2 space-y-0.5">
        {navItems.map((item) => {
          const Icon = item.icon
          const isActive = location.pathname === item.path
          return (
            <button
              key={item.path}
              onClick={() => void go(item.path)}
              title={collapsed ? t(item.labelKey) : undefined}
              className={`group w-full flex items-center gap-3 rounded-btn cursor-pointer transition-colors h-9 ${
                collapsed ? 'justify-center px-0' : 'px-3'
              } ${
                isActive
                  ? 'bg-accent-soft text-accent'
                  : 'text-content-secondary hover:bg-surface-2 hover:text-content'
              }`}
            >
              <Icon size={18} strokeWidth={isActive ? 2.2 : 1.8} className="flex-shrink-0" />
              {!collapsed && <span className="text-[13px] truncate">{t(item.labelKey)}</span>}
            </button>
          )
        })}
      </nav>

      {/* Update banner floats above the footer when a new version is pending */}
      <div className="relative">
        {!collapsed && <UpdateBanner />}
      </div>

      {/* Footer actions: a single "more" entry (with version + update dot) that
          opens an upward popover, plus the always-visible collapse toggle. An
          optional '@product' slot sits on the left (e.g. an account avatar),
          taking the spot the "more" entry would otherwise occupy. */}
      <div className="flex-shrink-0 px-2 py-2 border-t border-subtle relative" ref={menuRef}>
        {menuOpen && (
          <FooterMenu
            theme={theme}
            checking={checking}
            pendingUpdate={availableUpdate}
            upToDate={checkedManually && updateStatusState === 'not-available' && !availableUpdate}
            onLogs={() => {
              setMenuOpen(false)
              void go('/logs')
            }}
            onTheme={toggleTheme}
            themeId={themeId}
            themes={themes}
            onThemeId={setThemeId}
            onCheckUpdate={checkUpdate}
            onOpenLink={(url) => {
              setMenuOpen(false)
              openExternal(url)
            }}
          />
        )}

        <div className={collapsed ? 'space-y-0.5' : 'flex items-center gap-1'}>
          {/* Left side: either the built-in "more" entry (version + dots) or,
              when an extension provides one and hides the built-in menu, its
              footer slot (e.g. an account avatar). */}
          {product.slots?.NavRailFooter && product.nav?.hideFooterMenu ? (
            <div className={collapsed ? '' : 'flex-1 min-w-0'}>
              <product.slots.NavRailFooter />
            </div>
          ) : (
            !product.nav?.hideFooterMenu && (
              <button
                onClick={() => setMenuOpen((o) => !o)}
                title={t('menu_more')}
                className={`relative inline-flex items-center rounded-btn cursor-pointer transition-colors ${
                  menuOpen ? 'bg-surface-2 text-content' : 'text-content-tertiary hover:text-content hover:bg-surface-2'
                } ${collapsed ? 'w-full h-9 justify-center' : 'h-8 px-2 gap-1.5'}`}
              >
                {!collapsed && version && (
                  <span className="text-[12px] truncate">{`v${version}`}</span>
                )}
                <MoreHorizontal size={17} className="flex-shrink-0" />
                {pendingUpdate && (
                  <span className="absolute top-1 right-1 h-2 w-2 rounded-full bg-danger" />
                )}
              </button>
            )
          )}

          {!collapsed && !(product.slots?.NavRailFooter && product.nav?.hideFooterMenu) && (
            <div className="flex-1" />
          )}

          <FooterBtn collapsed={collapsed} onClick={toggleNav} title={collapsed ? t('nav_expand') : t('nav_collapse')}>
            {collapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}
          </FooterBtn>
        </div>
      </div>
      </div>
    </aside>
  )
}

// Brand mark for the top-left corner (Windows/Linux). Uses the desktop app's
// own icon (transparent PNG with its own rounded shape), so it sits cleanly on
// both light and dark backgrounds without extra styling.
const BrandLogo: React.FC = () => (
  <img
    src={brandLogo}
    alt="CowAgent"
    draggable={false}
    className="flex-shrink-0 w-7 h-7 object-contain"
  />
)

const FooterBtn: React.FC<{
  collapsed: boolean
  onClick: () => void
  title: string
  active?: boolean
  children: React.ReactNode
}> = ({ collapsed, onClick, title, active, children }) => (
  <button
    onClick={onClick}
    title={title}
    className={`inline-flex items-center gap-1.5 rounded-btn cursor-pointer transition-colors ${
      active
        ? 'bg-accent-soft text-accent'
        : 'text-content-tertiary hover:text-content hover:bg-surface-2'
    } ${collapsed ? 'w-full h-9 justify-center' : 'h-8 px-2'}`}
  >
    {children}
  </button>
)

// Upward popover holding the secondary actions previously crammed into the
// footer (theme, language, logs, update check). Keeps the footer to a single
// entry so new items can be added here without cluttering the rail.
const FooterMenu: React.FC<{
  theme: string
  checking: boolean
  pendingUpdate: boolean
  upToDate: boolean
  themeId: string
  themes: Theme[]
  onThemeId: (id: string) => void
  onLogs: () => void
  onTheme: () => void
  onCheckUpdate: () => void
  onOpenLink: (url: string) => void
}> = ({ theme, checking, pendingUpdate, upToDate, themeId, themes, onThemeId, onLogs, onTheme, onCheckUpdate, onOpenLink }) => {
  const [themeMenuOpen, setThemeMenuOpen] = useState(false)
  const updateLabel = checking
    ? t('update_checking')
    : upToDate
      ? t('update_latest')
      : t('update_check')
  return (
  <div className="absolute bottom-full left-2 right-2 mb-2 z-50 rounded-lg border border-default bg-elevated shadow-lg py-1">
    {/* External destinations (skill hub, docs, website, feedback). An
        extension may hide this group to keep the menu to app actions only. */}
    {!product.nav?.hideExternalLinks && (
      <>
        <MenuItem icon={<Store size={16} />} label={t('menu_skill_hub')} onClick={() => onOpenLink(SKILL_HUB_URL)} />
        <MenuItem icon={<FileText size={16} />} label={t('menu_docs')} onClick={() => onOpenLink(docsUrl())} />
        <MenuItem icon={<Globe size={16} />} label={t('menu_website')} onClick={() => onOpenLink(websiteUrl())} />
        <MenuItem
          icon={<MessageSquareWarning size={16} />}
          label={t('menu_feedback')}
          onClick={() => onOpenLink(FEEDBACK_URL)}
        />
        <div className="my-1 border-t border-subtle" />
      </>
    )}

    {/* App actions below: update, theme, language, logs */}
    <MenuItem
      icon={checking ? <Loader2 size={16} className="animate-spin" /> : <Download size={16} />}
      label={updateLabel}
      onClick={onCheckUpdate}
      dot={pendingUpdate}
      disabled={checking || upToDate}
    />
    <MenuItem
      icon={theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
      label={theme === 'dark' ? t('menu_theme_light') : t('menu_theme_dark')}
      onClick={onTheme}
    />
    <MenuItem
      icon={<Palette size={16} />}
      label={t('menu_theme_picker')}
      trailing={themeMenuOpen ? '▾' : '▸'}
      onClick={() => setThemeMenuOpen((o) => !o)}
    />
    {themeMenuOpen &&
      themes.map((th) => (
        <button
          key={th.id}
          onClick={() => onThemeId(th.id)}
          className="w-full flex items-center gap-2.5 pl-8 pr-3 h-9 text-[13px] text-content-secondary hover:bg-surface-2 hover:text-content cursor-pointer transition-colors"
        >
          <ThemeSwatch preview={th.preview ?? { accent: '#4abe6e', bg: '#111', surface: '#1c1c1f' }} />
          <span className="flex-1 text-left truncate">{th.name}</span>
          {themeId === th.id && <Check size={14} className="flex-shrink-0 text-accent" />}
        </button>
      ))}
    <MenuItem icon={<ScrollText size={16} />} label={t('menu_logs')} onClick={onLogs} />
  </div>
  )
}

// Tiny 3-color preview (bg / surface / accent) for the theme picker.
const ThemeSwatch: React.FC<{ preview: { accent: string; bg: string; surface: string } }> = ({
  preview,
}) => (
  <span className="flex-shrink-0 inline-flex h-4 w-4 rounded-full overflow-hidden border border-default">
    <span className="w-1/3 h-full" style={{ background: preview.bg }} />
    <span className="w-1/3 h-full" style={{ background: preview.surface }} />
    <span className="w-1/3 h-full" style={{ background: preview.accent }} />
  </span>
)

const MenuItem: React.FC<{
  icon: React.ReactNode
  label: string
  trailing?: string
  dot?: boolean
  disabled?: boolean
  onClick: () => void
}> = ({ icon, label, trailing, dot, disabled, onClick }) => (
  <button
    disabled={disabled}
    onClick={onClick}
    className="w-full flex items-center gap-2.5 px-3 h-9 text-[13px] text-content-secondary hover:bg-surface-2 hover:text-content cursor-pointer transition-colors disabled:cursor-default disabled:hover:bg-transparent disabled:hover:text-content-secondary"
  >
    <span className="flex-shrink-0 text-content-tertiary relative">
      {icon}
      {dot && <span className="absolute -top-0.5 -right-0.5 h-1.5 w-1.5 rounded-full bg-danger" />}
    </span>
    <span className="flex-1 text-left truncate">{label}</span>
    {trailing && <span className="text-[11px] font-medium text-content-tertiary">{trailing}</span>}
  </button>
)

export default NavRail
