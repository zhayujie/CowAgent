import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Check, ChevronRight, Plus, Terminal, Upload, Wand2, X } from 'lucide-react'
import { t, localizedLabel, getLang } from '../../../i18n'
import apiClient, {
  ShareApiError,
  type GuestShare,
  type GuestShareConfig,
  type GuestSharesOverview,
} from '../../../api/client'
import { Btn, Dropdown, Field, Modal, TextInput, Toggle } from '../primitives'
import {
  SHARE_COLORS,
  SHARE_DEFAULT_COLOR,
  SHARE_DEFAULT_QUOTA,
  SHARE_FOOTER_TEXT,
  shareFooterUrl,
  SHARE_LANGUAGES,
  SHARE_LANGUAGE_NAMES,
  SHARE_LOGO_MAX,
  SHARE_LOGO_TYPES,
  SHARE_MAX_QUESTIONS,
  SHARE_DEFAULT_TOOLS,
  SHARE_NETWORK_TOOLS,
  SHARE_TOOLS,
  isLightColor,
} from './shareCommon'

const TEXTAREA =
  'w-full px-3 py-2 rounded-btn border border-strong bg-inset text-sm text-content placeholder:text-content-tertiary placeholder:opacity-60 focus:outline-none focus:border-accent transition-colors'
const SECTION = 'pt-2 text-xs font-semibold uppercase tracking-wide text-content-tertiary'
const CHIP_BASE = 'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs transition-colors'

interface Props {
  /** null while closed; '' creates a page, a slug edits it. */
  slug: string | null
  focus?: 'password'
  overview: GuestSharesOverview | null
  defaultModel: string
  onClose: () => void
  /** A page was written; notice is empty when the editor stays open after a later step failed. */
  onSaved: (share: GuestShare, notice: string) => void
  onNotice: (text: string) => void
}

