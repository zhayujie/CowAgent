/// <reference lib="dom" />
import {tr} from '../i18n';
import type {PickedFile} from './types';

export type RecorderTick = (elapsedMs: number, level: number | null) => void;

export class MicPermissionError extends Error {}

interface Session {
  recorder: MediaRecorder;
  stream: MediaStream;
  chunks: Blob[];
  audio: AudioContext | null;
  timer: ReturnType<typeof setInterval>;
  startedAt: number;
}

let current: Session | null = null;

const PREFERRED = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'];

function teardown(s: Session) {
  clearInterval(s.timer);
  s.stream.getTracks().forEach(track => track.stop());
  s.audio?.close().catch(() => undefined);
}

export async function startRecording(onTick: RecorderTick): Promise<void> {
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
    throw new Error(tr('media_record_unsupported'));
  }
  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({audio: true});
  } catch {
    throw new MicPermissionError(tr('media_mic_denied'));
  }
  const mimeType = PREFERRED.find(m => MediaRecorder.isTypeSupported(m));
  const recorder = new MediaRecorder(stream, mimeType ? {mimeType} : undefined);
  const chunks: Blob[] = [];
  recorder.ondataavailable = e => e.data.size && chunks.push(e.data);

  let audio: AudioContext | null = null;
  let analyser: AnalyserNode | null = null;
  try {
    audio = new AudioContext();
    analyser = audio.createAnalyser();
    analyser.fftSize = 256;
    audio.createMediaStreamSource(stream).connect(analyser);
  } catch {
    audio = null;
    analyser = null;
  }
  const buf = analyser ? new Uint8Array(analyser.fftSize) : null;
  const startedAt = Date.now();
  const timer = setInterval(() => {
    let level: number | null = null;
    if (analyser && buf) {
      analyser.getByteTimeDomainData(buf);
      let peak = 0;
      for (const v of buf) {
        peak = Math.max(peak, Math.abs(v - 128));
      }
      level = Math.min(1, (peak / 128) * 2.2);
    }
    onTick(Date.now() - startedAt, level);
  }, 80);

  recorder.start();
  current = {recorder, stream, chunks, audio, timer, startedAt};
}

export async function stopRecording(): Promise<(PickedFile & {durationMs: number}) | null> {
  const s = current;
  current = null;
  if (!s) {
    return null;
  }
  const durationMs = Date.now() - s.startedAt;
  await new Promise<void>(resolve => {
    s.recorder.onstop = () => resolve();
    s.recorder.stop();
  });
  teardown(s);
  const type = s.recorder.mimeType || 'audio/webm';
  const blob = new Blob(s.chunks, {type});
  if (!blob.size) {
    return null;
  }
  const ext = type.includes('ogg') ? 'ogg' : type.includes('mp4') ? 'm4a' : 'webm';
  return {uri: URL.createObjectURL(blob), name: `recording.${ext}`, type, size: blob.size, blob, durationMs};
}

export async function cancelRecording(): Promise<void> {
  const s = current;
  current = null;
  if (!s) {
    return;
  }
  if (s.recorder.state !== 'inactive') {
    s.recorder.stop();
  }
  teardown(s);
}
