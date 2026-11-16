import {
  faCirclePlay,
  faFile,
  faFileLines,
  faImage,
  faWindowMaximize,
} from '@fortawesome/free-regular-svg-icons';
import type {IconDefinition} from '@fortawesome/fontawesome-svg-core';
import React from 'react';
import {Image, StyleSheet, View} from 'react-native';
import {serverUrl} from '../api/cowApi';
import {type ChatFile, fileFromPayload} from '../files/chatFile';
import {openFile} from '../files/openFile';
import type {Artifact} from '../protocol/events';
import type {Palette} from '../theme/palette';
import {useTheme} from '../theme/theme';
import {Icon} from './Icon';

export type KindGroup = keyof Palette['kind'];

export function kindGroup(kind: string | undefined): KindGroup {
  switch (kind) {
    case 'html':
      return 'web';
    case 'image':
      return 'image';
    case 'video':
    case 'audio':
      return 'media';
    case 'markdown':
    case 'pdf':
    case 'office':
    case 'text':
    case 'csv':
    case 'code':
      return 'doc';
    default:
      return 'other';
  }
}

export const KIND_ICON: Record<KindGroup, IconDefinition> = {
  web: faWindowMaximize,
  doc: faFileLines,
  image: faImage,
  media: faCirclePlay,
  other: faFile,
};

export const KIND_LABEL: Record<KindGroup, string> = {
  web: '网页',
  doc: '文档',
  image: '图片',
  media: '音视频',
  other: '文件',
};

export function artifactFile(a: Artifact): ChatFile | null {
  const file = fileFromPayload(a);
  return file && a.title ? {...file, name: a.title} : file;
}

export function openArtifact(a: Artifact) {
  const file = artifactFile(a);
  if (file) {
    openFile(file);
  }
}

/** Square tile: the image itself for pictures, a tinted glyph otherwise. */
export function KindTile({
  kind,
  previewUrl,
  size = 34,
}: {
  kind: string | undefined;
  previewUrl?: string;
  size?: number;
}) {
  const t = useTheme();
  const group = kindGroup(kind);
  const [bg, fg] = t.kind[group];
  const box = {width: size, height: size, borderRadius: Math.round(size * 0.26)};
  if (group === 'image' && previewUrl) {
    return <Image source={{uri: serverUrl(previewUrl)}} style={[box, {backgroundColor: bg}]} resizeMethod="resize" />;
  }
  return (
    <View style={[box, tileStyles.center, {backgroundColor: bg}]}>
      <Icon icon={KIND_ICON[group]} size={Math.round(size * 0.4)} color={fg} />
    </View>
  );
}

const tileStyles = StyleSheet.create({
  center: {alignItems: 'center', justifyContent: 'center'},
});
