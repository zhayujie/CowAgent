import React, { useState, useRef, useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  PanelLeftClose,
  PanelLeftOpen,
  Sun,
  Moon,
  ScrollText,
  MoreHorizontal,
  Languages,
  Download,
  Loader2,
  Globe,
  FileText,
  Store,
  MessageSquareWarning,
  Palette,
  SquarePen,
  ExternalLink,
} from 'lucide-react'
import type { Theme } from '../theme/themes'
import ThemeFlyout from '../components/ThemePicker'
import ThemeAddModal from '../components/ThemeAddModal'
import type { MenuGroup, MenuItem } from '../types'
// The desktop app's own brand icon (transparent PNG), bundled by Vite.
import brandLogo from '../assets/logo.png'
import { t, getLang, setLang, Lang } from '../i18n'
import { useUIStore } from '../store/uiStore'
import { guardDocEditors } from '../store/docEditorStore'
import { useTheme } from '../hooks/useTheme'
import { usePlatform } from '../hooks/usePlatform'
import { useUpdateStore, hasPendingUpdate, hasAvailableUpdate } from '../store/updateStore'
import UpdateBanner from '../components/UpdateBanner'
import Tooltip from '../components/Tooltip'
import { useMenuStore } from '../store/menuStore'
import { groupLabel, itemIcon, itemLabel, itemRoute, itemShows } from '../lib/menu'
import { product } from '@product'

// Fallback shown when app.getVersion() is unavailable (dev/web preview). Keep
// in sync with desktop/package.json "version"; the packaged app overrides this
// with the real value via IPC, so it only matters outside a packaged build.
const FALLBACK_VERSION = '2.2.2'

// External links opened in the user's default browser. The window-open handler
// in the main process routes window.open() through shell.openExternal.
// English is the default (no suffix); Chinese gets a /zh suffix. Skill hub is
// language-agnostic.
const SKILL_HUB_URL = 'https://skills.cowagent.ai/'
// GitHub issues — where users report bugs / request features.
const FEEDBACK_URL = 'https://github.com/zhayujie/CowAgent/issues'

const websiteUrl = () => (getLang() === 'zh' ? 'https://cowagent.cn' : 'https://cowagent.ai')
const docsUrl = () => (getLang() === 'zh' ? 'https://docs.cowagent.ai/zh' : 'https://docs.cowagent.ai')

const openExternal = (url: string) => {
  window.open(url, '_blank', 'noopener,noreferrer')
}

interface NavRailProps {
  onLangChange: () => void
}

