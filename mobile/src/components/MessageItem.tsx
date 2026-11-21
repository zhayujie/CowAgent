import type {IconDefinition} from '@fortawesome/fontawesome-svg-core';
import {faCopy} from '@fortawesome/free-regular-svg-icons';
import {
  faChevronRight,
  faCheck,
  faCircleExclamation,
  faCircleNotch,
  faGear,
  faHourglassHalf,
  faLightbulb,
  faMinus,
  faShare,
  faStop,
  faXmark,
} from '@fortawesome/free-solid-svg-icons';
import React, {memo, useEffect, useState} from 'react';
import {ActivityIndicator, Image, Platform, Pressable, ScrollView, Text, View} from 'react-native';
import Animated, {
  cancelAnimation,
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withTiming,
} from 'react-native-reanimated';
import {tr, trf, type MessageKey} from '../i18n';
import {useAgentStore} from '../store/agentStore';
import type {
  AttachmentKind,
  ChatMessage,
  MessageAttachment,
  Speaker,
  Step,
  SubStep,
  ToolStatus,
  ToolStep,
} from '../store/chatStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {clockTime, formatCount, formatSeconds, kindFromName} from '../utils/format';
import {serverFileUrl} from '../api/cowApi';
import {type ChatFile, sameFile} from '../files/chatFile';
import {openFileRef, useImageViewer} from '../files/openFile';
import {copyText} from '../utils/clipboard';
import {AgentAvatar} from './AgentAvatar';
import {KindTile} from './ArtifactStrip';
import {Dots} from './Dots';
import {FileCard, FileSheet, InlineImage} from './FileViews';
import {Icon} from './Icon';
import {RowToggleContext, useAnchoredRow, useRowToggle} from './listAnchor';
import {Markdown} from './Markdown';
import {showToast} from './Toast';

const MONO = Platform.select({ios: 'Menlo', default: 'monospace'});
const ROW_PADDING = 14;
const AVATAR = 28;
const AVATAR_GAP = 10;
const BUBBLE_PADDING = 13;
const BUBBLE_RADIUS = 18;
/** Everything beside the text of a reply bubble, so its tables size to the bubble. */
const BUBBLE_INSET = ROW_PADDING * 2 + AVATAR + AVATAR_GAP + BUBBLE_PADDING * 2 + 2;
/** A finished reply with more steps than this folds the earlier ones away. */
const FOLD_AFTER = 6;
const FOLD_KEEP = 3;
const DETAIL_MAX_CHARS = 20000;

function MessageItemImpl({
  message,
  labelled,
  onOpenContext,
}: {
  message: ChatMessage;
  labelled?: boolean;
  /** Opens the conversation's context usage, from a reply's token count. */
  onOpenContext?: () => void;
}) {
  if (message.role === 'user') {
    return <UserTurn message={message} />;
  }
  return <AssistantTurn message={message} labelled={!!labelled || !!message.peer} onOpenContext={onOpenContext} />;
}

const copyMessage = (text: string) =>
  copyText(text).then(ok => ok && showToast(tr('common_copied')));

function CopyButton({text}: {text: string}) {
  const t = useTheme();
  const styles = useStyles();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={tr('common_copy')}
      hitSlop={10}
      onPress={() => copyMessage(text)}
      style={({pressed}) => [styles.copy, pressed && styles.pressed]}>
      <Icon icon={faCopy} size={11} color={t.t4} />
    </Pressable>
  );
}

export const MessageItem = memo(MessageItemImpl);

/** The server copy of a picture the user sent, which the viewer shows and the save options fetch. */
const sentImage = (a: MessageAttachment): ChatFile => ({name: a.name, kind: 'image', rawUrl: serverFileUrl(a.path)});

