import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useEffect, useMemo, useState} from 'react';
import {KeyboardAvoidingView, Platform, ScrollView, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {getModels, setCapability, setVoiceReplyMode} from '../api/cowApi';
import {InfoRow, InputRow, OptionRow, PickerSheet, Section} from '../components/forms';
import {ActionButton, Notice} from '../components/settings';
import {showToast, ToastHost} from '../components/Toast';
import {EmptyState, PageHeader} from '../components/ui';
import {tr, trf} from '../i18n';
import type {RootStackParamList} from '../navigation/types';
import type {CapabilityPick, ModelsState, VoiceReplyMode} from '../protocol/resources';
import {describeConnectError} from '../store/serverStore';
import {makeStyles} from '../theme/theme';
import {
  CAPABILITY_META,
  capabilityProviders,
  needsTypedModel,
  providerLabel,
  REPLY_MODES,
  resolveModels,
  resolveVoices,
} from '../utils/capabilities';

type Props = StackScreenProps<RootStackParamList, 'Capability'>;

/** Past this many models the list moves into a sheet instead of filling the page. */
const INLINE_MODELS = 8;

interface Draft {
  provider: string;
  model: string;
  /** Typed model id: custom vendors without a catalog, or "自定义" where allowed. */
  typed: string;
  typing: boolean;
  voice: string;
}

function initialDraft(data: ModelsState, pick: CapabilityPick, freeModel: boolean): Draft {
  const provider = pick.current_provider ?? '';
  const model = pick.current_model ?? '';
  const typedOnly = needsTypedModel(
    data.providers.find(p => p.id === provider),
    provider,
  );
  const listed = resolveModels(data, pick, provider).some(o => o.value === model);
  const typing = typedOnly || (freeModel && !!model && !listed);
  return {provider, model: typing ? '' : model, typed: typing ? model : '', typing, voice: pick.current_voice ?? ''};
}

export function CapabilityScreen({navigation, route}: Props) {
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const {key} = route.params;
  const meta = CAPABILITY_META[key];
  const [data, setData] = useState<ModelsState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [sheet, setSheet] = useState<'model' | 'voice' | null>(null);
  const [saving, setSaving] = useState(false);
  const [mode, setMode] = useState<VoiceReplyMode>('off');

  const load = useCallback(async () => {
    try {
      const next = await getModels();
      const pick = next.capabilities[key];
      setData(next);
      if (pick) {
        setDraft(initialDraft(next, pick, !!meta.freeModel));
        setMode(pick.reply_mode ?? 'off');
      }
      setError(null);
    } catch (e) {
      setError(describeConnectError(e));
    }
  }, [key, meta.freeModel]);

  useEffect(() => {
    load();
  }, [load]);

  const pick = data?.capabilities[key];
  const providers = useMemo(
    () => (data && pick && draft ? capabilityProviders(data, pick, draft.provider) : []),
    [data, pick, draft],
  );

  if (!data || !pick || !draft) {
    return (
      <View style={styles.root}>
        <PageHeader title={meta.title} onBack={navigation.goBack} />
        <EmptyState loading={!error} title={tr('common_load_failed')} hint={error ?? tr('settings_cap_missing')} />
      </View>
    );
  }

  const initial = initialDraft(data, pick, !!meta.freeModel);
  const vendor = data.providers.find(p => p.id === draft.provider);
  const typedOnly = needsTypedModel(vendor, draft.provider);
  const models = resolveModels(data, pick, draft.provider);
  const finalModel = draft.typing ? draft.typed.trim() : draft.model;
  const voices = key === 'tts' ? resolveVoices(pick, draft.provider, finalModel) : [];
  const locked = pick.editable === false;
  const dirty =
    draft.provider !== initial.provider ||
    finalModel !== (initial.typing ? initial.typed : initial.model) ||
    (key === 'tts' && draft.voice !== initial.voice);
  const showChoice = key !== 'tts' || mode !== 'off';

  const chooseProvider = (id: string) => {
    if (id === draft.provider) {
      return;
    }
    if (needsTypedModel(data.providers.find(p => p.id === id), id)) {
      const typed = id === pick.current_provider ? pick.current_model ?? '' : '';
      setDraft({provider: id, model: '', typed, typing: true, voice: ''});
      return;
    }
    const first = resolveModels(data, pick, id)[0]?.value ?? '';
    setDraft({provider: id, model: first, typed: '', typing: false, voice: resolveVoices(pick, id, first)[0]?.value ?? ''});
  };

  const chooseModel = (model: string) => {
    setSheet(null);
    setDraft({...draft, model, typing: false, voice: resolveVoices(pick, draft.provider, model)[0]?.value ?? ''});
  };

  const saveMode = async (next: VoiceReplyMode) => {
    const prev = mode;
    setMode(next);
    try {
      await setVoiceReplyMode(next);
      showToast(next === 'off' ? tr('settings_voice_reply_off_toast') : tr('settings_voice_reply_saved'));
    } catch (e) {
      setMode(prev);
      showToast(trf('common_save_failed_detail', {error: describeConnectError(e)}));
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      await setCapability({
        capability: key,
        provider_id: draft.provider,
        model: finalModel,
        ...(key === 'tts' ? {voice: draft.voice} : {}),
      });
      showToast(tr('common_saved'));
      await load();
    } catch (e) {
      showToast(trf('common_save_failed_detail', {error: describeConnectError(e)}));
    } finally {
      setSaving(false);
    }
  };

  const autoHint =
    !draft.provider && pick.fallback_provider
      ? trf('settings_currently_using', {
          name: [providerLabel(data, pick.fallback_provider), pick.fallback_model].filter(Boolean).join(' · '),
        })
      : meta.emptyDesc;

  const modelSection = !!draft.provider && (
    <Section
      title={tr('settings_model')}
      footer={
        key === 'embedding'
          ? `${pick.current_dim ? trf('settings_embedding_dim', {dim: pick.current_dim}) : ''}${tr('settings_embedding_rebuild')}`
          : undefined
      }>
      {typedOnly ? (
        <InputRow
          first
          value={draft.typed}
          onChangeText={typed => setDraft({...draft, typed})}
          placeholder={tr('settings_model_id_ph')}
          mono
        />
      ) : models.length > INLINE_MODELS && !draft.typing ? (
        <InfoRow
          first
          title={tr('settings_model')}
          value={draft.model || tr('settings_please_select')}
          mono
          onPress={() => setSheet('model')}
        />
      ) : (
        models.map((m, i) => (
          <OptionRow
            key={m.value}
            first={i === 0}
            title={m.value}
            hint={m.hint}
            mono
            selected={!draft.typing && draft.model === m.value}
            onPress={() => chooseModel(m.value)}
          />
        ))
      )}
      {!typedOnly && models.length > INLINE_MODELS && draft.typing && (
        <InfoRow first title={tr('settings_pick_from_list')} onPress={() => setSheet('model')} />
      )}
      {!typedOnly && meta.freeModel && (
        <OptionRow
          first={!models.length}
          title={tr('settings_custom')}
          hint={tr('settings_custom_model_hint')}
          selected={draft.typing}
          onPress={() => setDraft({...draft, typing: true})}
        />
      )}
      {!typedOnly && draft.typing && (
        <InputRow
          value={draft.typed}
          onChangeText={typed => setDraft({...draft, typed})}
          placeholder={tr('settings_model_id_ph')}
          mono
        />
      )}
    </Section>
  );

  return (
    <View style={styles.root}>
      <PageHeader title={meta.title} subtitle={meta.blurb} onBack={navigation.goBack} />
      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={{paddingBottom: insets.bottom + 32}} keyboardShouldPersistTaps="handled">
          {locked && <Notice style={styles.notice}>{pick.note || tr('settings_cap_locked')}</Notice>}

          {key === 'tts' && (
            <Section title={tr('settings_voice_reply')} footer={tr('settings_voice_reply_footer')}>
              {REPLY_MODES.map((m, i) => (
                <OptionRow key={m.value} first={i === 0} title={m.label} selected={mode === m.value} onPress={() => saveMode(m.value)} />
              ))}
            </Section>
          )}

          {showChoice && !locked && (
            <>
              <Section title={tr('settings_vendor')} footer={providers.length ? undefined : tr('settings_no_vendor_for_cap')}>
                {!!meta.emptyLabel && (
                  <OptionRow first title={meta.emptyLabel} hint={autoHint} selected={!draft.provider} onPress={() => chooseProvider('')} />
                )}
                {providers.map((id, i) => (
                  <OptionRow
                    key={id}
                    first={!meta.emptyLabel && i === 0}
                    title={providerLabel(data, id)}
                    hint={data.providers.find(p => p.id === id)?.configured === false ? tr('settings_no_api_key') : undefined}
                    selected={draft.provider === id}
                    onPress={() => chooseProvider(id)}
                  />
                ))}
              </Section>
              {modelSection}
              {key === 'tts' && !!draft.provider && !!voices.length && (
                <Section title={tr('settings_voice')}>
                  <InfoRow
                    first
                    title={tr('settings_voice')}
                    value={draft.voice || tr('settings_please_select')}
                    hint={voices.find(v => v.value === draft.voice)?.hint}
                    onPress={() => setSheet('voice')}
                  />
                </Section>
              )}
              {!!pick.note && <Notice style={styles.notice}>{pick.note}</Notice>}
              <ActionButton
                label={tr('common_save')}
                tone="primary"
                loading={saving}
                disabled={!dirty || (!!draft.provider && !finalModel)}
                onPress={save}
                style={styles.save}
              />
            </>
          )}
        </ScrollView>
      </KeyboardAvoidingView>

      <PickerSheet
        visible={sheet === 'model'}
        title={tr('settings_select_model')}
        options={models}
        selected={draft.typing ? undefined : draft.model}
        mono
        onSelect={chooseModel}
        onClose={() => setSheet(null)}
      />
      <PickerSheet
        visible={sheet === 'voice'}
        title={tr('settings_select_voice')}
        options={voices}
        selected={draft.voice}
        onSelect={voice => {
          setSheet(null);
          setDraft({...draft, voice});
        }}
        onClose={() => setSheet(null)}
      />
      <ToastHost bottom={insets.bottom + 28} />
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  flex: {flex: 1},
  notice: {marginHorizontal: 14, marginTop: 16},
  save: {marginHorizontal: 14, marginTop: 24},
}));
