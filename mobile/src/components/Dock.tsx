import {faKeyboard} from '@fortawesome/free-regular-svg-icons';
import {
  faArrowUp,
  faMicrochip,
  faMicrophone,
  faPlus,
  faRotateRight,
  faShieldHalved,
  faStop,
  faXmark,
} from '@fortawesome/free-solid-svg-icons';
import React, {forwardRef, useImperativeHandle, useRef, useState} from 'react';
import {
  ActivityIndicator,
  Image,
  Keyboard,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from 'react-native';
import {tr, trf} from '../i18n';
import type {Recording} from '../media/types';
import type {PermissionMode} from '../protocol/resources';
import type {PendingAttachment} from '../store/composerStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {kindFromName} from '../utils/format';
import {KindTile} from './ArtifactStrip';
import {PERMISSION_META} from './ComposerSheets';
import {Icon} from './Icon';
import {HoldToTalk} from './VoiceInput';

const LINE_HEIGHT = 22;
const MIN_HEIGHT = LINE_HEIGHT;
const MAX_HEIGHT = LINE_HEIGHT * 6;

interface Props {
  text: string;
  onChangeText: (text: string) => void;
  placeholder: string;
  busy: boolean;
  /** Returning false keeps the typed text in the box. */
  onSend: (text: string) => boolean | void;
  onStop: () => void;
  onVoice: (rec: Recording) => void;
  /** A voice message is still being turned into text. */
  transcribing: boolean;
  attachments: PendingAttachment[];
  onRemoveAttachment: (id: string) => void;
  onRetryAttachment: (id: string) => void;
  onOpenAttach: () => void;
  model?: string;
  modelPinned: boolean;
  onOpenModel: () => void;
  permission?: PermissionMode;
  permissionPinned: boolean;
  onOpenPermission: () => void;
}

export const Dock = forwardRef<TextInput | null, Props>(function DockInner(
  {
    text,
    onChangeText,
    placeholder,
    busy,
    onSend,
    onStop,
    onVoice,
    transcribing,
    attachments,
    onRemoveAttachment,
    onRetryAttachment,
    onOpenAttach,
    model,
    modelPinned,
    onOpenModel,
    permission,
    permissionPinned,
    onOpenPermission,
  },
  ref,
) {
  const t = useTheme();
  const styles = useStyles();
  const input = useRef<TextInput>(null);
  useImperativeHandle(ref, () => input.current as TextInput);
  const [focused, setFocused] = useState(false);
  const [height, setHeight] = useState(MIN_HEIGHT);
  const [voiceMode, setVoiceMode] = useState(false);

  const uploading = attachments.some(a => a.status === 'uploading');
  const ready = attachments.some(a => a.status === 'done');
  const canSend = (text.trim().length > 0 || ready) && !uploading && !busy && !transcribing;

  const submit = () => {
    if (!canSend) {
      return;
    }
    if (onSend(text.trim()) === false) {
      return;
    }
    onChangeText('');
    setHeight(MIN_HEIGHT);
  };

  const toggleVoice = () => {
    if (voiceMode) {
      setVoiceMode(false);
      setTimeout(() => input.current?.focus(), 60);
    } else {
      Keyboard.dismiss();
      setVoiceMode(true);
    }
  };

  const perm = permission ? PERMISSION_META[permission] : undefined;

  return (
    <View style={styles.wrap}>
      <View style={[styles.card, focused && styles.cardFocused]}>
        {attachments.length > 0 && (
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            keyboardShouldPersistTaps="handled"
            contentContainerStyle={styles.tray}>
            {attachments.map(a => (
              <AttachmentChip
                key={a.id}
                item={a}
                onRemove={() => onRemoveAttachment(a.id)}
                onRetry={() => onRetryAttachment(a.id)}
              />
            ))}
          </ScrollView>
        )}

        {voiceMode ? (
          <HoldToTalk disabled={busy || transcribing} onRecorded={onVoice} />
        ) : (
          <TextInput
            ref={input}
            style={[styles.input, {height}]}
            value={text}
            onChangeText={onChangeText}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            onContentSizeChange={e =>
              setHeight(Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, e.nativeEvent.contentSize.height)))
            }
            placeholder={placeholder}
            placeholderTextColor={t.t3}
            selectionColor={t.accent}
            cursorColor={t.accent}
            multiline
          />
        )}

        <View style={styles.divider} />

        <View style={styles.toolbar}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={tr('composer_attach_a11y')}
            onPress={onOpenAttach}
            hitSlop={4}
            style={({pressed}) => [styles.tool, pressed && styles.toolPressed]}>
            <Icon icon={faPlus} size={15} color={t.t2} />
          </Pressable>

          <Pressable
            accessibilityRole="button"
            accessibilityLabel={trf('composer_model_a11y', {
              name: model === undefined ? tr('composer_loading') : model || tr('common_not_configured'),
            })}
            onPress={onOpenModel}
            hitSlop={4}
            style={({pressed}) => [styles.tool, modelPinned && styles.toolPinned, pressed && styles.toolPressed]}>
            <Icon icon={faMicrochip} size={15} color={modelPinned ? t.accent : t.t2} />
          </Pressable>

          <Pressable
            accessibilityRole="button"
            accessibilityLabel={trf('composer_permission_a11y', {name: perm?.name ?? tr('composer_loading')})}
            onPress={onOpenPermission}
            hitSlop={4}
            style={({pressed}) => [styles.tool, permissionPinned && styles.toolPinned, pressed && styles.toolPressed]}>
            <Icon icon={perm?.icon ?? faShieldHalved} size={15} color={permissionPinned ? t.accent : t.t2} />
          </Pressable>

          <View style={styles.spacer} />

          <Pressable
            accessibilityRole="button"
            accessibilityLabel={voiceMode ? tr('composer_to_keyboard') : tr('composer_to_voice')}
            onPress={toggleVoice}
            hitSlop={4}
            style={({pressed}) => [styles.tool, pressed && styles.toolPressed]}>
            <Icon icon={voiceMode ? faKeyboard : faMicrophone} size={15} color={t.t2} />
          </Pressable>

          {busy ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={tr('composer_stop')}
              onPress={onStop}
              hitSlop={6}
              style={({pressed}) => [styles.send, styles.stop, pressed && styles.stopPressed]}>
              <Icon icon={faStop} size={11} color={t.t1} />
            </Pressable>
          ) : (
            !voiceMode && (
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={uploading ? tr('composer_uploading_a11y') : tr('composer_send')}
                onPress={submit}
                disabled={!canSend}
                hitSlop={6}
                style={({pressed}) => [
                  styles.send,
                  !canSend && styles.sendOff,
                  pressed && styles.sendPressed,
                ]}>
                {uploading ? (
                  <ActivityIndicator size="small" color={t.t3} />
                ) : (
                  <Icon icon={faArrowUp} size={14} color={canSend ? t.onAccent : t.t3} />
                )}
              </Pressable>
            )
          )}
        </View>
      </View>
    </View>
  );
});

