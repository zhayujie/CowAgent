import { create } from 'zustand'

interface TimelineState {
  /** True while a message-navigator jump is loading pages or gliding; the chat
   *  page holds off its own auto-scroll and load-more so they don't fight it. */
  jumping: boolean
  setJumping: (v: boolean) => void
}

export const useTimelineStore = create<TimelineState>((set) => ({
  jumping: false,
  setJumping: (jumping) => set({ jumping }),
}))
