import {create} from 'zustand';
import {cancelRequest, getHistory, sendMessage, serverFileUrl} from '../api/cowApi';
import {STREAM_FLUSH_INTERVAL_MS} from '../config/defaults';
import {
  type ChatFile,
  fileFromEvent,
  fileFromPayload,
  fileFromSendResult,
  mergeFile,
  sameFile,
} from '../files/chatFile';
import {tr} from '../i18n';
import type {
  HistoryMessage,
  Role,
  RunState,
  StreamEvent,
  Usage,
} from '../protocol/events';
import {subscribeChat} from '../realtime/chatStream';
import {agentParam, useAgentStore} from './agentStore';
import {resetOnSignOut} from './reset';
import {onServerEnvelope} from './serverStore';

/** `stopped`: the reply ended before the tool reported back. */
export type ToolStatus = 'running' | 'success' | 'error' | 'stopped';

/** A tool call a sub agent made inside the card of the call that spawned it. */
export interface SubStep {
  id: string;
  name: string;
  args?: Record<string, unknown>;
  status: ToolStatus;
  seconds?: number;
  error?: string;
}

export interface ToolStep {
  kind: 'tool';
  id: string;
  name: string;
  args?: Record<string, unknown>;
  status: ToolStatus;
  seconds?: number;
  /** What the model got back. The live stream cuts it at 2000 characters. */
  result?: string;
  /** The outcome written for a person, shown in place of `result`. */
  display?: string;
  /** Output so far while the tool is still running. */
  progress?: string;
  /** The teammate an `agent_delegate` call handed the work to. */
  handoff?: string;
  substeps?: SubStep[];
  /** Stays unfolded once it settles, as it was while streaming. */
  keepOpen?: boolean;
  /** What a `send` call delivered; pictures show right under the call. */
  file?: ChatFile;
}

export type Step =
  | {kind: 'text'; id: string; text: string}
  | {kind: 'thinking'; id: string; text: string; seconds?: number}
  | ToolStep;

export interface Speaker {
  id: string;
  name?: string;
}

export type AttachmentKind = 'image' | 'video' | 'directory' | 'file' | 'workspace_ref';

/** A file the user sent along with a message. */
export interface MessageAttachment {
  name: string;
  path: string;
  kind: AttachmentKind;
  /** What to show for an image: the local pick while sending, the server copy in history. */
  previewUri?: string;
}

export interface ChatMessage {
  id: string;
  role: Role;
  content: string;
  /** Unix seconds. */
  createdAt?: number;
  attachments?: MessageAttachment[];
  /** A voice message still being turned into text; it has no content yet. */
  transcribing?: boolean;
  /** Total across the turn's thinking steps, measured live only. */
  thinkingSeconds?: number;
  /** The Agent that answered; pushes and older replies don't say. */
  speaker?: Speaker;
  /** A teammate answering inside another Agent's turn. */
  peer?: boolean;
  /** Where a replayed hand-off's own steps are stored, until they are filled in. */
  delegate?: {sessionId: string; agentId: string};
  steps?: Step[];
  /** Files the reply wrote or sent, shown below its answer. */
  files?: ChatFile[];
  usage?: Usage;
  streaming?: boolean;
  cancelled?: boolean;
  /** A replayed reply that never reached its answer. */
  runState?: RunState;
  error?: string;
}

interface ActiveRequest {
  requestId: string | null;
  unsubscribe: (() => void) | null;
  /** Ends the turn on screen at once; the server stops it on its own time. */
  stop?: () => void;
}

/** One request's bubbles. A teammate taking the floor opens a bubble of its own. */
interface Turn {
  sessionId: string;
  ids: string[];
  /** The bubble events are written into. */
  current: string;
  /** Who holds the floor, innermost last; the first is the Agent addressed. */
  floor: Speaker[];
}

interface ChatState {
  currentSessionId: string | null;
  messages: Record<string, ChatMessage[]>;
  loading: Record<string, boolean>;
  /** Replies streaming right now, by session; at most `MAX_REPLYING` of them. */
  active: Record<string, ActiveRequest>;
  setCurrentSession: (sessionId: string) => void;
  loadHistory: (sessionId: string, agentId?: string | null) => Promise<void>;
  send: (
    sessionId: string,
    text: string,
    agentId?: string | null,
    opts?: {attachments?: MessageAttachment[]; voice?: boolean; replaceId?: string},
  ) => Promise<void>;
  /** Holds the place of a voice message until its text is known; returns the bubble's id. */
  addTranscribing: (sessionId: string) => string;
  removeMessage: (sessionId: string, id: string) => void;
  cancel: (sessionId: string) => Promise<void>;
}

