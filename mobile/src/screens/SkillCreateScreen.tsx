import type {StackScreenProps} from '@react-navigation/stack';
import React, {useEffect, useRef, useState} from 'react';
import {KeyboardAvoidingView, Platform, ScrollView, Text, TextInput, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {createSkill} from '../api/cowApi';
import {ActionButton, ConfirmSheet, Footnote, MONO} from '../components/settings';
import {showToast, ToastHost} from '../components/Toast';
import {PageHeader} from '../components/ui';
import {tr} from '../i18n';
import type {RootStackParamList} from '../navigation/types';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {skillErrorText} from './SkillsScreen';

type Props = StackScreenProps<RootStackParamList, 'SkillCreate'>;

export function SkillCreateScreen({navigation}: Props) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [body, setBody] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [leaving, setLeaving] = useState<(() => void) | null>(null);
  const dirty = !!(name.trim() || description.trim() || body.trim());
  const guard = useRef(dirty);
  guard.current = dirty && !busy;

  useEffect(
    () =>
      navigation.addListener('beforeRemove', e => {
        if (!guard.current) {
          return;
        }
        e.preventDefault();
        setLeaving(() => () => navigation.dispatch(e.data.action));
      }),
    [navigation],
  );

  const submit = async () => {
    if (!name.trim()) {
      setError(tr('skill_create_name_required'));
      return;
    }
    if (!description.trim()) {
      setError(tr('skill_err_desc_required'));
      return;
    }
    setBusy(true);
    setError(null);
    guard.current = false;
    try {
      const res = await createSkill({name: name.trim(), description: description.trim(), body});
      showToast(tr('skill_created'));
      navigation.replace('SkillDetail', {name: res.name});
    } catch (e) {
      setError(skillErrorText(e));
      setBusy(false);
    }
  };

  const field = (
    value: string,
    onChange: (v: string) => void,
    opts: {placeholder: string; lines?: number; mono?: boolean},
  ) => (
    <TextInput
      value={value}
      onChangeText={v => {
        onChange(v);
        setError(null);
      }}
      placeholder={opts.placeholder}
      placeholderTextColor={t.t4}
      selectionColor={t.accent}
      cursorColor={t.accent}
      autoCapitalize="none"
      autoCorrect={false}
      multiline={!!opts.lines}
      style={[
        styles.field,
        opts.mono && styles.mono,
        !!opts.lines && [styles.multi, {minHeight: 22 + opts.lines * 21}],
      ]}
    />
  );

  return (
    <View style={styles.root}>
      <PageHeader title={tr('skill_create')} onBack={navigation.goBack} />
      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={[styles.body, {paddingBottom: insets.bottom + 32}]} keyboardShouldPersistTaps="handled">
          <Text style={styles.label}>{tr('common_name')}</Text>
          {field(name, setName, {placeholder: tr('skill_create_name_ph')})}
          <Text style={styles.hint}>{tr('skill_create_name_hint')}</Text>

          <Text style={styles.label}>{tr('common_description')}</Text>
          {field(description, setDescription, {placeholder: tr('skill_create_desc_ph'), lines: 3})}
          <Text style={styles.hint}>{tr('skill_create_desc_hint')}</Text>

          <Text style={styles.label}>{tr('skill_create_body')}</Text>
          {field(body, setBody, {placeholder: tr('skill_create_body_ph'), lines: 8, mono: true})}
          <Text style={styles.hint}>{tr('skill_create_body_hint')}</Text>

          {!!error && <Text style={styles.error}>{error}</Text>}
          <ActionButton label={tr('skill_create_submit')} tone="primary" loading={busy} onPress={submit} style={styles.submit} />
          <Footnote flush>{tr('skill_create_footnote')}</Footnote>
        </ScrollView>
      </KeyboardAvoidingView>
      <ConfirmSheet
        visible={!!leaving}
        title={tr('skill_create_discard_title')}
        message={tr('skill_create_discard_message')}
        confirmLabel={tr('skill_discard')}
        danger
        onConfirm={() => {
          const go = leaving;
          setLeaving(null);
          guard.current = false;
          go?.();
        }}
        onClose={() => setLeaving(null)}
      />
      <ToastHost bottom={insets.bottom + 28} />
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  flex: {flex: 1},
  body: {paddingHorizontal: 18, paddingTop: 4},
  label: {fontSize: 12, color: t.t3, marginTop: 18, marginBottom: 7},
  field: {
    minHeight: 46,
    paddingHorizontal: 14,
    paddingVertical: 12,
    borderRadius: radius.sm,
    backgroundColor: t.bg1,
    borderWidth: 1,
    borderColor: t.line1,
    fontSize: 15,
    lineHeight: 21,
    color: t.t1,
  },
  mono: {fontFamily: MONO, fontSize: 13},
  multi: {textAlignVertical: 'top'},
  hint: {fontSize: 12, lineHeight: 18, color: t.t4, marginTop: 6},
  error: {fontSize: 13, lineHeight: 20, color: t.danger, marginTop: 16},
  submit: {marginTop: 22},
}));
