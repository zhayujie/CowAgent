import {faArrowUpRightFromSquare} from '@fortawesome/free-solid-svg-icons';
import React, {useEffect, useState} from 'react';
import {Pressable, ScrollView, Text, TextInput, View} from 'react-native';
import {clearProviderCredential, saveCustomCatalog, setCustomProvider, setProviderCredential} from '../api/cowApi';
import {tr} from '../i18n';
import {openWebPage} from '../navigation/openWeb';
import type {CatalogModel, ProviderEntry} from '../protocol/resources';
import {describeConnectError} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {Icon} from './Icon';
import {labelText} from './ModelPicker';
import {ActionButton, MONO} from './settings';
import {Sheet} from './Sheet';
import {Chip} from './ui';

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
  onCleared,
}: {
  provider: ProviderEntry | null;
  /** Shown above the hint, e.g. that search shares these credentials. */
  note?: string;
  onClose: () => void;
  onSaved: () => Promise<void>;
  /** Offers to forget a saved key; called once it is gone. */
  onCleared?: () => Promise<void>;
}) {
  const t = useTheme();
  const styles = useStyles();
  const [key, setKey] = useState('');
  const [base, setBase] = useState('');
  const [busy, setBusy] = useState<'save' | 'clear' | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (provider) {
      setKey('');
      setBase(provider.api_base ?? '');
      setConfirmClear(false);
      setError(null);
    }
  }, [provider]);

  const hasBase = !!provider?.api_base_field;
  const presets = (hasBase && provider?.api_base_presets) || [];
  const preset = presets.find(p => p.value === base.trim());
  const baseChanged = hasBase && base.trim() !== (provider?.api_base ?? '');
  const save = async () => {
    if (!provider) {
      return;
    }
    setBusy('save');
    setError(null);
    try {
      await setProviderCredential(provider.id, key.trim(), baseChanged ? base.trim() : undefined);
      await onSaved();
    } catch (e) {
      setError(describeConnectError(e));
    } finally {
      setBusy(null);
    }
  };

  const clear = async () => {
    if (!provider || !onCleared) {
      return;
    }
    if (!confirmClear) {
      setConfirmClear(true);
      return;
    }
    setBusy('clear');
    setError(null);
    try {
      await clearProviderCredential(provider.id);
      await onCleared();
    } catch (e) {
      setError(describeConnectError(e));
    } finally {
      setBusy(null);
      setConfirmClear(false);
    }
  };

  const hint = error
    ? error
    : confirmClear
      ? tr('settings_clear_key_warn')
      : provider?.configured
        ? tr('settings_key_keep_hint')
        : tr('settings_key_local_hint');

  return (
    <Sheet visible={!!provider} onClose={onClose} title={provider ? labelText(provider.label, provider.id) : ''}>
      <ScrollView style={styles.scroll} keyboardShouldPersistTaps="handled">
        <View style={styles.body}>
          {!!note && <Text style={styles.note}>{note}</Text>}
          {presets.length > 0 && (
            <>
              <Text style={styles.fieldLabel}>{tr('settings_api_site')}</Text>
              <View style={styles.presets}>
                {presets.map(p => (
                  <Chip
                    key={p.value}
                    label={labelText(p.label, p.value)}
                    active={p.value === base.trim()}
                    onPress={() => setBase(p.value)}
                  />
                ))}
              </View>
            </>
          )}
          <Field
            label="API Key"
            value={key}
            onChangeText={setKey}
            placeholder={provider?.api_key_masked ? compactMask(provider.api_key_masked) : tr('settings_paste_api_key')}
            secure
          />
          {!!preset?.keys_url && (
            <Pressable
              accessibilityRole="link"
              hitSlop={6}
              onPress={() => openWebPage(preset.keys_url!)}
              style={({pressed}) => [styles.link, pressed && styles.pressed]}>
              <Text style={styles.linkText}>{tr('settings_get_key')}</Text>
              <Icon icon={faArrowUpRightFromSquare} size={10} color={t.accent} />
            </Pressable>
          )}
          {hasBase && !presets.length && (
            <Field
              label={tr('settings_api_base')}
              value={base}
              onChangeText={setBase}
              placeholder={provider?.api_base_placeholder || provider?.api_base_default || 'https://'}
              mono
              url
            />
          )}
          <Text style={[styles.hint, (!!error || confirmClear) && styles.error]}>{hint}</Text>
          <ActionButton
            label={tr('common_save')}
            tone="primary"
            loading={busy === 'save'}
            disabled={(!key.trim() && !baseChanged) || busy === 'clear'}
            onPress={save}
            style={styles.button}
          />
          {!!onCleared && !!provider?.configured && (
            <ActionButton
              label={confirmClear ? tr('settings_clear_key_confirm') : tr('settings_clear_key')}
              tone={confirmClear ? 'danger' : 'quiet'}
              loading={busy === 'clear'}
              disabled={busy === 'save'}
              onPress={clear}
              style={styles.deleteButton}
            />
          )}
        </View>
      </ScrollView>
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
      setError(tr('settings_need_name'));
      return;
    }
    if (!/^https?:\/\//i.test(base.trim())) {
      setError(tr('settings_api_base_invalid'));
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
    <Sheet
      visible={!!target}
      onClose={onClose}
      title={editing ? tr('settings_edit_custom_vendor') : tr('settings_add_custom_vendor')}>
      <ScrollView style={styles.scroll} keyboardShouldPersistTaps="handled">
        <View style={styles.body}>
          <Field label={tr('common_name')} value={name} onChangeText={setName} placeholder={tr('settings_custom_name_ph')} />
          <Field label={tr('settings_api_base')} value={base} onChangeText={setBase} placeholder="https://…/v1" mono url />
          <Field
            label="API Key"
            value={key}
            onChangeText={setKey}
            placeholder={editing?.api_key_masked ? compactMask(editing.api_key_masked) : tr('settings_optional_key_ph')}
            secure
          />
          <Field
            label={tr('settings_model')}
            value={models}
            onChangeText={setModels}
            placeholder={tr('settings_models_ph')}
            mono
          />
          <Text style={[styles.hint, !!error && styles.error]}>{error ?? tr('settings_custom_vendor_hint')}</Text>
          <ActionButton label={tr('common_save')} tone="primary" loading={busy} onPress={save} style={styles.button} />
          {!!editing && (
            <ActionButton
              label={tr('settings_delete_vendor')}
              tone="danger"
              onPress={() => onDelete(editing)}
              style={styles.deleteButton}
            />
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
  presets: {flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: 8},
  link: {flexDirection: 'row', alignItems: 'center', gap: 5, alignSelf: 'flex-start', paddingVertical: 4},
  linkText: {fontSize: 13, fontWeight: '500', color: t.accent},
  pressed: {opacity: 0.6},
  error: {color: t.danger},
  button: {marginTop: 14, marginBottom: 4},
  deleteButton: {marginTop: 8, marginBottom: 4},
}));
