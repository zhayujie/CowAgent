import {faCheck, faChevronRight} from '@fortawesome/free-solid-svg-icons';
import type {IconDefinition} from '@fortawesome/fontawesome-svg-core';
import React, {createContext, useContext, useEffect, useState, type ReactNode} from 'react';
import {
  ActivityIndicator,
  Platform,
  Pressable,
  ScrollView,
  Switch,
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
import {Sheet} from './Sheet';

export const MONO = Platform.select({
  ios: 'Menlo',
  android: 'monospace',
  web: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
  default: undefined,
});

const InCard = createContext(false);

/** A rounded surface holding related rows. */
export function SettingCard({children, style}: {children: ReactNode; style?: StyleProp<ViewStyle>}) {
  const styles = useStyles();
  return (
    <View style={[styles.card, style]}>
      <InCard.Provider value>{children}</InCard.Provider>
    </View>
  );
}

/** One line of a settings list: title, optional detail below, value and chevron on the right. */
export function SettingRow({
  icon,
  title,
  detail,
  fullDetail,
  value,
  onPress,
  onLongPress,
  chevron = !!onPress,
  right,
  action,
  mono,
  dim,
  last,
}: {
  icon?: IconDefinition;
  title: string;
  detail?: string;
  /** Show the whole detail instead of cutting it at two lines. */
  fullDetail?: boolean;
  value?: string;
  onPress?: () => void;
  onLongPress?: () => void;
  chevron?: boolean;
  /** Non-interactive content such as a tag; a tap on it counts as a tap on the row. */
  right?: ReactNode;
  /** A control with its own press handler, kept outside the row's button. */
  action?: ReactNode;
  mono?: boolean;
  dim?: boolean;
  last?: boolean;
}) {
  const t = useTheme();
  const styles = useStyles();
  const inCard = useContext(InCard);
  const head = (
    <>
      {icon && (
        <View style={styles.rowIcon}>
          <Icon icon={icon} size={14} color={t.t2} />
        </View>
      )}
      <View style={styles.rowText}>
        <Text style={[styles.rowTitle, dim && styles.dim, mono && !value && styles.mono]} numberOfLines={1}>
          {title}
        </Text>
        {!!detail && (
          <Text style={styles.rowDetail} numberOfLines={fullDetail ? undefined : 2}>
            {detail}
          </Text>
        )}
      </View>
      {!!value && (
        <Text style={[styles.rowValue, mono && styles.monoValue]} numberOfLines={1}>
          {value}
        </Text>
      )}
      {right}
    </>
  );
  const arrow = <Icon icon={faChevronRight} size={10} color={t.t4} />;
  if (!onPress && !onLongPress) {
    return (
      <View style={[styles.row, inCard && styles.rowInCard, last && styles.rowLast]}>
        {head}
        {action}
        {chevron && arrow}
      </View>
    );
  }
  const a11yLabel = value ? trf('settings_a11y_title_value', {title, value}) : title;
  // On the web a button inside a button is invalid HTML, so an action splits the row into sibling buttons.
  if (action) {
    return (
      <View style={[styles.row, inCard && styles.rowInCard, styles.rowSplit, last && styles.rowLast]}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={a11yLabel}
          onPress={onPress}
          onLongPress={onLongPress}
          style={({pressed}) => [styles.rowMain, pressed && styles.rowPressed]}>
          {head}
        </Pressable>
        {action}
        {chevron && (
          <Pressable
            accessible={false}
            importantForAccessibility="no"
            onPress={onPress}
            onLongPress={onLongPress}
            style={({pressed}) => [styles.rowArrow, pressed && styles.rowPressed]}>
            {arrow}
          </Pressable>
        )}
      </View>
    );
  }
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={a11yLabel}
      onPress={onPress}
      onLongPress={onLongPress}
      style={({pressed}) => [styles.row, inCard && styles.rowInCard, last && styles.rowLast, pressed && styles.rowPressed]}>
      {head}
      {chevron && arrow}
    </Pressable>
  );
}

// react-native-web paints the "on" thumb teal unless given its web-only activeThumbColor.
const WEB_THUMB = Platform.OS === 'web' ? ({activeThumbColor: '#FFFFFF'} as object) : {};

export function Toggle({
  value,
  onValueChange,
  disabled,
  label,
}: {
  value: boolean;
  onValueChange: (value: boolean) => void;
  disabled?: boolean;
  label?: string;
}) {
  const t = useTheme();
  return (
    <Switch
      value={value}
      onValueChange={onValueChange}
      disabled={disabled}
      accessibilityLabel={label}
      trackColor={{false: t.bg3, true: t.green}}
      thumbColor="#FFFFFF"
      ios_backgroundColor={t.bg3}
      {...WEB_THUMB}
    />
  );
}