const ShareEditor: React.FC<Props> = ({ slug, focus, overview, defaultModel, onClose, onSaved, onNotice }) => {
  const open = slug !== null
  const [editing, setEditing] = useState<GuestShare | null>(null)
  const [ready, setReady] = useState(false)
  const [name, setName] = useState('')
  const [language, setLanguage] = useState('')
  const [welcome, setWelcome] = useState('')
  const [questions, setQuestions] = useState<string[]>([])
  const [model, setModel] = useState('')
  const [color, setColor] = useState('')
  const [logoFile, setLogoFile] = useState<File | null>(null)
  const [logoReset, setLogoReset] = useState(false)
  const [pwdOn, setPwdOn] = useState(false)
  const [password, setPassword] = useState('')
  const [passwordSet, setPasswordSet] = useState(false)
  const [quota, setQuota] = useState(String(SHARE_DEFAULT_QUOTA))
  const [expires, setExpires] = useState('')
  const [tools, setTools] = useState<string[]>(SHARE_DEFAULT_TOOLS)
  const [skills, setSkills] = useState<string[]>([])
  const [refs, setRefs] = useState<{ path: string; note: string }[]>([])
  const [guestMd, setGuestMd] = useState('')
  const [footerText, setFooterText] = useState(SHARE_FOOTER_TEXT)
  const [footerUrl, setFooterUrl] = useState(shareFooterUrl)
  const [more, setMore] = useState(false)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const nameRef = useRef<HTMLInputElement>(null)
  const pwdRef = useRef<HTMLInputElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const fill = (share: GuestShare | null, cfg: GuestShareConfig, md: string) => {
    setEditing(share)
    setName(cfg.name || '')
    // A new page speaks the console's language until the owner picks another.
    const lang = share ? cfg.language || '' : getLang()
    setLanguage(SHARE_LANGUAGES.includes(lang) ? lang : '')
    setWelcome(cfg.welcome || '')
    setQuestions((cfg.suggested_questions || []).slice(0, SHARE_MAX_QUESTIONS))
    setModel(cfg.model ? `${cfg.provider || ''}|${cfg.model}` : '')
    const brand = cfg.branding || {}
    setColor(brand.color || '')
    setLogoFile(null)
    setLogoReset(false)
    setPwdOn(!!cfg.access?.password_required)
    setPassword('')
    setPasswordSet(!!share?.password_set)
    const q = cfg.limits?.daily_messages
    setQuota(String(q === undefined ? SHARE_DEFAULT_QUOTA : q))
    setExpires((cfg.expires_at || '').slice(0, 10))
    setTools(Array.isArray(cfg.tools) ? cfg.tools.slice() : SHARE_DEFAULT_TOOLS.slice())
    setSkills(Array.isArray(cfg.skills) ? cfg.skills.slice() : [])
    setRefs((cfg.references || []).map((r) => ({ path: r.path || '', note: r.note || '' })))
    setGuestMd(md)
    setFooterText(brand.footer_text === undefined ? SHARE_FOOTER_TEXT : brand.footer_text)
    setFooterUrl(brand.footer_url === undefined ? shareFooterUrl() : brand.footer_url)
    setMore(false)
    setError('')
    setSaving(false)
    setReady(true)
  }

  useEffect(() => {
    if (slug === null) {
      setReady(false)
      return
    }
    if (slug === '') {
      fill(null, { suggested_questions: [t('shares_default_q1'), t('shares_default_q2')] }, '')
      setTimeout(() => nameRef.current?.focus(), 30)
      return
    }
    apiClient
      .getGuestShare(slug)
      .then(({ share }) => {
        fill(share, share.raw_config || {}, share.guest_md || '')
        setTimeout(() => (focus === 'password' ? pwdRef.current : nameRef.current)?.focus(), 30)
      })
      .catch((e: Error) => {
        onClose()
        onNotice(e.message)
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug])

  const logoPreview = useMemo(() => (logoFile ? URL.createObjectURL(logoFile) : ''), [logoFile])
  useEffect(() => () => {
    if (logoPreview) URL.revokeObjectURL(logoPreview)
  }, [logoPreview])
  const hasSavedLogo = !!editing?.logo_version && !logoReset
  const logoSrc = logoPreview || (hasSavedLogo && editing ? apiClient.guestShareLogoUrl(editing) : apiClient.guestShareLogoUrl({ slug: '', logo_version: 0 }))

  const modelOptions = useMemo(() => {
    const options = [{ value: '', label: t('shares_model_follow'), hint: defaultModel }]
    const seen = new Set<string>()
    for (const p of overview?.models || []) {
      for (const m of p.models || []) {
        const v = `${p.id}|${m}`
        seen.add(v)
        options.push({ value: v, label: m, hint: localizedLabel(p.label) })
      }
    }
    if (model && !seen.has(model)) options.push({ value: model, label: model.slice(model.indexOf('|') + 1), hint: '' })
    return options
  }, [overview, defaultModel, model])

  const skillByName = useMemo(
    () => Object.fromEntries((overview?.skills || []).map((s) => [s.name, s])),
    [overview]
  )
  const skillOptions = (overview?.skills || [])
    .filter((s) => !s.needs_shell && !skills.includes(s.name))
    .map((s) => ({ value: s.name, label: s.name, hint: s.description }))
  const refOptions = [
    ...(overview?.references || [])
      .filter((r) => !refs.some((x) => x.path === r.path))
      .map((r) => {
        const kb = r.agent ? `${r.agent} · ${t('shares_ref_kb')}` : t('shares_ref_kb')
        return { value: r.path, label: r.category ? `${kb} / ${r.category}` : kb }
      }),
    { value: '__custom__', label: t('shares_ref_custom') },
  ]

  const pickLogo = (file?: File) => {
    if (!file) return
    if (!SHARE_LOGO_TYPES.includes(file.type)) return setError(t('shares_logo_type'))
    if (file.size > SHARE_LOGO_MAX) return setError(t('shares_logo_size'))
    setError('')
    setLogoFile(file)
    setLogoReset(false)
  }

  const save = async () => {
    if (!name.trim()) {
      setError(t('shares_name_required'))
      nameRef.current?.focus()
      return
    }
    if (pwdOn && password && password.length < 6) return setError(t('shares_password_short'))
    if (pwdOn && !password && !passwordSet) {
      setError(t('shares_password_required'))
      pwdRef.current?.focus()
      return
    }
    const url = footerUrl.trim()
    if (url && !/^https?:\/\/[^\s<>"']+$/i.test(url)) {
      setMore(true)
      return setError(t('shares_footer_url_invalid'))
    }
    const q = quota.trim() === '' ? SHARE_DEFAULT_QUOTA : Number(quota.trim())
    if (!Number.isInteger(q) || q < 0) return setError(t('shares_quota_invalid'))

    // Start from what is on disk so settings the form does not show survive.
    const base: GuestShareConfig = editing ? JSON.parse(JSON.stringify(editing.raw_config || {})) : {}
    const cut = model.indexOf('|')
    const config: GuestShareConfig = {
      ...base,
      name: name.trim(),
      language,
      welcome: welcome.trim(),
      suggested_questions: questions.map((s) => s.trim()).filter(Boolean),
      provider: model ? model.slice(0, cut) : '',
      model: model ? model.slice(cut + 1) : '',
      tools: tools.slice(),
      skills: skills.slice(),
      references: refs.map((r) => ({ path: r.path.trim(), note: r.note.trim() })).filter((r) => r.path),
      expires_at: expires || '',
      limits: { ...(base.limits || {}), daily_messages: q },
      access: { ...(base.access || {}), password_required: pwdOn },
      network: { ...(base.network || {}), enabled: tools.some((id) => SHARE_NETWORK_TOOLS.includes(id)) },
      branding: { ...(base.branding || {}), color, footer_text: footerText.trim(), footer_url: url },
    }

    setSaving(true)
    setError('')
    const isNew = !editing
    let current = editing
    try {
      let { share } = isNew
        ? await apiClient.createGuestShare(config, guestMd)
        : await apiClient.updateGuestShare(editing!.slug, config, guestMd)
      // Saving again after a later step fails must update this page, not create another.
      current = share
      setEditing(share)
      if (pwdOn && password) share = (await apiClient.guestShareAction(share.slug, 'password', { password })).share
      let logoError = ''
      try {
        if (logoFile) share = (await apiClient.uploadGuestShareLogo(share.slug, logoFile)).share
        else if (logoReset && share.logo_version) share = (await apiClient.deleteGuestShareLogo(share.slug)).share
      } catch (e) {
        const reason = e instanceof ShareApiError ? e.reason : ''
        logoError =
          reason === 'unsupported_image' ? t('shares_logo_type') : reason === 'too_large' ? t('shares_logo_size') : (e as Error).message
      }
      onSaved(share, logoError || t(isNew ? 'shares_created' : 'shares_saved'))
      onClose()
    } catch (e) {
      setSaving(false)
      setError(e instanceof ShareApiError && e.reason === 'console_password' ? t('shares_password_console') : (e as Error).message)
      if (isNew && current) onSaved(current, '')
    }
  }

  const chip = (on: boolean) =>
    `${CHIP_BASE} cursor-pointer ${
      on ? 'border-accent bg-accent-soft text-accent' : 'border-strong text-content-tertiary hover:text-content-secondary'
    }`

  return (
    <Modal
      open={open && ready}
      size="lg"
      title={editing ? t('shares_edit_title') : t('shares_new_title')}
      headerRight={
        <span className="text-xs text-content-tertiary truncate">{editing ? editing.name : t('shares_new_desc')}</span>
      }
      onClose={onClose}
      footer={
        <>
          <span className="flex-1 min-w-0 text-xs text-danger truncate">{error}</span>
          <Btn onClick={onClose}>{t('cancel')}</Btn>
          <Btn variant="primary" disabled={saving} onClick={() => void save()}>
            {t('config_save')}
          </Btn>
        </>
      }
    >
      <Field label={t('shares_field_name')}>
        <TextInput ref={nameRef} maxLength={60} value={name} placeholder={t('shares_field_name_ph')} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label={t('shares_field_model')}>
        <Dropdown value={model} options={modelOptions} onChange={setModel} />
      </Field>
      <Field label={t('shares_field_welcome')}>
        <textarea
          rows={2}
          maxLength={2000}
          className={`${TEXTAREA} resize-none`}
          value={welcome}
          placeholder={t('shares_field_welcome_ph')}
          onChange={(e) => setWelcome(e.target.value)}
        />
      </Field>
      <Field label={t('shares_field_questions')} labelTip={t('shares_field_questions_tip')}>
        <div className="space-y-2">
          {questions.map((q, i) => (
            <div key={i} className="flex gap-2">
              <TextInput
                maxLength={200}
                value={q}
                placeholder={t('shares_question_ph')}
                onChange={(e) => setQuestions(questions.map((x, j) => (j === i ? e.target.value : x)))}
              />
              <button
                type="button"
                onClick={() => setQuestions(questions.filter((_, j) => j !== i))}
                className="flex-shrink-0 w-9 flex items-center justify-center rounded-btn text-content-tertiary hover:text-content-secondary hover:bg-surface-2 cursor-pointer"
              >
                <X size={14} />
              </button>
            </div>
          ))}
        </div>
        <button
          type="button"
          disabled={questions.length >= SHARE_MAX_QUESTIONS}
          onClick={() => setQuestions([...questions, ''])}
          className="mt-2 inline-flex items-center gap-1.5 text-xs text-content-tertiary hover:text-accent cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Plus size={13} />
          {t('shares_add_question')}
        </button>
      </Field>

      <div className={SECTION}>{t('shares_section_look')}</div>
      <div className="grid grid-cols-2 gap-4">
        <Field label={t('shares_field_logo')} labelTip={t('shares_field_logo_tip')}>
          <div className="flex items-center gap-2">
            <img src={logoSrc} alt="" className="w-9 h-9 rounded-lg object-cover border border-default bg-surface-2" />
            <Btn className="!px-3 !py-1.5 text-xs inline-flex items-center gap-1.5" onClick={() => fileRef.current?.click()}>
              <Upload size={13} />
              {t('shares_logo_upload')}
            </Btn>
            {(logoFile || hasSavedLogo) && (
              <Btn
                className="!px-3 !py-1.5 text-xs"
                onClick={() => {
                  setLogoFile(null)
                  setLogoReset(true)
                }}
              >
                {t('shares_logo_reset')}
              </Btn>
            )}
            <input
              ref={fileRef}
              type="file"
              className="hidden"
              accept={SHARE_LOGO_TYPES.join(',')}
              onChange={(e) => {
                pickLogo(e.target.files?.[0])
                e.target.value = ''
              }}
            />
          </div>
        </Field>
        <Field label={t('shares_field_color')} labelTip={t('shares_field_color_tip')}>
          <div className="flex flex-wrap items-center gap-1.5 py-1">
            {[['', SHARE_DEFAULT_COLOR], ...SHARE_COLORS.map((c) => [c, c])].map(([value, swatch]) => (
              <button
                key={value || 'default'}
                type="button"
                title={value ? undefined : t('shares_color_default')}
                onClick={() => setColor(value)}
                style={{ background: swatch }}
                className={`w-6 h-6 rounded-full flex items-center justify-center cursor-pointer ring-offset-2 ring-offset-[var(--bg-elevated)] ${
                  color === value ? 'ring-2 ring-[var(--text-tertiary)]' : ''
                } ${isLightColor(swatch) ? 'text-slate-800' : 'text-white'}`}
              >
                {color === value && <Check size={12} />}
              </button>
            ))}
            <label
              title={t('shares_color_custom')}
              style={color && !SHARE_COLORS.includes(color) ? { background: color } : undefined}
              className={`relative w-6 h-6 rounded-full flex items-center justify-center cursor-pointer border border-dashed border-strong ${
                color && !SHARE_COLORS.includes(color) ? 'ring-2 ring-offset-2 ring-offset-[var(--bg-elevated)] ring-[var(--text-tertiary)] border-transparent text-white' : 'text-content-tertiary'
              }`}
            >
              {color && !SHARE_COLORS.includes(color) ? <Check size={12} /> : <Plus size={12} />}
              <input
                type="color"
                className="absolute inset-0 opacity-0 cursor-pointer"
                value={color && !SHARE_COLORS.includes(color) ? color : '#0ea5e9'}
                onChange={(e) => setColor(e.target.value.toLowerCase())}
              />
            </label>
          </div>
        </Field>
      </div>

      <div className={SECTION}>{t('shares_section_access')}</div>
      <Field label={t('shares_field_password')} labelAction={<Toggle checked={pwdOn} onChange={setPwdOn} />}>
        <TextInput
          ref={pwdRef}
          type="password"
          autoComplete="new-password"
          disabled={!pwdOn}
          value={password}
          className="disabled:opacity-60"
          placeholder={!pwdOn ? t('shares_password_off') : passwordSet ? t('shares_password_keep') : t('shares_password_new')}
          onChange={(e) => setPassword(e.target.value)}
        />
      </Field>
      <div className="grid grid-cols-2 gap-4">
        <Field label={t('shares_field_quota')} labelTip={t('shares_field_quota_tip')}>
          <TextInput type="number" min={0} max={100000} step={1} value={quota} onChange={(e) => setQuota(e.target.value)} />
        </Field>
        <Field label={t('shares_field_expires')} labelTip={t('shares_field_expires_tip')}>
          <TextInput type="date" value={expires} onChange={(e) => setExpires(e.target.value)} />
        </Field>
      </div>

      <div>
        <button
          type="button"
          onClick={() => setMore((v) => !v)}
          className="flex items-center gap-2 text-sm font-medium text-content-secondary hover:text-accent cursor-pointer"
        >
          <ChevronRight size={14} className={`transition-transform ${more ? 'rotate-90' : ''}`} />
          {t('shares_section_more')}
          <span className="text-xs font-normal text-content-tertiary">{t('shares_section_more_desc')}</span>
        </button>
        {more && (
          <div className="mt-4 space-y-4">
            <Field label={t('shares_field_tools')} labelTip={t('shares_field_tools_tip')}>
              <div className="flex flex-wrap gap-2">
                {SHARE_TOOLS.map((id) => (
                  <button
                    key={id}
                    type="button"
                    className={chip(tools.includes(id))}
                    onClick={() => setTools(tools.includes(id) ? tools.filter((x) => x !== id) : [...tools, id])}
                  >
                    {t(`shares_tool_${id}`)}
                  </button>
                ))}
              </div>
            </Field>
            <Field label={t('shares_field_skills')} labelTip={t('shares_field_skills_tip')}>
              {skills.length > 0 && (
                <div className="flex flex-wrap gap-2 mb-2">
                  {skills.map((s) => {
                    const info = skillByName[s]
                    const tip = [info?.needs_shell ? t('shares_skill_needs_shell') : '', info?.description || ''].filter(Boolean).join(' · ')
                    return (
                      <span
                        key={s}
                        title={tip || undefined}
                        className={`${CHIP_BASE} ${info?.needs_shell ? 'border-amber-300 text-amber-600 dark:border-amber-500/40 dark:text-amber-300' : 'border-accent bg-accent-soft text-accent'}`}
                      >
                        {info?.needs_shell ? <Terminal size={12} /> : <Wand2 size={12} />}
                        {s}
                        <button type="button" className="cursor-pointer opacity-70 hover:opacity-100" onClick={() => setSkills(skills.filter((x) => x !== s))}>
                          <X size={12} />
                        </button>
                      </span>
                    )
                  })}
                </div>
              )}
              {skillOptions.length > 0 ? (
                <div className="max-w-xs">
                  <Dropdown
                    value=""
                    placeholder={t('shares_skill_add')}
                    options={skillOptions}
                    onChange={(v) => v && setSkills([...skills, v])}
                  />
                </div>
              ) : (
                !skills.length && <p className="text-xs text-content-tertiary">{t('shares_skills_empty')}</p>
              )}
            </Field>
            <Field label={t('shares_field_paths')} labelTip={t('shares_field_paths_tip')}>
              {refs.length > 0 && (
                <div className="space-y-2 mb-2">
                  {refs.map((r, i) => (
                    <div key={i} className="flex gap-2">
                      <TextInput
                        className="font-mono text-[13px]"
                        value={r.path}
                        placeholder={t('shares_ref_path_ph')}
                        onChange={(e) => setRefs(refs.map((x, j) => (j === i ? { ...x, path: e.target.value } : x)))}
                      />
                      <TextInput
                        className="text-[13px]"
                        maxLength={500}
                        value={r.note}
                        placeholder={t('shares_ref_note_ph')}
                        onChange={(e) => setRefs(refs.map((x, j) => (j === i ? { ...x, note: e.target.value } : x)))}
                      />
                      <button
                        type="button"
                        onClick={() => setRefs(refs.filter((_, j) => j !== i))}
                        className="flex-shrink-0 w-9 flex items-center justify-center rounded-btn text-content-tertiary hover:text-content-secondary hover:bg-surface-2 cursor-pointer"
                      >
                        <X size={14} />
                      </button>
                    </div>
                  ))}
                </div>
              )}
              <div className="max-w-xs">
                <Dropdown
                  value=""
                  placeholder={t('shares_ref_add')}
                  options={refOptions}
                  onChange={(v) => setRefs([...refs, { path: v === '__custom__' ? '' : v, note: '' }])}
                />
              </div>
            </Field>
            <Field label={t('shares_field_rules')} labelTip={t('shares_field_rules_tip')}>
              <textarea
                rows={6}
                className={`${TEXTAREA} font-mono text-[13px] leading-relaxed`}
                value={guestMd}
                placeholder={t('shares_field_rules_ph')}
                onChange={(e) => setGuestMd(e.target.value)}
              />
            </Field>
            <div className="grid grid-cols-2 gap-4">
              <Field label={t('shares_field_language')} labelTip={t('shares_field_language_tip')}>
                <Dropdown
                  value={language}
                  options={SHARE_LANGUAGES.map((value) => ({ value, label: SHARE_LANGUAGE_NAMES[value] || t('shares_language_auto') }))}
                  onChange={setLanguage}
                />
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <Field label={t('shares_field_footer')} labelTip={t('shares_field_footer_tip')}>
                <TextInput maxLength={80} value={footerText} placeholder={t('shares_field_footer_ph')} onChange={(e) => setFooterText(e.target.value)} />
              </Field>
              <Field label={t('shares_field_footer_url')}>
                <TextInput
                  type="url"
                  maxLength={500}
                  spellCheck={false}
                  value={footerUrl}
                  placeholder={t('shares_field_footer_url_ph')}
                  onChange={(e) => setFooterUrl(e.target.value)}
                />
              </Field>
            </div>
          </div>
        )}
      </div>
    </Modal>
  )
}

export default ShareEditor
