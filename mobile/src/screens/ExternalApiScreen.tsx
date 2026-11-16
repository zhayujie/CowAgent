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
  const [message, setMessage] = useState('你好，用一句话介绍你自己');
  const [probing, setProbing] = useState(false);
  const [probe, setProbe] = useState<ChatApiProbe | null>(null);

  useEffect(() => {
    load().catch(() => undefined);
  }, [load]);

  if (!state) {
    return (
      <View style={styles.root}>
        <PageHeader title="开放对话 API" onBack={navigation.goBack} />
        <EmptyState loading={!error} title="加载失败" hint={error ?? undefined} />
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
      showToast(`操作失败：${describeConnectError(e)}`);
    } finally {
      setToggling(false);
    }
  };

  const copy = async (text: string, what: string) => {
    showToast((await copyText(text)) ? `已复制${what}` : '当前环境不支持复制，请长按文本手动选择');
  };

  const runProbe = async () => {
    setProbing(true);
    setProbe(null);
    setProbe(await probeChatApi(key, message.trim() || 'Hello'));
    setProbing(false);
  };

  return (
    <View style={styles.root}>
      <PageHeader title="开放对话 API" onBack={navigation.goBack} />
      <ScrollView contentContainerStyle={{paddingBottom: insets.bottom + 32}} keyboardShouldPersistTaps="handled">
        <Notice style={styles.notice}>
          <Text style={styles.strong}>接口兼容 OpenAI 格式</Text>，其他应用可以像调用模型一样调用你的 Agent。关闭后密钥仍保留，重新开启即可继续使用。
        </Notice>
        <SwitchRow
          title="启用对话 API"
          value={state.enabled}
          disabled={toggling}
          onValueChange={toggle}
          last
        />

        {!!key && (
          <>
            <GroupLabel style={styles.group}>API 密钥</GroupLabel>
            <SettingRow
              title={revealed ? key : mask(key)}
              detail={revealed ? '点按隐藏' : '点按显示完整密钥'}
              mono
              onPress={() => setRevealed(v => !v)}
              chevron={false}
              right={
                <Pressable accessibilityRole="button" hitSlop={8} onPress={() => copy(key, '密钥')}>
                  <Text style={styles.link}>复制</Text>
                </Pressable>
              }
            />
            <SettingRow title="重新生成密钥" detail="旧密钥会立即失效" onPress={() => setConfirmRegen(true)} last />

            <GroupLabel style={styles.group}>调用信息</GroupLabel>
            <SettingRow
              title="对话接口"
              value="/v1/chat/completions"
              mono
              onPress={() => copy(`${base}/chat/completions`, '接口地址')}
              chevron={false}
            />
            <SettingRow title="模型列表" value="/v1/models" mono chevron={false} last />

            <GroupLabel style={styles.group}>调用示例</GroupLabel>
            <View style={styles.langs}>
              {LANGS.map(l => (
                <Chip key={l.key} label={l.label} active={lang === l.key} onPress={() => setLang(l.key)} />
              ))}
              <View style={styles.flex} />
              <Pressable accessibilityRole="button" hitSlop={8} onPress={() => copy(example(lang, base, key), '示例代码')}>
                <Text style={styles.link}>复制</Text>
              </Pressable>
            </View>
            <CodeBlock text={example(lang, base, revealed ? key : mask(key))} />
            <Footnote>
              不传 conversation_id 时每次请求自带完整上下文，服务端不保留；传入 conversation_id 则由服务端保存这段对话的历史。
            </Footnote>
          </>
        )}

        {state.enabled && !!key && (
          <>
            <GroupLabel style={styles.group}>接口调试</GroupLabel>
            <View style={styles.probe}>
              <TextInput
                value={message}
                onChangeText={setMessage}
                placeholder="发一句话试试"
                placeholderTextColor={t.t4}
                selectionColor={t.accent}
                cursorColor={t.accent}
                multiline
                style={styles.probeInput}
              />
              <ActionButton label="发送测试请求" tone="primary" loading={probing} onPress={runProbe} />
            </View>
            {probe && (
              <>
                <SettingRow
                  title="状态"
                  value={probe.status ? `${probe.status}${probe.status === 200 ? ' OK' : ''}` : '未连通'}
                />
                <SettingRow title="耗时" value={formatDuration(probe.ms)} />
                {!!probe.usage && (
                  <SettingRow
                    title="Token"
                    value={`输入 ${formatCount(probe.usage.prompt_tokens ?? 0)} · 输出 ${formatCount(
                      probe.usage.completion_tokens ?? 0,
                    )}`}
                  />
                )}
                <View style={styles.reply}>
                  <Text style={styles.replyLabel}>{probe.error ? '错误信息' : '回复'}</Text>
                  <Text style={styles.replyText} selectable numberOfLines={12}>
                    {probe.error ?? probe.reply ?? '（空回复）'}
                  </Text>
                </View>
              </>
            )}
            <Footnote>测试请求会真实调用一次 Agent，计入模型用量。</Footnote>
          </>
        )}
      </ScrollView>

      <ConfirmSheet
        visible={confirmRegen}
        title="重新生成密钥"
        message="旧密钥会立即失效，正在使用它的调用方需要换成新密钥。"
        confirmLabel="重新生成"
        danger
        onConfirm={async () => {
          try {
            await setExternalApi('regenerate');
            setRevealed(true);
            showToast('已生成新密钥');
          } catch (e) {
            showToast(`操作失败：${describeConnectError(e)}`);
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
