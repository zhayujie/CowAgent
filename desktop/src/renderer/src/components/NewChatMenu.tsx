import React, { useEffect, useRef, useState } from 'react'
import { Users, CircleCheck, Circle } from 'lucide-react'
import { t } from '../i18n'
import AgentAvatar from './AgentAvatar'
import { Modal, Btn } from '../pages/settings/primitives'
import { useAgentStore, selectMultiAgent, enabledDefaultFirst } from '../store/agentStore'
import { startNewChat, startTeamChat } from '../lib/newChat'
import { useWorkspaceStore } from '../store/workspaceStore'

interface NewChatMenuProps {
  /** Renders the trigger. `onClick` opens the menu in multi-Agent mode and
   *  starts a plain chat otherwise, so callers don't branch. */
  children: (props: { onClick: (e: React.MouseEvent) => void; open: boolean }) => React.ReactNode
  align?: 'start' | 'end'
  /** Where the menu opens relative to the trigger. */
  placement?: 'above' | 'below'
  /** Called after a conversation was started (any path). */
  onStarted?: (sessionId: string) => void
}

/**
 * The "new chat" entry point. With a single Agent there is nobody to choose
 * between, so the trigger simply starts a chat — exactly as before. With a team
 * it opens a menu: pick an Agent for a solo chat, or open the group picker to
 * start a conversation with several Agents at once (the web console's
 * new-chat menu).
 */
const NewChatMenu: React.FC<NewChatMenuProps> = ({ children, align = 'start', placement = 'below', onStarted }) => {
  const multiAgent = useAgentStore(selectMultiAgent)
  const agents = useAgentStore((s) => s.agents)
  const defaultAgentId = useAgentStore((s) => s.defaultAgentId)
  const activeAgentId = useAgentStore((s) => s.activeAgentId)
  const [open, setOpen] = useState(false)
  const [teamOpen, setTeamOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  const roster = enabledDefaultFirst(agents, defaultAgentId)

  const onTrigger = async (e: React.MouseEvent) => {
    if (!multiAgent) {
      // A new chat re-scopes the workspace panel, closing any open editor.
      if (!(await useWorkspaceStore.getState().guardUnsavedEdit())) return
      onStarted?.(startNewChat())
      return
    }
    e.stopPropagation()
    setOpen((v) => !v)
  }

  const startSolo = async (agentId: string) => {
    // A new chat re-scopes the workspace panel, closing any open editor.
    if (!(await useWorkspaceStore.getState().guardUnsavedEdit())) return
    setOpen(false)
    useAgentStore.getState().setActive(agentId)
    // A chat for the same Agent stays in the current space; another Agent's
    // chat starts on that Agent's own root, since the project belongs to the
    // previous owner.
    onStarted?.(startNewChat({ ownerId: agentId, inheritProject: agentId === activeAgentId }))
  }

  return (
    <div ref={rootRef} className="relative">
      {children({ onClick: onTrigger, open })}

      {open && (
        <div
          className={`absolute z-40 w-60 rounded-xl border border-default bg-elevated shadow-xl p-1.5 ${
            placement === 'above' ? 'bottom-full mb-1.5' : 'top-full mt-1.5'
          } ${align === 'end' ? 'right-0' : 'left-0'}`}
        >
          <div className="px-2 py-1.5 text-[11px] font-medium text-content-tertiary uppercase tracking-wide">
            {t('new_chat_pick_agent')}
          </div>
          {roster.map((a) => (
            <button
              key={a.id}
              type="button"
              onClick={() => startSolo(a.id)}
              className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-[13px] text-content-secondary hover:bg-surface-2 cursor-pointer transition-colors"
            >
              <AgentAvatar agent={a} size={20} />
              <span className="flex-1 min-w-0 text-left truncate">{a.name || a.id}</span>
            </button>
          ))}
          <div className="my-1 h-px bg-default" />
          <button
            type="button"
            onClick={() => {
              setOpen(false)
              setTeamOpen(true)
            }}
            className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-[13px] text-content-secondary hover:bg-surface-2 cursor-pointer transition-colors"
          >
            <span className="w-5 h-5 rounded-full bg-accent-soft text-accent flex items-center justify-center flex-shrink-0">
              <Users size={11} />
            </span>
            <span className="flex-1 min-w-0 text-left truncate">{t('new_team_chat')}</span>
          </button>
        </div>
      )}

      <TeamChatModal
        open={teamOpen}
        onClose={() => setTeamOpen(false)}
        onStarted={(id) => {
          setTeamOpen(false)
          onStarted?.(id)
        }}
      />
    </div>
  )
}

/**
 * Pick the Agents for a group conversation. The first one checked owns the
 * conversation (it receives every message and can hand turns to the others);
 * the rest are invited as members before the first message is sent.
 */
export const TeamChatModal: React.FC<{
  open: boolean
  onClose: () => void
  onStarted: (sessionId: string) => void
}> = ({ open, onClose, onStarted }) => {
  const agents = useAgentStore((s) => s.agents)
  const defaultAgentId = useAgentStore((s) => s.defaultAgentId)
  const activeAgentId = useAgentStore((s) => s.activeAgentId)
  const [picks, setPicks] = useState<string[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (open) {
      setPicks([activeAgentId || defaultAgentId].filter(Boolean))
      setError('')
    }
  }, [open, activeAgentId, defaultAgentId])

  const roster = enabledDefaultFirst(agents, defaultAgentId)

  const toggle = (id: string) => {
    setPicks((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
    setError('')
  }

  const start = async () => {
    const valid = picks.filter((id) => roster.some((a) => a.id === id))
    if (valid.length < 2) {
      setError(t('new_team_chat_min'))
      return
    }
    // A new chat re-scopes the workspace panel, closing any open editor.
    if (!(await useWorkspaceStore.getState().guardUnsavedEdit())) return
    setBusy(true)
    try {
      const [owner, ...guests] = valid
      const id = await startTeamChat(owner, guests)
      onStarted(id)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      title={t('new_team_chat')}
      onClose={onClose}
      footer={
        <>
          <Btn onClick={onClose}>{t('cancel')}</Btn>
          <Btn variant="primary" onClick={start} disabled={busy || picks.length < 2}>
            {t('new_team_chat_start')}
          </Btn>
        </>
      }
    >
      <p className="text-xs text-content-tertiary -mt-1">{t('new_team_chat_hint')}</p>
      <div className="space-y-1">
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
                <span className="rounded-full text-[10px] font-medium px-[7px] py-px bg-[#4ABE6E] text-white flex-shrink-0">
                  {t('new_team_chat_owner')}
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

export default NewChatMenu
