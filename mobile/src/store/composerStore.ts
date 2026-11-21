import {create} from 'zustand';
import {uploadAttachment} from '../api/cowApi';
import {isImageType, type PickedFile} from '../media/types';
import {agentParam} from './agentStore';
import type {AttachmentKind, MessageAttachment} from './chatStore';
import {resetOnSignOut} from './reset';

export const MAX_ATTACHMENTS = 9;

/** A file waiting in the composer; uploading starts as soon as it is picked. */
export interface PendingAttachment {
  id: string;
  name: string;
  kind: AttachmentKind;
  localUri: string;
  status: 'uploading' | 'done' | 'error';
  path?: string;
  error?: string;
}

interface ComposerState {
  items: PendingAttachment[];
  /** Returns how many files were left out because the tray was full. */
  add: (files: PickedFile[], sessionId: string, agentId: string | null) => number;
  /** A file already in the workspace, referenced in place instead of uploaded. */
  addRef: (path: string, name: string) => void;
  remove: (id: string) => void;
  retry: (id: string, sessionId: string, agentId: string | null) => void;
  clear: () => void;
  /** Uploaded items in send form; the tray is emptied. */
  take: () => MessageAttachment[];
}

let seq = 0;
/** Picks are kept so a failed upload can be retried without picking again. */
const sources = new Map<string, PickedFile>();

const kindOf = (file: PickedFile): AttachmentKind =>
  isImageType(file.type) ? 'image' : file.type.startsWith('video/') ? 'video' : 'file';

export const useComposerStore = create<ComposerState>((set, get) => {
  const patch = (id: string, fn: (a: PendingAttachment) => PendingAttachment) =>
    set(s => ({items: s.items.map(a => (a.id === id ? fn(a) : a))}));

  const upload = (id: string, sessionId: string, agentId: string | null) => {
    const file = sources.get(id);
    if (!file) {
      return;
    }
    patch(id, a => ({...a, status: 'uploading', error: undefined}));
    uploadAttachment(file, sessionId, agentParam(agentId))
      .then(res => {
        patch(id, a => ({
          ...a,
          status: 'done',
          path: res.file_path,
          name: res.file_name || a.name,
          kind: res.file_type === 'image' ? 'image' : res.file_type === 'video' ? 'video' : a.kind,
        }));
      })
      .catch(e => {
        patch(id, a => ({...a, status: 'error', error: e instanceof Error ? e.message : String(e)}));
      });
  };

  return {
    items: [],

    add: (files, sessionId, agentId) => {
      const room = Math.max(0, MAX_ATTACHMENTS - get().items.length);
      const accepted = files.slice(0, room);
      const added = accepted.map(file => {
        const id = `att-${Date.now()}-${++seq}`;
        sources.set(id, file);
        return {
          id,
          name: file.name,
          kind: kindOf(file),
          localUri: file.uri,
          status: 'uploading' as const,
        };
      });
      set(s => ({items: [...s.items, ...added]}));
      added.forEach(a => upload(a.id, sessionId, agentId));
      return files.length - accepted.length;
    },

    addRef: (path, name) => {
      const {items} = get();
      if (items.length >= MAX_ATTACHMENTS || items.some(a => a.kind === 'workspace_ref' && a.path === path)) {
        return;
      }
      const ref: PendingAttachment = {
        id: `att-${Date.now()}-${++seq}`,
        name,
        kind: 'workspace_ref',
        localUri: '',
        status: 'done',
        path,
      };
      set(s => ({items: [...s.items, ref]}));
    },

    remove: id => {
      sources.delete(id);
      set(s => ({items: s.items.filter(a => a.id !== id)}));
    },

    retry: (id, sessionId, agentId) => upload(id, sessionId, agentId),

    clear: () => {
      sources.clear();
      set({items: []});
    },

    take: () => {
      const ready = get()
        .items.filter(a => a.status === 'done' && a.path)
        .map(a => ({
          name: a.name,
          path: a.path as string,
          kind: a.kind,
          previewUri: a.kind === 'image' ? a.localUri : undefined,
        }));
      get().clear();
      return ready;
    },
  };
});

resetOnSignOut(useComposerStore, state => state.clear());
