import {faFolder, faKeyboard} from '@fortawesome/free-regular-svg-icons';
import {
  faArrowUp,
  faMicrochip,
  faMicrophone,
  faPaperclip,
  faRotateRight,
  faShieldHalved,
  faStop,
  faXmark,
} from '@fortawesome/free-solid-svg-icons';
import React, {forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState} from 'react';
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
import type {AgentBadge, PermissionMode, WorkspaceHit} from '../protocol/resources';
import type {PendingAttachment} from '../store/composerStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {matchMention, matchSlash} from '../utils/composerCommands';
import {kindFromName} from '../utils/format';
import {AgentAvatar} from './AgentAvatar';
import {KindTile} from './ArtifactStrip';
import {PERMISSION_META} from './ComposerSheets';
import {Icon} from './Icon';
import {HoldToTalk} from './VoiceInput';

const LINE_HEIGHT = 24;
const MIN_HEIGHT = LINE_HEIGHT * 2;
const MAX_HEIGHT = LINE_HEIGHT * 6;
const MENTION_AGENTS = 6;
const SEARCH_DELAY_MS = 150;

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
  onOpenModel: () => void;
  permission?: PermissionMode;
  onOpenPermission: () => void;
  /** Who `@` can address; empty outside a shared conversation. */
  roster: AgentBadge[];
  defaultAgentId: string | null;
  searchFiles: (query: string) => Promise<WorkspaceHit[]>;
  onPickFile: (hit: WorkspaceHit) => void;
}

