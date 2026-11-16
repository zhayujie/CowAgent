import React, {useMemo, useRef} from 'react';
import {PanResponder, StyleSheet, Text, View} from 'react-native';
import {create} from 'zustand';
import {tr, trf} from '../i18n';
import {cancelRecording, startRecording, stopRecording} from '../media/recorder';
import type {Recording} from '../media/types';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {formatClock} from '../utils/format';
import {showToast} from './Toast';

const MIN_MS = 700;
const MAX_MS = 60_000;
/** How far up the finger must slide before releasing cancels. */
const CANCEL_DY = 64;
const BARS = 22;

type Phase = 'idle' | 'recording';

interface VoiceState {
  phase: Phase;
  elapsed: number;
  /** Recent input levels, oldest first, each 0..1. */
  levels: number[];
  cancelArmed: boolean;
}

const QUIET = Array.from({length: BARS}, () => 0);
const IDLE: VoiceState = {phase: 'idle', elapsed: 0, levels: QUIET, cancelArmed: false};

const useVoiceStore = create<VoiceState>(() => IDLE);

let starting: Promise<boolean> | null = null;
let holding = false;
let armed = false;

function begin(onRecorded: (rec: Recording) => void) {
  if (useVoiceStore.getState().phase !== 'idle') {
    return;
  }
  holding = true;
  armed = false;
  useVoiceStore.setState({...IDLE, phase: 'recording'});
  starting = startRecording((elapsed, level) => {
    // Without metering, keep the bars breathing so the overlay never looks frozen.
    const next = level ?? 0.18 + Math.random() * 0.3;
    useVoiceStore.setState(s =>
      s.phase === 'recording' ? {elapsed, levels: [...s.levels.slice(1), next]} : s,
    );
    if (elapsed >= MAX_MS && holding) {
      finish(onRecorded);
    }
  }).then(
    () => true,
    e => {
      holding = false;
      useVoiceStore.setState(IDLE);
      showToast(e instanceof Error ? e.message : tr('voice_start_failed'));
      return false;
    },
  );
}

function move(dy: number) {
  const next = dy < -CANCEL_DY;
  if (holding && next !== armed) {
    armed = next;
    useVoiceStore.setState({cancelArmed: next});
  }
}

async function finish(onRecorded: (rec: Recording) => void, forceCancel = false) {
  if (!holding) {
    return;
  }
  holding = false;
  const ok = await starting;
  starting = null;
  if (!ok) {
    return;
  }
  if (armed || forceCancel) {
    await cancelRecording();
    useVoiceStore.setState(IDLE);
    return;
  }
  const rec = await stopRecording();
  useVoiceStore.setState(IDLE);
  if (!rec || rec.durationMs < MIN_MS) {
    showToast(tr('voice_too_short'));
    return;
  }
  onRecorded(rec);
}

/** "按住 说话" pad that replaces the text field in voice mode. */
export function HoldToTalk({disabled, onRecorded}: {disabled: boolean; onRecorded: (rec: Recording) => void}) {
  const styles = useStyles();
  const phase = useVoiceStore(s => s.phase);
  const cancelArmed = useVoiceStore(s => s.cancelArmed);
  const onRecordedRef = useRef(onRecorded);
  onRecordedRef.current = onRecorded;
  const disabledRef = useRef(disabled);
  disabledRef.current = disabled;

  const responder = useMemo(
    () =>
      PanResponder.create({
        onStartShouldSetPanResponder: () => !disabledRef.current,
        onMoveShouldSetPanResponder: () => false,
        // Keep the gesture while the finger slides up to cancel.
        onPanResponderTerminationRequest: () => false,
        onPanResponderGrant: () => begin(r => onRecordedRef.current(r)),
        onPanResponderMove: (_, g) => move(g.dy),
        onPanResponderRelease: () => {
          finish(r => onRecordedRef.current(r));
        },
        onPanResponderTerminate: () => {
          finish(r => onRecordedRef.current(r), true);
        },
      }),
    [],
  );

  const recording = phase === 'recording';
  let label = tr('voice_hold_to_talk');
  if (disabled && phase === 'idle') {
    label = tr('voice_wait_reply');
  } else if (recording) {
    label = cancelArmed ? tr('voice_release_cancel') : tr('voice_release_send');
  }

  return (
    <View
      {...responder.panHandlers}
      accessibilityRole="button"
      accessibilityLabel={tr('voice_pad_a11y')}
      style={[
        styles.pad,
        recording && styles.padActive,
        recording && cancelArmed && styles.padCancel,
      ]}>
      <Text
        selectable={false}
        style={[
          styles.padText,
          disabled && phase === 'idle' && styles.padTextMuted,
          recording && cancelArmed && styles.padTextCancel,
        ]}>
        {label}
      </Text>
    </View>
  );
}