function UserTurn({message}: {message: ChatMessage}) {
  const t = useTheme();
  const styles = useStyles();
  // Kept after closing so the sheet still has its file while it slides away.
  const [actingOn, setActingOn] = useState<ChatFile | null>(null);
  const [acting, setActing] = useState(false);
  const files = message.attachments ?? [];
  const images = files.filter(a => a.kind === 'image' && a.previewUri);
  const others = files.filter(a => !(a.kind === 'image' && a.previewUri));
  const single = images.length === 1;

  return (
    <View style={styles.userRow}>
      {images.length > 0 && (
        <View style={styles.userImages}>
          {images.map((img, i) => (
            <Pressable
              key={`${img.path}-${i}`}
              accessibilityRole="imagebutton"
              accessibilityLabel={trf('chat_view_image', {name: img.name})}
              accessibilityHint={tr('file_long_press_hint')}
              onPress={() => useImageViewer.getState().show(sentImage(img))}
              onLongPress={() => {
                setActingOn(sentImage(img));
                setActing(true);
              }}
              delayLongPress={350}>
              {single ? (
                <FittedImage uri={img.previewUri as string} />
              ) : (
                <Image source={{uri: img.previewUri}} style={styles.userImage} resizeMethod="resize" />
              )}
            </Pressable>
          ))}
        </View>
      )}
      {others.map((f, i) => (
        <Pressable
          key={`${f.path}-${i}`}
          accessibilityRole="button"
          accessibilityLabel={trf('file_open_named', {path: f.name})}
          onPress={() => openFileRef(f.path)}
          style={({pressed}) => [styles.userFile, pressed && styles.userFilePressed]}>
          <KindTile
            kind={f.kind === 'directory' ? 'other' : f.kind === 'video' ? 'video' : kindFromName(f.name)}
            size={30}
          />
          <View style={styles.userFileText}>
            <Text style={styles.userFileName} numberOfLines={1} ellipsizeMode="middle">
              {f.name}
            </Text>
            <Text style={styles.userFileSub}>{tr(ATTACHMENT_LABEL[f.kind])}</Text>
          </View>
        </Pressable>
      ))}
      {message.transcribing ? (
        <View style={[styles.userBubble, styles.userBubbleWait]} accessibilityLabel={tr('chat_transcribing')}>
          <ActivityIndicator size="small" color={t.onAccent} />
        </View>
      ) : (
        !!message.content && (
          <View style={styles.userBubble}>
            <Text selectable style={styles.userText}>
              {message.content}
            </Text>
          </View>
        )
      )}
      {(!!message.createdAt || !!message.content) && !message.transcribing && (
        <View style={[styles.metaRow, styles.userMetaRow]}>
          {!!message.content && <CopyButton text={message.content} />}
          {!!message.createdAt && <Text style={styles.meta}>{clockTime(message.createdAt)}</Text>}
        </View>
      )}
      {actingOn && <FileSheet file={actingOn} visible={acting} onClose={() => setActing(false)} />}
    </View>
  );
}

const SINGLE_MAX_W = 200;
const SINGLE_MAX_H = 260;
const SINGLE_MIN_H = 80;

/** A lone picture keeps its own proportions, like a photo in a chat thread. */
function FittedImage({uri}: {uri: string}) {
  const styles = useStyles();
  const [ratio, setRatio] = useState(1);
  useEffect(() => {
    let alive = true;
    Image.getSize(
      uri,
      (w, h) => alive && w > 0 && h > 0 && setRatio(w / h),
      () => undefined,
    );
    return () => {
      alive = false;
    };
  }, [uri]);
  let width = SINGLE_MAX_W;
  let height = width / ratio;
  if (height > SINGLE_MAX_H) {
    height = SINGLE_MAX_H;
    width = Math.max(SINGLE_MIN_H, height * ratio);
  }
  height = Math.max(SINGLE_MIN_H, height);
  return <Image source={{uri}} style={[styles.userImageSingle, {width, height}]} resizeMethod="resize" />;
}

const ATTACHMENT_LABEL: Record<AttachmentKind, MessageKey> = {
  image: 'chat_attachment_image',
  video: 'chat_attachment_video',
  directory: 'chat_attachment_directory',
  file: 'chat_attachment_file',
  workspace_ref: 'chat_attachment_workspace_ref',
};

