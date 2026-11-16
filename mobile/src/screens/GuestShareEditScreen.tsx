import {faCheck, faChevronDown, faChevronUp, faPlus, faXmark} from '@fortawesome/free-solid-svg-icons';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useEffect, useMemo, useState} from 'react';
import {KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {createGuestShare, getGuestShare, getGuestShares, setGuestSharePassword, updateGuestShare} from '../api/cowApi';
import {InfoRow, InputRow, OptionRow, PickerSheet, Section, type PickerOption} from '../components/forms';
import {Icon} from '../components/Icon';
import {labelText} from '../components/ModelPicker';
import {ActionButton, Toggle} from '../components/settings';
import {showToast} from '../components/Toast';
import {Chip, EmptyState, PageHeader} from '../components/ui';
import type {RootStackParamList} from '../navigation/types';
import type {GuestShare, GuestSharesOverview} from '../protocol/resources';
import {useConfigStore} from '../store/configStore';
import {makeStyles, useTheme} from '../theme/theme';
import {
  buildShareConfig,
  draftFromConfig,
  newShareDraft,
  SHARE_COLORS,
  SHARE_DEFAULT_COLOR,
  SHARE_LANGUAGES,
  SHARE_MAX_QUESTIONS,
  SHARE_TOOLS,
  toggleIn,
  TOOL_LABEL,
  validateDraft,
  type ShareDraft,
} from '../utils/guestShares';
import {describeShareError} from './GuestSharesScreen';

type Props = StackScreenProps<RootStackParamList, 'GuestShareEdit'>;

const referenceLabel = (r: {agent: string; category: string}) => {
  const kb = r.agent ? `${r.agent} · 知识库` : '知识库';
  return r.category ? `${kb} / ${r.category}` : kb;
};

export function GuestShareEditScreen({navigation, route}: Props) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const {slug, focus} = route.params;
  const defaultModel = useConfigStore(s => s.config?.model ?? '');
  const [overview, setOverview] = useState<GuestSharesOverview | null>(null);
  const [share, setShare] = useState<GuestShare | null>(null);
  const [draft, setDraft] = useState<ShareDraft | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [modelSheet, setModelSheet] = useState(false);
  const [more, setMore] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [list, detail] = await Promise.all([getGuestShares(), slug ? getGuestShare(slug) : Promise.resolve(null)]);
        if (!alive) {
          return;
        }
        setOverview(list);
        setShare(detail?.share ?? null);
        setDraft(detail ? draftFromConfig(detail.share, detail.share.raw_config ?? {}, detail.share.guest_md ?? '') : newShareDraft());
      } catch (e) {
        if (alive) {
          setLoadError(describeShareError(e));
        }
      }
    })();
    return () => {
      alive = false;
    };
  }, [slug]);

  const modelOptions = useMemo<PickerOption[]>(() => {
    const options: PickerOption[] = [{value: '', label: '默认模型', hint: defaultModel || undefined}];
    const seen = new Set<string>();
    for (const p of overview?.models ?? []) {
      for (const m of p.models ?? []) {
        seen.add(`${p.id}|${m}`);
        options.push({value: `${p.id}|${m}`, label: m, group: labelText(p.label, p.id)});
      }
    }
    if (draft?.model && !seen.has(draft.model)) {
      options.push({value: draft.model, label: draft.model.slice(draft.model.indexOf('|') + 1)});
    }
    return options;
  }, [overview, defaultModel, draft?.model]);

  const title = slug ? '编辑访客页面' : '新建访客页面';
  if (!draft || !overview) {
    return (
      <View style={styles.root}>
        <PageHeader title={title} onBack={navigation.goBack} />
        <EmptyState loading={!loadError} title="加载失败" hint={loadError ?? undefined} />
      </View>
    );
  }

  const set = (patch: Partial<ShareDraft>) => setDraft({...draft, ...patch});
  const passwordSet = !!share?.password_set;
  const modelLabel = draft.model ? draft.model.slice(draft.model.indexOf('|') + 1) : '默认模型';
  const skills = [
    ...overview.skills.filter(s => !s.needs_shell || draft.skills.includes(s.name)).map(s => s.name),
    ...draft.skills.filter(name => !overview.skills.some(s => s.name === name)),
  ];
  const references = [
    ...overview.references.map(r => ({path: r.path, label: referenceLabel(r)})),
    ...draft.references
      .filter(r => !overview.references.some(x => x.path === r.path))
      .map(r => ({path: r.path, label: r.path})),
  ];

  const toggleReference = (path: string) => {
    const has = draft.references.some(r => r.path === path);
    set({references: has ? draft.references.filter(r => r.path !== path) : [...draft.references, {path, note: ''}]});
  };

  const save = async () => {
    const problem = validateDraft(draft, passwordSet);
    if (problem) {
      setError(problem);
      return;
    }
    setSaving(true);
    setError(null);
    const config = buildShareConfig(draft, share?.raw_config);
    try {
      const saved = share
        ? (await updateGuestShare(share.slug, config, draft.rules)).share
        : (await createGuestShare(config, draft.rules)).share;
      // A retry after the password step fails must update this page, not create another.
      setShare(saved);
      if (draft.passwordRequired && draft.password) {
        await setGuestSharePassword(saved.slug, draft.password);
      }
      showToast(slug ? '已保存' : '已创建');
      navigation.goBack();
    } catch (e) {
      setError(describeShareError(e));
      setSaving(false);
    }
  };

  return (
    <View style={styles.root}>
      <PageHeader title={title} subtitle={share ? share.name || share.slug : '访客无需登录，打开链接即可对话'} onBack={navigation.goBack} />
      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={{paddingBottom: insets.bottom + 32}} keyboardShouldPersistTaps="handled">
          <Section title="基本信息">
            <InputRow first label="名称" value={draft.name} onChangeText={name => set({name})} placeholder="访客看到的标题，例如「产品咨询」" autoFocus={!slug} />
            <InfoRow title="模型" value={modelLabel} mono={!!draft.model} onPress={() => setModelSheet(true)} />
            <InputRow label="欢迎语" value={draft.welcome} onChangeText={welcome => set({welcome})} placeholder="访客打开链接时看到的第一句话" multiline />
          </Section>

          <Section
            title={`引导问题 ${draft.questions.length}/${SHARE_MAX_QUESTIONS}`}
            footer="显示在欢迎页，访客点击即可提问">
            {draft.questions.map((q, i) => (
              <InputRow
                key={i}
                first={i === 0}
                value={q}
                onChangeText={v => set({questions: draft.questions.map((x, j) => (j === i ? v : x))})}
                placeholder="输入一个问题"
                right={
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel="删除这个问题"
                    hitSlop={10}
                    onPress={() => set({questions: draft.questions.filter((_, j) => j !== i)})}
                    style={styles.remove}>
                    <Icon icon={faXmark} size={11} color={t.t3} />
                  </Pressable>
                }
              />
            ))}
            {draft.questions.length < SHARE_MAX_QUESTIONS && (
              <Pressable
                accessibilityRole="button"
                onPress={() => set({questions: [...draft.questions, '']})}
                style={({pressed}) => [styles.addRow, !!draft.questions.length && styles.divider, pressed && styles.pressed]}>
                <Icon icon={faPlus} size={11} color={t.accent} />
                <Text style={styles.addText}>添加问题</Text>
              </Pressable>
            )}
          </Section>

          <Section title="访问控制">
            <InfoRow
              first
              title="访问密码"
              hint={draft.passwordRequired ? undefined : '未开启，任何拿到链接的人都能访问'}
              right={
                <Toggle value={draft.passwordRequired} onValueChange={passwordRequired => set({passwordRequired})} label="访问密码" />
              }
            />
            {draft.passwordRequired && (
              <InputRow
                value={draft.password}
                onChangeText={password => set({password})}
                placeholder={passwordSet ? '已设置，留空则不修改' : '至少 6 位，不要与访问密码相同'}
                secure
                mono
                autoFocus={focus === 'password'}
              />
            )}
            <InputRow
              label="每人每日提问"
              value={draft.quota}
              onChangeText={quota => set({quota: quota.replace(/[^\d]/g, '')})}
              placeholder="0 表示不限制"
              keyboardType="number-pad"
            />
            <InputRow
              label="有效期至"
              value={draft.expires}
              onChangeText={expires => set({expires})}
              placeholder="留空表示长期有效，如 2026-12-31"
              keyboardType="numbers-and-punctuation"
              mono
            />
          </Section>

          <Section title="主题色" footer="用于按钮、访客消息气泡和嵌入网页的对话入口">
            <View style={styles.swatches}>
              {['', ...SHARE_COLORS].map(c => {
                const active = draft.color === c;
                return (
                  <Pressable
                    key={c || 'default'}
                    accessibilityRole="radio"
                    accessibilityLabel={c || '默认'}
                    accessibilityState={{selected: active}}
                    onPress={() => set({color: c})}
                    style={[styles.swatch, {backgroundColor: c || SHARE_DEFAULT_COLOR}, active && styles.swatchActive]}>
                    {active && <Icon icon={faCheck} size={12} color="#fff" />}
                  </Pressable>
                );
              })}
            </View>
          </Section>

          <Section style={styles.moreSection}>
            <InfoRow
              first
              title="更多设置"
              hint="工具、技能、参考资料、访客规则、语言、页脚"
              right={<Icon icon={more ? faChevronUp : faChevronDown} size={11} color={t.t3} />}
              onPress={() => setMore(v => !v)}
            />
          </Section>

          {more && (
            <>
              <Section title="可用工具" footer="写入类工具只作用于每位访客自己的临时目录">
                <View style={styles.chips}>
                  {SHARE_TOOLS.map(id => (
                    <Chip key={id} label={TOOL_LABEL[id] ?? id} active={draft.tools.includes(id)} onPress={() => set({tools: toggleIn(draft.tools, id)})} />
                  ))}
                </View>
              </Section>

              <Section title="技能" footer="访客无法执行命令，依赖命令或脚本的技能不在可选范围内">
                {skills.length ? (
                  <View style={styles.chips}>
                    {skills.map(name => (
                      <Chip key={name} label={name} active={draft.skills.includes(name)} onPress={() => set({skills: toggleIn(draft.skills, name)})} />
                    ))}
                  </View>
                ) : (
                  <Text style={styles.empty}>没有可供访客使用的技能</Text>
                )}
              </Section>

              <Section title="参考资料" footer="访客的 Agent 可以只读访问这些目录，访客看不到真实路径。其他目录请在电脑上添加">
                {references.length ? (
                  <View style={styles.chips}>
                    {references.map(r => (
                      <Chip
                        key={r.path}
                        label={r.label}
                        active={draft.references.some(x => x.path === r.path)}
                        onPress={() => toggleReference(r.path)}
                      />
                    ))}
                  </View>
                ) : (
                  <Text style={styles.empty}>知识库里还没有可选的分类</Text>
                )}
              </Section>

              <Section title="访客规则" footer="写入 Agent 的系统提示词：你是谁、为谁服务、能回答什么、超出范围怎么回复。留空则只遵循平台默认规则">
                <InputRow
                  first
                  value={draft.rules}
                  onChangeText={rules => set({rules})}
                  placeholder="例如：你是 CowAgent 的智能助手，帮助开发者解答安装、配置和使用问题，回答简洁友好。"
                  multiline
                />
              </Section>

              <Section title="语言" footer="页面界面和 Agent 系统提示词使用的语言">
                {SHARE_LANGUAGES.map((l, i) => (
                  <OptionRow key={l.value || 'auto'} first={i === 0} title={l.label} selected={draft.language === l.value} onPress={() => set({language: l.value})} />
                ))}
              </Section>

              <Section title="页脚">
                <InputRow first label="页脚文字" value={draft.footerText} onChangeText={footerText => set({footerText})} placeholder="留空则不显示" />
                <InputRow label="页脚链接" value={draft.footerUrl} onChangeText={footerUrl => set({footerUrl})} placeholder="https://，留空则不加链接" keyboardType="url" mono />
              </Section>
            </>
          )}

          {!!error && <Text style={styles.error}>{error}</Text>}
          <ActionButton label={slug ? '保存' : '创建'} tone="primary" loading={saving} onPress={save} style={styles.save} />
        </ScrollView>
      </KeyboardAvoidingView>

      <PickerSheet
        visible={modelSheet}
        title="模型"
        options={modelOptions}
        selected={draft.model}
        onSelect={model => {
          setModelSheet(false);
          set({model});
        }}
        onClose={() => setModelSheet(false)}
      />
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  flex: {flex: 1},
  divider: {borderTopWidth: 1, borderTopColor: t.line1},
  pressed: {backgroundColor: t.bg2},
  remove: {width: 26, height: 26, alignItems: 'center', justifyContent: 'center', borderRadius: 13, backgroundColor: t.bg2},
  addRow: {flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 14, paddingVertical: 14},
  addText: {fontSize: 14, fontWeight: '500', color: t.accent},
  swatches: {flexDirection: 'row', flexWrap: 'wrap', gap: 12, paddingHorizontal: 14, paddingVertical: 14},
  swatch: {width: 30, height: 30, borderRadius: 15, alignItems: 'center', justifyContent: 'center'},
  swatchActive: {borderWidth: 2, borderColor: t.bg1, transform: [{scale: 1.12}]},
  moreSection: {marginTop: 14},
  chips: {flexDirection: 'row', flexWrap: 'wrap', gap: 8, padding: 12},
  empty: {fontSize: 13, color: t.t3, paddingHorizontal: 14, paddingVertical: 14},
  error: {fontSize: 13, lineHeight: 19, color: t.danger, paddingHorizontal: 18, paddingTop: 16},
  save: {marginHorizontal: 14, marginTop: 20},
}));
