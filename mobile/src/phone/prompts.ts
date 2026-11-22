import {create} from 'zustand';
import type {AppPermission} from '../media/permissions';
import {readJSON, writeJSON} from '../storage/kv';

export type Choice = 'once' | 'always' | 'deny';

export type PhonePrompt =
  | {kind: 'confirm'; id: string; action: string; target: string; settle: (c: Choice) => void}
  // Something only the system settings can change, offered with the way there.
  | {kind: 'blocked'; id: string; permission: AppPermission}
  | {kind: 'location_off'; id: string};

interface PromptState {
  prompts: PhonePrompt[];
  /** Shown above the system dialog while it asks, which itself can't say why on Android. */
  purpose: AppPermission | null;
  /** What the user lets the agent do without asking each time. */
  trusted: string[];
}

export const usePhonePrompts = create<PromptState>(() => ({prompts: [], purpose: null, trusted: []}));

const TRUSTED_KEY = 'phone:trusted';

let loading: Promise<void> | null = null;

/** Read once; a request waits for it so what was always allowed is not asked again. */
export function loadTrusted(): Promise<void> {
  loading ??= readJSON<string[]>(TRUSTED_KEY, []).then(saved =>
    usePhonePrompts.setState({trusted: Array.isArray(saved) ? saved.filter(s => typeof s === 'string') : []}),
  );
  return loading;
}

export const isTrusted = (scope: string) => usePhonePrompts.getState().trusted.includes(scope);

export function setTrusted(scope: string, on: boolean): void {
  const rest = usePhonePrompts.getState().trusted.filter(t => t !== scope);
  const trusted = on ? [...rest, scope] : rest;
  usePhonePrompts.setState({trusted});
  writeJSON(TRUSTED_KEY, trusted).catch(() => undefined);
}

const remove = (id: string) => usePhonePrompts.setState(s => ({prompts: s.prompts.filter(p => p.id !== id)}));

export function askConfirm(id: string, action: string, target: string): Promise<Choice> {
  return new Promise(resolve => {
    const settle = (c: Choice) => {
      remove(id);
      resolve(c);
    };
    usePhonePrompts.setState(s => ({prompts: [...s.prompts, {kind: 'confirm', id, action, target, settle}]}));
  });
}

export function showBlocked(id: string, permission: AppPermission): void {
  usePhonePrompts.setState(s => ({
    prompts: [...s.prompts.filter(p => !(p.kind === 'blocked' && p.permission === permission)), {kind: 'blocked', id, permission}],
  }));
}

export function showLocationOff(id: string): void {
  usePhonePrompts.setState(s => ({prompts: [...s.prompts.filter(p => p.kind !== 'location_off'), {kind: 'location_off', id}]}));
}

/** The kernel stopped waiting: a question nobody will read the answer to goes away. */
export function dismissPrompt(id: string): void {
  const prompt = usePhonePrompts.getState().prompts.find(p => p.id === id);
  if (prompt?.kind === 'confirm') {
    prompt.settle('deny');
  } else if (prompt) {
    remove(id);
  }
}

export const closePrompt = remove;

/** Turns every open question down and drops the rest. */
export function clearPrompts(): void {
  usePhonePrompts.getState().prompts.forEach(p => p.kind === 'confirm' && p.settle('deny'));
  usePhonePrompts.setState({prompts: []});
}

export const setPurpose = (purpose: AppPermission | null) => usePhonePrompts.setState({purpose});
