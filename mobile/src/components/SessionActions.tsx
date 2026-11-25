import {faPenToSquare, faTrashCan} from '@fortawesome/free-regular-svg-icons';
import {faArrowDown, faArrowUp, faPlus, faThumbtack} from '@fortawesome/free-solid-svg-icons';
import type {IconDefinition} from '@fortawesome/fontawesome-svg-core';
import React, {useEffect, useState} from 'react';
import {Pressable, Text, TextInput, View} from 'react-native';
import {tr} from '../i18n';
import type {SessionItem} from '../protocol/events';
import {useAgentStore} from '../store/agentStore';
import {useLayoutStore} from '../store/layoutStore';
import {useProjectStore} from '../store/projectStore';
import {useSessionStore} from '../store/sessionStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import type {SessionGroup, Space} from '../utils/sessionGroups';
import {Sheet} from './Sheet';
import {Icon} from './Icon';

/** Pin, rename and delete for one conversation, as a long press on it offers. */
export function SessionActions({
  session,
  onClose,
  onDeleted,
}: {
  session: SessionItem | null;
  onClose: () => void;
  onDeleted?: (session: SessionItem) => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  const [mode, setMode] = useState<'menu' | 'rename' | 'confirmDelete'>('menu');
  const [title, setTitle] = useState('');
  const [error, setError] = useState<string | null>(null);
  const store = useSessionStore.getState();

  useEffect(() => {
    if (session) {
      setMode('menu');
      setTitle(session.title ?? '');
      setError(null);
    }
  }, [session]);

  const run = async (fn: () => Promise<void>) => {
    try {
      await fn();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const remove = (s: SessionItem) =>
    run(async () => {
      await store.remove(s);
      onDeleted?.(s);
    });

  return (
    <Sheet visible={!!session} onClose={onClose} title={session?.title || tr('session_untitled')}>
      {mode === 'rename' ? (
        <View style={styles.renameBox}>
          <TextInput
            value={title}
            onChangeText={setTitle}
            autoFocus
            selectTextOnFocus
            maxLength={60}
            placeholder={tr('session_name_placeholder')}
            placeholderTextColor={t.t3}
            selectionColor={t.accent}
            style={styles.renameInput}
            returnKeyType="done"
            onSubmitEditing={() => session && title.trim() && run(() => store.rename(session, title.trim()))}
          />
          <Pressable
            accessibilityRole="button"
            disabled={!title.trim()}
            onPress={() => session && run(() => store.rename(session, title.trim()))}
            style={({pressed}) => [styles.renameSave, !title.trim() && styles.disabled, pressed && styles.renameSavePressed]}>
            <Text style={styles.renameSaveText}>{tr('common_save')}</Text>
          </Pressable>
        </View>
      ) : (
        <>
          <SessionAction
            icon={faThumbtack}
            label={session?.pinned ? tr('session_unpin') : tr('session_pin')}
            onPress={() => session && run(() => store.setPinned(session, !session.pinned))}
          />
          <SessionAction icon={faPenToSquare} label={tr('common_rename')} onPress={() => setMode('rename')} />
          <SessionAction
            icon={faTrashCan}
            label={mode === 'confirmDelete' ? tr('session_confirm_delete') : tr('common_delete')}
            danger
            onPress={() => (mode === 'confirmDelete' ? session && remove(session) : setMode('confirmDelete'))}
          />
        </>
      )}
      {!!error && <Text style={styles.error}>{error}</Text>}
    </Sheet>
  );
}

/** A long press on a workspace heading: start a chat there, rename, reorder or forget the project. */
export function SpaceActions({
  group,
  keys,
  onClose,
  onNewChat,
}: {
  group: SessionGroup | null;
  /** The spaces as listed, which a move reorders. */
  keys: string[];
  onClose: () => void;
  onNewChat: (space: Space) => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  const [mode, setMode] = useState<'menu' | 'rename' | 'confirmDelete'>('menu');
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const store = useSessionStore.getState();
  const space = group?.space;
  const path = space?.path ?? null;
  const at = group ? keys.indexOf(group.key) : -1;

  useEffect(() => {
    if (group) {
      setMode('menu');
      setName(group.title);
      setError(null);
    }
  }, [group]);

  const run = async (fn: () => Promise<void>) => {
    try {
      await fn();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  // The chat on screen may sit in the project just renamed or forgotten.
  const reloadChatProject = () => {
    const sessionId = useLayoutStore.getState().sessionId;
    if (sessionId) {
      useProjectStore.getState().load(sessionId, useAgentStore.getState().currentId).catch(() => undefined);
    }
  };

  const rename = () =>
    path &&
    name.trim() &&
    run(async () => {
      await store.renameSpace(path, name.trim());
      reloadChatProject();
    });

  const move = (delta: number) => group && run(() => store.moveSpace(group.key, delta, keys));

  return (
    <Sheet visible={!!group} onClose={onClose} title={group?.title}>
      {mode === 'rename' ? (
        <View style={styles.renameBox}>
          <TextInput
            value={name}
            onChangeText={setName}
            autoFocus
            selectTextOnFocus
            maxLength={60}
            placeholder={tr('composer_ws_new_placeholder')}
            placeholderTextColor={t.t3}
            selectionColor={t.accent}
            style={styles.renameInput}
            returnKeyType="done"
            onSubmitEditing={rename}
          />
          <Pressable
            accessibilityRole="button"
            disabled={!name.trim()}
            onPress={rename}
            style={({pressed}) => [styles.renameSave, !name.trim() && styles.disabled, pressed && styles.renameSavePressed]}>
            <Text style={styles.renameSaveText}>{tr('common_save')}</Text>
          </Pressable>
        </View>
      ) : (
        <>
          <SessionAction
            icon={faPlus}
            label={tr('space_new_chat')}
            onPress={() => {
              if (group && space) {
                if (useSessionStore.getState().collapsed.includes(group.key)) {
                  store.toggleCollapsed(group.key);
                }
                onClose();
                onNewChat(space);
              }
            }}
          />
          {!!path && <SessionAction icon={faPenToSquare} label={tr('space_rename')} onPress={() => setMode('rename')} />}
          {at > 0 && <SessionAction icon={faArrowUp} label={tr('space_move_up')} onPress={() => move(-1)} />}
          {at >= 0 && at < keys.length - 1 && (
            <SessionAction icon={faArrowDown} label={tr('space_move_down')} onPress={() => move(1)} />
          )}
          {!!path && (
            <SessionAction
              icon={faTrashCan}
              label={mode === 'confirmDelete' ? tr('space_confirm_delete') : tr('space_delete')}
              danger
              onPress={() =>
                mode === 'confirmDelete'
                  ? run(async () => {
                      await store.removeSpace(path);
                      reloadChatProject();
                    })
                  : setMode('confirmDelete')
              }
            />
          )}
          {mode === 'confirmDelete' && <Text style={styles.note}>{tr('space_delete_note')}</Text>}
        </>
      )}
      {!!error && <Text style={styles.error}>{error}</Text>}
    </Sheet>
  );
}

export function SessionAction({
  icon,
  label,
  danger,
  onPress,
}: {
  icon: IconDefinition;
  label: string;
  danger?: boolean;
  onPress: () => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      style={({pressed}) => [styles.action, pressed && styles.pressed]}>
      <View style={styles.actionIcon}>
        <Icon icon={icon} size={15} color={danger ? t.danger : t.t2} />
      </View>
      <Text style={[styles.actionText, danger && {color: t.danger}]}>{label}</Text>
    </Pressable>
  );
}

const useStyles = makeStyles(t => ({
  action: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 14,
    paddingHorizontal: 12,
    paddingVertical: 14,
    borderRadius: radius.md,
  },
  pressed: {backgroundColor: t.bg2},
  actionIcon: {width: 20, alignItems: 'center'},
  actionText: {fontSize: 16, color: t.t1},
  error: {fontSize: 13, color: t.danger, paddingHorizontal: 12, paddingTop: 8},
  note: {fontSize: 13, lineHeight: 19, color: t.t3, paddingHorizontal: 12, paddingBottom: 6},
  renameBox: {flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 6, paddingVertical: 6},
  renameInput: {
    flex: 1,
    height: 46,
    paddingHorizontal: 14,
    borderRadius: radius.md,
    backgroundColor: t.bg2,
    borderWidth: 1,
    borderColor: t.accentLine,
    fontSize: 15,
    color: t.t1,
  },
  renameSave: {
    height: 46,
    paddingHorizontal: 18,
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: t.green,
  },
  renameSavePressed: {backgroundColor: t.greenDeep},
  renameSaveText: {fontSize: 15, fontWeight: '600', color: t.onAccent},
  disabled: {opacity: 0.4},
}));