/** The Agent behind a reply; untagged replies belong to the conversation's own Agent. */
function useSpeaker(speaker?: Speaker) {
  const agents = useAgentStore(s => s.agents);
  const roster = useAgentStore(s => s.roster);
  const defaultId = useAgentStore(s => s.defaultId);
  const currentId = useAgentStore(s => s.currentId);
  const id = speaker?.id || currentId || '';
  const profile = agents.find(a => a.id === id) ?? roster.find(a => a.id === id);
  const name = profile?.name || speaker?.name || id || 'CowAgent';
  return {agent: profile ?? {id, name}, name, isDefault: !id || id === defaultId};
}

function AssistantTurn({
  message,
  labelled,
  onOpenContext,
}: {
  message: ChatMessage;
  labelled: boolean;
  onOpenContext?: () => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  const speaker = useSpeaker(message.speaker);
  const row = useAnchoredRow(!!message.streaming);
  const [showAll, setShowAll] = useState(false);
  const steps = message.steps ?? [];
  const foldable = !message.streaming && steps.length > FOLD_AFTER;
  const folded = foldable && !showAll;
  const shown = folded ? steps.slice(-FOLD_KEEP) : steps;
  const calls = steps.filter(s => s.kind === 'tool').length;
  const hiddenCalls = steps.slice(0, -FOLD_KEEP).filter(s => s.kind === 'tool').length;
  const files = message.files ?? [];
  // Folding hides how the reply got there, never what it delivered.
  const foldedFiles = folded
    ? steps
        .slice(0, -FOLD_KEEP)
        .filter((s): s is ToolStep => s.kind === 'tool' && !!s.file)
    : [];
  const last = steps[steps.length - 1];
  const liveThinking =
    !!message.streaming && !message.content && last?.kind === 'thinking' ? last.id : null;
  const waiting = !!message.streaming && !message.content && !steps.length;
  // A running tool spins and streamed text moves on its own. What looks finished is the
  // wait on the model between them, when nothing arrives, so the dots fill exactly that.
  const toolBusy = steps.some(s => s.kind === 'tool' && s.status === 'running');
  const progress = `${message.content.length}:${steps.length}:${last ? stepSize(last) : 0}`;
  const stalled = useStalled(!!message.streaming && !waiting && !toolBusy, progress);
  const working = stalled && !liveThinking;
  const hasAnswer =
    !!message.content || !!files.length || !!message.cancelled || !!message.runState || !!message.error;

  return (
    <RowToggleContext.Provider value={row.toggle}>
      <View style={styles.assistantRow} onLayout={row.onLayout}>
        <View style={styles.avatar}>
          <AgentAvatar agent={speaker.agent} isDefault={speaker.isDefault} size={AVATAR} />
        </View>
        <View style={styles.assistantColumn}>
          {labelled && (
            <Text style={styles.speakerName} numberOfLines={1}>
              {speaker.name}
            </Text>
          )}
          <View style={styles.bubble}>
            {steps.length > 0 && (
              <View style={[styles.process, hasAnswer && styles.processDivided]}>
                {foldable && (
                  <Pressable
                    accessibilityRole="button"
                    accessibilityState={{expanded: showAll}}
                    onPress={() => row.toggle(() => setShowAll(v => !v))}
                    hitSlop={6}
                    style={styles.fold}>
                    <Text style={styles.foldText} numberOfLines={1}>
                      {showAll
                        ? calls
                          ? trf('chat_calls_total', {n: calls})
                          : trf('chat_steps_total', {n: steps.length})
                        : hiddenCalls
                          ? trf('chat_calls_hidden', {n: hiddenCalls})
                          : trf('chat_steps_hidden', {n: steps.length - FOLD_KEEP})}
                    </Text>
                    <Text style={styles.foldAction}>{showAll ? tr('chat_steps_collapse') : tr('chat_steps_expand')}</Text>
                  </Pressable>
                )}
                {foldedFiles.map(step => (
                  <SentFile key={step.id} file={step.file!} carded={files} />
                ))}
                {shown.map(step => (
                  <StepRow key={step.id} step={step} live={step.id === liveThinking} carded={files} />
                ))}
              </View>
            )}

            {waiting && (
              <View style={styles.waiting}>
                <Dots />
              </View>
            )}

            {!!message.content && <Markdown value={message.content} inset={BUBBLE_INSET} />}

            {files.length > 0 && (
              <View style={[styles.files, !!message.content && styles.filesAfterText]}>
                {files.map(f =>
                  f.kind === 'image' ? (
                    <InlineImage key={f.path ?? f.rawUrl ?? f.name} file={f} />
                  ) : (
                    <FileCard key={f.path ?? f.rawUrl ?? f.name} file={f} />
                  ),
                )}
              </View>
            )}

            {working && (
              <View style={styles.working}>
                <Dots size={3} />
              </View>
            )}

            {message.cancelled && (
              <View style={styles.status}>
                <Icon icon={faStop} size={9} color={t.t3} />
                <Text style={styles.statusText}>{tr('chat_stopped')}</Text>
              </View>
            )}
            {!message.cancelled && message.runState && (
              <View style={styles.status}>
                <Icon
                  icon={message.runState === 'running' ? faHourglassHalf : faCircleExclamation}
                  size={9}
                  color={t.t3}
                />
                <Text style={styles.statusText}>
                  {tr(message.runState === 'running' ? 'chat_still_running' : 'chat_interrupted')}
                </Text>
              </View>
            )}
            {!!message.error && <Text style={styles.error}>{message.error}</Text>}
          </View>
          {!message.streaming && <MetaLine message={message} onOpenContext={onOpenContext} />}
        </View>
      </View>
    </RowToggleContext.Provider>
  );
}

/** How far a step has got, so any streamed addition to it changes the number. */
function stepSize(step: Step): number {
  if (step.kind === 'tool') {
    return (step.progress?.length ?? 0) + (step.substeps?.length ?? 0) + (step.status === 'running' ? 0 : 1);
  }
  return step.text.length;
}

const STALL_MS = 700;

/** True once `progress` has stood still for a moment while `active`. */
function useStalled(active: boolean, progress: string): boolean {
  const [stalled, setStalled] = useState(false);
  useEffect(() => {
    setStalled(false);
    if (!active) {
      return;
    }
    const timer = setTimeout(() => setStalled(true), STALL_MS);
    return () => clearTimeout(timer);
  }, [active, progress]);
  return stalled;
}

function StepRow({step, live, carded}: {step: Step; live: boolean; carded: ChatFile[]}) {
  const styles = useStyles();
  if (step.kind === 'text') {
    return (
      <View style={styles.note}>
        <Markdown value={step.text} compact inset={BUBBLE_INSET} />
      </View>
    );
  }
  if (step.kind === 'thinking') {
    return <Thinking text={step.text} seconds={step.seconds} live={live} />;
  }
  return (
    <>
      <ToolCard step={step} />
      {!!step.file && <SentFile file={step.file} carded={carded} />}
    </>
  );
}

/** What a `send` call delivered, under the call; a document already carded below stays there. */
function SentFile({file, carded}: {file: ChatFile; carded: ChatFile[]}) {
  const styles = useStyles();
  if (file.kind === 'image') {
    return (
      <View style={styles.sent}>
        <InlineImage file={file} />
      </View>
    );
  }
  if (carded.some(f => sameFile(f, file))) {
    return null;
  }
  return (
    <View style={styles.sent}>
      <FileCard file={file} />
    </View>
  );
}

function Chevron({open}: {open: boolean}) {
  const t = useTheme();
  const styles = useStyles();
  return (
    <View style={[styles.chevron, open && styles.chevronOpen]}>
      <Icon icon={faChevronRight} size={8} color={t.t4} />
    </View>
  );
}

// Amber, the same in both themes.
const BULB = '#FBBF24';

function Thinking({text, seconds, live}: {text: string; seconds?: number; live: boolean}) {
  const styles = useStyles();
  const toggle = useRowToggle();
  const [userOpen, setUserOpen] = useState(false);
  const open = live || userOpen;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{expanded: open}}
      disabled={live}
      onPress={() => toggle(() => setUserOpen(v => !v))}
      style={({pressed}) => [styles.thinking, pressed && styles.pressed]}>
      <View style={styles.stepHead}>
        <Icon icon={faLightbulb} size={11} color={BULB} />
        <Text style={styles.stepTitle}>{live ? tr('chat_thinking_live') : tr('chat_thinking_done')}</Text>
        {live ? (
          <Dots size={3} />
        ) : (
          !!seconds && <Text style={styles.stepTime}>{formatSeconds(seconds)}</Text>
        )}
        <View style={styles.flex} />
        {!live && <Chevron open={open} />}
      </View>
      <Text
        selectable={open}
        style={styles.thinkText}
        numberOfLines={open ? undefined : 2}>
        {text.trim()}
      </Text>
    </Pressable>
  );
}