export function SwitchRow({
  icon,
  title,
  detail,
  fullDetail,
  value,
  onValueChange,
  disabled,
  last,
}: {
  icon?: IconDefinition;
  title: string;
  detail?: string;
  fullDetail?: boolean;
  value: boolean;
  onValueChange: (value: boolean) => void;
  disabled?: boolean;
  last?: boolean;
}) {
  return (
    <SettingRow
      icon={icon}
      title={title}
      detail={detail}
      fullDetail={fullDetail}
      dim={disabled}
      last={last}
      right={<Toggle value={value} onValueChange={onValueChange} disabled={disabled} label={title} />}
    />
  );
}

/** State told in words; one green for "on", neutral grey for everything else. */
export function StatusTag({label, on}: {label: string; on?: boolean}) {
  const styles = useStyles();
  return (
    <View style={[styles.tag, on && styles.tagOn]}>
      <Text style={[styles.tagText, on && styles.tagTextOn]}>{label}</Text>
    </View>
  );
}

export function Notice({children, style}: {children: ReactNode; style?: StyleProp<ViewStyle>}) {
  const styles = useStyles();
  return (
    <View style={[styles.notice, style]}>
      <Text style={styles.noticeText}>{children}</Text>
    </View>
  );
}

export function Footnote({children, flush}: {children: ReactNode; flush?: boolean}) {
  const styles = useStyles();
  return <Text style={[styles.footnote, flush && styles.footnoteFlush]}>{children}</Text>;
}

export function Kpis({items}: {items: {value: string; unit?: string; label: string}[]}) {
  const styles = useStyles();
  return (
    <View style={styles.kpis}>
      {items.map(k => (
        <View key={k.label} style={styles.kpi}>
          <Text style={styles.kpiValue} numberOfLines={1}>
            {k.value}
            {!!k.unit && <Text style={styles.kpiUnit}> {k.unit}</Text>}
          </Text>
          <Text style={styles.kpiLabel}>{k.label}</Text>
        </View>
      ))}
    </View>
  );
}

export function CodeBlock({text, style}: {text: string; style?: StyleProp<ViewStyle>}) {
  const styles = useStyles();
  return (
    <View style={[styles.code, style]}>
      <Text style={styles.codeText} selectable>
        {text}
      </Text>
    </View>
  );
}

export function ActionButton({
  label,
  onPress,
  tone = 'quiet',
  loading,
  disabled,
  style,
  icon,
}: {
  label: string;
  onPress: () => void;
  tone?: 'primary' | 'quiet' | 'danger';
  loading?: boolean;
  disabled?: boolean;
  style?: StyleProp<ViewStyle>;
  icon?: IconDefinition;
}) {
  const t = useTheme();
  const styles = useStyles();
  const color = tone === 'primary' ? t.onAccent : tone === 'danger' ? t.danger : t.t1;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{disabled: disabled || loading, busy: loading}}
      disabled={disabled || loading}
      onPress={onPress}
      style={({pressed}) => [
        styles.button,
        tone === 'primary' && styles.buttonPrimary,
        tone === 'danger' && styles.buttonDanger,
        pressed && styles.buttonPressed,
        (disabled || loading) && styles.buttonDisabled,
        style,
      ]}>
      {loading ? (
        <ActivityIndicator size="small" color={color} />
      ) : (
        <View style={styles.buttonInner}>
          {icon && <Icon icon={icon} size={12} color={color} />}
          <Text style={[styles.buttonText, {color}]}>{label}</Text>
        </View>
      )}
    </Pressable>
  );
}

