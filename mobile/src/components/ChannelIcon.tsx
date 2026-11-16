import type {IconDefinition} from '@fortawesome/fontawesome-svg-core';
import {
  faAt,
  faBuilding,
  faComment,
  faCommentDots,
  faHashtag,
  faHeadset,
  faMessage,
  faNewspaper,
  faPaperPlane,
  faPlug,
  faRobot,
} from '@fortawesome/free-solid-svg-icons';
import React from 'react';
import {Tile, type Tone} from './SkillIcon';

const CHANNEL_ICONS: Record<string, {icon: IconDefinition; tone: Tone}> = {
  weixin: {icon: faComment, tone: 'doc'},
  feishu: {icon: faPaperPlane, tone: 'web'},
  dingtalk: {icon: faMessage, tone: 'web'},
  wecom_bot: {icon: faRobot, tone: 'doc'},
  qq: {icon: faCommentDots, tone: 'web'},
  wechatcom_app: {icon: faBuilding, tone: 'doc'},
  wechat_kf: {icon: faHeadset, tone: 'doc'},
  wechatmp: {icon: faNewspaper, tone: 'doc'},
  telegram: {icon: faPaperPlane, tone: 'web'},
  slack: {icon: faHashtag, tone: 'media'},
  discord: {icon: faAt, tone: 'media'},
};

export function ChannelIcon({name, size = 38, off}: {name: string; size?: number; off?: boolean}) {
  const meta = CHANNEL_ICONS[name] ?? {icon: faPlug, tone: 'image' as Tone};
  return <Tile icon={meta.icon} tone={meta.tone} size={size} off={off} />;
}
