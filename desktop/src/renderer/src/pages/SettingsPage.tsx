import React, { useCallback, useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { t } from '../i18n'
import { product } from '@product'
import BasicSettings from './settings/BasicSettings'
import ModelsTab from './settings/ModelsTab'
import IntegrationsTab from './settings/IntegrationsTab'
import DevicesTab from './settings/DevicesTab'

interface SettingsPageProps {
  baseUrl: string
  onLangChange?: () => void
}

type Tab = 'basic' | 'models' | 'integrations' | 'devices'

const SettingsPage: React.FC<SettingsPageProps> = ({ baseUrl, onLangChange }) => {
  const location = useLocation()
  const navigate = useNavigate()
  const modelsTabHidden = product.models?.hideModelsTab === true
  // Deep links: /settings?tab=models, /settings?tab=integrations. The tab also
  // lives in the URL so a remount (e.g. after a backend restart) keeps it.
  const requested = new URLSearchParams(location.search).get('tab')
  const initial: Tab =
    requested === 'integrations' || requested === 'devices'
      ? requested
      : !modelsTabHidden && requested === 'models'
        ? 'models'
        : 'basic'
  const [tab, setTab] = useState<Tab>(initial)
  // A deep link followed while Settings is already open.
  useEffect(() => {
    if (requested) setTab(initial)
  }, [requested]) // eslint-disable-line react-hooks/exhaustive-deps
  const [focusPassword, setFocusPassword] = useState(false)

  const switchTab = (next: Tab) => {
    setTab(next)
    navigate({ search: next === 'basic' ? '' : `?tab=${next}` }, { replace: true })
  }

  const clearFocusPassword = useCallback(() => setFocusPassword(false), [])
  const goToPassword = () => {
    switchTab('basic')
    setFocusPassword(true)
  }

  const tabs: { key: Tab; label: string }[] = [
    { key: 'basic', label: t('settings_tab_basic') },
    ...(modelsTabHidden ? [] : [{ key: 'models' as Tab, label: t('settings_tab_models') }]),
    { key: 'integrations', label: t('settings_tab_integrations') },
    { key: 'devices', label: t('settings_tab_devices') },
  ]

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-3xl mx-auto">
        <div className="mb-5">
          <h2 className="text-xl font-bold text-content">{t('menu_settings')}</h2>
          <p className="text-sm text-content-tertiary mt-1">{t('config_desc')}</p>
        </div>

        {/* Tab bar */}
        <div className="flex items-center gap-1 mb-6 border-b border-default">
          {tabs.map((tb) => (
            <button
              key={tb.key}
              onClick={() => switchTab(tb.key)}
              className={`relative px-4 py-2.5 text-sm font-medium cursor-pointer transition-colors -mb-px border-b-2 ${
                tab === tb.key
                  ? 'text-accent border-accent'
                  : 'text-content-tertiary border-transparent hover:text-content-secondary'
              }`}
            >
              {tb.label}
            </button>
          ))}
        </div>

        {tab === 'devices' ? (
          <DevicesTab onGoToPassword={goToPassword} onGoToIntegrations={() => switchTab('integrations')} />
        ) : tab === 'integrations' ? (
          <IntegrationsTab baseUrl={baseUrl} onGoToPassword={goToPassword} />
        ) : tab === 'basic' || modelsTabHidden ? (
          <BasicSettings
            baseUrl={baseUrl}
            onLangChange={onLangChange}
            onOpenModels={modelsTabHidden ? undefined : () => switchTab('models')}
            focusPassword={focusPassword}
            onPasswordFocused={clearFocusPassword}
          />
        ) : (
          <ModelsTab baseUrl={baseUrl} />
        )}
      </div>
    </div>
  )
}

export default SettingsPage
