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
import {tr, trf} from '../i18n';
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
  SHARE_PASSWORD_MIN,
  SHARE_TOOLS,
  toggleIn,
  TOOL_LABEL,
  validateDraft,
  type ShareDraft,
} from '../utils/guestShares';
import {describeShareError} from './GuestSharesScreen';

type Props = StackScreenProps<RootStackParamList, 'GuestShareEdit'>;

const referenceLabel = (r: {agent: string; category: string}) => {
  const kb = r.agent ? `${r.agent} · ${tr('share_ref_kb')}` : tr('share_ref_kb');
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
    const options: PickerOption[] = [{value: '', label: tr('share_default_model'), hint: defaultModel || undefined}];
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

  const title = tr(slug ? 'share_edit_title' : 'share_new');
  if (!draft || !overview) {
    return (
      <View style={styles.root}>
        <PageHeader title={title} onBack={navigation.goBack} />
        <EmptyState loading={!loadError} title={tr('common_load_failed')} hint={loadError ?? undefined} />
      </View>
    );
  }

  const set = (patch: Partial<ShareDraft>) => setDraft({...draft, ...patch});
  const passwordSet = !!share?.password_set;
  const modelLabel = draft.model ? draft.model.slice(draft.model.indexOf('|') + 1) : tr('share_default_model');
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
      showToast(tr(slug ? 'common_saved' : 'share_created'));
      navigation.goBack();
    } catch (e) {
      setError(describeShareError(e));
      setSaving(false);
    }
  };

  return (
    <View style={styles.root}>
      <PageHeader
        title={title}
        subtitle={share ? share.name || share.slug : tr('share_new_desc')}
        onBack={navigation.goBack}
      />
      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={{paddingBottom: insets.bottom + 32}} keyboardShouldPersistTaps="handled">
          <Section title={tr('share_section_basic')}>
            <InputRow
              first
              label={tr('common_name')}
              value={draft.name}
              onChangeText={name => set({name})}
              placeholder={tr('share_name_ph')}
              autoFocus={!slug}
            />
            <InfoRow title={tr('share_model')} value={modelLabel} mono={!!draft.model} onPress={() => setModelSheet(true)} />
            <InputRow
              label={tr('share_welcome')}
              value={draft.welcome}
              onChangeText={welcome => set({welcome})}
              placeholder={tr('share_welcome_ph')}
              multiline
            />
          </Section>

          <Section
            title={trf('share_questions_count', {n: draft.questions.length, max: SHARE_MAX_QUESTIONS})}
            footer={tr('share_questions_tip')}>
            {draft.questions.map((q, i) => (
              <InputRow
                key={i}
                first={i === 0}
                value={q}
                onChangeText={v => set({questions: draft.questions.map((x, j) => (j === i ? v : x))})}
                placeholder={tr('share_question_ph')}
                right={
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel={tr('share_remove_question')}
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
                <Text style={styles.addText}>{tr('share_add_question')}</Text>
              </Pressable>
            )}
          </Section>

          <Section title={tr('share_section_access')}>
            <InfoRow
              first
              title={tr('share_password')}
              hint={draft.passwordRequired ? undefined : tr('share_password_off')}
              right={
                <Toggle
                  value={draft.passwordRequired}
                  onValueChange={passwordRequired => set({passwordRequired})}
                  label={tr('share_password')}
                />
              }
            />
            {draft.passwordRequired && (
              <InputRow
                value={draft.password}
                onChangeText={password => set({password})}
                placeholder={
                  passwordSet ? tr('share_password_keep') : trf('share_password_new', {min: SHARE_PASSWORD_MIN})
                }
                secure
                mono
                autoFocus={focus === 'password'}
              />
            )}
            <InputRow
              label={tr('share_quota')}
              value={draft.quota}
              onChangeText={quota => set({quota: quota.replace(/[^\d]/g, '')})}
              placeholder={tr('share_quota_ph')}
              keyboardType="number-pad"
            />
            <InputRow
              label={tr('share_expires')}
              value={draft.expires}
              onChangeText={expires => set({expires})}
              placeholder={tr('share_expires_ph')}
              keyboardType="numbers-and-punctuation"
              mono
            />
          </Section>

          <Section title={tr('share_color')} footer={tr('share_color_tip')}>
            <View style={styles.swatches}>
              {['', ...SHARE_COLORS].map(c => {
                const active = draft.color === c;
                return (
                  <Pressable
                    key={c || 'default'}
                    accessibilityRole="radio"
                    accessibilityLabel={c || tr('share_color_default')}
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
              title={tr('share_more')}
              hint={tr('share_more_desc')}
              right={<Icon icon={more ? faChevronUp : faChevronDown} size={11} color={t.t3} />}
              onPress={() => setMore(v => !v)}
            />
          </Section>

          {more && (
            <>
              <Section title={tr('share_tools')} footer={tr('share_tools_tip')}>
                <View style={styles.chips}>
                  {SHARE_TOOLS.map(id => (
                    <Chip key={id} label={TOOL_LABEL[id] ?? id} active={draft.tools.includes(id)} onPress={() => set({tools: toggleIn(draft.tools, id)})} />
                  ))}
                </View>
              </Section>

              <Section title={tr('share_skills')} footer={tr('share_skills_tip')}>
                {skills.length ? (
                  <View style={styles.chips}>
                    {skills.map(name => (
                      <Chip key={name} label={name} active={draft.skills.includes(name)} onPress={() => set({skills: toggleIn(draft.skills, name)})} />
                    ))}
                  </View>
                ) : (
                  <Text style={styles.empty}>{tr('share_skills_empty')}</Text>
                )}
              </Section>

              <Section title={tr('share_refs')} footer={tr('share_refs_tip')}>
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
                  <Text style={styles.empty}>{tr('share_refs_empty')}</Text>
                )}
              </Section>

              <Section title={tr('share_rules')} footer={tr('share_rules_tip')}>
                <InputRow
                  first
                  value={draft.rules}
                  onChangeText={rules => set({rules})}
                  placeholder={tr('share_rules_ph')}
                  multiline
                />
              </Section>

              <Section title={tr('share_language')} footer={tr('share_language_tip')}>
                {SHARE_LANGUAGES.map((l, i) => (
                  <OptionRow key={l.value || 'auto'} first={i === 0} title={l.label} selected={draft.language === l.value} onPress={() => set({language: l.value})} />
                ))}
              </Section>

              <Section title={tr('share_footer')}>
                <InputRow
                  first
                  label={tr('share_footer_text')}
                  value={draft.footerText}
                  onChangeText={footerText => set({footerText})}
                  placeholder={tr('share_footer_text_ph')}
                />
                <InputRow
                  label={tr('share_footer_url')}
                  value={draft.footerUrl}
                  onChangeText={footerUrl => set({footerUrl})}
                  placeholder={tr('share_footer_url_ph')}
                  keyboardType="url"
                  mono
                />
              </Section>
            </>
          )}

          {!!error && <Text style={styles.error}>{error}</Text>}
          <ActionButton
            label={tr(slug ? 'common_save' : 'share_create')}
            tone="primary"
            loading={saving}
            onPress={save}
            style={styles.save}
          />
        </ScrollView>
      </KeyboardAvoidingView>

      <PickerSheet
        visible={modelSheet}
        title={tr('share_model')}
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
