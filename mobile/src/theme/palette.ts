/**
 * Two lightness ladders sharing one brand green. Depth comes from the step
 * between surfaces (bg0 -> bg3) rather than from shadows, and text hierarchy
 * from opacity (t1 -> t4) rather than from extra hues.
 */
export interface Palette {
  isDark: boolean;
  /** Screen background. */
  bg0: string;
  /** Raised surfaces: drawer, trace pill, artifact strip. */
  bg1: string;
  /** Controls: input dock, agent pill, pressed rows. */
  bg2: string;
  /** Inactive controls such as a disabled send button. */
  bg3: string;
  /** Behind grouped cards, as on the settings page. */
  grouped: string;
  /** The cards on `grouped`. */
  card: string;
  line1: string;
  line2: string;
  t1: string;
  t2: string;
  t3: string;
  t4: string;
  green: string;
  greenDeep: string;
  /** Green used for text and icons; brighter on dark, deeper on light. */
  accent: string;
  /** Translucent green for selected rows and chips. */
  accentSoft: string;
  accentLine: string;
  onAccent: string;
  danger: string;
  dangerSoft: string;
  scrim: string;
  avatarBg: string;
  avatarText: string;
  codeBg: string;
  inlineCodeBg: string;
  inlineCodeText: string;
  /** Tints for artifact kinds: [background, foreground]. */
  kind: Record<'web' | 'doc' | 'image' | 'media' | 'other', [string, string]>;
}

export const dark: Palette = {
  isDark: true,
  bg0: '#0A0A0B',
  bg1: '#141416',
  bg2: '#1B1B1E',
  bg3: '#232327',
  grouped: '#0A0A0B',
  card: '#161618',
  line1: 'rgba(255,255,255,0.06)',
  line2: 'rgba(255,255,255,0.10)',
  t1: '#EDEDEF',
  t2: 'rgba(237,237,239,0.70)',
  t3: 'rgba(237,237,239,0.48)',
  t4: 'rgba(237,237,239,0.30)',
  green: '#35A85B',
  greenDeep: '#228547',
  accent: '#4BBE72',
  accentSoft: 'rgba(53,168,91,0.14)',
  accentLine: 'rgba(63,190,110,0.28)',
  onAccent: '#FFFFFF',
  danger: '#F2706B',
  dangerSoft: 'rgba(242,112,107,0.12)',
  scrim: 'rgba(0,0,0,0.52)',
  avatarBg: '#1E3A29',
  avatarText: '#9FE0B6',
  codeBg: '#141416',
  inlineCodeBg: 'rgba(53,168,91,0.16)',
  inlineCodeText: '#7DD69A',
  kind: {
    web: ['rgba(76,141,255,0.12)', '#82AEFF'],
    doc: ['rgba(53,168,91,0.13)', '#5CC97F'],
    image: ['rgba(243,152,0,0.13)', '#F0AC4E'],
    media: ['rgba(155,107,255,0.13)', '#A98CFF'],
    other: ['rgba(255,255,255,0.06)', 'rgba(237,237,239,0.70)'],
  },
};

export const light: Palette = {
  isDark: false,
  bg0: '#FFFFFF',
  bg1: '#F7F7F8',
  bg2: '#F1F1F3',
  bg3: '#E6E6E9',
  grouped: '#F2F2F5',
  card: '#FFFFFF',
  line1: 'rgba(15,15,20,0.06)',
  line2: 'rgba(15,15,20,0.10)',
  t1: '#17171A',
  t2: 'rgba(23,23,26,0.72)',
  t3: 'rgba(23,23,26,0.52)',
  t4: 'rgba(23,23,26,0.34)',
  green: '#35A85B',
  greenDeep: '#228547',
  accent: '#2B9650',
  accentSoft: 'rgba(53,168,91,0.10)',
  accentLine: 'rgba(53,168,91,0.30)',
  onAccent: '#FFFFFF',
  danger: '#D93F3A',
  dangerSoft: 'rgba(217,63,58,0.08)',
  scrim: 'rgba(15,15,20,0.32)',
  avatarBg: '#E3F5E9',
  avatarText: '#228547',
  codeBg: '#F5F6F8',
  inlineCodeBg: 'rgba(53,168,91,0.10)',
  inlineCodeText: '#1C6B3B',
  kind: {
    web: ['rgba(59,118,230,0.10)', '#2F6BD8'],
    doc: ['rgba(53,168,91,0.10)', '#228547'],
    image: ['rgba(230,140,0,0.12)', '#B9710A'],
    media: ['rgba(124,92,224,0.10)', '#6E4FD0'],
    other: ['rgba(15,15,20,0.05)', 'rgba(23,23,26,0.72)'],
  },
};

export const radius = {lg: 20, md: 14, sm: 10, xs: 8} as const;