/** A sheet holding one text field and a save button. */
export function FieldSheet({
  visible,
  title,
  initial = '',
  placeholder,
  hint,
  keyboardType,
  secure,
  multiline,
  mono,
  allowEmpty = true,
  submitLabel,
  describe,
  onSubmit,
  onClose,
}: {
  visible: boolean;
  title: string;
  initial?: string;
  placeholder?: string;
  hint?: string;
  /** Feedback on what is typed so far; takes the hint's place while it returns something. */
  describe?: (value: string) => {text: string; tone?: 'danger' | 'warn' | 'ok'} | null;
  keyboardType?: KeyboardTypeOptions;
  secure?: boolean;
  multiline?: boolean;
  mono?: boolean;
  allowEmpty?: boolean;
  submitLabel?: string;
  onSubmit: (value: string) => Promise<void> | void;
  onClose: () => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  const [value, setValue] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (visible) {
      setValue(initial);
      setError(null);
    }
  }, [visible, initial]);

  const live = describe && value ? describe(value) : null;
  const toneStyle = {danger: styles.sheetError, warn: styles.sheetWarn, ok: styles.sheetOk};

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await onSubmit(value.trim());
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet visible={visible} onClose={onClose} title={title}>
      <View style={styles.sheetBody}>
        <TextInput
          value={value}
          onChangeText={setValue}
          placeholder={placeholder}
          placeholderTextColor={t.t4}
          selectionColor={t.accent}
          cursorColor={t.accent}
          keyboardType={keyboardType}
          secureTextEntry={secure}
          multiline={multiline}
          autoCapitalize="none"
          autoCorrect={false}
          autoFocus
          onSubmitEditing={multiline ? undefined : submit}
          style={[styles.field, multiline && styles.fieldMulti, mono && styles.mono]}
        />
        {error ? (
          <Text style={[styles.sheetHint, styles.sheetError]}>{error}</Text>
        ) : live ? (
          <Text style={[styles.sheetHint, live.tone && toneStyle[live.tone]]}>{live.text}</Text>
        ) : (
          !!hint && <Text style={styles.sheetHint}>{hint}</Text>
        )}
        <ActionButton
          label={submitLabel ?? tr('common_save')}
          tone="primary"
          loading={busy}
          disabled={!allowEmpty && !value.trim()}
          onPress={submit}
          style={styles.sheetButton}
        />
      </View>
    </Sheet>
  );
}

export interface Choice<K extends string> {
  key: K;
  label: string;
  desc?: string;
  icon?: IconDefinition;
}

