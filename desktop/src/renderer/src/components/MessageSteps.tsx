import React, { useEffect, useRef, useState } from 'react'
import { ChevronRight, Loader2, Check, X, Lightbulb, Shield } from 'lucide-react'
import type { MessageStep, SubStep } from '../types'
import { t } from '../i18n'
import Markdown from './Markdown'
import { permLabel } from '../lib/permission'
import { useSessionSettingsStore } from '../store/sessionSettingsStore'

/**
 * Assistant reasoning / tool steps, styled to match the web console: small,
 * muted, collapsible rows with an indented detail panel.
 */

const ThinkingStep: React.FC<{ content: string; streaming?: boolean }> = ({ content, streaming }) => {
  const [expanded, setExpanded] = useState(false)
  return (
    <div className="text-xs text-content-tertiary mb-1 last:mb-0">
      <div
        className="flex items-center gap-1.5 cursor-pointer hover:text-content-secondary select-none transition-colors"
        onClick={() => setExpanded((v) => !v)}
      >
        <Lightbulb size={13} className={`flex-shrink-0 text-amber-400 ${streaming ? 'animate-pulse' : ''}`} />
        <span className="flex-1">{streaming ? t('thinking_in_progress') : t('thinking_done')}</span>
        <ChevronRight size={11} className={`transition-transform opacity-50 ${expanded ? 'rotate-90' : ''}`} />
      </div>
      {expanded && (
        <pre className="mt-1.5 ml-4 p-2 rounded-md bg-inset border border-subtle whitespace-pre-wrap leading-relaxed max-h-[260px] overflow-y-auto font-sans text-content-tertiary">
          {content}
        </pre>
      )}
    </div>
  )
}

/** One tool call a sub agent made, in the list under its step. */
const SubStepRow: React.FC<{ sub: SubStep }> = ({ sub }) => {
  const running = sub.status === 'running'
  const failed = !running && sub.status !== 'success'
  return (
    <div className="flex items-center gap-1.5 py-0.5 min-w-0" title={sub.error}>
      {running ? (
        <Loader2 size={10} className="flex-shrink-0 text-accent animate-spin" />
      ) : failed ? (
        <X size={10} className="flex-shrink-0 text-danger" />
      ) : (
        <Check size={10} className="flex-shrink-0 text-accent" />
      )}
      <span className="font-medium flex-shrink-0">{sub.name}</span>
      {/* A step that failed says so where it happened; what the successful
          ones found is already in the sub agent's report. */}
      <span className={`truncate opacity-70 ${sub.error ? 'text-danger' : ''}`}>
        {sub.error || sub.args}
      </span>
      {sub.execution_time !== undefined && sub.execution_time > 0 && (
        <span className="ml-auto flex-shrink-0 opacity-50">{sub.execution_time}s</span>
      )}
    </div>
  )
}

