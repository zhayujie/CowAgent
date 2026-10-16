export const CHAT_BOTTOM_THRESHOLD = 48

export interface ScrollMetrics {
  scrollTop: number
  scrollHeight: number
  clientHeight: number
}

export function distanceFromBottom(metrics: ScrollMetrics): number {
  return Math.max(0, metrics.scrollHeight - metrics.scrollTop - metrics.clientHeight)
}

export function shouldShowScrollToBottom(following: boolean, metrics: ScrollMetrics): boolean {
  return !following && distanceFromBottom(metrics) > CHAT_BOTTOM_THRESHOLD
}

export function followingAfterUserScroll(
  current: boolean,
  direction: 'up' | 'down' | null,
  metrics: ScrollMetrics,
): boolean {
  if (direction === 'up') return false
  if (direction === 'down' && distanceFromBottom(metrics) <= CHAT_BOTTOM_THRESHOLD) return true
  return current
}

export function shouldFollowContentChange(following: boolean, jumping: boolean): boolean {
  return following && !jumping
}

export function shouldApplyBottomScroll(input: {
  following: boolean
  jumping: boolean
  currentSession: string
  scheduledSession: string
}): boolean {
  return shouldFollowContentChange(input.following, input.jumping) && input.currentSession === input.scheduledSession
}
