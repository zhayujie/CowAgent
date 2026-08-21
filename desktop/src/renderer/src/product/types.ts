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
}

export interface ProductExtension {
  auth?: ProductAuth
  slots?: ProductSlots
  routes?: ProductRoute[]
  onboarding?: ProductOnboarding
  models?: ProductModels
  nav?: ProductNav
  links?: ProductLinks
}
