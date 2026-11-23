import type {IconDefinition} from '@fortawesome/fontawesome-svg-core';
import {
  faBolt,
  faBookOpen,
  faBrain,
  faClock,
  faCloudArrowDown,
  faCodeBranch,
  faEye,
  faFileLines,
  faFilePen,
  faFolderOpen,
  faGlobe,
  faImage,
  faKey,
  faMagnifyingGlass,
  faPaperPlane,
  faPenToSquare,
  faPlug,
  faRotateLeft,
  faTerminal,
  faUsers,
  faWandMagicSparkles,
  faWrench,
} from '@fortawesome/free-solid-svg-icons';
import React, {useEffect, useState} from 'react';
import {Image, View} from 'react-native';
import {PHONE_TOOLS} from '../phone/catalog';
import type {Skill} from '../protocol/resources';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {Icon} from './Icon';

const TOOL_ICONS: Record<string, IconDefinition> = {
  bash: faTerminal,
  edit: faPenToSquare,
  read: faFileLines,
  write: faFilePen,
  ls: faFolderOpen,
  search_files: faMagnifyingGlass,
  send: faPaperPlane,
  web_search: faMagnifyingGlass,
  web_fetch: faCloudArrowDown,
  browser: faGlobe,
  vision: faEye,
  env_config: faKey,
  scheduler: faClock,
  current_time: faClock,
  memory_get: faBrain,
  memory_search: faBrain,
  agent_delegate: faUsers,
  subagent: faCodeBranch,
  evolution_undo: faRotateLeft,
};

export type Tone = 'web' | 'doc' | 'image' | 'media';

const BUILTIN: Record<string, {icon: IconDefinition; tone: Tone}> = {
  'skill-creator': {icon: faWandMagicSparkles, tone: 'image'},
  'knowledge-wiki': {icon: faBookOpen, tone: 'doc'},
  'image-generation': {icon: faImage, tone: 'web'},
};

export function Tile({icon, tone, size, off}: {icon: IconDefinition; tone: Tone | 'accent'; size: number; off?: boolean}) {
  const t = useTheme();
  const styles = useStyles();
  const [bg, fg] = off ? [t.bg2, t.t4] : tone === 'accent' ? [t.accentSoft, t.accent] : t.kind[tone];
  return (
    <View style={[styles.tile, {width: size, height: size, backgroundColor: bg}]}>
      <Icon icon={icon} size={Math.round(size * 0.4)} color={fg} />
    </View>
  );
}

export function SkillIcon({skill, size = 38}: {skill: Skill; size?: number}) {
  const styles = useStyles();
  const [broken, setBroken] = useState(false);
  useEffect(() => setBroken(false), [skill.icon]);
  if (skill.icon && !broken) {
    return (
      <Image
        source={{uri: skill.icon}}
        resizeMethod="resize"
        onError={() => setBroken(true)}
        style={[styles.image, {width: size, height: size}, !skill.enabled && styles.imageOff]}
      />
    );
  }
  const builtin = skill.ships_with_install ? BUILTIN[skill.name] : undefined;
  return (
    <Tile icon={builtin?.icon ?? faBolt} tone={builtin?.tone ?? 'accent'} size={size} off={!skill.enabled} />
  );
}

export function ToolIcon({name, size = 34}: {name: string; size?: number}) {
  return <Tile icon={TOOL_ICONS[name] ?? PHONE_TOOLS[name]?.icon ?? faWrench} tone="web" size={size} />;
}

export function McpIcon({off, size = 34}: {off?: boolean; size?: number}) {
  return <Tile icon={faPlug} tone="image" size={size} off={off} />;
}

const useStyles = makeStyles(t => ({
  tile: {borderRadius: radius.sm, alignItems: 'center', justifyContent: 'center'},
  image: {borderRadius: radius.sm, backgroundColor: t.bg2},
  imageOff: {opacity: 0.45},
}));
