import type {StackScreenProps} from '@react-navigation/stack';
import React, {useEffect, useRef, useState} from 'react';
import {KeyboardAvoidingView, Platform, ScrollView, Text, TextInput, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {createSkill} from '../api/cowApi';
import {ActionButton, ConfirmSheet, Footnote, MONO} from '../components/settings';
import {showToast, ToastHost} from '../components/Toast';
import {PageHeader} from '../components/ui';
import type {RootStackParamList} from '../navigation/types';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {skillErrorText} from './SkillsScreen';

type Props = StackScreenProps<RootStackParamList, 'SkillCreate'>;

const BODY_PLACEHOLDER = '## 使用场景\n什么时候该用这个技能\n\n## 步骤\n1. …\n2. …';

export function SkillCreateScreen({route, navigation}: Props) {
  const agentId = route.params?.agentId;
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
      setError('先给技能起个名字');
      return;
    }
    if (!description.trim()) {
      setError('请填写描述，Agent 靠它判断什么时候使用这个技能');
      return;
    }
    setBusy(true);
    setError(null);
    guard.current = false;
    try {
      const res = await createSkill({name: name.trim(), description: description.trim(), body}, agentId);
      showToast('技能已创建');
      navigation.replace('SkillDetail', {name: res.name, agentId});
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
      <PageHeader title="新建技能" onBack={navigation.goBack} />
      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={[styles.body, {paddingBottom: insets.bottom + 32}]} keyboardShouldPersistTaps="handled">
          <Text style={styles.label}>名称</Text>
          {field(name, setName, {placeholder: '如 weather-report 或 天气 weather'})}
          <Text style={styles.hint}>目录名取其中的英文字母和数字，转成小写连字符形式；整段会保留为显示名。</Text>

          <Text style={styles.label}>描述</Text>
          {field(description, setDescription, {placeholder: '查询城市天气并生成出行建议。用户问到天气、穿衣、出行时使用。', lines: 3})}
          <Text style={styles.hint}>Agent 根据这段话判断什么时候调用这个技能，写清楚它做什么、在什么情况下用。</Text>

          <Text style={styles.label}>说明（可选）</Text>
          {field(body, setBody, {placeholder: BODY_PLACEHOLDER, lines: 8, mono: true})}
          <Text style={styles.hint}>写在 SKILL.md 正文里的步骤和要求，用 Markdown。创建后还可以继续编辑。</Text>

          {!!error && <Text style={styles.error}>{error}</Text>}
          <ActionButton label="创建" tone="primary" loading={busy} onPress={submit} style={styles.submit} />
          <Footnote flush>需要附带脚本或资料文件时，可以打包成 .zip，在技能页用「上传文件」安装。</Footnote>
        </ScrollView>
      </KeyboardAvoidingView>
      <ConfirmSheet
        visible={!!leaving}
        title="放弃新建"
        message="填写的内容还没有保存，离开后就找不回来了。"
        confirmLabel="放弃"
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
