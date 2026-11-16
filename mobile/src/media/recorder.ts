import {PermissionsAndroid, Platform} from 'react-native';
import AudioRecorderPlayer, {
  AudioEncoderAndroidType,
  AudioSourceAndroidType,
  AVEncoderAudioQualityIOSType,
  AVEncodingOption,
  OutputFormatAndroidType,
  type AudioSet,
} from 'react-native-audio-recorder-player';
import type {Recording} from './types';

export type RecorderTick = (elapsedMs: number, level: number | null) => void;

const player = new AudioRecorderPlayer();

// Speech only: 16 kHz mono AAC keeps uploads small and is what ASR wants anyway.
const AUDIO_SET = {
  AudioSourceAndroid: AudioSourceAndroidType.MIC,
  OutputFormatAndroid: OutputFormatAndroidType.MPEG_4,
  AudioEncoderAndroid: AudioEncoderAndroidType.AAC,
  AudioSamplingRateAndroid: 16000,
  AudioChannelsAndroid: 1,
  AudioEncodingBitRateAndroid: 64000,
  AVFormatIDKeyIOS: AVEncodingOption.aac,
  AVSampleRateKeyIOS: 16000,
  AVNumberOfChannelsKeyIOS: 1,
  AVEncoderAudioQualityKeyIOS: AVEncoderAudioQualityIOSType.medium,
  AudioSourceHarmony: 1,
  AudioMimeHarmony: 'audio/mp4a-latm',
  AudioFileFormatHarmony: 'm4a',
  AudioEncodingBitRateHarmony: 64000,
  AudioSamplingRateHarmony: 16000,
  AudioChannelsHarmony: 1,
} as AudioSet;

const MIME: Record<string, string> = {m4a: 'audio/mp4', mp4: 'audio/mp4', aac: 'audio/aac'};

export class MicPermissionError extends Error {}

async function ensurePermission() {
  if (Platform.OS === 'android') {
    const res = await PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.RECORD_AUDIO);
    if (res !== PermissionsAndroid.RESULTS.GRANTED) {
      throw new MicPermissionError('没有麦克风权限');
    }
  } else if ((Platform.OS as string) === 'harmony') {
    // On HarmonyOS this resolves to the ohos build, which knows HARMONY permissions.
    const perms = require('react-native-permissions');
    const res = await perms.request(perms.PERMISSIONS.HARMONY.MICROPHONE);
    if (res !== perms.RESULTS.GRANTED) {
      throw new MicPermissionError('没有麦克风权限');
    }
  }
  // iOS prompts on its own the first time the recorder starts.
}

let startedAt = 0;

export async function startRecording(onTick: RecorderTick): Promise<void> {
  await ensurePermission();
  const target = (Platform.OS as string) === 'harmony' ? 'voice.m4a' : undefined;
  try {
    await player.startRecorder(target, AUDIO_SET, true);
  } catch (e) {
    throw Platform.OS === 'ios' ? new MicPermissionError('没有麦克风权限') : e;
  }
  startedAt = Date.now();
  await player.setSubscriptionDuration(0.08).catch(() => undefined);
  player.addRecordBackListener(e => {
    // Metering arrives in dBFS (about -60 quiet .. 0 loud); not every platform reports it.
    const db = e.currentMetering;
    const level = typeof db === 'number' ? Math.max(0, Math.min(1, (db + 60) / 60)) : null;
    onTick(e.currentPosition || Date.now() - startedAt, level);
  });
}

export async function stopRecording(): Promise<Recording | null> {
  player.removeRecordBackListener();
  const durationMs = Date.now() - startedAt;
  const raw = await player.stopRecorder().catch(() => '');
  if (!raw || /^Already/.test(raw)) {
    return null;
  }
  const uri = /^[a-z]+:\/\//i.test(raw) ? raw : `file://${raw}`;
  const ext = uri.split('?')[0].split('.').pop()?.toLowerCase() || 'm4a';
  return {uri, name: `recording.${ext}`, type: MIME[ext] ?? 'audio/mp4', durationMs};
}

export async function cancelRecording(): Promise<void> {
  player.removeRecordBackListener();
  await player.stopRecorder().catch(() => undefined);
}