/**
 * Each streaming reply holds one HTTP connection open for its whole run, and
 * the platform allows only a few per host (4 on iOS, 5 on Android). Beyond two,
 * history and list requests would queue behind the streams.
 */
export const MAX_REPLYING = 2;

const without = <T>(map: Record<string, T>, key: string): Record<string, T> => {
  const next = {...map};
  delete next[key];
  return next;
};

let localId = 0;
const nextId = (prefix: string) => `${prefix}-${Date.now()}-${++localId}`;

const CANCEL_MARKER = /^\s*_\(Cancelled(?: by user)?\)_\s*$/;

// Labels the server writes when it folds attachments into the prompt, in every UI language.
const MARKER_KINDS: Record<string, AttachmentKind> = {
  工作空间文件: 'workspace_ref',
  工作空间檔案: 'workspace_ref',
  'Workspace file': 'workspace_ref',
  工作空间目录: 'workspace_ref',
  工作空间目錄: 'workspace_ref',
  'Workspace directory': 'workspace_ref',
  图片: 'image',
  圖片: 'image',
  Image: 'image',
  视频: 'video',
  影片: 'video',
  Video: 'video',
  目录: 'directory',
  目錄: 'directory',
  Directory: 'directory',
  文件: 'file',
  檔案: 'file',
  File: 'file',
};
const MARKER_LINE = /^\[([^\]:]+):\s*(.+)\]$/;

/** History only keeps the prompt text, so attachments come back from its trailing `[label: path]` lines. */
function splitAttachments(content: string): {text: string; attachments?: MessageAttachment[]} {
  const lines = content.split('\n');
  const found: MessageAttachment[] = [];
  while (lines.length) {
    const line = lines[lines.length - 1].trim();
    if (!line) {
      lines.pop();
      continue;
    }
    const match = MARKER_LINE.exec(line);
    const kind = match && MARKER_KINDS[match[1].trim()];
    if (!match || !kind) {
      break;
    }
    const path = match[2].trim();
    found.unshift({
      kind,
      path,
      name: path.split(/[\\/]/).filter(Boolean).pop() || path,
      previewUri: kind === 'image' ? serverFileUrl(path) : undefined,
    });
    lines.pop();
  }
  return found.length
    ? {text: lines.join('\n').trimEnd(), attachments: found}
    : {text: content};
}

const DELEGATE_TOOL = 'agent_delegate';
const SEND_TOOL = 'send';

/** The teammate reply an `agent_delegate` result carries, if it got one. */
function handoffOf(
  result: string | undefined,
): {speaker: Speaker; content: string; sessionId?: string} | null {
  if (!result) {
    return null;
  }
  try {
    const p = JSON.parse(result) as {
      content?: unknown;
      agent_id?: unknown;
      agent_name?: unknown;
      session_id?: unknown;
    };
    if (!p || typeof p.content !== 'string' || !p.content.trim()) {
      return null;
    }
    const id = typeof p.agent_id === 'string' ? p.agent_id : '';
    const name = typeof p.agent_name === 'string' && p.agent_name ? p.agent_name : undefined;
    // Only a teammate in this process has a session here; a remote one doesn't.
    const sessionId = typeof p.session_id === 'string' && p.session_id ? p.session_id : undefined;
    return {speaker: {id, name}, content: p.content, sessionId};
  } catch {
    return null;
  }
}

/**
 * One stored assistant turn as the bubbles it streamed as. A hand-off is stored
 * inside the delegating Agent's turn, but live it read as the teammate answering
 * in a bubble of its own; replay it the same way.
 */
