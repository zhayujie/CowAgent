import React, { useState } from 'react'
import apiClient from '../api/client'
import { t, tf } from '../i18n'

interface LoginGateProps {
  // Called once the password is accepted (auth cookie set), so the app can
  // proceed to the main UI.
  onAuthenticated: () => void
}

/**
 * Shown when the backend has a web_password set and the current session isn't
 * authenticated yet. Submitting the correct password sets an auth cookie
 * (handled by the backend), after which the app reloads its data.
 */
const LoginGate: React.FC<LoginGateProps> = ({ onAuthenticated }) => {
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!password || submitting) return
    setSubmitting(true)
    setError('')
    try {
      const res = await apiClient.authLogin(password)
      if (res.status === 'success') {
        onAuthenticated()
      } else if (res.reason === 'locked') {
        setError(tf('login_locked', { n: Math.max(1, Math.ceil((res.retry_after || 60) / 60)) }))
      } else {
        setError(t('login_error'))
      }
    } catch {
      setError(t('login_error'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="h-screen w-screen flex items-center justify-center bg-gray-50 dark:bg-[#111111]">
      <form onSubmit={submit} className="text-center space-y-6 max-w-md px-8 w-full">
        <img src="./logo.jpg" alt="CowAgent" className="w-16 h-16 rounded-2xl mx-auto shadow-lg shadow-primary-500/20" />
        <div className="space-y-2">
          <h1 className="text-xl font-bold text-slate-800 dark:text-slate-100">{t('login_title')}</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">{t('login_desc')}</p>
        </div>
        <input
          type="password"
          autoFocus
          value={password}
          onChange={(e) => {
            setPassword(e.target.value)
            if (error) setError('')
          }}
          placeholder={t('login_placeholder')}
          className="w-full px-4 py-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-[#1a1a1a] text-slate-800 dark:text-slate-100 text-sm outline-none focus:border-primary-500 transition-colors"
        />
        {error && <p className="text-sm text-red-500">{error}</p>}
        <button
          type="submit"
          disabled={submitting || !password}
          className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 bg-primary-500 hover:bg-primary-600 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg transition-colors text-sm font-medium cursor-pointer"
        >
          {submitting ? t('login_checking') : t('login_submit')}
        </button>
      </form>
    </div>
  )
}

export default LoginGate
