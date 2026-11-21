import type {IconDefinition} from '@fortawesome/fontawesome-svg-core';
import {faEllipsis, faFloppyDisk, faPen, faRotateLeft} from '@fortawesome/free-solid-svg-icons';
import type {StackNavigationProp} from '@react-navigation/stack';
import React, {useCallback, useEffect, useRef, useState} from 'react';
import {ActivityIndicator, Pressable, ScrollView, Text, TextInput, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {ApiError} from '../api/http';
import {tr, trf} from '../i18n';
import type {RootStackParamList} from '../navigation/types';
import {describeConnectError} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {Icon} from './Icon';
import {Markdown} from './Markdown';
import {ConfirmSheet, MONO} from './settings';
import {showToast, ToastHost} from './Toast';
import {EmptyState, IconButton, PageHeader} from './ui';
import {AvoidKeyboard} from './AvoidKeyboard';

export interface LoadedDoc {
  content: string;
  /** The baseline a save is checked against; null saves unconditionally. */
  mtime: number | null;
  editable: boolean;
  /** Shown in place of the path when the page cannot be edited. */
  readonlyReason?: string;
}

export interface DocSource {
  load: () => Promise<LoadedDoc>;
  /** Resolves to the new baseline; a stale baseline must reject with a conflict (see `isConflict`). */
  save: (content: string, mtime: number | null) => Promise<number | null>;
}

/** The workspace route answers `code: "conflict"`, the knowledge route `payload.conflict`. */
export function isConflict(e: unknown): boolean {
  if (!(e instanceof ApiError) || !e.body) {
    return false;
  }
  const payload = e.body.payload as {conflict?: boolean} | null | undefined;
  return e.body.code === 'conflict' || !!payload?.conflict;
}

/** Icon-only take on the desktop client's document buttons: Edit, then Save beside Discard while editing. */
export function EditActions({
  editing,
  editable,
  saving,
  onEdit,
  onSave,
  onCancel,
}: {
  editing: boolean;
  editable: boolean;
  saving: boolean;
  onEdit: () => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  const styles = useStyles();
  if (!editing) {
    return editable ? <DocButton icon={faPen} label={tr('common_edit')} onPress={onEdit} /> : null;
  }
  return (
    <View style={styles.actions}>
      <DocButton primary icon={faFloppyDisk} label={tr('common_save')} busy={saving} onPress={onSave} />
      <DocButton icon={faRotateLeft} label={tr('ui_discard_changes')} disabled={saving} onPress={onCancel} />
    </View>
  );
}

function DocButton({
  icon,
  label,
  onPress,
  primary,
  busy,
  disabled,
}: {
  icon: IconDefinition;
  label: string;
  onPress: () => void;
  primary?: boolean;
  busy?: boolean;
  disabled?: boolean;
}) {
  const t = useTheme();
  const styles = useStyles();
  const color = primary ? t.onAccent : t.t2;
  const off = busy || disabled;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{disabled: off, busy}}
      disabled={off}
      hitSlop={4}
      onPress={onPress}
      style={({pressed}) => [
        styles.docButton,
        primary ? styles.docButtonPrimary : styles.docButtonQuiet,
        pressed && styles.docButtonPressed,
        off && styles.docButtonOff,
      ]}>
      {busy ? <ActivityIndicator size="small" color={color} /> : <Icon icon={icon} size={14} color={color} />}
    </Pressable>
  );
}

