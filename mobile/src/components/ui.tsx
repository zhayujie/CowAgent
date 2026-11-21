import {faChevronDown, faChevronLeft} from '@fortawesome/free-solid-svg-icons';
import type {IconDefinition} from '@fortawesome/fontawesome-svg-core';
import React, {useState, type ReactNode} from 'react';
import {ActivityIndicator, Pressable, Text, View, type StyleProp, type ViewStyle} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {tr, trf} from '../i18n';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {Icon} from './Icon';

export function IconButton({
  icon,
  label,
  onPress,
  filled,
  size = 15,
  color,
  children,
}: {
  icon?: IconDefinition;
  label: string;
  onPress?: () => void;
  /** Quiet surface for the one button that leads the bar. */
  filled?: boolean;
  size?: number;
  color?: string;
  children?: ReactNode;
}) {
  const t = useTheme();
  const styles = useStyles();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={onPress}
      disabled={!onPress}
      hitSlop={6}
      style={({pressed}) => [
        styles.iconButton,
        filled && styles.iconButtonFilled,
        pressed && styles.iconButtonPressed,
      ]}>
      {children ?? (icon && <Icon icon={icon} size={size} color={color ?? t.t2} />)}
    </Pressable>
  );
}

/** Three hairlines, the shorter one in the middle. */
export function Burger() {
  const styles = useStyles();
  return (
    <View style={styles.burger}>
      <View style={styles.burgerLine} />
      <View style={[styles.burgerLine, styles.burgerShort]} />
      <View style={styles.burgerLine} />
    </View>
  );
}

const BACK_WIDTH = 36;

/** Back on the left, actions on the right, title centred on the screen whatever their widths. */
export function PageHeader({
  title,
  count,
  subtitle,
  onTitlePress,
  onBack,
  right,
  background,
}: {
  title: string;
  count?: number | string;
  /** A second line under the title, e.g. whose data the page shows. */
  subtitle?: string;
  /** Makes the title block a button, with a chevron hinting at the choice behind it. */
  onTitlePress?: () => void;
  onBack: () => void;
  right?: ReactNode;
  /** Matches a page whose background isn't the default, such as a grouped one. */
  background?: string;
}) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const [rightWidth, setRightWidth] = useState(0);
  const inset = Math.max(BACK_WIDTH, rightWidth) + 8;
  const titleBlock = (
    <>
      <Text style={styles.pageTitle} numberOfLines={1}>
        {title}
        {!!count && <Text style={styles.pageCount}> {count}</Text>}
      </Text>
      {!!subtitle && (
        <View style={styles.pageSubRow}>
          <Text style={styles.pageSubtitle} numberOfLines={1}>
            {subtitle}
          </Text>
          {!!onTitlePress && <Icon icon={faChevronDown} size={8} color={t.t3} />}
        </View>
      )}
    </>
  );
  return (
    <View style={[styles.pageHeader, {paddingTop: insets.top + 6}, !!background && {backgroundColor: background}]}>
      <IconButton icon={faChevronLeft} label={tr('common_back')} onPress={onBack} filled size={13} color={t.t1} />
      <View style={[styles.pageTitleWrap, {top: insets.top + 6, left: 14 + inset, right: 14 + inset}]} pointerEvents="box-none">
        {onTitlePress ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={subtitle ? trf('ui_title_switch_a11y', {title, subtitle}) : title}
            hitSlop={6}
            onPress={onTitlePress}
            style={({pressed}) => [styles.pageTitleButton, pressed && styles.pageTitlePressed]}>
            {titleBlock}
          </Pressable>
        ) : (
          <View style={styles.pageTitleButton} pointerEvents="none">
            {titleBlock}
          </View>
        )}
      </View>
      <View onLayout={e => setRightWidth(e.nativeEvent.layout.width)}>{right}</View>
    </View>
  );
}

/**
 * A section title on a page. `small` is for groups within one list, such as
 * dates or vendors in a sheet, trailed by a hairline.
 */
export function GroupLabel({
  children,
  style,
  small,
  action,
}: {
  children: string;
  style?: StyleProp<ViewStyle>;
  small?: boolean;
  /** A control at the right end, e.g. to edit the group. */
  action?: ReactNode;
}) {
  const styles = useStyles();
  return (
    <View style={[styles.group, style]}>
      <Text style={[small ? styles.groupTextSmall : styles.groupText, !!action && styles.groupTextFill]} numberOfLines={1}>
        {children}
      </Text>
      {small && <View style={styles.groupLine} />}
      {action}
    </View>
  );
}

export function EmptyState({
  title,
  hint,
  loading,
  icon,
}: {
  title: string;
  hint?: string;
  loading?: boolean;
  icon?: IconDefinition;
}) {
  const t = useTheme();
  const styles = useStyles();
  if (loading) {
    return (
      <View style={styles.empty}>
        <ActivityIndicator color={t.t3} />
      </View>
    );
  }
  return (
    <View style={styles.empty}>
      {icon && (
        <View style={styles.emptyIcon}>
          <Icon icon={icon} size={22} color={t.t3} />
        </View>
      )}
      <Text style={styles.emptyTitle}>{title}</Text>
      {!!hint && <Text style={styles.emptyHint}>{hint}</Text>}
    </View>
  );
}

