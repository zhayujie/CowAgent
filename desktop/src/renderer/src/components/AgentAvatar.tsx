import React, { useState } from 'react'
import { product } from '@product'
import apiClient from '../api/client'
import type { AgentProfile } from '../types'
import { useAgentStore, findAgent } from '../store/agentStore'

/**
 * An Agent's face: its uploaded image when it has one, else a tinted disc with
 * the first character of its name. Mirrors the web console's `agentAvatarHTML`,
 * down to the same tones, so the same Agent looks the same in both clients.
 *
 * A null agent means the id no longer resolves — a conversation pinned to a
 * since-deleted Agent. Fall back to the default Agent's face rather than an
 * empty disc, so the deleted Agent visibly degrades to the default one.
 */

// A stable tone per Agent id, deterministic so a face keeps its colour across
// the app and across restarts. Tinted background with darker text rather than a
// saturated fill: a roster of a dozen should read as one calm list. Spelled out
// as whole class strings because Tailwind only emits classes it can see
// literally in the source. Tone 0 is the neutral one, worn by an Agent with no
// id yet. These match the web console's .agent-avatar-tone-* rules.
const PALETTE = [
  'bg-[#eef1f5] text-[#4b5563] dark:bg-[#2a2f36] dark:text-[#b6bec9]',
  'bg-[#eaf0f7] text-[#3f5f80] dark:bg-[#26313d] dark:text-[#a8c0d6]',
  'bg-[#ebf3ed] text-[#46694e] dark:bg-[#263329] dark:text-[#a9c7b0]',
  'bg-[#f4f1e9] text-[#6b5f45] dark:bg-[#33302a] dark:text-[#cdbe9f]',
  'bg-[#f5eeeb] text-[#7a564d] dark:bg-[#352c2a] dark:text-[#d0b0a7]',
  'bg-[#f0eef6] text-[#574f70] dark:bg-[#2e2b38] dark:text-[#b8b0d0]',
]

function toneFor(id: string): string {
  let hash = 0
  for (let i = 0; i < id.length; i++) hash = (hash * 31 + id.charCodeAt(i)) >>> 0
  return PALETTE[hash % PALETTE.length]
}

// Array.from rather than [0] so an astral-plane character is taken whole
// instead of as half a surrogate pair.
function initial(name: string): string {
  return (Array.from((name || '').trim())[0] || '').toUpperCase()
}

interface AgentAvatarProps {
  agent?: Pick<AgentProfile, 'id' | 'name' | 'avatar' | 'avatar_rev'> | null
  size?: number
  className?: string
  // 'circle' (default) for roster/composer faces; 'square' for chat bubbles,
  // matching the rounded-square logo the assistant bubble used before.
  shape?: 'circle' | 'square'
}

const AgentAvatar: React.FC<AgentAvatarProps> = ({ agent, size = 32, className = '', shape = 'circle' }) => {
  const radius = shape === 'square' ? 'rounded-lg' : 'rounded-full'
  // Bust the <img> cache when the roster revision changes (an avatar was
  // replaced). Reading it here also re-renders faces after an upload.
  const revision = useAgentStore((s) => s.revision)
  const defaultAgentId = useAgentStore((s) => s.defaultAgentId)
  const [failed, setFailed] = useState(false)

  // Pinned to a deleted Agent: degrade to the default Agent's face.
  if (!agent && defaultAgentId) {
    agent = findAgent(defaultAgentId) ?? null
  }

  const hasImage = !!agent && agent.avatar === 'image' && !failed
  const px = { width: size, height: size }
  const id = agent?.id || ''

  // The default (built-in) Agent has no uploaded avatar; wear the brand face
  // instead of a bare initial disc, so its face matches the rest of the app. A
  // product supplies its own, which it may resolve per account at runtime;
  // otherwise use the same round logo.jpg the login/chat screens and web console
  // use (not the wide-margin square logo.png), filled edge-to-edge with
  // object-cover so a circle face reads as a clean disc, not an octagon.
  //
  // Only when nothing was uploaded: an Agent the user gave a face keeps it,
  // brand or not, and that includes this one.
  const isDefault = !!agent && !!defaultAgentId && agent.id === defaultAgentId
  if (!hasImage && isDefault) {
    const Brand = product.slots?.AssistantAvatar
    if (Brand) {
      return (
        <div style={px} className={`${radius} overflow-hidden flex-shrink-0 ${className}`}>
          <Brand />
        </div>
      )
    }
    return (
      <img
        src="./logo.jpg"
        alt={agent?.name || 'CowAgent'}
        draggable={false}
        style={px}
        className={`${radius} object-cover flex-shrink-0 ${className}`}
      />
    )
  }

  if (hasImage && agent) {
    // Prefer the per-file token (avatar mtime) so a re-upload busts the cache
    // even when the roster revision is unchanged; fall back to it otherwise.
    return (
      <img
        src={apiClient.agentAvatarUrl(agent.id, agent.avatar_rev || revision || agent.id)}
        alt={agent.name || agent.id}
        draggable={false}
        onError={() => setFailed(true)}
        style={px}
        className={`${radius} object-cover flex-shrink-0 ${className}`}
      />
    )
  }

  return (
    <span
      style={{ ...px, fontSize: Math.round(size * 0.42) }}
      className={`${radius} ${toneFor(id)} flex items-center justify-center flex-shrink-0 font-semibold select-none ${className}`}
    >
      {initial(agent?.name || id)}
    </span>
  )
}

export default AgentAvatar