function fromHistoryMessage(m: HistoryMessage, index: number): ChatMessage[] {
  const id = `h-${m._seq ?? index}-${m.created_at}`;
  if (m.role === 'user') {
    const {text, attachments} = splitAttachments(m.content ?? '');
    return [{id, role: 'user', content: text, attachments}];
  }
  const raw = m.steps ?? [];
  const runState = m.run_state;
  let lastContent = -1;
  // A reply without its answer has no final text: every text it wrote stays a step.
  raw.forEach((s, i) => {
    if (s.type === 'content' && !runState) {
      lastContent = i;
    }
  });
  const speaker = m.extras?.agent_id ? {id: m.extras.agent_id} : undefined;
  const bubbles: ChatMessage[] = [];
  let steps: Step[] = [];
  if (m.reasoning?.trim() && !raw.some(s => s.type === 'thinking')) {
    steps.push({kind: 'thinking', id: `${id}-r`, text: m.reasoning.trim()});
  }
  raw.forEach((s, i) => {
    const sid = `${id}-s${i}`;
    if (s.type === 'thinking') {
      if (s.content.trim()) {
        steps.push({kind: 'thinking', id: sid, text: s.content.trim()});
      }
    } else if (s.type === 'content') {
      if (i !== lastContent && s.content.trim() && !CANCEL_MARKER.test(s.content)) {
        steps.push({kind: 'text', id: sid, text: s.content.trim()});
      }
    } else if (s.type === 'tool') {
      const handoff = s.name === DELEGATE_TOOL && !s.is_error ? handoffOf(s.result) : null;
      steps.push({
        kind: 'tool',
        id: s.id ?? sid,
        name: s.name ?? 'tool',
        args: s.arguments,
        status: s.is_error ? 'error' : 'success',
        result: s.result || undefined,
        display: s.display || undefined,
        handoff: handoff ? handoff.speaker.name || handoff.speaker.id : undefined,
        file: s.name === SEND_TOOL && !s.is_error ? fileFromSendResult(s.result) ?? undefined : undefined,
      });
      if (handoff) {
        bubbles.push({id: `${id}-b${i}`, role: 'assistant', content: '', steps, speaker});
        bubbles.push({
          id: `${id}-p${i}`,
          role: 'assistant',
          content: handoff.content,
          speaker: handoff.speaker,
          peer: true,
          delegate:
            handoff.sessionId && handoff.speaker.id
              ? {sessionId: handoff.sessionId, agentId: handoff.speaker.id}
              : undefined,
        });
        steps = [];
      }
    }
  });
  const cancelled = CANCEL_MARKER.test(m.content);
  const answer = m.content || (lastContent >= 0 ? (raw[lastContent] as {content: string}).content : '');
  const content = cancelled || runState ? '' : answer;
  const files = (m.artifacts ?? []).map(fileFromPayload).filter((f): f is ChatFile => !!f);
  if (!bubbles.length || steps.length || content.trim() || files.length || cancelled || runState) {
    bubbles.push({
      id,
      role: 'assistant',
      content,
      steps: steps.length ? steps : undefined,
      files: files.length ? files : undefined,
      usage: m.usage,
      cancelled,
      runState,
      speaker,
    });
  }
  return bubbles;
}

/**
 * The server returns a page in conversation order. Not every turn has a `_seq`
 * (a run cut off before storing anything has none), so it can't be re-sorted.
 */
function fromHistory(items: HistoryMessage[]): ChatMessage[] {
  return items.flatMap((m, i) => fromHistoryMessage(m, i).map(msg => ({...msg, createdAt: m.created_at})));
}

const MAX_DELEGATE_DEPTH = 3;
const MAX_DELEGATE_PAGES = 5;

/** A reply's opening, compared loosely: a hand-off with files appends their links. */
const answerKey = (text: string) => text.replace(/\s+/g, ' ').trim().slice(0, 200);
const sameAnswer = (a: string, b: string) => !!a && !!b && (a.startsWith(b) || b.startsWith(a));

/**
 * The delegating Agent's history keeps only a hand-off's answer; what the
 * teammate did to get there is stored as a turn of its own delegated session.
 * Replay that turn in place of the bare answer, as it streamed live.
 */