function AttachmentChip({
  item,
  onRemove,
  onRetry,
}: {
  item: PendingAttachment;
  onRemove: () => void;
  onRetry: () => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  const failed = item.status === 'error';
  const remove = (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={trf('composer_remove_attachment', {name: item.name})}
      onPress={onRemove}
      hitSlop={8}
      style={styles.remove}>
      <Icon icon={faXmark} size={9} color="#FFFFFF" />
    </Pressable>
  );

  if (item.kind === 'image') {
    return (
      <View style={styles.thumbWrap}>
        <Pressable
          disabled={!failed}
          onPress={onRetry}
          accessibilityLabel={failed ? tr('composer_upload_failed_retry') : item.name}>
          <Image source={{uri: item.localUri}} style={styles.thumb} resizeMethod="resize" />
          {item.status !== 'done' && (
            <View style={[styles.thumbVeil, failed && styles.thumbVeilError]}>
              {failed ? (
                <Icon icon={faRotateRight} size={14} color="#FFFFFF" />
              ) : (
                <ActivityIndicator size="small" color="#FFFFFF" />
              )}
            </View>
          )}
        </Pressable>
        {remove}
      </View>
    );
  }

  let sub = (item.name.split('.').pop() ?? '').toUpperCase() || tr('chat_attachment_file');
  if (item.status === 'uploading') {
    sub = tr('composer_uploading');
  } else if (failed) {
    sub = tr('composer_upload_failed_retry');
  }
  return (
    <View style={styles.thumbWrap}>
      <Pressable
        disabled={!failed}
        onPress={onRetry}
        style={[styles.file, failed && styles.fileError]}>
        <KindTile kind={item.kind === 'video' ? 'video' : kindFromName(item.name)} size={32} />
        <View style={styles.fileText}>
          <Text style={styles.fileName} numberOfLines={1} ellipsizeMode="middle">
            {item.name}
          </Text>
          <Text style={[styles.fileSub, failed && {color: t.danger}]} numberOfLines={1}>
            {sub}
          </Text>
        </View>
      </Pressable>
      {remove}
    </View>
  );
}

const useStyles = makeStyles(t => ({
  wrap: {paddingHorizontal: 12, paddingTop: 8, paddingBottom: 8, backgroundColor: t.bg0},
  card: {
    borderRadius: radius.lg - 2,
    backgroundColor: t.bg2,
    borderWidth: 1,
    borderColor: t.line2,
  },
  cardFocused: {borderColor: t.accentLine},
  tray: {gap: 8, paddingHorizontal: 10, paddingTop: 10},
  thumbWrap: {paddingTop: 6, paddingRight: 6},
  thumb: {width: 56, height: 56, borderRadius: radius.sm, backgroundColor: t.bg3},
  thumbVeil: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    borderRadius: radius.sm,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(0,0,0,0.38)',
  },
  thumbVeilError: {backgroundColor: 'rgba(200,40,40,0.55)'},
  remove: {
    position: 'absolute',
    top: 0,
    right: 0,
    width: 18,
    height: 18,
    borderRadius: 9,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: t.isDark ? '#4A4A50' : 'rgba(23,23,26,0.72)',
    borderWidth: 1.5,
    borderColor: t.bg2,
  },
  file: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 9,
    height: 56,
    width: 176,
    paddingLeft: 10,
    paddingRight: 12,
    borderRadius: radius.sm,
    backgroundColor: t.isDark ? t.bg1 : t.bg0,
    borderWidth: 1,
    borderColor: t.line1,
  },
  fileError: {borderColor: t.danger},
  fileText: {flex: 1, minWidth: 0},
  fileName: {fontSize: 13, fontWeight: '500', color: t.t1},
  fileSub: {fontSize: 11, color: t.t3, marginTop: 3, letterSpacing: 0.2},
  input: {
    marginHorizontal: 14,
    marginTop: 12,
    marginBottom: 8,
    padding: 0,
    fontSize: 15,
    lineHeight: LINE_HEIGHT,
    color: t.t1,
    textAlignVertical: 'top',
  },
  divider: {height: 1, marginHorizontal: 12, backgroundColor: t.line1},
  toolbar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 7,
    paddingVertical: 7,
  },
  tool: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
  toolPressed: {backgroundColor: t.bg3},
  toolPinned: {backgroundColor: t.accentSoft},
  spacer: {flex: 1},
  send: {
    width: 32,
    height: 32,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: t.green,
  },
  sendOff: {backgroundColor: t.bg3},
  sendPressed: {backgroundColor: t.greenDeep},
  stop: {backgroundColor: t.bg3},
  stopPressed: {backgroundColor: t.line2},
}));
