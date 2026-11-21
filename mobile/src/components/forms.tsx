import {faCheck, faChevronRight, faEye, faEyeSlash, type IconDefinition} from '@fortawesome/free-solid-svg-icons';
import React, {useState, type ReactNode} from 'react';
import {
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
  type KeyboardTypeOptions,
  type StyleProp,
  type ViewStyle,
} from 'react-native';
import {tr, trf} from '../i18n';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {Icon} from './Icon';
import {MONO} from './settings';
import {Sheet} from './Sheet';

/** A titled card of rows; rows draw their own dividers via `first`. */
export function Section({
  title,
  action,
  footer,
  children,
  style,
}: {
  title?: string;
  action?: ReactNode;
  footer?: string;
  children: ReactNode;
  style?: StyleProp<ViewStyle>;
}) {
  const styles = useStyles();
  return (
    <View style={[styles.section, style]}>
      {(!!title || !!action) && (
        <View style={styles.sectionHead}>
          <Text style={styles.sectionTitle}>{title}</Text>
          {action}
        </View>
      )}
      <View style={styles.group}>{children}</View>
      {!!footer && <Text style={styles.footer}>{footer}</Text>}
    </View>
  );
}

/** A single-choice row: the check marks the current pick. */
export function OptionRow({
  title,
  hint,
  selected,
  first,
  mono,
  onPress,
}: {
  title: string;
  hint?: string;
  selected: boolean;
  first?: boolean;
  mono?: boolean;
  onPress: () => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  return (
    <Pressable
      accessibilityRole="radio"
      accessibilityState={{selected}}
      onPress={onPress}
      style={({pressed}) => [styles.row, !first && styles.divider, pressed && styles.pressed]}>
      <View style={styles.flex}>
        <Text style={[styles.rowTitle, mono && styles.mono, selected && styles.rowTitleOn]} numberOfLines={1}>
          {title}
        </Text>
        {!!hint && (
          <Text style={styles.rowHint} numberOfLines={2}>
            {hint}
          </Text>
        )}
      </View>
      <View style={styles.check}>{selected && <Icon icon={faCheck} size={13} color={t.accent} />}</View>
    </Pressable>
  );
}

/** Title on the left, value on the right; a chevron appears when it navigates. */
export function InfoRow({
  title,
  value,
  hint,
  icon,
  first,
  mono,
  danger,
  right,
  onPress,
  onLongPress,
}: {
  title: string;
  value?: string;
  hint?: string;
  icon?: IconDefinition;
  first?: boolean;
  mono?: boolean;
  danger?: boolean;
  right?: ReactNode;
  onPress?: () => void;
  onLongPress?: () => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  const body = (
    <>
      {!!icon && <Icon icon={icon} size={14} color={danger ? t.danger : t.t2} />}
      <View style={styles.infoText}>
        <Text style={[styles.rowTitle, danger && styles.danger]} numberOfLines={1}>
          {title}
        </Text>
        {!!hint && (
          <Text style={styles.rowHint} numberOfLines={2}>
            {hint}
          </Text>
        )}
      </View>
      {!!value && (
        <Text style={[styles.infoValue, mono && styles.monoSmall]} numberOfLines={1} selectable={!onPress}>
          {value}
        </Text>
      )}
      {right}
      {!!onPress && !right && <Icon icon={faChevronRight} size={10} color={t.t4} />}
    </>
  );
  if (!onPress && !onLongPress) {
    return <View style={[styles.row, !first && styles.divider]}>{body}</View>;
  }
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={value ? trf('settings_a11y_title_value', {title, value}) : title}
      onPress={onPress}
      onLongPress={onLongPress}
      style={({pressed}) => [styles.row, !first && styles.divider, pressed && styles.pressed]}>
      {body}
    </Pressable>
  );
}

/** A labelled text field living inside a Section. */
export function InputRow({
  label,
  value,
  onChangeText,
  placeholder,
  first,
  mono,
  secure,
  multiline,
  keyboardType,
  maxLength,
  autoFocus,
  right,
}: {
  label?: string;
  value: string;
  onChangeText: (value: string) => void;
  placeholder?: string;
  first?: boolean;
  mono?: boolean;
  secure?: boolean;
  multiline?: boolean;
  keyboardType?: KeyboardTypeOptions;
  maxLength?: number;
  autoFocus?: boolean;
  right?: ReactNode;
}) {
  const t = useTheme();
  const styles = useStyles();
  const [revealed, setRevealed] = useState(false);
  return (
    <View style={[styles.fieldRow, !label && styles.fieldRowBare, !first && styles.divider]}>
      {!!label && <Text style={styles.fieldLabel}>{label}</Text>}
      <View style={styles.inputLine}>
        <TextInput
          value={value}
          onChangeText={onChangeText}
          placeholder={placeholder}
          placeholderTextColor={t.t4}
          selectionColor={t.accent}
          cursorColor={t.accent}
          secureTextEntry={secure && !revealed}
          multiline={multiline}
          keyboardType={keyboardType}
          maxLength={maxLength}
          autoFocus={autoFocus}
          autoCapitalize="none"
          autoCorrect={false}
          spellCheck={false}
          accessibilityLabel={label ?? placeholder}
          style={[styles.input, mono && styles.mono, multiline && styles.inputMulti]}
        />
        {secure && (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={revealed ? tr('settings_hide') : tr('settings_show')}
            hitSlop={10}
            onPress={() => setRevealed(v => !v)}
            style={styles.eye}>
            <Icon icon={revealed ? faEyeSlash : faEye} size={14} color={t.t3} />
          </Pressable>
        )}
        {right}
      </View>
    </View>
  );
}

export interface PickerOption {
  value: string;
  label?: string;
  hint?: string;
  /** Rows sharing a group are listed under its label. */
  group?: string;
}

/** A scrollable single-choice list for options too long for a ChoiceSheet. */
export function PickerSheet({
  visible,
  title,
  options,
  selected,
  mono,
  onSelect,
  onClose,
}: {
  visible: boolean;
  title: string;
  options: PickerOption[];
  selected?: string;
  mono?: boolean;
  onSelect: (value: string) => void;
  onClose: () => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  return (
    <Sheet visible={visible} onClose={onClose} title={title}>
      <ScrollView style={styles.sheetScroll} keyboardShouldPersistTaps="handled">
        {options.map((o, i) => {
          const active = o.value === selected;
          const groupHead = !!o.group && o.group !== options[i - 1]?.group;
          return (
            <React.Fragment key={`${o.group ?? ''}/${o.value}`}>
              {groupHead && <Text style={styles.sheetGroup}>{o.group}</Text>}
              <Pressable
                accessibilityRole="radio"
                accessibilityState={{selected: active}}
                onPress={() => onSelect(o.value)}
                style={({pressed}) => [styles.sheetRow, pressed && styles.pressed]}>
                <View style={styles.flex}>
                  <Text style={[styles.sheetName, mono && styles.mono, active && styles.rowTitleOn]} numberOfLines={1}>
                    {o.label ?? o.value}
                  </Text>
                  {!!o.hint && (
                    <Text style={styles.rowHint} numberOfLines={2}>
                      {o.hint}
                    </Text>
                  )}
                </View>
                {active && <Icon icon={faCheck} size={13} color={t.accent} />}
              </Pressable>
            </React.Fragment>
          );
        })}
      </ScrollView>
    </Sheet>
  );
}

const useStyles = makeStyles(t => ({
  flex: {flex: 1, minWidth: 0},
  sheetScroll: {flexGrow: 0, flexShrink: 1},
  sheetGroup: {fontSize: 13, fontWeight: '600', color: t.t2, paddingHorizontal: 12, paddingTop: 14, paddingBottom: 4},
  sheetRow: {flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 12, paddingVertical: 11, borderRadius: radius.sm},
  sheetName: {fontSize: 15, color: t.t1},
  section: {marginTop: 22},
  sectionHead: {flexDirection: 'row', alignItems: 'center', paddingHorizontal: 18, marginBottom: 10, minHeight: 20},
  sectionTitle: {flex: 1, fontSize: 16, fontWeight: '600', letterSpacing: -0.2, color: t.t1},
  group: {
    marginHorizontal: 14,
    borderRadius: radius.md,
    backgroundColor: t.bg1,
    borderWidth: 1,
    borderColor: t.line1,
    overflow: 'hidden',
  },
  footer: {fontSize: 12, lineHeight: 18, color: t.t4, paddingHorizontal: 18, paddingTop: 10},
  divider: {borderTopWidth: 1, borderTopColor: t.line1},
  pressed: {backgroundColor: t.bg2},
  row: {flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: 50, paddingHorizontal: 14, paddingVertical: 12},
  rowTitle: {fontSize: 15, color: t.t1, letterSpacing: -0.1},
  rowTitleOn: {color: t.accent, fontWeight: '500'},
  rowHint: {fontSize: 12, lineHeight: 17, color: t.t3, marginTop: 3},
  check: {width: 16, alignItems: 'center'},
  infoText: {flexShrink: 1, minWidth: 0, flexGrow: 1},
  infoValue: {flexShrink: 1, maxWidth: '58%', fontSize: 14, color: t.t3, textAlign: 'right'},
  danger: {color: t.danger},
  mono: {fontFamily: MONO, fontSize: 13.5},
  monoSmall: {fontFamily: MONO, fontSize: 12.5},
  fieldRow: {paddingHorizontal: 14, paddingTop: 11, paddingBottom: 4},
  fieldRowBare: {paddingTop: 4},
  fieldLabel: {fontSize: 12, color: t.t3},
  inputLine: {flexDirection: 'row', alignItems: 'center', gap: 10},
  input: {flex: 1, minHeight: 38, paddingVertical: 8, paddingHorizontal: 0, fontSize: 15, color: t.t1},
  inputMulti: {minHeight: 96, maxHeight: 220, textAlignVertical: 'top'},
  eye: {paddingVertical: 8},
}));