async function expandDelegations(messages: ChatMessage[], depth = 0): Promise<ChatMessage[]> {
  const wanted = messages.filter(m => m.delegate);
  if (!wanted.length) {
    return messages;
  }
  const groups = new Map<string, {sessionId: string; agentId: string; peers: ChatMessage[]}>();
  for (const m of wanted) {
    const {sessionId, agentId} = m.delegate!;
    const key = `${agentId}\n${sessionId}`;
    const group = groups.get(key) ?? {sessionId, agentId, peers: []};
    group.peers.push(m);
    groups.set(key, group);
  }

  const replays = new Map<string, ChatMessage[]>();
  if (depth < MAX_DELEGATE_DEPTH) {
    await Promise.all(
      [...groups.values()].map(async ({sessionId, agentId, peers}) => {
        const left = new Map(peers.map(p => [p.id, answerKey(p.content)]));
        try {
          for (let page = 1; page <= MAX_DELEGATE_PAGES && left.size; page++) {
            const res = await getHistory(sessionId, agentParam(agentId), page);
            res.messages.forEach((h, i) => {
              const key = h.role === 'assistant' ? answerKey(h.content ?? '') : '';
              const match = [...left].find(([, want]) => sameAnswer(key, want));
              if (match) {
                left.delete(match[0]);
                replays.set(match[0], fromHistoryMessage(h, i));
              }
            });
            if (!res.has_more) {
              break;
            }
          }
        } catch {
          // The bare answer stays; the steps are a bonus.
        }
      }),
    );
  }

  const next = messages.flatMap(m => {
    if (!m.delegate) {
      return [m];
    }
    const replay = replays.get(m.id);
    if (!replay?.length) {
      return [{...m, delegate: undefined}];
    }
    const bubbles = replay.map((r, i): ChatMessage => ({
      ...r,
      id: `${m.id}-d${i}`,
      createdAt: m.createdAt,
      peer: true,
      speaker: r.speaker && r.speaker.id !== m.speaker?.id ? r.speaker : m.speaker,
    }));
    const tail = bubbles[bubbles.length - 1];
    if (replay[replay.length - 1].peer) {
      bubbles.push({...m, id: `${m.id}-d${bubbles.length}`, delegate: undefined});
    } else {
      // What the delegating Agent was handed, files included; being an answer, the turn did finish.
      bubbles[bubbles.length - 1] = {...tail, content: m.content, runState: undefined};
    }
    return bubbles;
  });
  return expandDelegations(next, depth + 1);
}

const nowSeconds = () => Date.now() / 1000;

const isBlank = (m: ChatMessage) =>
  !m.content.trim() && !m.steps?.length && !m.files?.length && !m.error && !m.cancelled;

/** Pending text per message, flushed to the store on a short interval. */
const pending = new Map<string, {sessionId: string; content: string; reasoning: string}>();
/** The thinking step each message is writing, and when that thinking began. */
const thinking = new Map<string, {stepId: string | null; startedAt: number}>();
let flushTimer: ReturnType<typeof setTimeout> | null = null;
/** Moves on whenever a turn starts or ends in a session; a history page fetched across that is stale. */
const turnEpoch = new Map<string, number>();
/** Requests the user stopped, never picked up again from history while the server winds them down. */
const stoppedRequests = new Set<string>();

