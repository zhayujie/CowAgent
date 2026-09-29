import type { MessageStep } from '../types'

/** Who took a handed-over task, and what they answered. */
export interface HandoffPayload {
  agent_id: string
  agent_name: string
  content: string
}

/**
 * Read a hand-off out of a tool step, or null when it is any other call.
 *
 * A teammate that returned nothing is not a hand-off for this purpose: with no
 * reply there is no turn to show, so the call stays an ordinary card.
 */
export function handoffPayload(step: MessageStep): HandoffPayload | null {
  const payload = isHandoff(step) ? parseResult(step) : null
  if (!payload) return null
  const content = typeof payload.content === 'string' ? payload.content : ''
  if (!content) return null
  return {
    agent_id: String(payload.agent_id || ''),
    agent_name: String(payload.agent_name || payload.agent_id || ''),
    content,
  }
}

/**
 * The teammate a hand-off names, from the moment the call is made.
 *
 * Unlike `handoffPayload` this does not wait for a reply. The card has to read
 * "handed to X" while the teammate is still working, or it shows the raw tool
 * name and auto-expands — and it has already opened by the time the reply that
 * would have identified it arrives.
 */
export function handoffTarget(step: MessageStep): string | null {
  if (!isHandoff(step)) return null
  const payload = parseResult(step)
  const target = payload.agent_name || payload.agent_id || step.arguments?.agent_id
  return target ? String(target) : null
}

function isHandoff(step: MessageStep): boolean {
  return !!step && step.type === 'tool' && step.name === 'agent_delegate'
}

function parseResult(step: MessageStep): Record<string, unknown> {
  try {
    const parsed = JSON.parse(step.result || '{}')
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}