/** A glyph turning in place, for a tool still at work. */
function Spinning({icon, size, color}: {icon: IconDefinition; size: number; color: string}) {
  const turn = useSharedValue(0);
  useEffect(() => {
    turn.value = withRepeat(withTiming(1, {duration: 1000, easing: Easing.linear}), -1);
    return () => cancelAnimation(turn);
  }, [turn]);
  const rotate = useAnimatedStyle(() => ({transform: [{rotate: `${turn.value * 360}deg`}]}), [turn]);
  return (
    <Animated.View style={rotate}>
      <Icon icon={icon} size={size} color={color} />
    </Animated.View>
  );
}

function StatusIcon({
  status,
  handoff,
  size,
  sub,
}: {
  status: ToolStatus;
  handoff?: boolean;
  size: number;
  sub?: boolean;
}) {
  const t = useTheme();
  if (status === 'running') {
    return <Spinning icon={sub ? faCircleNotch : faGear} size={size} color={sub ? t.t3 : t.accent} />;
  }
  if (status === 'stopped') {
    return <Icon icon={faMinus} size={size} color={t.t3} />;
  }
  if (status === 'error') {
    return <Icon icon={faXmark} size={size} color={t.danger} />;
  }
  return <Icon icon={handoff ? faShare : faCheck} size={size} color={sub ? t.t3 : t.accent} />;
}

