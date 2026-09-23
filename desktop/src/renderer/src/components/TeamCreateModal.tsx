import React, { useEffect, useState } from 'react'
import { Circle, CircleCheck } from 'lucide-react'
import { t } from '../i18n'
import AgentAvatar from './AgentAvatar'
import { Modal, Btn, TextInput } from '../pages/settings/primitives'
import { useAgentStore, enabledDefaultFirst } from '../store/agentStore'
import { useTeamStore } from '../store/teamStore'
import { openNamedTeam } from '../lib/newChat'

/**
 * Create a named team (the sidebar's "Teams" section): a name plus the Agents
 * that make it up. The first one checked leads the team — the same picker as
 * the group-chat modal, plus a name. On success the new team is opened right
 * away, mirroring the web console.
 */
const TeamCreateModal: React.FC<{
  open: boolean
  onClose: () => void
  onStarted?: (sessionId: string) => void
}> = ({ open, onClose, onStarted }) => {
  const agents = useAgentStore((s) => s.agents)
  const defaultAgentId = useAgentStore((s) => s.defaultAgentId)
  const [name, setName] = useState('')
  const [picks, setPicks] = useState<string[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (open) {
      setName('')
      setPicks([])
      setError('')
    }
  }, [open])

  const roster = enabledDefaultFirst(agents, defaultAgentId)

  const toggle = (id: string) => {
    setPicks((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
    setError('')
  }

  const create = async () => {
    const trimmed = name.trim()
    if (!trimmed) {
      setError(t('team_create_need_name'))
      return
    }
    if (!picks.length) {
      setError(t('team_create_need_leader'))
      return
    }
    setBusy(true)
    try {
      const team = await useTeamStore.getState().create(trimmed, picks[0], picks.slice(1))
      onClose()
      const id = await openNamedTeam(team.id)
      if (id) onStarted?.(id)
    } catch (e) {
      setError(e instanceof Error && e.message ? e.message : t('team_create_failed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      title={t('team_create_title')}
      onClose={onClose}
      footer={
        <>
          <Btn onClick={onClose}>{t('cancel')}</Btn>
          <Btn variant="primary" onClick={create} disabled={busy}>
            {t('team_create_start')}
          </Btn>
        </>
      }
    >
      <p className="text-xs text-content-tertiary -mt-1">{t('team_create_hint')}</p>
      <div className="pt-1">
        <label className="block text-xs font-medium text-content-secondary mb-1">
          {t('team_create_name')}
        </label>
        <TextInput
          autoFocus
          value={name}
          onChange={(e) => {
            setName(e.target.value)
            setError('')
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !busy) create()
          }}
          placeholder={t('team_create_name_ph')}
          maxLength={60}
        />
      </div>
      <div className="space-y-1 pt-1">
        {roster.map((a) => {
          const rank = picks.indexOf(a.id)
          const on = rank !== -1
          return (
            <button
              key={a.id}
              type="button"
              onClick={() => toggle(a.id)}
              className={`w-full flex items-center gap-3 px-3 py-2 rounded-btn border text-left cursor-pointer transition-colors ${
                on ? 'border-accent bg-accent-soft' : 'border-default hover:bg-surface-2'
              }`}
            >
              <AgentAvatar agent={a} size={28} />
              <span className="flex-1 min-w-0 text-sm text-content truncate">{a.name || a.id}</span>
              {rank === 0 && (
                <span className="px-1.5 py-0.5 rounded-full text-[10px] bg-amber-500/10 text-amber-600 flex-shrink-0">
                  {t('team_leader_tag')}
                </span>
              )}
              {on ? (
                <CircleCheck size={16} className="text-accent flex-shrink-0" />
              ) : (
                <Circle size={16} className="text-content-disabled flex-shrink-0" />
              )}
            </button>
          )
        })}
      </div>
      {error && <p className="text-xs text-danger">{error}</p>}
    </Modal>
  )
}

export default TeamCreateModal