const ToolStep: React.FC<{ step: MessageStep }> = ({ step }) => {
  const substeps = step.substeps || []
  const [expanded, setExpanded] = useState(false)
  // A tool that wrote something for a person to read opens itself, and a sub
  // agent's first step is the first sign of life from a call that runs for
  // minutes. Everything else stays shut: its output is a trace. Opening is
  // once and only once, so the reader can shut it again and have it stay shut.
  const opened = useRef(false)
  useEffect(() => {
    if (opened.current || (!step.display && substeps.length === 0)) return
    opened.current = true
    setExpanded(true)
  }, [step.display, substeps.length])
  const running = step.status === 'running'
  const isError = step.is_error || (!!step.status && step.status !== 'success' && !running)

  const icon = running ? (
    <Loader2 size={12} className="text-accent animate-spin" />
  ) : isError ? (
    <X size={12} className="text-danger" />
  ) : (
    <Check size={12} className="text-accent" />
  )

  return (
    <div className="text-xs text-content-tertiary mb-1 last:mb-0">
      <div
        className="flex items-center gap-1.5 cursor-pointer hover:text-content-secondary select-none transition-colors"
        onClick={() => setExpanded((v) => !v)}
      >
        <span className="flex-shrink-0">{icon}</span>
        <span className={`font-medium ${isError ? 'text-danger' : ''}`}>{step.name}</span>
        {step.execution_time !== undefined && (
          <span className="opacity-60">{step.execution_time}s</span>
        )}
        {substeps.length > 0 && (
          <span className="opacity-60">
            {substeps.length === 1 ? '1 step' : `${substeps.length} steps`}
          </span>
        )}
        <ChevronRight size={11} className={`ml-auto transition-transform opacity-50 ${expanded ? 'rotate-90' : ''}`} />
      </div>
      {expanded && (
        <div className="mt-1.5 ml-4 p-2 rounded-md bg-inset border border-subtle space-y-2">
          {step.arguments && Object.keys(step.arguments).length > 0 && (
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-wide opacity-60 mb-1">Input</div>
              <pre className="font-mono text-[11px] whitespace-pre-wrap break-all max-h-[200px] overflow-y-auto leading-relaxed">
                {JSON.stringify(step.arguments, null, 2)}
              </pre>
            </div>
          )}
          {substeps.length > 0 && (
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-wide opacity-60 mb-1">Steps</div>
              <div className="max-h-[240px] overflow-y-auto text-[11px] leading-relaxed">
                {substeps.map((sub) => (
                  <SubStepRow key={sub.id} sub={sub} />
                ))}
              </div>
            </div>
          )}
          {/* The outcome written for a person is what gets shown; the raw
              result is the form the model was handed and stays hidden then. */}
          {step.display ? (
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-wide opacity-60 mb-1">
                {isError ? 'Error' : 'Output'}
              </div>
              <div className="max-h-[420px] overflow-y-auto">
                <Markdown content={step.display} />
              </div>
            </div>
          ) : (
            step.result && (
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-wide opacity-60 mb-1">
                  {isError ? 'Error' : 'Output'}
                </div>
                <pre
                  className={`font-mono text-[11px] whitespace-pre-wrap break-all max-h-[240px] overflow-y-auto leading-relaxed ${
                    isError ? 'text-danger' : ''
                  }`}
                >
                  {step.result.length > 4000 ? step.result.slice(0, 4000) + '\n… (truncated)' : step.result}
                </pre>
              </div>
            )
          )}
        </div>
      )}
      {step.permission_denied && <PermissionDeniedHint mode={step.permission_mode} />}
    </div>
  )
}

const PermissionDeniedHint: React.FC<{ mode?: string }> = ({ mode }) => {
  const label = permLabel(mode)
  return (
    <div className="mt-1.5 mb-1 flex items-center gap-2 px-3 py-2 rounded-lg border border-default bg-inset text-[12px] text-content-secondary">
      <Shield size={13} className="shrink-0 text-content-tertiary" />
      <span className="flex-1 min-w-0">
        {t('perm_denied_hint').replace('{name}', label)}
      </span>
      <button
        type="button"
        onClick={() => useSessionSettingsStore.getState().setOpenMenu('permission')}
        className="shrink-0 px-2 py-0.5 rounded-md text-[12px] font-medium text-accent-contrast bg-accent hover:bg-accent-hover cursor-pointer transition-colors"
      >
        {t('perm_denied_action')}
      </button>
    </div>
  )
}

/** Renders an ordered list of assistant steps (thinking / content / tool). */
const MessageSteps: React.FC<{ steps: MessageStep[] }> = ({ steps }) => {
  if (!steps.length) return null
  return (
    <div>
      {steps.map((step, i) => {
        if (step.type === 'thinking') return <ThinkingStep key={i} content={step.content || ''} />
        if (step.type === 'tool') return <ToolStep key={i} step={step} />
        if (step.type === 'content' && step.content)
          return (
            <div key={i} className="mb-2 pb-2 border-b border-dashed border-default last:border-0 last:mb-0 last:pb-0">
              <Markdown content={step.content} />
            </div>
          )
        return null
      })}
    </div>
  )
}

export { ThinkingStep, ToolStep }
export default MessageSteps
