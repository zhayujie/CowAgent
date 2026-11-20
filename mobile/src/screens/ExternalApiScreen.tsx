import type {StackScreenProps} from '@react-navigation/stack';
import React, {useEffect, useRef, useState} from 'react';
import {Pressable, ScrollView, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {getIntegrations} from '../api/cowApi';
import {http} from '../api/http';
import {CodeBlock, ConfirmSheet, Footnote, SettingRow, SwitchRow} from '../components/settings';
import {showToast, ToastHost} from '../components/Toast';
import {Chip, EmptyState, GroupLabel, PageHeader} from '../components/ui';
import {getLang, tr, trf, type MessageKey} from '../i18n';
import {openWebPage} from '../navigation/openWeb';
import type {RootStackParamList} from '../navigation/types';
import type {IntegrationsState} from '../protocol/resources';
import {useConfigStore} from '../store/configStore';
import {describeConnectError} from '../store/serverStore';
import {makeStyles} from '../theme/theme';
import {copyText} from '../utils/clipboard';
import {integrationBase} from '../utils/integrations';

type Props = StackScreenProps<RootStackParamList, 'ExternalApi'>;

type Lang = 'curl' | 'python' | 'node';
const LANGS: {key: Lang; label: string}[] = [
  {key: 'curl', label: 'cURL'},
  {key: 'python', label: 'Python'},
  {key: 'node', label: 'Node.js'},
];

type Action = 'enable' | 'disable' | 'regenerate';
const CONFIRM: Record<Action, {title: MessageKey; message: MessageKey; ok: MessageKey; danger: boolean}> = {
  enable: {title: 'extapi_enable', message: 'extapi_enable_confirm', ok: 'extapi_enable_ok', danger: false},
  disable: {title: 'extapi_disable', message: 'extapi_disable_confirm', ok: 'extapi_disable_ok', danger: true},
  regenerate: {title: 'extapi_regenerate', message: 'extapi_regenerate_confirm', ok: 'extapi_regenerate', danger: true},
};

const mask = (key: string) => (key ? `${key.slice(0, 7)}********${key.slice(-4)}` : '');

const docsUrl = () =>
  `${getLang() === 'zh' ? 'https://docs.cowagent.ai/zh' : 'https://docs.cowagent.ai'}/extensions/chat-api`;

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
      'const data = await resp.json();',
      'console.log(data.choices[0].message.content);',
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
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const state = useConfigStore(s => s.externalApi);
  const error = useConfigStore(s => s.error);
  const load = useConfigStore(s => s.load);
  const setExternalApi = useConfigStore(s => s.setExternalApi);
  const [revealed, setRevealed] = useState(false);
  const [lang, setLang] = useState<Lang>('curl');
  const [confirm, setConfirm] = useState<Action | null>(null);
  // Keeps the sheet's text while it slides away.
  const shown = useRef<Action>('enable');
  if (confirm) {
    shown.current = confirm;
  }
  const [access, setAccess] = useState<IntegrationsState | null>(null);

  useEffect(() => {
    load().catch(() => undefined);
    getIntegrations().then(setAccess, () => undefined);
  }, [load]);

  if (!state) {
    return (
      <View style={styles.root}>
        <PageHeader title={tr('extapi_title')} onBack={navigation.goBack} />
        <EmptyState loading={!error} title={tr('common_load_failed')} hint={error ?? undefined} />
      </View>
    );
  }

  const base = `${integrationBase(access, http.getBaseUrl())}/v1`;
  const key = state.api_key;
  const sheet = CONFIRM[shown.current];

  const copy = async (text: string, what: string) => {
    showToast((await copyText(text)) ? trf('common_copied_what', {what}) : tr('extapi_copy_unsupported'));
  };

  const run = async (action: Action) => {
    try {
      await setExternalApi(action);
      if (action === 'regenerate') {
        setRevealed(true);
        showToast(tr('extapi_regenerated'));
      }
    } catch (e) {
      showToast(trf('extapi_action_failed', {error: describeConnectError(e)}));
    } finally {
      setConfirm(null);
    }
  };

  const docsLink = (
    <Text style={styles.docs} onPress={() => openWebPage(docsUrl())}>
      {tr('extapi_docs')}
    </Text>
  );

  return (
    <View style={styles.root}>
      <PageHeader title={tr('extapi_title')} onBack={navigation.goBack} />
      <ScrollView contentContainerStyle={[styles.body, {paddingBottom: insets.bottom + 32}]}>
        <SwitchRow
          title={tr('extapi_title')}
          detail={tr('extapi_desc')}
          value={state.enabled}
          onValueChange={on => setConfirm(on ? 'enable' : 'disable')}
          last
        />

        {!state.enabled || !key ? (
          <Footnote>
            {tr('extapi_off_hint')} {docsLink}
          </Footnote>
        ) : (
          <>
            <GroupLabel style={styles.group}>{tr('extapi_base_url')}</GroupLabel>
            <SettingRow
              title={base}
              mono
              chevron={false}
              action={
                <Pressable accessibilityRole="button" hitSlop={8} onPress={() => copy(base, tr('extapi_base_url'))}>
                  <Text style={styles.link}>{tr('common_copy')}</Text>
                </Pressable>
              }
              last
            />

            <GroupLabel style={styles.group}>API Key</GroupLabel>
            <SettingRow
              title={revealed ? key : mask(key)}
              detail={tr(revealed ? 'extapi_tap_hide' : 'extapi_tap_reveal')}
              mono
              onPress={() => setRevealed(v => !v)}
              chevron={false}
              action={
                <Pressable accessibilityRole="button" hitSlop={8} onPress={() => copy(key, 'API Key')}>
                  <Text style={styles.link}>{tr('common_copy')}</Text>
                </Pressable>
              }
            />
            <SettingRow title={tr('extapi_regenerate')} onPress={() => setConfirm('regenerate')} last />
            <Footnote>{tr('extapi_key_hint')}</Footnote>

            <GroupLabel style={styles.group}>{tr('extapi_example')}</GroupLabel>
            <View style={styles.langs}>
              {LANGS.map(l => (
                <Chip key={l.key} label={l.label} active={lang === l.key} onPress={() => setLang(l.key)} />
              ))}
              <View style={styles.flex} />
              <Pressable
                accessibilityRole="button"
                hitSlop={8}
                onPress={() => copy(example(lang, base, key), tr('extapi_example'))}>
                <Text style={styles.link}>{tr('common_copy')}</Text>
              </Pressable>
            </View>
            <CodeBlock text={example(lang, base, revealed ? key : mask(key))} />
            <Footnote>{tr('extapi_example_hint')}</Footnote>
            <Footnote>{docsLink}</Footnote>
          </>
        )}
      </ScrollView>

      <ConfirmSheet
        visible={!!confirm}
        title={tr(sheet.title)}
        message={tr(sheet.message)}
        confirmLabel={tr(sheet.ok)}
        danger={sheet.danger}
        onConfirm={() => run(shown.current)}
        onClose={() => setConfirm(null)}
      />
      <ToastHost bottom={insets.bottom + 28} />
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  body: {paddingTop: 8},
  group: {marginTop: 26},
  link: {fontSize: 13, fontWeight: '500', color: t.accent},
  docs: {fontWeight: '500', color: t.accent},
  langs: {flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 18, marginBottom: 10},
  flex: {flex: 1},
}));
