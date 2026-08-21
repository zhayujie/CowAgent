import React, { useCallback, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { create } from 'zustand'
import { X } from 'lucide-react'
import { t } from '../i18n'

/**
 * Global image lightbox, mirroring the web console's `_openImageLightbox`:
 * dark overlay, image contained to 92vw/92vh, close on backdrop click or Esc.
 * Any component can open it via `useLightboxStore.getState().open(src)`.
 */

interface LightboxState {
  src: string | null
  open: (src: string) => void
  close: () => void
}

export const useLightboxStore = create<LightboxState>((set) => ({
  src: null,
  open: (src) => set({ src }),
  close: () => set({ src: null }),
}))

const Lightbox: React.FC = () => {
  const src = useLightboxStore((s) => s.src)
  const close = useLightboxStore((s) => s.close)

  const onKey = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    },
    [close]
  )

  useEffect(() => {
    if (!src) return
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [src, onKey])

  if (!src) return null

  return createPortal(
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/85 cursor-zoom-out"
      onClick={close}
      role="dialog"
      aria-modal="true"
    >
      <img
        src={src}
        alt=""
        draggable={false}
        className="max-w-[92vw] max-h-[92vh] rounded-lg shadow-2xl object-contain select-none cursor-default"
        onClick={(e) => e.stopPropagation()}
      />
      <button
        type="button"
        onClick={close}
        aria-label={t('msg_image_close')}
        title={t('msg_image_close')}
        className="absolute top-4 right-4 inline-flex items-center justify-center w-9 h-9 rounded-full bg-white/10 text-white/80 hover:text-white hover:bg-white/20 cursor-pointer transition-colors"
      >
        <X size={18} />
      </button>
    </div>,
    document.body
  )
}

export default Lightbox