export function ChoiceSheet<K extends string>({
  visible,
  title,
  options,
  selected,
  note,
  onSelect,
  onClose,
}: {
  visible: boolean;
  title: string;
  options: Choice<K>[];
  selected?: K;
  note?: string;
  onSelect: (key: K) => void;
  onClose: () => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  return (
    <Sheet visible={visible} onClose={onClose} title={title}>
      <ScrollView style={styles.choiceList} bounces={false} keyboardShouldPersistTaps="handled">
        {options.map(o => {
          const active = o.key === selected;
          return (
            <Pressable
              key={o.key}
              accessibilityRole="button"
              accessibilityState={{selected: active}}
              onPress={() => onSelect(o.key)}
              style={({pressed}) => [styles.choice, pressed && styles.rowPressed]}>
              {o.icon && (
                <View style={[styles.choiceIcon, active && styles.choiceIconActive]}>
                  <Icon icon={o.icon} size={13} color={active ? t.accent : t.t2} />
                </View>
              )}
              <View style={styles.rowText}>
                <Text style={styles.choiceName}>{o.label}</Text>
                {!!o.desc && <Text style={styles.choiceDesc}>{o.desc}</Text>}
              </View>
              {active && <Icon icon={faCheck} size={13} color={t.accent} />}
            </Pressable>
          );
        })}
      </ScrollView>
      {!!note && <Text style={styles.choiceNote}>{note}</Text>}
    </Sheet>
  );
}

/** States the consequence first, then offers a single way forward. */
export function ConfirmSheet({
  visible,
  title,
  message,
  confirmLabel,
  danger,
  onConfirm,
  onClose,
}: {
  visible: boolean;
  title: string;
  message: string;
  confirmLabel: string;
  danger?: boolean;
  onConfirm: () => Promise<void> | void;
  onClose: () => void;
}) {
  const styles = useStyles();
  const [busy, setBusy] = useState(false);
  const confirm = async () => {
    setBusy(true);
    try {
      await onConfirm();
    } finally {
      setBusy(false);
    }
  };
  return (
    <Sheet visible={visible} onClose={onClose} title={title}>
      <View style={styles.sheetBody}>
        <Text style={styles.confirmText}>{message}</Text>
        <View style={styles.confirmActions}>
          <ActionButton label={tr('common_cancel')} onPress={onClose} style={styles.flex} />
          <ActionButton
            label={confirmLabel}
            tone={danger ? 'danger' : 'primary'}
            loading={busy}
            onPress={confirm}
            style={styles.flex}
          />
        </View>
      </View>
    </Sheet>
  );
}

const useStyles = makeStyles(t => ({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    minHeight: 52,
    marginHorizontal: 18,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: t.line1,
  },
  rowInCard: {marginHorizontal: 14},
  rowLast: {borderBottomWidth: 0},
  card: {
    marginHorizontal: 16,
    borderRadius: radius.md,
    backgroundColor: t.bg1,
    borderWidth: 1,
    borderColor: t.line1,
    overflow: 'hidden',
  },
  rowSplit: {paddingVertical: 0},
  rowArrow: {alignSelf: 'stretch', justifyContent: 'center', paddingLeft: 6},
  rowMain: {flex: 1, minWidth: 0, minHeight: 52, flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 12},
  rowPressed: {opacity: 0.6},
  rowIcon: {width: 18, alignItems: 'center'},
  rowText: {flex: 1, minWidth: 0},
  rowTitle: {fontSize: 15, color: t.t1, letterSpacing: -0.1},
  rowDetail: {fontSize: 12, lineHeight: 17, color: t.t3, marginTop: 3},
  rowValue: {flexShrink: 1, maxWidth: '55%', fontSize: 14, color: t.t3, textAlign: 'right'},
  dim: {color: t.t3},
  mono: {fontFamily: MONO, fontSize: 13},
  monoValue: {fontFamily: MONO, fontSize: 12},
  tag: {paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6, backgroundColor: t.bg2},
  tagOn: {backgroundColor: t.accentSoft},
  tagText: {fontSize: 11, fontWeight: '500', color: t.t3},
  tagTextOn: {color: t.accent},
  notice: {
    marginHorizontal: 18,
    marginBottom: 6,
    paddingHorizontal: 14,
    paddingVertical: 11,
    borderRadius: radius.sm,
    backgroundColor: t.bg1,
    borderWidth: 1,
    borderColor: t.line1,
  },
  noticeText: {fontSize: 13, lineHeight: 20, color: t.t2},
  footnote: {fontSize: 12, lineHeight: 19, color: t.t4, paddingHorizontal: 18, paddingTop: 12},
  footnoteFlush: {paddingHorizontal: 0},
  kpis: {flexDirection: 'row', gap: 10, paddingHorizontal: 18, marginBottom: 8},
  kpi: {
    flex: 1,
    paddingHorizontal: 14,
    paddingVertical: 13,
    borderRadius: radius.md,
    backgroundColor: t.bg1,
    borderWidth: 1,
    borderColor: t.line1,
  },
  kpiValue: {fontSize: 22, fontWeight: '600', letterSpacing: -0.6, color: t.t1, fontVariant: ['tabular-nums']},
  kpiUnit: {fontSize: 13, fontWeight: '500', color: t.t3, letterSpacing: 0},
  kpiLabel: {fontSize: 12, color: t.t3, marginTop: 4},
  code: {
    marginHorizontal: 18,
    paddingHorizontal: 13,
    paddingVertical: 12,
    borderRadius: radius.sm,
    backgroundColor: t.codeBg,
    borderWidth: 1,
    borderColor: t.line1,
  },
  codeText: {fontFamily: MONO, fontSize: 12, lineHeight: 19, color: t.t2},
  button: {
    height: 44,
    paddingHorizontal: 18,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: radius.sm,
    backgroundColor: t.bg2,
    borderWidth: 1,
    borderColor: t.line1,
  },
  buttonPrimary: {backgroundColor: t.green, borderColor: t.green},
  buttonDanger: {backgroundColor: t.dangerSoft, borderColor: 'transparent'},
  buttonPressed: {opacity: 0.75},
  buttonDisabled: {opacity: 0.45},
  buttonInner: {flexDirection: 'row', alignItems: 'center', gap: 7},
  buttonText: {fontSize: 15, fontWeight: '500'},
  sheetBody: {paddingHorizontal: 12, paddingTop: 4},
  field: {
    minHeight: 46,
    paddingHorizontal: 14,
    paddingVertical: 12,
    borderRadius: radius.sm,
    backgroundColor: t.bg2,
    borderWidth: 1,
    borderColor: t.line1,
    fontSize: 15,
    color: t.t1,
  },
  fieldMulti: {minHeight: 120, maxHeight: 240, textAlignVertical: 'top'},
  sheetHint: {fontSize: 12, lineHeight: 18, color: t.t4, paddingTop: 8},
  sheetError: {color: t.danger},
  sheetWarn: {color: t.kind.image[1]},
  sheetOk: {color: t.accent},
  sheetButton: {marginTop: 14, marginBottom: 4},
  choice: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 12,
    paddingVertical: 12,
    borderRadius: radius.md,
  },
  choiceIcon: {
    width: 34,
    height: 34,
    borderRadius: radius.sm,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: t.bg2,
  },
  choiceIconActive: {backgroundColor: t.accentSoft},
  choiceName: {fontSize: 15, fontWeight: '500', color: t.t1},
  choiceDesc: {fontSize: 12, lineHeight: 17, color: t.t3, marginTop: 3},
  choiceList: {flexGrow: 0, flexShrink: 1},
  choiceNote: {fontSize: 12, lineHeight: 18, color: t.t4, paddingHorizontal: 12, paddingTop: 8, paddingBottom: 4},
  confirmText: {fontSize: 14, lineHeight: 22, color: t.t2, paddingBottom: 16},
  confirmActions: {flexDirection: 'row', gap: 10, paddingBottom: 4},
  flex: {flex: 1},
}));