const NavRail: React.FC<NavRailProps> = ({ onLangChange }) => {
  const location = useLocation()
  const navigate = useNavigate()
  const { navCollapsed, toggleNav } = useUIStore()
  const { theme, toggleTheme, themeId, themes, appName, setThemeId, reloadThemes, importTheme, openThemesDir } =
    useTheme()
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

  const menu = useMenuStore((s) => s.doc)
  const openMenuEditor = useMenuStore((s) => s.openEditor)
  // Always draw by group — the built-in menu is "Chat" / "Manage" until the
  // user saves their own. Empty groups (e.g. footer-only Monitor) drop out.
  const sections: { group: MenuGroup; items: MenuItem[] }[] = menu.groups
    .map((group) => ({ group, items: group.items.filter(itemShows) }))
    .filter((s) => s.items.length)

  const openItem = (item: MenuItem) => {
    if (item.type === 'url' && item.open === 'tab') {
      if (item.url) openExternal(item.url)
      return
    }
    void go(itemRoute(item))
  }

  const updateState = useUpdateStore()
  // Footer dot: hidden once dismissed for this version (user asked for this).
  const pendingUpdate = hasPendingUpdate(updateState)
  // Menu "check for update" dot: stays as long as an update actually exists,
  // even after dismissing the footer badge.
  const availableUpdate = hasAvailableUpdate(updateState)
  const checking = updateState.status?.state === 'checking'

  const [menuOpen, setMenuOpen] = useState(false)
  const [addThemeOpen, setAddThemeOpen] = useState(false)
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

  const toggleLanguage = () => {
    const next: Lang = getLang() === 'zh' ? 'en' : 'zh'
    setLang(next)
    onLangChange()
  }

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
      <nav className="flex-1 overflow-y-auto px-2 py-2">
        {sections.map(({ group, items }, index) => (
          <div
            key={group.id}
            className={index ? (collapsed ? 'mt-1.5 pt-1.5 border-t border-subtle' : 'mt-2') : ''}
          >
            {!collapsed && (
              <div className="group/head relative flex items-center pr-1">
                <div className="flex-1 min-w-0 px-3 pt-1 pb-1 text-[11px] font-medium text-content-tertiary truncate select-none">
                  {groupLabel(group)}
                </div>
                <Tooltip label={t('menu_edit')} placement="right">
                  <button
                    type="button"
                    onClick={() => openMenuEditor()}
                    aria-label={t('menu_edit')}
                    className="flex-shrink-0 w-6 h-6 inline-flex items-center justify-center rounded-md
                               text-content-tertiary opacity-0 group-hover/head:opacity-100 hover:opacity-100
                               hover:bg-surface-2 hover:text-content cursor-pointer transition-opacity"
                  >
                    <SquarePen size={11} />
                  </button>
                </Tooltip>
              </div>
            )}
            <div className="space-y-0.5">
              {items.map((item) => {
                const Icon = itemIcon(item)
                const label = itemLabel(item)
                const isActive = location.pathname === itemRoute(item)
                return (
                  <button
                    key={item.id}
                    onClick={() => openItem(item)}
                    title={collapsed ? label : undefined}
                    className={`group w-full flex items-center gap-3 rounded-btn cursor-pointer transition-colors h-9 ${
                      collapsed ? 'justify-center px-0' : 'px-3'
                    } ${
                      isActive
                        ? 'bg-accent-soft text-accent'
                        : 'text-content-secondary hover:bg-surface-2 hover:text-content'
                    }`}
                  >
                    <Icon size={18} strokeWidth={isActive ? 2.2 : 1.8} className="flex-shrink-0" />
                    {!collapsed && <span className="flex-1 min-w-0 text-left text-[13px] truncate">{label}</span>}
                    {!collapsed && item.type === 'url' && item.open === 'tab' && (
                      <ExternalLink size={12} className="flex-shrink-0 opacity-50" />
                    )}
                  </button>
                )
              })}
            </div>
          </div>
        ))}
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
            onEditMenu={() => {
              setMenuOpen(false)
              openMenuEditor()
            }}
            onTheme={toggleTheme}
            themeId={themeId}
            themes={themes}
            onThemeId={setThemeId}
            onThemesOpen={() => void reloadThemes()}
            onAddTheme={() => {
              setMenuOpen(false)
              setAddThemeOpen(true)
            }}
            onLanguage={toggleLanguage}
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

          {/* The editor lives in the "more" menu. A build that hides it keeps a
              button, unless its own footer slot takes over the menu. */}
          {product.nav?.hideFooterMenu && !product.slots?.NavRailFooter && (
            <FooterBtn collapsed={collapsed} onClick={() => openMenuEditor()} title={t('menu_edit')}>
              <SquarePen size={16} />
            </FooterBtn>
          )}
          <FooterBtn collapsed={collapsed} onClick={toggleNav} title={collapsed ? t('nav_expand') : t('nav_collapse')}>
            {collapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}
          </FooterBtn>
        </div>
      </div>
      </div>
      <ThemeAddModal
        open={addThemeOpen}
        onClose={() => setAddThemeOpen(false)}
        onImport={importTheme}
        onOpenDir={() => void openThemesDir()}
      />
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
  onThemesOpen: () => void
  onAddTheme: () => void
  onLogs: () => void
  onEditMenu: () => void
  onTheme: () => void
  onLanguage: () => void
  onCheckUpdate: () => void
  onOpenLink: (url: string) => void
}> = ({ theme, checking, pendingUpdate, upToDate, themeId, themes, onThemeId, onThemesOpen, onAddTheme, onLogs, onEditMenu, onTheme, onLanguage, onCheckUpdate, onOpenLink }) => {
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

    {/* App actions below: update, theme, language, menu, logs */}
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
    {/* Theme picker: hovering opens a flyout beside the menu, bottom-aligned
        with it, so a long list never grows the menu. The wrapper is left
        unpositioned so the flyout anchors to the menu box. */}
    <ThemeFlyout
      flyoutClassName="left-full -bottom-px pl-1.5"
      onOpen={onThemesOpen}
      themes={themes}
      themeId={themeId}
      onSelect={onThemeId}
      onAdd={onAddTheme}
    >
      <MenuItem icon={<Palette size={16} />} label={t('menu_theme_picker')} trailing="▸" onClick={() => {}} />
    </ThemeFlyout>
    <MenuItem
      icon={<Languages size={16} />}
      label={t('menu_language')}
      trailing={getLang() === 'zh' ? 'EN' : '中'}
      onClick={onLanguage}
    />
    <MenuItem icon={<SquarePen size={16} />} label={t('menu_edit')} onClick={onEditMenu} />
    <MenuItem icon={<ScrollText size={16} />} label={t('menu_logs')} onClick={onLogs} />
  </div>
  )
}

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