function ToolCard({step}: {step: ToolStep}) {
  const styles = useStyles();
  const toggle = useRowToggle();
  const [userOpen, setUserOpen] = useState<boolean | null>(null);
  const running = step.status === 'running';
  // Output or sub steps arriving while it runs are worth watching.
  const open =
    userOpen ?? (running ? !!step.progress || !!step.substeps?.length : !!step.keepOpen);
  const failed = step.status === 'error';
  const label = step.handoff ? trf('chat_handoff_to', {name: step.handoff}) : step.name;
  const subCount = step.substeps?.length ?? 0;
  return (
    <View>
      <Pressable
        accessibilityRole="button"
        accessibilityState={{expanded: open}}
        accessibilityLabel={trf(open ? 'chat_tool_collapse_a11y' : 'chat_tool_expand_a11y', {label})}
        onPress={() => toggle(() => setUserOpen(!open))}
        hitSlop={{top: 4, bottom: 4}}
        style={({pressed}) => [styles.toolHead, pressed && styles.pressed]}>
        <View style={styles.toolIcon}>
          <StatusIcon status={step.status} handoff={!!step.handoff} size={10} />
        </View>
        <Text style={[styles.toolName, failed && styles.toolNameFailed]} numberOfLines={1}>
          {label}
          {!!step.seconds && <Text style={styles.toolTime}> {formatSeconds(step.seconds)}</Text>}
        </Text>
        {subCount > 0 && <Text style={styles.toolCount}>{subCount}</Text>}
        <View style={styles.flex} />
        <Chevron open={open} />
      </Pressable>
      {open && <ToolDetail step={step} />}
    </View>
  );
}