type Suggestion =
  | {kind: 'command'; key: string; cmd: string; value: string; desc: string}
  | {kind: 'agent'; key: string; agent: AgentBadge}
  | {kind: 'file'; key: string; hit: WorkspaceHit};

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
    onOpenModel,
    permission,
    onOpenPermission,
    roster,
    defaultAgentId,
    searchFiles,
    onPickFile,
  },
  ref,
) {
  const t = useTheme();
  const styles = useStyles();
  const input = useRef<TextInput>(null);
  useImperativeHandle(ref, () => input.current as TextInput);
  const [height, setHeight] = useState(MIN_HEIGHT);
  const [voiceMode, setVoiceMode] = useState(false);
  const [cursor, setCursor] = useState(0);
  // Text the menu was closed for; it stays closed until the text changes.
  const [dismissedFor, setDismissedFor] = useState<string | null>(null);
  const [files, setFiles] = useState<{query: string; hits: WorkspaceHit[]} | null>(null);

  const uploading = attachments.some(a => a.status === 'uploading');
  const ready = attachments.some(a => a.status === 'done');
  const hasContent = text.trim().length > 0 || ready || uploading;
  const canSend = (text.trim().length > 0 || ready) && !uploading && !busy && !transcribing;

  const commands = useMemo(() => matchSlash(text), [text]);
  const mention = useMemo(
    () => (commands.length ? null : matchMention(text, Math.min(cursor, text.length))),
    [commands.length, text, cursor],
  );
  const mentionQuery = mention?.query ?? null;

  useEffect(() => {
    if (mentionQuery === null) {
      setFiles(null);
      return;
    }
    let live = true;
    const timer = setTimeout(() => {
      searchFiles(mentionQuery).then(
        hits => live && setFiles({query: mentionQuery, hits}),
        () => live && setFiles({query: mentionQuery, hits: []}),
      );
    }, SEARCH_DELAY_MS);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [mentionQuery, searchFiles]);

  const suggestions = useMemo((): Suggestion[] => {
    if (voiceMode || text === dismissedFor) {
      return [];
    }
    if (commands.length) {
      return commands.map(c => ({kind: 'command', key: c.cmd, cmd: c.cmd.trim(), value: c.cmd, desc: tr(c.desc)}));
    }
    if (mentionQuery === null) {
      return [];
    }
    const q = mentionQuery.toLowerCase();
    const agents: Suggestion[] = roster
      .filter(a => !q || a.id.toLowerCase().includes(q) || a.name.toLowerCase().includes(q))
      .slice(0, MENTION_AGENTS)
      .map(a => ({kind: 'agent', key: `agent:${a.id}`, agent: a}));
    const hits: Suggestion[] = (files?.hits ?? []).map(h => ({kind: 'file', key: `file:${h.path}`, hit: h}));
    return [...agents, ...hits];
  }, [voiceMode, text, dismissedFor, commands, mentionQuery, roster, files]);
  const searching = mentionQuery !== null && files?.query !== mentionQuery;

  const accept = (s: Suggestion) => {
    if (s.kind === 'command') {
      setDismissedFor(s.value);
      onChangeText(s.value);
    } else if (mention) {
      const before = text.slice(0, mention.start);
      const after = text.slice(Math.min(cursor, text.length));
      let next: string;
      if (s.kind === 'agent') {
        next = `${before}@${s.agent.name || s.agent.id} ${after}`;
      } else {
        // The file travels as an attachment, not as text.
        onPickFile(s.hit);
        next = before + after;
      }
      setDismissedFor(next);
      onChangeText(next);
    }
    input.current?.focus();
  };

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
  const modelName = model === undefined ? tr('composer_loading') : model || tr('common_not_configured');
  const showMenu = suggestions.length > 0 || (mentionQuery !== null && !voiceMode && text !== dismissedFor);

  return (
    <View style={styles.wrap}>
      {showMenu && (
        <View style={styles.menu}>
          {suggestions.length === 0 ? (
            <Text style={styles.menuEmpty}>
              {searching ? tr('composer_mention_searching') : tr('composer_mention_empty')}
            </Text>
          ) : (
            <ScrollView keyboardShouldPersistTaps="always" bounces={false} style={styles.menuScroll}>
              {suggestions.map((s, i) => {
                const head =
                  s.kind === 'command'
                    ? i === 0 && tr('composer_slash_title')
                    : s.kind === 'agent'
                      ? i === 0 && tr('composer_mention_agents')
                      : suggestions[i - 1]?.kind !== 'file' && tr('composer_mention_files');
                return (
                  <React.Fragment key={s.key}>
                    {!!head && <Text style={styles.menuHead}>{head}</Text>}
                    <SuggestionRow item={s} defaultAgentId={defaultAgentId} onPress={() => accept(s)} />
                  </React.Fragment>
                );
              })}
            </ScrollView>
          )}
        </View>
      )}

      <View style={styles.card}>
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
          // A voice message takes only the attachments already uploaded.
          <HoldToTalk disabled={busy || transcribing || uploading} onRecorded={onVoice} />
        ) : (
          <TextInput
            ref={input}
            style={[styles.input, {height}]}
            value={text}
            onChangeText={next => {
              setDismissedFor(null);
              onChangeText(next);
            }}
            onSelectionChange={e => setCursor(e.nativeEvent.selection.end)}
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

        <View style={styles.toolbar}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={tr('composer_attach_a11y')}
            onPress={onOpenAttach}
            hitSlop={4}
            style={({pressed}) => [styles.tool, pressed && styles.toolPressed]}>
            <Icon icon={faPaperclip} size={18} color={t.t2} />
          </Pressable>

          <Pressable
            accessibilityRole="button"
            accessibilityLabel={trf('composer_model_a11y', {name: modelName})}
            onPress={onOpenModel}
            hitSlop={4}
            style={({pressed}) => [styles.tool, pressed && styles.toolPressed]}>
            <Icon icon={faMicrochip} size={17} color={t.t2} />
          </Pressable>

          <Pressable
            accessibilityRole="button"
            accessibilityLabel={trf('composer_permission_a11y', {name: perm?.name ?? tr('composer_loading')})}
            onPress={onOpenPermission}
            hitSlop={4}
            style={({pressed}) => [styles.tool, pressed && styles.toolPressed]}>
            <Icon icon={perm?.icon ?? faShieldHalved} size={16} color={t.t2} />
          </Pressable>

          <View style={styles.spacer} />

          {busy ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={tr('composer_stop')}
              onPress={onStop}
              hitSlop={6}
              style={({pressed}) => [styles.send, styles.stop, pressed && styles.pressed]}>
              <Icon icon={faStop} size={10} color={t.onAccent} />
            </Pressable>
          ) : (
            <>
              {/* Attachments alone still leave the choice of saying what to do with them. */}
              {(voiceMode || !text.trim()) && (
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel={voiceMode ? tr('composer_to_keyboard') : tr('composer_to_voice')}
                  onPress={toggleVoice}
                  hitSlop={4}
                  style={({pressed}) => [styles.tool, pressed && styles.toolPressed]}>
                  <Icon icon={voiceMode ? faKeyboard : faMicrophone} size={18} color={t.t2} />
                </Pressable>
              )}
              {!voiceMode && hasContent && (
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel={uploading ? tr('composer_uploading_a11y') : tr('composer_send')}
                  onPress={submit}
                  disabled={!canSend}
                  hitSlop={6}
                  style={({pressed}) => [styles.send, !canSend && styles.sendOff, pressed && styles.pressed]}>
                  {uploading ? (
                    <ActivityIndicator size="small" color={t.t3} />
                  ) : (
                    <Icon icon={faArrowUp} size={16} color={canSend ? t.onAccent : t.t3} />
                  )}
                </Pressable>
              )}
            </>
          )}
        </View>
      </View>
    </View>
  );
});

