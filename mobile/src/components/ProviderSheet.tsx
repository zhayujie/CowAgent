import React, {useEffect, useState} from 'react';
import {ScrollView, Text, TextInput, View} from 'react-native';
import {saveCustomCatalog, setCustomProvider, setProviderCredential} from '../api/cowApi';
import type {CatalogModel, ProviderEntry} from '../protocol/resources';
import {describeConnectError} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {labelText} from './ModelPicker';
import {ActionButton, MONO} from './settings';
import {Sheet} from './Sheet';

/** The server masks keys with one * per hidden character, which overruns a phone row. */
export const compactMask = (masked: string) => masked.replace(/\*{4,}/g, '••••');

function Field({
  label,
  value,
  onChangeText,
  placeholder,
  secure,
  mono,
  url,
}: {
  label: string;
  value: string;
  onChangeText: (v: string) => void;
  placeholder?: string;
  secure?: boolean;
  mono?: boolean;
  url?: boolean;
}) {
  const t = useTheme();
  const styles = useStyles();
  return (
    <>
      <Text style={styles.fieldLabel}>{label}</Text>
      <TextInput
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={t.t4}
        selectionColor={t.accent}
        cursorColor={t.accent}
        autoCapitalize="none"
        autoCorrect={false}
        secureTextEntry={secure}
        keyboardType={url ? 'url' : 'default'}
        accessibilityLabel={label}
        style={[styles.field, mono && styles.mono]}
      />
    </>
  );
}

/** API key (and base, where the vendor has one) of a built-in vendor. */
export function ProviderSheet({
  provider,
  note,
  onClose,
  onSaved,
}: {
  provider: ProviderEntry | null;
  /** Shown above the hint, e.g. that search shares these credentials. */
  note?: string;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const styles = useStyles();
  const [key, setKey] = useState('');
  const [base, setBase] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (provider) {
      setKey('');
      setBase(provider.api_base ?? '');
      setError(null);
    }
  }, [provider]);

  const hasBase = !!provider?.api_base_field;
  const baseChanged = hasBase && base.trim() !== (provider?.api_base ?? '');
  const save = async () => {
    if (!provider) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await setProviderCredential(provider.id, key.trim(), baseChanged ? base.trim() : undefined);
      await onSaved();
    } catch (e) {
      setError(describeConnectError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet visible={!!provider} onClose={onClose} title={provider ? labelText(provider.label, provider.id) : ''}>
      <View style={styles.body}>
        {!!note && <Text style={styles.note}>{note}</Text>}
        <Field
          label="API Key"
          value={key}
          onChangeText={setKey}
          placeholder={provider?.api_key_masked ? compactMask(provider.api_key_masked) : '粘贴 API Key'}
          secure
        />
        {hasBase && (
          <Field
            label="接口地址"
            value={base}
            onChangeText={setBase}
            placeholder={provider?.api_base_placeholder || provider?.api_base_default || 'https://'}
            mono
            url
          />
        )}
        <Text style={[styles.hint, !!error && styles.error]}>
          {error ?? (provider?.configured ? '留空表示保留当前 Key，只改接口地址。' : 'Key 只保存在你的 CowAgent 服务端。')}
        </Text>
        <ActionButton
          label="保存"
          tone="primary"
          loading={busy}
          disabled={!key.trim() && !baseChanged}
          onPress={save}
          style={styles.button}
        />
      </View>
    </Sheet>
  );
}

const splitModels = (raw: string) => [
  ...new Set(
    raw
      .split(/[\n,，]/)
      .map(s => s.trim())
      .filter(Boolean),
  ),
];

/**
 * Any OpenAI-compatible endpoint. The model list doubles as its catalog, so the
 * models typed here show up in every model picker.
 */
export function CustomProviderSheet({
  target,
  onClose,
  onSaved,
  onDelete,
}: {
  target: ProviderEntry | 'new' | null;
  onClose: () => void;
  onSaved: (name: string) => Promise<void>;
  onDelete: (provider: ProviderEntry) => void;
}) {
  const styles = useStyles();
  const editing = target && target !== 'new' ? target : null;
  const [name, setName] = useState('');
  const [base, setBase] = useState('');
  const [key, setKey] = useState('');
  const [models, setModels] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!target) {
      return;
    }
    setName(editing ? editing.custom_name || labelText(editing.label, '') : '');
    setBase(editing?.api_base ?? '');
    setKey('');
    setModels((editing?.effective?.length ? editing.effective.map(m => m.name) : editing?.models ?? []).join(', '));
    setError(null);
  }, [target, editing]);

  const save = async () => {
    const list = splitModels(models);
    if (!name.trim()) {
      setError('请填写名称');
      return;
    }
    if (!/^https?:\/\//i.test(base.trim())) {
      setError('接口地址需要以 http:// 或 https:// 开头');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await setCustomProvider({
        ...(editing?.custom_id ? {id: editing.custom_id} : {}),
        name: name.trim(),
        api_base: base.trim(),
        ...(key.trim() ? {api_key: key.trim()} : {}),
        ...(list[0] ? {model: list[0]} : {}),
      });
      const cid = res.id || editing?.custom_id;
      const saved = editing?.catalog ?? [];
      if (cid && list.join('\n') !== saved.map(m => m.name).join('\n')) {
        const catalog: CatalogModel[] = list.map(n => saved.find(m => m.name === n) ?? {name: n, capabilities: ['text']});
        await saveCustomCatalog(`custom:${cid}`, catalog);
      }
      await onSaved(name.trim());
    } catch (e) {
      setError(describeConnectError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet visible={!!target} onClose={onClose} title={editing ? '编辑自定义厂商' : '添加自定义厂商'}>
      <ScrollView style={styles.scroll} keyboardShouldPersistTaps="handled">
        <View style={styles.body}>
          <Field label="名称" value={name} onChangeText={setName} placeholder="如「公司网关」" />
          <Field label="接口地址" value={base} onChangeText={setBase} placeholder="https://…/v1" mono url />
          <Field
            label="API Key"
            value={key}
            onChangeText={setKey}
            placeholder={editing?.api_key_masked ? compactMask(editing.api_key_masked) : '没有可留空'}
            secure
          />
          <Field label="模型" value={models} onChangeText={setModels} placeholder="模型 ID，多个用逗号分隔" mono />
          <Text style={[styles.hint, !!error && styles.error]}>
            {error ?? '接口需遵循 OpenAI API 协议。第一个模型作为默认模型。'}
          </Text>
          <ActionButton label="保存" tone="primary" loading={busy} onPress={save} style={styles.button} />
          {!!editing && (
            <ActionButton label="删除厂商" tone="danger" onPress={() => onDelete(editing)} style={styles.deleteButton} />
          )}
        </View>
      </ScrollView>
    </Sheet>
  );
}

const useStyles = makeStyles(t => ({
  scroll: {flexGrow: 0, flexShrink: 1},
  body: {paddingHorizontal: 12, paddingTop: 2},
  note: {fontSize: 13, lineHeight: 19, color: t.t2, paddingBottom: 8},
  fieldLabel: {fontSize: 12, color: t.t3, marginBottom: 6, marginTop: 6},
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
    marginBottom: 6,
  },
  mono: {fontFamily: MONO, fontSize: 13},
  hint: {fontSize: 12, lineHeight: 18, color: t.t4, paddingTop: 4},
  error: {color: t.danger},
  button: {marginTop: 14, marginBottom: 4},
  deleteButton: {marginTop: 8, marginBottom: 4},
}));