/** Floating level meter shown while the finger is down. */
export function VoiceOverlay() {
  const t = useTheme();
  const styles = useStyles();
  const {phase, elapsed, levels, cancelArmed} = useVoiceStore();
  if (phase !== 'recording') {
    return null;
  }
  const left = Math.ceil((MAX_MS - elapsed) / 1000);
  return (
    <View pointerEvents="none" style={[StyleSheet.absoluteFill, styles.overlay]}>
      <View style={[styles.meter, cancelArmed && styles.meterCancel]}>
        <View style={styles.bars}>
          {levels.map((l, i) => (
            <View
              key={i}
              style={[styles.bar, {height: 4 + Math.round(l * 26)}, cancelArmed && styles.barCancel]}
            />
          ))}
        </View>
        <Text style={[styles.clock, cancelArmed && styles.clockCancel]}>
          {left <= 10 ? trf('voice_seconds_left', {n: left}) : formatClock(elapsed)}
        </Text>
      </View>
      <Text style={[styles.hint, cancelArmed && {color: t.danger}]}>
        {cancelArmed ? tr('voice_hint_cancel') : tr('voice_hint_send')}
      </Text>
    </View>
  );
}

const useStyles = makeStyles(t => ({
  pad: {
    height: 42,
    marginHorizontal: 10,
    marginTop: 10,
    marginBottom: 10,
    borderRadius: radius.sm,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: t.bg3,
  },
  padActive: {backgroundColor: t.accentSoft},
  padCancel: {backgroundColor: t.dangerSoft},
  padText: {fontSize: 15, fontWeight: '600', color: t.t1, letterSpacing: 1},
  padTextMuted: {fontSize: 14, fontWeight: '400', color: t.t3, letterSpacing: 0.4},
  padTextCancel: {color: t.danger},
  overlay: {
    alignItems: 'center',
    justifyContent: 'flex-end',
    paddingBottom: 150,
    backgroundColor: t.isDark ? 'rgba(0,0,0,0.42)' : 'rgba(15,15,20,0.16)',
  },
  meter: {
    width: 188,
    paddingTop: 18,
    paddingBottom: 12,
    borderRadius: radius.lg,
    alignItems: 'center',
    gap: 10,
    backgroundColor: t.green,
  },
  meterCancel: {backgroundColor: t.isDark ? '#3A2324' : '#FBE3E2'},
  bars: {flexDirection: 'row', alignItems: 'center', gap: 3, height: 30},
  bar: {width: 3, borderRadius: 2, backgroundColor: 'rgba(255,255,255,0.92)'},
  barCancel: {backgroundColor: t.danger},
  clock: {
    fontSize: 12,
    color: 'rgba(255,255,255,0.86)',
    fontVariant: ['tabular-nums'],
    letterSpacing: 0.4,
  },
  clockCancel: {color: t.danger},
  hint: {marginTop: 14, fontSize: 13, color: t.isDark ? 'rgba(255,255,255,0.78)' : t.t2},
}));
