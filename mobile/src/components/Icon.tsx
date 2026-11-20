import type {IconDefinition} from '@fortawesome/fontawesome-svg-core';
import {FontAwesomeIcon} from '@fortawesome/react-native-fontawesome';
import React from 'react';

interface Props {
  icon: IconDefinition;
  size?: number;
  color?: string;
}

/** Font Awesome glyphs, the same set the web console uses. */
export function Icon({icon, size = 16, color}: Props) {
  return <FontAwesomeIcon icon={icon} size={size} color={color} />;
}
