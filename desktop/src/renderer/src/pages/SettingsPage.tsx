import React, { useState } from 'react'
import { useLocation } from 'react-router-dom'
import { t } from '../i18n'
import { product } from '@product'
import BasicSettings from './settings/BasicSettings'
import ModelsTab from './settings/ModelsTab'

interface SettingsPageProps {
  baseUrl: string
}

type Tab = 'basic' | 'models'

const SettingsPage: React.FC<SettingsPageProps> = ({ baseUrl }) => {
  const location = useLocation()
  const modelsTabHidden = product.models?.hideModelsTab === true
  // Allow deep-linking to the models tab via /settings?tab=models.
  const initial: Tab =
    !modelsTabHidden && new URLSearchParams(location.search).get('tab') === 'models' ? 'models' : 'basic'
  const [tab, setTab] = useState<Tab>(initial)

  const tabs: { key: Tab; label: string }[] = [
    { key: 'basic', label: t('settings_tab_basic') },
    ...(modelsTabHidden ? [] : [{ key: 'models' as Tab, label: t('settings_tab_models') }]),
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
              onClick={() => setTab(tb.key)}
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

        {tab === 'basic' || modelsTabHidden ? (
          <BasicSettings
            baseUrl={baseUrl}
            onOpenModels={modelsTabHidden ? undefined : () => setTab('models')}
          />
        ) : (
          <ModelsTab baseUrl={baseUrl} />
        )}
      </div>
    </div>
  )
}

export default SettingsPage
