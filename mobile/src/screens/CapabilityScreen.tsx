import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useEffect, useMemo, useState} from 'react';
import {KeyboardAvoidingView, Platform, ScrollView, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {getModels, setCapability, setVoiceReplyMode} from '../api/cowApi';
import {InfoRow, InputRow, OptionRow, PickerSheet, Section} from '../components/forms';
import {ActionButton, Notice} from '../components/settings';
import {showToast, ToastHost} from '../components/Toast';
import {EmptyState, PageHeader} from '../components/ui';
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
        <EmptyState loading={!error} title="加载失败" hint={error ?? '服务端没有返回这项能力'} />
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
      showToast(next === 'off' ? '已关闭语音回复' : '语音回复模式已保存');
    } catch (e) {
      setMode(prev);
      showToast(`保存失败：${describeConnectError(e)}`);
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
      showToast('已保存');
      await load();
    } catch (e) {
      showToast(`保存失败：${describeConnectError(e)}`);
    } finally {
      setSaving(false);
    }
  };

  const autoHint =
    !draft.provider && pick.fallback_provider
      ? `当前使用 ${[providerLabel(data, pick.fallback_provider), pick.fallback_model].filter(Boolean).join(' · ')}`
      : meta.emptyDesc;

  const modelSection = !!draft.provider && (
    <Section
      title="模型"
      footer={
        key === 'embedding'
          ? `${pick.current_dim ? `当前维度 ${pick.current_dim}。` : ''}切换向量模型后，已有索引将失效，需要重建。`
          : undefined
      }>
      {typedOnly ? (
        <InputRow
          first
          value={draft.typed}
          onChangeText={typed => setDraft({...draft, typed})}
          placeholder="填写模型 ID"
          mono
        />
      ) : models.length > INLINE_MODELS && !draft.typing ? (
        <InfoRow first title="模型" value={draft.model || '请选择'} mono onPress={() => setSheet('model')} />
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
        <InfoRow first title="从列表选择" onPress={() => setSheet('model')} />
      )}
      {!typedOnly && meta.freeModel && (
        <OptionRow
          first={!models.length}
          title="自定义"
          hint="列表里没有时，手动填写模型 ID"
          selected={draft.typing}
          onPress={() => setDraft({...draft, typing: true})}
        />
      )}
      {!typedOnly && draft.typing && (
        <InputRow value={draft.typed} onChangeText={typed => setDraft({...draft, typed})} placeholder="填写模型 ID" mono />
      )}
    </Section>
  );

  return (
    <View style={styles.root}>
      <PageHeader title={meta.title} subtitle={meta.blurb} onBack={navigation.goBack} />
      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={{paddingBottom: insets.bottom + 32}} keyboardShouldPersistTaps="handled">
          {locked && <Notice style={styles.notice}>{pick.note || '这项能力由当前主模型决定，不能单独设置。'}</Notice>}

          {key === 'tts' && (
            <Section title="语音回复" footer="决定何时以语音回复用户">
              {REPLY_MODES.map((m, i) => (
                <OptionRow key={m.value} first={i === 0} title={m.label} selected={mode === m.value} onPress={() => saveMode(m.value)} />
              ))}
            </Section>
          )}

          {showChoice && !locked && (
            <>
              <Section title="厂商" footer={providers.length ? undefined : '还没有能提供这项能力的厂商，先在「模型厂商」里填入 API Key'}>
                {!!meta.emptyLabel && (
                  <OptionRow first title={meta.emptyLabel} hint={autoHint} selected={!draft.provider} onPress={() => chooseProvider('')} />
                )}
                {providers.map((id, i) => (
                  <OptionRow
                    key={id}
                    first={!meta.emptyLabel && i === 0}
                    title={providerLabel(data, id)}
                    hint={data.providers.find(p => p.id === id)?.configured === false ? '未配置 API Key' : undefined}
                    selected={draft.provider === id}
                    onPress={() => chooseProvider(id)}
                  />
                ))}
              </Section>
              {modelSection}
              {key === 'tts' && !!draft.provider && !!voices.length && (
                <Section title="音色">
                  <InfoRow
                    first
                    title="音色"
                    value={draft.voice || '请选择'}
                    hint={voices.find(v => v.value === draft.voice)?.hint}
                    onPress={() => setSheet('voice')}
                  />
                </Section>
              )}
              {!!pick.note && <Notice style={styles.notice}>{pick.note}</Notice>}
              <ActionButton
                label="保存"
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
        title="选择模型"
        options={models}
        selected={draft.typing ? undefined : draft.model}
        mono
        onSelect={chooseModel}
        onClose={() => setSheet(null)}
      />
      <PickerSheet
        visible={sheet === 'voice'}
        title="选择音色"
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