export function DocPage({
  navigation,
  title,
  meta,
  source,
  startEditing,
  onLink,
  onMore,
  onSaved,
  transform,
}: {
  navigation: StackNavigationProp<RootStackParamList>;
  title: string;
  /** The small line under the header, e.g. the file's path. */
  meta?: string;
  source: DocSource;
  startEditing?: boolean;
  onLink?: (href: string) => boolean;
  /** Shows a "more" button beside Edit, for actions the page itself owns. */
  onMore?: () => void;
  onSaved?: () => void;
  /** Applied to the text for reading only; the editor always shows it as stored. */
  transform?: (content: string) => string;
}) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const [doc, setDoc] = useState<LoadedDoc | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const [stale, setStale] = useState(false);
  const [leaving, setLeaving] = useState<(() => void) | null>(null);
  const dirty = editing && !!doc && draft !== doc.content;
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  const autoEdit = useRef(startEditing);

  const load = useCallback(async () => {
    try {
      const res = await source.load();
      setDoc(res);
      setError(null);
      setStale(false);
      if (autoEdit.current && res.editable) {
        autoEdit.current = false;
        setDraft(res.content);
        setEditing(true);
      }
    } catch (e) {
      setError(describeConnectError(e));
    }
  }, [source]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(
    () =>
      navigation.addListener('beforeRemove', e => {
        if (!dirtyRef.current) {
          return;
        }
        e.preventDefault();
        setLeaving(() => () => navigation.dispatch(e.data.action));
      }),
    [navigation],
  );

  const startEdit = () => {
    setDraft(doc?.content ?? '');
    setEditing(true);
  };

  const cancelEdit = () => {
    if (dirty) {
      setLeaving(() => () => setEditing(false));
    } else {
      setEditing(false);
    }
  };

  /** Picks up what was written elsewhere as the new baseline, leaving the draft as typed. */
  const resync = async () => {
    try {
      const res = await source.load();
      setDoc(res);
      setStale(false);
    } catch (e) {
      showToast(trf('ui_sync_failed', {error: describeConnectError(e)}));
    }
  };

  const save = async () => {
    if (!doc) {
      return;
    }
    if (draft === doc.content) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      const mtime = await source.save(draft, doc.mtime);
      setDoc({...doc, content: draft, mtime});
      setEditing(false);
      setStale(false);
      showToast(tr('common_saved'));
      onSaved?.();
    } catch (e) {
      if (isConflict(e)) {
        setStale(true);
      } else {
        showToast(trf('common_save_failed_detail', {error: describeConnectError(e)}));
      }
    } finally {
      setSaving(false);
    }
  };

  const headerAction =
    doc && !editing && onMore ? <IconButton icon={faEllipsis} label={tr('ui_more_actions')} onPress={onMore} /> : null;

  const metaLine = doc && !doc.editable && doc.readonlyReason ? doc.readonlyReason : meta;

  return (
    <View style={styles.root}>
      <PageHeader title={title} onBack={navigation.goBack} right={headerAction} />
      {(!!metaLine || !!doc?.editable) && (
        <View style={styles.toolbar}>
          <Text style={[styles.meta, !!doc && !doc.editable && styles.metaReadonly]} numberOfLines={1}>
            {metaLine}
          </Text>
          {!!doc && (
            <EditActions
              editing={editing}
              editable={doc.editable}
              saving={saving}
              onEdit={startEdit}
              onSave={save}
              onCancel={cancelEdit}
            />
          )}
        </View>
      )}
      {stale && (
        <Pressable onPress={resync} style={styles.stale}>
          <Text style={styles.staleText}>{tr('ui_doc_stale')}</Text>
        </Pressable>
      )}
      {!doc ? (
        <EmptyState loading={!error} title={tr('common_load_failed')} hint={error ?? undefined} />
      ) : editing ? (
        <AvoidKeyboard style={styles.flex}>
          <TextInput
            value={draft}
            onChangeText={setDraft}
            multiline
            autoFocus
            autoCapitalize="none"
            autoCorrect={false}
            textAlignVertical="top"
            selectionColor={t.accent}
            cursorColor={t.accent}
            placeholder={tr('ui_doc_placeholder')}
            placeholderTextColor={t.t4}
            style={[styles.editor, {paddingBottom: insets.bottom + 24}]}
          />
        </AvoidKeyboard>
      ) : (
        <ScrollView contentContainerStyle={[styles.body, {paddingBottom: insets.bottom + 32}]}>
          {doc.content.trim() ? (
            <Markdown value={transform ? transform(doc.content) : doc.content} onLink={onLink} />
          ) : (
            <EmptyState title={tr('ui_doc_empty')} hint={doc.editable ? tr('ui_doc_empty_hint') : undefined} />
          )}
        </ScrollView>
      )}
      <ConfirmSheet
        visible={!!leaving}
        title={tr('ui_discard_changes')}
        message={tr('ui_discard_message')}
        confirmLabel={tr('ui_discard')}
        danger
        onConfirm={() => {
          const go = leaving;
          setLeaving(null);
          setEditing(false);
          dirtyRef.current = false;
          go?.();
        }}
        onClose={() => setLeaving(null)}
      />
      <ToastHost bottom={insets.bottom + 28} />
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  flex: {flex: 1},
  toolbar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    minHeight: 44,
    paddingHorizontal: 18,
    paddingBottom: 8,
    borderBottomWidth: 1,
    borderBottomColor: t.line1,
  },
  meta: {flex: 1, fontFamily: MONO, fontSize: 12, color: t.t4},
  metaReadonly: {fontFamily: undefined, color: t.t3},
  actions: {flexDirection: 'row', alignItems: 'center', gap: 8},
  docButton: {
    alignItems: 'center',
    justifyContent: 'center',
    width: 34,
    height: 32,
    borderRadius: radius.sm,
  },
  docButtonPrimary: {backgroundColor: t.accent},
  docButtonQuiet: {borderWidth: 1, borderColor: t.line2},
  docButtonPressed: {opacity: 0.75},
  docButtonOff: {opacity: 0.5},
  stale: {
    marginHorizontal: 18,
    marginBottom: 10,
    padding: 12,
    borderRadius: 10,
    backgroundColor: t.dangerSoft,
  },
  staleText: {fontSize: 13, lineHeight: 19, color: t.danger},
  body: {paddingHorizontal: 18, paddingTop: 6, flexGrow: 1},
  editor: {
    flex: 1,
    paddingHorizontal: 18,
    paddingTop: 8,
    fontFamily: MONO,
    fontSize: 13,
    lineHeight: 21,
    color: t.t1,
  },
}));