function SuggestionRow({
  item,
  defaultAgentId,
  onPress,
}: {
  item: Suggestion;
  defaultAgentId: string | null;
  onPress: () => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  let lead: React.ReactNode;
  let title: string;
  let sub: string;
  if (item.kind === 'command') {
    lead = null;
    title = item.cmd;
    sub = item.desc;
  } else if (item.kind === 'agent') {
    lead = <AgentAvatar agent={item.agent} isDefault={item.agent.id === defaultAgentId} size={26} />;
    title = item.agent.name || item.agent.id;
    sub = item.agent.id;
  } else {
    lead = item.hit.is_dir ? (
      <View style={styles.folder}>
        <Icon icon={faFolder} size={14} color={t.t2} />
      </View>
    ) : (
      <KindTile kind={kindFromName(item.hit.name)} size={26} />
    );
    title = item.hit.name;
    sub = item.hit.path;
  }
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      style={({pressed}) => [styles.menuRow, pressed && styles.menuRowPressed]}>
      {lead}
      <View style={styles.menuText}>
        <Text style={[styles.menuTitle, item.kind === 'command' && styles.menuCmd]} numberOfLines={1}>
          {title}
        </Text>
        <Text style={styles.menuSub} numberOfLines={1} ellipsizeMode={item.kind === 'file' ? 'middle' : 'tail'}>
          {sub}
        </Text>
      </View>
    </Pressable>
  );
}

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

  const ref = item.kind === 'workspace_ref';
  let sub = ref
    ? tr('composer_ref_sub')
    : (item.name.split('.').pop() ?? '').toUpperCase() || tr('chat_attachment_file');
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

const useStyles = makeStyles(t => {
  const surface = t.isDark ? t.bg2 : t.card;
  return {
    wrap: {paddingHorizontal: 12, paddingTop: 6, paddingBottom: 6, backgroundColor: t.bg0},
    card: {
      borderRadius: 26,
      backgroundColor: surface,
      borderWidth: 1,
      borderColor: t.line2,
      shadowColor: '#000',
      shadowOpacity: t.isDark ? 0 : 0.05,
      shadowRadius: 10,
      shadowOffset: {width: 0, height: 2},
      elevation: t.isDark ? 0 : 2,
    },
    menu: {
      marginBottom: 8,
      paddingVertical: 6,
      borderRadius: radius.lg,
      backgroundColor: surface,
      borderWidth: 1,
      borderColor: t.line2,
      shadowColor: '#000',
      shadowOpacity: t.isDark ? 0 : 0.08,
      shadowRadius: 16,
      shadowOffset: {width: 0, height: 4},
      elevation: t.isDark ? 0 : 4,
    },
    menuScroll: {maxHeight: 264},
    menuHead: {
      fontSize: 11,
      fontWeight: '600',
      letterSpacing: 0.6,
      color: t.t4,
      paddingHorizontal: 16,
      paddingTop: 8,
      paddingBottom: 4,
    },
    menuEmpty: {fontSize: 13, color: t.t3, paddingHorizontal: 16, paddingVertical: 12},
    menuRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 12,
      marginHorizontal: 6,
      paddingHorizontal: 10,
      paddingVertical: 9,
      borderRadius: radius.sm,
    },
    menuRowPressed: {backgroundColor: t.bg2},
    menuText: {flex: 1, minWidth: 0},
    menuTitle: {fontSize: 15, fontWeight: '500', color: t.t1},
    menuCmd: {letterSpacing: 0.2},
    menuSub: {fontSize: 12, color: t.t3, marginTop: 2},
    folder: {
      width: 26,
      height: 26,
      borderRadius: 8,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: t.bg2,
    },
    tray: {gap: 8, paddingHorizontal: 12, paddingTop: 12},
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
      borderColor: surface,
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
      backgroundColor: t.bg1,
      borderWidth: 1,
      borderColor: t.line1,
    },
    fileError: {borderColor: t.danger},
    fileText: {flex: 1, minWidth: 0},
    fileName: {fontSize: 13, fontWeight: '500', color: t.t1},
    fileSub: {fontSize: 11, color: t.t3, marginTop: 3, letterSpacing: 0.2},
    input: {
      marginHorizontal: 18,
      marginTop: 14,
      marginBottom: 2,
      padding: 0,
      fontSize: 16,
      lineHeight: LINE_HEIGHT,
      color: t.t1,
      textAlignVertical: 'top',
    },
    toolbar: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 2,
      paddingHorizontal: 8,
      paddingTop: 4,
      paddingBottom: 8,
    },
    tool: {
      width: 40,
      height: 40,
      borderRadius: 20,
      alignItems: 'center',
      justifyContent: 'center',
    },
    toolPressed: {backgroundColor: t.bg2},
    spacer: {flex: 1},
    send: {
      width: 38,
      height: 38,
      borderRadius: 19,
      marginRight: 1,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: t.green,
    },
    sendOff: {backgroundColor: t.bg3},
    stop: {backgroundColor: t.t4},
    pressed: {opacity: 0.8},
  };
});