export const useChatStore = create<ChatState>((set, get) => {
  const patch = (
    sessionId: string,
    messageId: string,
    fn: (m: ChatMessage) => ChatMessage,
  ) =>
    set(state => ({
      messages: {
        ...state.messages,
        [sessionId]: (state.messages[sessionId] ?? []).map(m =>
          m.id === messageId ? fn(m) : m,
        ),
      },
    }));

  const flush = () => {
    if (flushTimer) {
      clearTimeout(flushTimer);
      flushTimer = null;
    }
    const {active} = get();
    pending.forEach((buf, messageId) => {
      // Signed out meanwhile: the session belongs to another server now.
      if (!active[buf.sessionId]) {
        return;
      }
      const open = thinking.get(messageId);
      patch(buf.sessionId, messageId, m => {
        let steps = m.steps ?? [];
        if (buf.reasoning) {
          const last = steps[steps.length - 1];
          if (open?.stepId && last?.kind === 'thinking' && last.id === open.stepId) {
            steps = [...steps.slice(0, -1), {...last, text: last.text + buf.reasoning}];
          } else {
            const step: Step = {kind: 'thinking', id: nextId('think'), text: buf.reasoning};
            if (open) {
              open.stepId = step.id;
            }
            steps = [...steps, step];
          }
        }
        return {...m, content: m.content + buf.content, steps: steps.length ? steps : undefined};
      });
    });
    pending.clear();
  };

  const buffer = (sessionId: string, messageId: string, field: 'content' | 'reasoning', text: string) => {
    const buf = pending.get(messageId) ?? {sessionId, content: '', reasoning: ''};
    buf[field] += text;
    pending.set(messageId, buf);
    if (!flushTimer) {
      flushTimer = setTimeout(flush, STREAM_FLUSH_INTERVAL_MS);
    }
  };

  /** Close the thinking step once the model moves on to answering or acting. */
  const stopThinking = (sessionId: string, messageId: string) => {
    const open = thinking.get(messageId);
    if (!open) {
      return;
    }
    flush();
    thinking.delete(messageId);
    const seconds = Math.max(0.1, (Date.now() - open.startedAt) / 1000);
    patch(sessionId, messageId, m => ({
      ...m,
      thinkingSeconds: (m.thinkingSeconds ?? 0) + seconds,
      steps: m.steps?.map(s => (s.kind === 'thinking' && s.id === open.stepId ? {...s, seconds} : s)),
    }));
  };

  /** Update a tool card wherever it is; a hand-off settles after its teammate's bubble. */
  const patchTool = (turn: Turn, toolId: string | undefined, fn: (s: ToolStep) => ToolStep) => {
    if (!toolId) {
      return;
    }
    set(state => ({
      messages: {
        ...state.messages,
        [turn.sessionId]: (state.messages[turn.sessionId] ?? []).map(m =>
          turn.ids.includes(m.id) && m.steps?.some(s => s.kind === 'tool' && s.id === toolId)
            ? {...m, steps: m.steps.map(s => (s.kind === 'tool' && s.id === toolId ? fn(s) : s))}
            : m,
        ),
      },
    }));
  };

  const openBubble = (turn: Turn) => {
    const msg: ChatMessage = {
      id: nextId('a'),
      role: 'assistant',
      content: '',
      createdAt: nowSeconds(),
      streaming: true,
      speaker: turn.floor[turn.floor.length - 1],
      peer: turn.floor.length > 1 || undefined,
    };
    turn.ids.push(msg.id);
    turn.current = msg.id;
    set(s => ({
      messages: {...s.messages, [turn.sessionId]: [...(s.messages[turn.sessionId] ?? []), msg]},
    }));
  };

  const sealBubble = (turn: Turn) => {
    stopThinking(turn.sessionId, turn.current);
    flush();
    patch(turn.sessionId, turn.current, m => ({...m, streaming: false}));
  };

  const applyEvent = (turn: Turn, event: StreamEvent) => {
    const {sessionId} = turn;
    const messageId = turn.current;
    switch (event.type) {
      case 'reasoning':
        if (!thinking.has(messageId)) {
          thinking.set(messageId, {stepId: null, startedAt: Date.now()});
        }
        buffer(sessionId, messageId, 'reasoning', event.content ?? '');
        break;
      case 'delta':
        stopThinking(sessionId, messageId);
        buffer(sessionId, messageId, 'content', event.content ?? '');
        break;
      case 'tool_start':
        stopThinking(sessionId, messageId);
        flush();
        // Text streamed before a tool call is narration, not the answer.
        patch(sessionId, messageId, m => {
          const steps = [...(m.steps ?? [])];
          if (m.content.trim()) {
            steps.push({kind: 'text', id: nextId('txt'), text: m.content.trim()});
          }
          steps.push({
            kind: 'tool',
            id: event.tool_call_id ?? nextId('tool'),
            name: event.tool ?? 'tool',
            args: event.arguments,
            status: 'running',
          });
          return {...m, content: '', steps};
        });
        break;
      case 'tool_progress':
        patchTool(turn, event.tool_call_id, s => ({...s, progress: event.content || s.progress}));
        break;
      case 'tool_end':
        patchTool(turn, event.tool_call_id, s => ({
          ...s,
          status: event.status && event.status !== 'success' ? 'error' : 'success',
          seconds: event.execution_time,
          result: event.result || undefined,
          display: event.display || undefined,
          progress: undefined,
          // The reader just waited for an outcome written for them; a hand-off's is the bubble below.
          keepOpen: !!event.display && s.name !== DELEGATE_TOOL,
          file:
            s.name === SEND_TOOL && event.status === 'success'
              ? fileFromSendResult(event.result) ?? undefined
              : undefined,
        }));
        break;
      case 'subagent_step':
        patchTool(turn, event.card_id, s => {
          const subs = s.substeps ?? [];
          const id = event.step_id;
          if (!id) {
            return s;
          }
          if (event.phase === 'start') {
            return subs.some(x => x.id === id)
              ? s
              : {
                  ...s,
                  substeps: [...subs, {id, name: event.tool ?? 'tool', args: event.arguments, status: 'running'}],
                };
          }
          return {
            ...s,
            substeps: subs.map(x =>
              x.id === id
                ? {
                    ...x,
                    status: event.status && event.status !== 'success' ? 'error' : 'success',
                    seconds: event.execution_time || undefined,
                    error: event.error || undefined,
                  }
                : x,
            ),
          };
        });
        break;
      case 'peer_start': {
        const speaker: Speaker = {id: event.agent_id ?? '', name: event.agent_name || undefined};
        patchTool(turn, event.card_id, s => ({...s, handoff: speaker.name || speaker.id}));
        sealBubble(turn);
        turn.floor.push(speaker);
        openBubble(turn);
        break;
      }
      case 'peer_end':
        sealBubble(turn);
        if (turn.floor.length > 1) {
          turn.floor.pop();
        }
        openBubble(turn);
        break;
      case 'image':
      case 'video':
      case 'file':
      case 'artifact': {
        const file = fileFromEvent(event);
        if (!file) {
          break;
        }
        const media = file.kind === 'image' || file.kind === 'video';
        const underCall = (get().messages[sessionId] ?? []).some(
          m =>
            turn.ids.includes(m.id) &&
            m.steps?.some(s => s.kind === 'tool' && !!s.file && sameFile(s.file, file)),
        );
        // A picture a `send` call delivered already shows under that call.
        if (media && underCall) {
          break;
        }
        patch(sessionId, messageId, m => {
          const files = m.files ?? [];
          const at = files.findIndex(f => sameFile(f, file));
          return {
            ...m,
            files: at < 0 ? [...files, file] : files.map((f, i) => (i === at ? mergeFile(f, file) : f)),
          };
        });
        break;
      }
      case 'done':
        stopThinking(sessionId, messageId);
        flush();
        patch(sessionId, messageId, m => ({
          ...m,
          content: m.cancelled ? m.content : event.content || m.content,
          usage: event.usage ?? m.usage,
          streaming: false,
        }));
        break;
      case 'cancelled':
        flush();
        patch(sessionId, messageId, m => ({...m, cancelled: true}));
        break;
      case 'error':
        flush();
        patch(sessionId, messageId, m => ({
          ...m,
          streaming: false,
          error: event.message ?? event.content ?? tr('chat_generate_failed'),
        }));
        break;
      default:
        break;
    }
  };

  const bumpEpoch = (sessionId: string) => turnEpoch.set(sessionId, (turnEpoch.get(sessionId) ?? 0) + 1);

  /** Ends a turn on screen; its first bubble stays even if nothing was written into it. */
  const control = (turn: Turn) => {
    const {sessionId} = turn;
    const ownId = turn.ids[0];
    const ctl = {
      settled: false,
      /** Stopped by the user: the turn is over on screen while the server winds down. */
      stopped: false,
      unsubscribe: null as (() => void) | null,
      finish: () => {
        if (ctl.settled) {
          return;
        }
        ctl.settled = true;
        bumpEpoch(sessionId);
        turn.ids.forEach(id => stopThinking(sessionId, id));
        flush();
        set(state => ({
          // After a sign-out the session may already be streaming a newer turn.
          active: state.active[sessionId]?.stop === ctl.stop ? without(state.active, sessionId) : state.active,
          messages: {
            ...state.messages,
            [sessionId]: (state.messages[sessionId] ?? [])
              // A bubble opened for a speaker who then said nothing is noise.
              .filter(m => !turn.ids.includes(m.id) || m.id === ownId || !isBlank(m))
              .map(m =>
                turn.ids.includes(m.id)
                  ? {
                      ...m,
                      streaming: false,
                      steps: m.steps?.map(s =>
                        s.kind === 'tool' && s.status === 'running' ? {...s, status: 'stopped'} : s,
                      ),
                    }
                  : m,
              ),
          },
        }));
      },
      stop: () => {
        if (ctl.settled) {
          return;
        }
        ctl.stopped = true;
        // Left open, a late event would write into whatever server is signed in by then.
        ctl.unsubscribe?.();
        patch(sessionId, turn.current, m => ({...m, cancelled: true}));
        ctl.finish();
      },
    };
    return ctl;
  };

  const follow = (
    turn: Turn,
    ctl: ReturnType<typeof control>,
    requestId: string,
    agentId: string | null | undefined,
    afterSeq = 0,
  ) => {
    ctl.unsubscribe = subscribeChat(
      requestId,
      {
        onEvent: event => {
          applyEvent(turn, event);
          // The answer is stored; with auto TTS on, `stream_end` waits up to a
          // minute for the audio. Free the composer now, as the web console does.
          if (event.type === 'done') {
            ctl.finish();
          }
        },
        onEnd: end => {
          // After `done` only the audio tail was left; the next message may
          // already be streaming, which a history reload would wipe.
          if (ctl.settled) {
            return;
          }
          if (end.kind === 'failed') {
            patch(turn.sessionId, turn.current, m => ({...m, error: end.error}));
          }
          ctl.finish();
          if (end.kind === 'resync') {
            get().loadHistory(turn.sessionId, agentId).catch(() => undefined);
          }
        },
      },
      afterSeq,
    );
    set(s => {
      const own = s.active[turn.sessionId];
      return own?.stop === ctl.stop
        ? {active: {...s.active, [turn.sessionId]: {...own, requestId, unsubscribe: ctl.unsubscribe}}}
        : s;
    });
  };

  /**
   * Follows a reply the server is still streaming into a session just loaded
   * from history, as the web console does: the stored part is on screen, the
   * rest arrives after `afterSeq`. Without this a reply left mid-stream (by
   * switching sessions or a dropped stream) would stay cut off.
   */
  const resume = (
    sessionId: string,
    agentId: string | null | undefined,
    requestId: string,
    afterSeq: number,
  ) => {
    const list = get().messages[sessionId] ?? [];
    const last = list[list.length - 1];
    const stored = last?.role === 'assistant' && last.runState === 'running';
    const ownerId = agentId ?? useAgentStore.getState().currentId;
    const bubble: ChatMessage = stored
      ? {...last, runState: undefined, streaming: true}
      : {
          id: nextId('a'),
          role: 'assistant',
          content: '',
          createdAt: nowSeconds(),
          streaming: true,
          speaker: ownerId ? {id: ownerId} : undefined,
        };
    const turn: Turn = {
      sessionId,
      ids: [bubble.id],
      current: bubble.id,
      floor: bubble.speaker ? [bubble.speaker] : [],
    };
    const ctl = control(turn);
    bumpEpoch(sessionId);
    set(s => ({
      messages: {...s.messages, [sessionId]: stored ? [...list.slice(0, -1), bubble] : [...list, bubble]},
      active: {...s.active, [sessionId]: {requestId, unsubscribe: null, stop: ctl.stop}},
    }));
    follow(turn, ctl, requestId, agentId, afterSeq);
  };

  return {
    currentSessionId: null,
    messages: {},
    loading: {},
    active: {},

    setCurrentSession: sessionId => set({currentSessionId: sessionId}),

    loadHistory: async (sessionId, agentId) => {
      const epoch = turnEpoch.get(sessionId) ?? 0;
      // A reply streaming into this session is matched by its local ids, and
      // one that ended while the page was in flight is newer than it: the
      // server's copy would drop the rest of the answer.
      const stale = () => !!get().active[sessionId] || (turnEpoch.get(sessionId) ?? 0) !== epoch;
      set(s => ({loading: {...s.loading, [sessionId]: true}}));
      try {
        const page = await getHistory(sessionId, agentParam(agentId));
        if (stale()) {
          return;
        }
        const loaded = fromHistory(page.messages);
        set(s => ({messages: {...s.messages, [sessionId]: loaded}}));
        if (loaded.some(m => m.delegate)) {
          const expanded = await expandDelegations(loaded);
          // A message sent meanwhile owns the list now.
          set(s => (s.messages[sessionId] === loaded ? {messages: {...s.messages, [sessionId]: expanded}} : s));
        }
        const live = page.active_request;
        // With every slot taken the page stays as stored, like the web console before a reload.
        const full = Object.keys(get().active).length >= MAX_REPLYING;
        if (live?.request_id && !stoppedRequests.has(live.request_id) && !full && !stale()) {
          resume(sessionId, agentId, live.request_id, live.after_seq ?? 0);
        }
      } finally {
        set(s => ({loading: {...s.loading, [sessionId]: false}}));
      }
    },

    addTranscribing: sessionId => {
      const id = nextId('u');
      const msg: ChatMessage = {id, role: 'user', content: '', createdAt: nowSeconds(), transcribing: true};
      set(s => ({messages: {...s.messages, [sessionId]: [...(s.messages[sessionId] ?? []), msg]}}));
      return id;
    },

    removeMessage: (sessionId, id) =>
      set(s => ({messages: {...s.messages, [sessionId]: (s.messages[sessionId] ?? []).filter(m => m.id !== id)}})),

    send: async (sessionId, text, agentId, opts = {}) => {
      const {active} = get();
      if (active[sessionId] || Object.keys(active).length >= MAX_REPLYING) {
        if (opts.replaceId) {
          get().removeMessage(sessionId, opts.replaceId);
        }
        return;
      }
      const attachments = opts.attachments?.length ? opts.attachments : undefined;
      const userMsg: ChatMessage = {
        id: nextId('u'),
        role: 'user',
        content: text,
        createdAt: nowSeconds(),
        attachments,
      };
      const ownerId = agentId ?? useAgentStore.getState().currentId;
      const botMsg: ChatMessage = {
        id: nextId('a'),
        role: 'assistant',
        content: '',
        createdAt: nowSeconds(),
        streaming: true,
        speaker: ownerId ? {id: ownerId} : undefined,
      };
      const turn: Turn = {
        sessionId,
        ids: [botMsg.id],
        current: botMsg.id,
        floor: botMsg.speaker ? [botMsg.speaker] : [],
      };
      const ctl = control(turn);

      bumpEpoch(sessionId);
      set(s => ({
        messages: {
          ...s.messages,
          [sessionId]: [...(s.messages[sessionId] ?? []).filter(m => m.id !== opts.replaceId), userMsg, botMsg],
        },
        active: {...s.active, [sessionId]: {requestId: null, unsubscribe: null, stop: ctl.stop}},
      }));

      try {
        const res = await sendMessage(sessionId, text, agentParam(agentId), {
          attachments: attachments?.map(a => ({
            file_path: a.path,
            file_name: a.name,
            file_type: a.kind,
          })),
          isVoice: opts.voice,
        });
        // Stopped before the server named the request: cancel it now, show nothing of it.
        if (ctl.stopped) {
          if (res.request_id) {
            stoppedRequests.add(res.request_id);
            cancelRequest(res.request_id, sessionId).catch(() => undefined);
          }
          return;
        }
        // Signed out while the message was posting: nothing is left to stream into.
        if (get().active[sessionId]?.stop !== ctl.stop) {
          return;
        }
        if (!res.request_id) {
          patch(sessionId, botMsg.id, m => ({...m, content: res.inline_reply ?? ''}));
          ctl.finish();
          return;
        }
        if (res.speaker) {
          turn.floor[0] = {id: res.speaker};
          patch(sessionId, botMsg.id, m => ({...m, speaker: turn.floor[0]}));
        }
        follow(turn, ctl, res.request_id, agentId);
      } catch (e) {
        if (ctl.stopped) {
          return;
        }
        patch(sessionId, botMsg.id, m => ({
          ...m,
          error: e instanceof Error ? e.message : String(e),
        }));
        ctl.finish();
      }
    },

    cancel: async sessionId => {
      const active = get().active[sessionId];
      if (!active) {
        return;
      }
      active.stop?.();
      if (active.requestId) {
        stoppedRequests.add(active.requestId);
        await cancelRequest(active.requestId, sessionId);
      }
    },
  };
});

resetOnSignOut(useChatStore, state => {
  Object.values(state.active).forEach(a => a.unsubscribe?.());
  pending.clear();
  thinking.clear();
  turnEpoch.clear();
  stoppedRequests.clear();
});

onServerEnvelope(envelope => {
  if (envelope.type !== 'push.message' || !envelope.payload.session_id) {
    return;
  }
  const sessionId = envelope.payload.session_id;
  useChatStore.setState(s => {
    if (!s.messages[sessionId]) {
      return s;
    }
    const pushed: ChatMessage = {
      id: `push-${envelope.seq}`,
      role: 'assistant',
      content: envelope.payload.content,
    };
    return {messages: {...s.messages, [sessionId]: [...s.messages[sessionId], pushed]}};
  });
});
