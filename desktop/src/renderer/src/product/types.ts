// ============================================================
// Optional extension contract.
//
// The core imports a single `product` object from '@product'. By default
// that alias resolves to product/default (an empty object → no change).
// An alternate build can point the alias at another module (see
// vite.config.ts COW_PRODUCT_DIR) and fill in the fields below. Every
// field is optional; absent means "keep the default behavior". The core
// must degrade gracefully when a field is missing.
// ============================================================
import type React from 'react'
import type { Attachment, SkillInfo } from '../types'

// Optional gate rendered before the main UI. When present, the core shows
// <Gate/> until the extension reports the session no longer needs it.
export interface ProductAuth {
  Gate: React.FC<{ onAuthenticated: () => void }>
  // Whether the gate is currently required. Implementations may use their
  // own hooks/state internally.
  useRequiresAuth: () => boolean
}

// Optional UI mount points the core renders if provided.
export interface ProductSlots {
  // Rendered at the bottom of the nav rail.
  NavRailFooter?: React.FC
  // Rendered on the right side of the top titlebar strip.
  HeaderRight?: React.FC
  // Rendered in the nav-rail brand area (top-left, Windows/Linux only) in place
  // of the default logo + app name. Receives whether the rail is collapsed so
  // it can render a compact mark. Lets a build show a custom wordmark.
  NavRailBrand?: React.FC<{ collapsed: boolean }>
  // Rendered as the assistant message avatar in place of the default app icon.
  // Lets a build show its own (or an OEM's) square logo next to replies.
  AssistantAvatar?: React.FC
  // Rendered as the logo on the empty new-chat home screen in place of the
  // default app logo. Lets a build show its own square logo there too.
  HomeLogo?: React.FC
  // Rendered as the logo on the startup/connecting status screen in place of
  // the default app logo. Lets a build show its own square logo there too.
  StatusLogo?: React.FC
}

// Extra routes appended to the core <Routes>. Path is a HashRouter path.
export interface ProductRoute {
  path: string
  element: React.ReactNode
}

export interface ProductOnboarding {
  // Set false to disable the built-in setup wizard. Defaults to enabled.
  enabled?: boolean
}

export interface ProductModels {
  // Set false to hide the "add custom provider" entry. Defaults to allowed.
  allowCustomProviders?: boolean
  // Set true to hide the standalone "models" settings tab. Defaults to shown.
  hideModelsTab?: boolean
  // Set true to hide the provider dropdown in basic settings (e.g. when the
  // model list comes from a single managed source). Defaults to shown.
  hideProviderSelect?: boolean
  // Optional replacement for the model selection control in basic settings.
  // Controlled: receives the current model id and reports changes. When set,
  // the core renders this instead of its built-in model dropdown.
  ModelPicker?: React.FC<{ value: string; onChange: (model: string) => void }>
  // Set true to show a masked+editable API key field for the current provider
  // inside basic settings, useful when the standalone models tab is hidden.
  showManagedApiKey?: boolean
  // Optional actions rendered on the model / API key field label rows in basic
  // settings (e.g. a link to where the value is managed).
  ModelFieldLink?: React.FC
  ApiKeyFieldLink?: React.FC
  // Optional replacement for the per-session model chip in the chat composer.
  // When set, the core renders this instead of its built-in provider-grouped
  // menu, so a build whose models come from a different source can present them
  // however it likes. `sessionId` identifies the conversation being edited.
  SessionModelPicker?: React.FC<{ sessionId: string }>
}

// Optional nav-rail customization. Lets a build tailor the footer menu's
// external destinations without touching core code.
export interface ProductNav {
  // Set true to hide the built-in external links group (skill hub, docs,
  // website, feedback). Defaults to shown.
  hideExternalLinks?: boolean
  // Set true to hide the built-in footer "more" entry (version label + menu),
  // e.g. when an extension provides its own footer menu. The collapse toggle
  // stays. Defaults to shown.
  hideFooterMenu?: boolean
}

// Optional external links a build can override (e.g. a differently-branded
// docs site). Each returns null to fall back to the core default.
export interface ProductLinks {
  // The "what's new" page for a given version. `lang` is the UI language
  // (e.g. 'zh'). Return null to use the core docs site.
  releaseNotesUrl?: (version: string, lang: string) => string | null
  // Hide the "what's new" entry of the update panel.
  hideReleaseNotes?: boolean
}

export interface ProductSkillMarketProps {
  // What is installed now, so the catalogue can mark installed and outdated entries.
  installed: SkillInfo[]
  // Report skills just installed: the page's list refreshes and highlights them.
  onInstalled: (names: string[]) => void
}

export interface ProductSkillLabel {
  name?: string
  description?: string
}

export interface ProductSkills {
  // Set true to only offer local upload when adding a skill, hiding the
  // online sources and the skill hub link. Defaults to all sources.
  uploadOnly?: boolean
  // A catalogue to browse and install from, shown as the first tab of the
  // install dialog in place of the online sources. The page then lists
  // built-in skills first and the rest newest first.
  Market?: React.FC<ProductSkillMarketProps>
  // Name of that tab; defaults to the generic market label.
  marketLabel?: string
  // Set true to open the page on skills, with built-in tools and MCP servers
  // moved to a second tab. Defaults to one page with every section.
  skillsFirst?: boolean
  // Display name and description of built-in skills, by skill name, in place
  // of the ones in their SKILL.md. The agent still reads SKILL.md.
  builtinLabels?: Record<string, ProductSkillLabel>
}

export interface ProductSuggestion {
  title: string
  // Shown on the card.
  text: string
  // Dropped into the input on click; defaults to `text`.
  prompt?: string
  // Defaults to the built-in icon at the same position.
  icon?: React.ComponentType<{ size?: number | string; className?: string }>
  // Takes over the click instead of filling the input, e.g. to collect a few
  // values first. `display`, if given, is shown for the turn while the agent
  // still gets the full `text`.
  onSelect?: (actions: { send: (text: string, display?: string, attachments?: Attachment[]) => void }) => void
}

export interface ProductChat {
  // Replaces the suggestion cards on the new-chat screen. Return null to keep
  // the defaults; an empty list shows no cards.
  useSuggestions?: () => ProductSuggestion[] | null
}

export interface ProductAgents {
  // Name shown for the built-in default agent while it still has its stock
  // name; one the user gave it is kept. Return null to keep the stock name.
  defaultAgentName?: () => string | null
}

export interface ProductExtension {
  auth?: ProductAuth
  slots?: ProductSlots
  routes?: ProductRoute[]
  onboarding?: ProductOnboarding
  models?: ProductModels
  nav?: ProductNav
  links?: ProductLinks
  skills?: ProductSkills
  chat?: ProductChat
  agents?: ProductAgents
}
