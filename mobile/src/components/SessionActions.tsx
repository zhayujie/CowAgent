import {faPenToSquare, faTrashCan} from '@fortawesome/free-regular-svg-icons';
import {faThumbtack} from '@fortawesome/free-solid-svg-icons';
import type {IconDefinition} from '@fortawesome/fontawesome-svg-core';
import React, {useEffect, useState} from 'react';
import {Pressable, Text, TextInput, View} from 'react-native';
import {tr} from '../i18n';
import type {SessionItem} from '../protocol/events';
import {useSessionStore} from '../store/sessionStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
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
