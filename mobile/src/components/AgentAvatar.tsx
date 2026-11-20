import React from 'react';
import {Image, Text, View} from 'react-native';
import {agentAvatarUrl} from '../api/cowApi';
import logo from '../assets/logo-mark.png';
import type {AgentProfile} from '../protocol/resources';
import {makeStyles} from '../theme/theme';

const isImageUrl = (s: string) => /^(https?:|data:image\/)/i.test(s);
/** What the roster stores once a picture has been uploaded in place of an emoji. */
const UPLOADED = 'image';

/**
 * The default Agent wears the product logo; others show their uploaded picture,
 * their emoji avatar or the first letter of their name on a muted green tile.
 */
export function AgentAvatar({
  agent,
  isDefault,
  size = 26,
}: {
  agent?: Pick<AgentProfile, 'name' | 'avatar'> & Partial<Pick<AgentProfile, 'id' | 'avatar_rev'>>;
  isDefault?: boolean;
  size?: number;
}) {
  const styles = useStyles();
  const box = {width: size, height: size, borderRadius: Math.round(size * 0.3)};
  const avatar = agent?.avatar?.trim();
  if (isDefault && !avatar) {
    return <Image source={logo} style={{width: size, height: size}} />;
  }
  if (avatar === UPLOADED && agent?.id) {
    return (
      <Image
        source={{uri: agentAvatarUrl({id: agent.id, avatar_rev: agent.avatar_rev})}}
        style={[styles.image, box]}
        resizeMethod="resize"
      />
    );
  }
  if (avatar && isImageUrl(avatar)) {
    return <Image source={{uri: avatar}} style={[styles.image, box]} resizeMethod="resize" />;
  }
  const glyph = (avatar && avatar !== UPLOADED ? avatar : '') || (agent?.name ?? 'C').trim().slice(0, 1).toUpperCase();
  return (
    <View style={[styles.tile, box]}>
      <Text style={[styles.glyph, {fontSize: Math.round(size * 0.46)}]}>{glyph}</Text>
    </View>
  );
}

const useStyles = makeStyles(t => ({
  image: {backgroundColor: t.bg2},
  tile: {alignItems: 'center', justifyContent: 'center', backgroundColor: t.avatarBg},
  glyph: {color: t.avatarText, fontWeight: '600'},
}));