export function Chip({
  label,
  active,
  onPress,
}: {
  label: string;
  active?: boolean;
  onPress: () => void;
}) {
  const styles = useStyles();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{selected: active}}
      onPress={onPress}
      style={({pressed}) => [styles.chip, active && styles.chipActive, pressed && !active && styles.chipPressed]}>
      <Text style={[styles.chipText, active && styles.chipTextActive]}>{label}</Text>
    </Pressable>
  );
}

export function Segmented<K extends string>({
  options,
  value,
  onChange,
}: {
  options: {key: K; label: string; count?: number; icon?: IconDefinition}[];
  value: K;
  onChange: (key: K) => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  return (
    <View style={styles.segment}>
      {options.map(o => {
        const active = value === o.key;
        return (
          <Pressable
            key={o.key}
            accessibilityRole="tab"
            accessibilityState={{selected: active}}
            onPress={() => onChange(o.key)}
            style={[styles.segmentItem, active && styles.segmentItemActive]}>
            {o.icon && <Icon icon={o.icon} size={12} color={active ? t.t1 : t.t3} />}
            <Text style={[styles.segmentText, active && styles.segmentTextActive]}>
              {o.label}
              {active && o.count ? <Text style={styles.segmentCount}> {o.count}</Text> : null}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const useStyles = makeStyles(t => ({
  segment: {
    flexDirection: 'row',
    marginHorizontal: 14,
    marginTop: 6,
    marginBottom: 6,
    padding: 3,
    borderRadius: radius.sm + 1,
    backgroundColor: t.bg2,
  },
  segmentItem: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    paddingVertical: 7,
    borderRadius: radius.xs,
  },
  segmentItemActive: {
    backgroundColor: t.isDark ? t.bg3 : t.bg0,
    borderWidth: t.isDark ? 0 : 1,
    borderColor: t.line1,
  },
  segmentText: {fontSize: 14, color: t.t3},
  segmentTextActive: {color: t.t1, fontWeight: '600'},
  segmentCount: {color: t.t3, fontWeight: '400', fontVariant: ['tabular-nums']},
  iconButton: {
    width: 36,
    height: 36,
    borderRadius: radius.sm,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: 'transparent',
  },
  iconButtonFilled: {backgroundColor: t.bg2, borderColor: t.line1},
  iconButtonPressed: {backgroundColor: t.bg3},
  burger: {gap: 4, alignItems: 'flex-start', width: 17},
  burgerLine: {width: 17, height: 1.5, borderRadius: 1, backgroundColor: t.t2},
  burgerShort: {width: 12},
  pageHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
    paddingHorizontal: 14,
    paddingBottom: 8,
    backgroundColor: t.bg0,
  },
  pageTitleWrap: {position: 'absolute', bottom: 8, alignItems: 'center', justifyContent: 'center'},
  pageTitleButton: {alignItems: 'center', maxWidth: '100%', paddingHorizontal: 8, borderRadius: radius.sm},
  pageTitlePressed: {backgroundColor: t.bg2},
  pageTitle: {fontSize: 17, lineHeight: 21, fontWeight: '600', letterSpacing: -0.3, color: t.t1, textAlign: 'center'},
  pageCount: {fontSize: 13, fontWeight: '400', color: t.t3, fontVariant: ['tabular-nums']},
  pageSubRow: {flexDirection: 'row', alignItems: 'center', gap: 4, maxWidth: '100%'},
  pageSubtitle: {fontSize: 12, lineHeight: 15, color: t.t3, flexShrink: 1},
  group: {flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 18, marginBottom: 10},
  groupText: {fontSize: 16, fontWeight: '600', letterSpacing: -0.2, color: t.t1},
  groupTextSmall: {fontSize: 13, fontWeight: '600', color: t.t2},
  groupTextFill: {flex: 1},
  groupLine: {flex: 1, height: 1, backgroundColor: t.line1},
  empty: {flex: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 40, paddingVertical: 80},
  emptyIcon: {
    width: 52,
    height: 52,
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: t.bg2,
    marginBottom: 14,
  },
  emptyTitle: {fontSize: 15, color: t.t2, fontWeight: '500'},
  emptyHint: {fontSize: 13, lineHeight: 20, color: t.t3, marginTop: 8, textAlign: 'center'},
  chip: {
    paddingHorizontal: 13,
    paddingVertical: 6,
    borderRadius: 999,
    backgroundColor: t.bg1,
    borderWidth: 1,
    borderColor: t.line1,
  },
  chipActive: {backgroundColor: t.accentSoft, borderColor: t.accentLine},
  chipPressed: {backgroundColor: t.bg2},
  chipText: {fontSize: 13, color: t.t2},
  chipTextActive: {color: t.accent, fontWeight: '600'},
}));