const asText = (value: string) => value.replace(/\r\n/g, '\n');

const prettyArgs = (args: Record<string, unknown> | undefined) => {
  if (!args || !Object.keys(args).length) {
    return '(none)';
  }
  try {
    return JSON.stringify(args, null, 2);
  } catch {
    return String(args);
  }
};

/** A JSON result laid out like the input above it; anything else as it came. */
function prettyResult(result: string): string {
  const text = asText(result);
  if (!/^\s*[[{]/.test(text)) {
    return text;
  }
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

const SUBSTEP_ARGS_CHARS = 90;

/** Tool arguments on one line, for a step in a list of dozens. */
function summarizeArgs(args: Record<string, unknown> | undefined): string {
  if (!args) {
    return '';
  }
  const joined = Object.entries(args)
    .map(([key, value]) => `${key}=${typeof value === 'object' ? JSON.stringify(value) : String(value)}`)
    .join(', ');
  return joined.length > SUBSTEP_ARGS_CHARS ? `${joined.slice(0, SUBSTEP_ARGS_CHARS)}…` : joined;
}

/** Output past the cap is cut, so one giant result can't stall the list. */
function Pre({text, error}: {text: string; error?: boolean}) {
  const styles = useStyles();
  const cut = text.length > DETAIL_MAX_CHARS;
  return (
    <ScrollView style={styles.preScroll} nestedScrollEnabled>
      <Text selectable style={[styles.pre, error && styles.preError]}>
        {cut ? `${text.slice(0, DETAIL_MAX_CHARS)}…` : text}
      </Text>
      {cut && (
        <Text style={styles.preNote}>{trf('chat_output_truncated', {max: DETAIL_MAX_CHARS, total: text.length})}</Text>
      )}
    </ScrollView>
  );
}

function ToolDetail({step}: {step: ToolStep}) {
  const styles = useStyles();
  const failed = step.status === 'error';
  const output = step.result ?? step.progress;
  // A settled tool with nothing to show drops the section, as the web console does.
  const showOutput = !!step.display || !!output || step.status === 'running';
  return (
    <View style={styles.toolDetail}>
      <View style={styles.section}>
        <Text style={styles.sectionLabel}>INPUT</Text>
        <Pre text={prettyArgs(step.args)} />
      </View>

      {!!step.substeps?.length && (
        <View style={styles.section}>
          <Text style={styles.sectionLabel}>STEPS</Text>
          <ScrollView style={styles.subScroll} nestedScrollEnabled>
            {step.substeps.map(sub => (
              <SubStepRow key={sub.id} sub={sub} />
            ))}
          </ScrollView>
        </View>
      )}

      {showOutput && (
        <View style={styles.section}>
          <Text style={styles.sectionLabel}>{failed ? 'ERROR' : 'OUTPUT'}</Text>
          {step.display ? (
            <ScrollView style={styles.display} nestedScrollEnabled>
              <Markdown value={step.display} compact inset={BUBBLE_INSET + 40} />
            </ScrollView>
          ) : output ? (
            <Pre text={step.result ? prettyResult(step.result) : asText(output)} error={failed} />
          ) : null}
        </View>
      )}
    </View>
  );
}

function SubStepRow({sub}: {sub: SubStep}) {
  const styles = useStyles();
  const failed = sub.status === 'error';
  return (
    <View style={styles.sub}>
      <View style={styles.subIcon}>
        <StatusIcon status={sub.status} size={9} sub />
      </View>
      <Text style={styles.subName}>{sub.name}</Text>
      <Text style={[styles.subArgs, failed && styles.subFailed]} numberOfLines={1}>
        {failed && sub.error ? sub.error : summarizeArgs(sub.args)}
      </Text>
      {!!sub.seconds && <Text style={styles.subTime}>{formatSeconds(sub.seconds)}</Text>}
    </View>
  );
}

function MetaLine({message, onOpenContext}: {message: ChatMessage; onOpenContext?: () => void}) {
  const styles = useStyles();
  const u = message.usage;
  const total = u ? u.total_tokens ?? (u.prompt_tokens ?? 0) + (u.completion_tokens ?? 0) : 0;
  const parts: string[] = [];
  if (message.createdAt) {
    parts.push(clockTime(message.createdAt));
  }
  if (u && total) {
    parts.push(`${formatCount(total)} tokens`);
    if (u.prompt_tokens && u.prompt_cache_hit_tokens) {
      parts.push(trf('chat_cache_hit', {pct: Math.round((u.prompt_cache_hit_tokens * 100) / u.prompt_tokens)}));
    }
  }
  if (!parts.length && !message.content) {
    return null;
  }
  const label = parts.length > 0 && <Text style={styles.meta}>{parts.join(' · ')}</Text>;
  return (
    <View style={styles.metaRow}>
      {label && total > 0 && onOpenContext ? (
        <Pressable
          accessibilityRole="button"
          accessibilityHint={tr('chat_usage_hint')}
          hitSlop={8}
          onPress={onOpenContext}
          style={({pressed}) => pressed && styles.pressed}>
          {label}
        </Pressable>
      ) : (
        label
      )}
      {!!message.content && <CopyButton text={message.content} />}
    </View>
  );
}

const useStyles = makeStyles(t => {
  const bubbleBg = t.isDark ? t.bg1 : t.bg0;
  return {
    flex: {flex: 1},
    pressed: {opacity: 0.6},
    userRow: {paddingHorizontal: ROW_PADDING, paddingTop: 18, alignItems: 'flex-end'},
    userBubble: {
      maxWidth: '80%',
      paddingHorizontal: 15,
      paddingVertical: 10,
      borderRadius: BUBBLE_RADIUS,
      backgroundColor: t.green,
    },
    userText: {fontSize: 15, lineHeight: 22.5, color: t.onAccent, letterSpacing: 0.1},
    userBubbleWait: {minWidth: 56, alignItems: 'center'},
    metaRow: {flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 6, marginLeft: 2},
    userMetaRow: {marginLeft: 0, marginRight: 2},
    copy: {paddingVertical: 2, paddingHorizontal: 2},
    userImages: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      justifyContent: 'flex-end',
      gap: 6,
      maxWidth: '80%',
      marginBottom: 6,
    },
    userImage: {width: 84, height: 84, borderRadius: radius.sm, backgroundColor: t.bg2},
    userImageSingle: {borderRadius: radius.md, backgroundColor: t.bg2},
    userFile: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 10,
      maxWidth: '80%',
      minWidth: 160,
      marginBottom: 6,
      paddingVertical: 8,
      paddingLeft: 8,
      paddingRight: 14,
      borderRadius: radius.md,
      backgroundColor: t.bg1,
      borderWidth: 1,
      borderColor: t.line1,
    },
    userFilePressed: {backgroundColor: t.bg2},
    userFileText: {flexShrink: 1, minWidth: 0},
    userFileName: {fontSize: 13, fontWeight: '500', color: t.t1},
    userFileSub: {fontSize: 11, color: t.t3, marginTop: 2},

    assistantRow: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: AVATAR_GAP,
      paddingHorizontal: ROW_PADDING,
      paddingTop: 16,
    },
    avatar: {paddingTop: 1},
    assistantColumn: {flex: 1, minWidth: 0},
    speakerName: {
      marginBottom: 4,
      marginLeft: 2,
      fontSize: 11.5,
      fontWeight: '500',
      color: t.t3,
    },
    bubble: {
      paddingHorizontal: BUBBLE_PADDING,
      paddingVertical: 11,
      borderRadius: BUBBLE_RADIUS,
      borderWidth: 1,
      borderColor: t.isDark ? t.line1 : t.line2,
      backgroundColor: bubbleBg,
    },
    process: {gap: 5},
    processDivided: {
      paddingBottom: 12,
      marginBottom: 10,
      borderBottomWidth: 1,
      borderBottomColor: t.line1,
    },
    fold: {flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 2},
    foldText: {flex: 1, fontSize: 12, color: t.t3},
    foldAction: {fontSize: 12, fontWeight: '500', color: t.accent},
    waiting: {paddingVertical: 6},
    working: {paddingTop: 8, paddingBottom: 2},
    note: {paddingHorizontal: 2},
    sent: {marginLeft: 18, marginTop: 2, marginBottom: 2},
    files: {gap: 8},
    filesAfterText: {marginTop: 10},

    stepHead: {flexDirection: 'row', alignItems: 'center', gap: 7, minHeight: 20},
    stepTitle: {fontSize: 12.5, fontWeight: '500', color: t.t2},
    stepTime: {fontSize: 11, color: t.t3, fontVariant: ['tabular-nums']},
    chevron: {width: 12, alignItems: 'center'},
    chevronOpen: {transform: [{rotate: '90deg'}]},
    thinking: {paddingHorizontal: 2, paddingVertical: 2},
    thinkText: {marginTop: 3, marginLeft: 18, fontSize: 12.5, lineHeight: 19.5, color: t.t3},

    toolHead: {flexDirection: 'row', alignItems: 'center', gap: 6, minHeight: 19},
    toolIcon: {width: 12, alignItems: 'center'},
    toolName: {flexShrink: 1, fontSize: 12, lineHeight: 17, color: t.t3},
    toolNameFailed: {color: t.danger},
    toolTime: {fontSize: 10.5, color: t.t4, fontVariant: ['tabular-nums']},
    toolCount: {fontSize: 10.5, color: t.t4},
    toolDetail: {
      gap: 6,
      marginTop: 6,
      marginLeft: 16,
      padding: 8,
      borderRadius: 6,
      borderWidth: 1,
      borderColor: t.isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)',
      backgroundColor: t.isDark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.02)',
    },
    section: {gap: 2},
    sectionLabel: {fontSize: 10, fontWeight: '600', letterSpacing: 0.5, color: t.t4},
    preScroll: {maxHeight: 200},
    pre: {fontFamily: MONO, fontSize: 11, lineHeight: 16.5, paddingVertical: 4, color: t.t3},
    preError: {color: t.danger},
    preNote: {fontSize: 10.5, color: t.t4, paddingBottom: 4},
    display: {
      maxHeight: 240,
      marginTop: 4,
      paddingHorizontal: 8,
      paddingVertical: 6,
      borderRadius: 4,
      backgroundColor: t.isDark ? '#111111' : '#f1f5f9',
    },
    subScroll: {maxHeight: 240, paddingVertical: 2},
    sub: {flexDirection: 'row', alignItems: 'center', gap: 6, minHeight: 18},
    subIcon: {width: 10, alignItems: 'center'},
    subName: {fontFamily: MONO, fontSize: 11, color: t.t3},
    subArgs: {flex: 1, minWidth: 0, fontSize: 11, color: t.t4},
    subFailed: {color: t.danger},
    subTime: {fontSize: 10.5, color: t.t4, fontVariant: ['tabular-nums']},

    status: {flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 6},
    statusText: {fontSize: 12, color: t.t3},
    error: {
      marginTop: 8,
      paddingHorizontal: 12,
      paddingVertical: 9,
      borderRadius: radius.sm,
      fontSize: 12.5,
      lineHeight: 18,
      color: t.danger,
      backgroundColor: t.dangerSoft,
      overflow: 'hidden',
    },
    meta: {
      fontSize: 11,
      color: t.t4,
      letterSpacing: 0.2,
      fontVariant: ['tabular-nums'],
    },
  };
});
