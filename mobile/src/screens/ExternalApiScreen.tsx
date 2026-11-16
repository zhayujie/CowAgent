import type {StackScreenProps} from '@react-navigation/stack';
import React, {useEffect, useState} from 'react';
import {Pressable, ScrollView, Text, TextInput, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {probeChatApi, type ChatApiProbe} from '../api/cowApi';
import {http} from '../api/http';
import {
  ActionButton,
  CodeBlock,
  ConfirmSheet,
  Footnote,
  Notice,
  SettingRow,
  SwitchRow,
} from '../components/settings';
import {showToast, ToastHost} from '../components/Toast';
import {Chip, EmptyState, GroupLabel, PageHeader} from '../components/ui';
import {tr, trf} from '../i18n';
import type {RootStackParamList} from '../navigation/types';
import {useConfigStore} from '../store/configStore';
import {describeConnectError} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {copyText} from '../utils/clipboard';
import {formatCount, formatDuration} from '../utils/format';

type Props = StackScreenProps<RootStackParamList, 'ExternalApi'>;

type Lang = 'curl' | 'python' | 'node';
const LANGS: {key: Lang; label: string}[] = [
  {key: 'curl', label: 'curl'},
  {key: 'python', label: 'Python'},
  {key: 'node', label: 'Node'},
];

const mask = (key: string) => (key ? `${key.slice(0, 7)}••••••••${key.slice(-4)}` : '');

/** Same snippets as the console's chat API card. */
function example(lang: Lang, base: string, key: string): string {
  if (lang === 'python') {
    return [
      'import requests',
      '',
      'resp = requests.post(',
      `    "${base}/chat/completions",`,
      `    headers={"Authorization": "Bearer ${key}"},`,
      '    json={"messages": [{"role": "user", "content": "Hello"}]},',
      ')',
      'print(resp.json()["choices"][0]["message"]["content"])',
    ].join('\n');
  }
  if (lang === 'node') {
    return [
      `const resp = await fetch("${base}/chat/completions", {`,
      '  method: "POST",',
      `  headers: { "Authorization": "Bearer ${key}", "Content-Type": "application/json" },`,
      '  body: JSON.stringify({ messages: [{ role: "user", content: "Hello" }] }),',
      '});',
      'console.log((await resp.json()).choices[0].message.content);',
    ].join('\n');
  }
  return [
    `curl ${base}/chat/completions \\`,
    `  -H "Authorization: Bearer ${key}" \\`,
    '  -H "Content-Type: application/json" \\',
    `  -d '{"messages": [{"role": "user", "content": "Hello"}]}'`,
  ].join('\n');
}

export function ExternalApiScreen({navigation}: Props) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const state = useConfigStore(s => s.externalApi);
  const error = useConfigStore(s => s.error);
  const load = useConfigStore(s => s.load);
  const setExternalApi = useConfigStore(s => s.setExternalApi);
  const [revealed, setRevealed] = useState(false);
  const [lang, setLang] = useState<Lang>('curl');
  const [confirmRegen, setConfirmRegen] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [message, setMessage] = useState(() => tr('extapi_default_message'));
  const [probing, setProbing] = useState(false);
  const [probe, setProbe] = useState<ChatApiProbe | null>(null);

  useEffect(() => {
    load().catch(() => undefined);
  }, [load]);

  if (!state) {
    return (
      <View style={styles.root}>
        <PageHeader title={tr('extapi_title')} onBack={navigation.goBack} />
        <EmptyState loading={!error} title={tr('common_load_failed')} hint={error ?? undefined} />
      </View>
    );
  }

  const base = `${http.getBaseUrl()}/v1`;
  const key = state.api_key;

  const toggle = async (on: boolean) => {
    setToggling(true);
    try {
      await setExternalApi(on ? 'enable' : 'disable');
    } catch (e) {
      showToast(trf('extapi_action_failed', {error: describeConnectError(e)}));
    } finally {
      setToggling(false);
    }
  };

  const copy = async (text: string, what: string) => {
    showToast((await copyText(text)) ? trf('common_copied_what', {what}) : tr('extapi_copy_unsupported'));
  };

  const runProbe = async () => {
    setProbing(true);
    setProbe(null);
    setProbe(await probeChatApi(key, message.trim() || 'Hello'));
    setProbing(false);
  };

  return (
    <View style={styles.root}>
      <PageHeader title={tr('extapi_title')} onBack={navigation.goBack} />
      <ScrollView contentContainerStyle={{paddingBottom: insets.bottom + 32}} keyboardShouldPersistTaps="handled">
        <Notice style={styles.notice}>
          <Text style={styles.strong}>{tr('extapi_notice_strong')}</Text>
          {tr('extapi_notice_rest')}
        </Notice>
        <SwitchRow
          title={tr('extapi_enable')}
          value={state.enabled}
          disabled={toggling}
          onValueChange={toggle}
          last
        />

        {!!key && (
          <>
            <GroupLabel style={styles.group}>{tr('extapi_key')}</GroupLabel>
            <SettingRow
              title={revealed ? key : mask(key)}
              detail={tr(revealed ? 'extapi_tap_hide' : 'extapi_tap_reveal')}
              mono
              onPress={() => setRevealed(v => !v)}
              chevron={false}
              right={
                <Pressable accessibilityRole="button" hitSlop={8} onPress={() => copy(key, tr('extapi_what_key'))}>
                  <Text style={styles.link}>{tr('common_copy')}</Text>
                </Pressable>
              }
            />
            <SettingRow
              title={tr('extapi_regenerate_key')}
              detail={tr('extapi_regenerate_hint')}
              onPress={() => setConfirmRegen(true)}
              last
            />

            <GroupLabel style={styles.group}>{tr('extapi_call_info')}</GroupLabel>
            <SettingRow
              title={tr('extapi_chat_endpoint')}
              value="/v1/chat/completions"
              mono
              onPress={() => copy(`${base}/chat/completions`, tr('extapi_what_endpoint'))}
              chevron={false}
            />
            <SettingRow title={tr('extapi_models')} value="/v1/models" mono chevron={false} last />

            <GroupLabel style={styles.group}>{tr('extapi_examples')}</GroupLabel>
            <View style={styles.langs}>
              {LANGS.map(l => (
                <Chip key={l.key} label={l.label} active={lang === l.key} onPress={() => setLang(l.key)} />
              ))}
              <View style={styles.flex} />
              <Pressable
                accessibilityRole="button"
                hitSlop={8}
                onPress={() => copy(example(lang, base, key), tr('extapi_what_example'))}>
                <Text style={styles.link}>{tr('common_copy')}</Text>
              </Pressable>
            </View>
            <CodeBlock text={example(lang, base, revealed ? key : mask(key))} />
            <Footnote>{tr('extapi_context_note')}</Footnote>
          </>
        )}

        {state.enabled && !!key && (
          <>
            <GroupLabel style={styles.group}>{tr('extapi_debug')}</GroupLabel>
            <View style={styles.probe}>
              <TextInput
                value={message}
                onChangeText={setMessage}
                placeholder={tr('extapi_probe_placeholder')}
                placeholderTextColor={t.t4}
                selectionColor={t.accent}
                cursorColor={t.accent}
                multiline
                style={styles.probeInput}
              />
              <ActionButton label={tr('extapi_probe_send')} tone="primary" loading={probing} onPress={runProbe} />
            </View>
            {probe && (
              <>
                <SettingRow
                  title={tr('extapi_status')}
                  value={probe.status ? `${probe.status}${probe.status === 200 ? ' OK' : ''}` : tr('extapi_unreachable')}
                />
                <SettingRow title={tr('extapi_latency')} value={formatDuration(probe.ms)} />
                {!!probe.usage && (
                  <SettingRow
                    title="Token"
                    value={trf('extapi_tokens', {
                      input: formatCount(probe.usage.prompt_tokens ?? 0),
                      output: formatCount(probe.usage.completion_tokens ?? 0),
                    })}
                  />
                )}
                <View style={styles.reply}>
                  <Text style={styles.replyLabel}>{tr(probe.error ? 'extapi_error' : 'extapi_reply')}</Text>
                  <Text style={styles.replyText} selectable numberOfLines={12}>
                    {probe.error ?? probe.reply ?? tr('extapi_empty_reply')}
                  </Text>
                </View>
              </>
            )}
            <Footnote>{tr('extapi_probe_note')}</Footnote>
          </>
        )}
      </ScrollView>

      <ConfirmSheet
        visible={confirmRegen}
        title={tr('extapi_regenerate_key')}
        message={tr('extapi_regenerate_message')}
        confirmLabel={tr('extapi_regenerate')}
        danger
        onConfirm={async () => {
          try {
            await setExternalApi('regenerate');
            setRevealed(true);
            showToast(tr('extapi_regenerated'));
          } catch (e) {
            showToast(trf('extapi_action_failed', {error: describeConnectError(e)}));
          } finally {
            setConfirmRegen(false);
          }
        }}
        onClose={() => setConfirmRegen(false)}
      />
      <ToastHost bottom={insets.bottom + 28} />
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  notice: {marginTop: 8, marginBottom: 4},
  strong: {color: t.t1, fontWeight: '600'},
  group: {marginTop: 26},
  link: {fontSize: 13, fontWeight: '500', color: t.accent},
  langs: {flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 18, marginBottom: 10},
  flex: {flex: 1},
  probe: {gap: 10, paddingHorizontal: 18, marginBottom: 4},
  probeInput: {
    minHeight: 72,
    paddingHorizontal: 14,
    paddingVertical: 12,
    borderRadius: radius.sm,
    backgroundColor: t.bg1,
    borderWidth: 1,
    borderColor: t.line1,
    fontSize: 15,
    lineHeight: 22,
    color: t.t1,
    textAlignVertical: 'top',
  },
  reply: {marginHorizontal: 18, paddingVertical: 12},
  replyLabel: {fontSize: 12, color: t.t3, marginBottom: 6},
  replyText: {fontSize: 14, lineHeight: 22, color: t.t1},
}));
