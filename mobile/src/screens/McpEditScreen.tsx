import {faChevronRight, faCircleCheck, faCircleXmark} from '@fortawesome/free-solid-svg-icons';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useState} from 'react';
import {ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, TextInput, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {testMcpServer} from '../api/cowApi';
import {Icon} from '../components/Icon';
import {ActionButton, Footnote, MONO, Toggle} from '../components/settings';
import {Chip, PageHeader, Segmented} from '../components/ui';
import type {RootStackParamList} from '../navigation/types';
import type {McpProbe, McpServer, McpTransport} from '../protocol/resources';
import {MCP_TRANSPORT_LABEL, mcpTransport, useMcpStore} from '../store/mcpStore';
import {describeConnectError} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {kvToObject, MCP_JSON_PLACEHOLDER, mcpServersToJson, objectToKv, parseMcpJson} from '../utils/mcp';
import {omit} from '../utils/object';

type Props = StackScreenProps<RootStackParamList, 'McpEdit'>;
type Mode = 'form' | 'json';
type Probe = McpProbe & {name: string};
type Result = {kind: 'error'; text: string} | {kind: 'probes'; probes: Probe[]; note?: string} | null;

const TRANSPORTS: McpTransport[] = ['stdio', 'streamable-http', 'sse'];
/** The fields the form owns; anything else on the stored config rides along untouched. */
const FORM_KEYS = ['name', 'type', 'command', 'args', 'env', 'url', 'headers', 'timeout', 'disabled', 'tool_name_prefix', 'scope', 'status'];

export function McpEditScreen({route, navigation}: Props) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const originalName = route.params?.name;
  const original = useMcpStore(s => s.servers?.find(x => x.name === originalName));
  const servers = useMcpStore(s => s.servers);
  const upsert = useMcpStore(s => s.upsert);
  const merge = useMcpStore(s => s.merge);

  const [mode, setMode] = useState<Mode>('form');
  const [name, setName] = useState(original?.name ?? '');
  const [type, setType] = useState<McpTransport>((original ? mcpTransport(original) : 'stdio') as McpTransport);
  const [command, setCommand] = useState(original?.command ?? '');
  const [args, setArgs] = useState((original?.args ?? []).join('\n'));
  const [env, setEnv] = useState(objectToKv(original?.env));
  const [url, setUrl] = useState(original?.url ?? '');
  const [headers, setHeaders] = useState(objectToKv(original?.headers));
  const [timeout, setTimeoutValue] = useState(original?.timeout ? String(original.timeout) : '');
  const [prefix, setPrefix] = useState(String(original?.tool_name_prefix ?? ''));
  const [scope, setScope] = useState(String(original?.scope ?? ''));
  const [enabled, setEnabled] = useState(!original?.disabled);
  const [advanced, setAdvanced] = useState(!!(original?.timeout || original?.tool_name_prefix || original?.scope));
  const [json, setJson] = useState(original ? mcpServersToJson([original]) : '');
  const [busy, setBusy] = useState<'save' | 'test' | null>(null);
  const [result, setResult] = useState<Result>(null);
  // After a failed check the next save skips it: the reason is on screen and the user chose to keep it.
  const [saveAnyway, setSaveAnyway] = useState(false);

  const edited = <T,>(set: (v: T) => void) => (v: T) => {
    set(v);
    setSaveAnyway(false);
  };

  const fromForm = (): McpServer => {
    const trimmedName = name.trim();
    if (!trimmedName) {
      throw new Error('先给服务起个名字');
    }
    const seconds = timeout.trim() ? Number(timeout.trim()) : undefined;
    if (seconds !== undefined && (!Number.isInteger(seconds) || seconds <= 0)) {
      throw new Error('超时需要是正整数秒');
    }
    const kept = original ? omit(original, FORM_KEYS as (keyof McpServer)[]) : {};
    const cfg: McpServer = {...kept, name: trimmedName, type};
    if (seconds) {
      cfg.timeout = seconds;
    }
    if (prefix.trim()) {
      cfg.tool_name_prefix = prefix.trim();
    }
    if (!enabled) {
      cfg.disabled = true;
    }
    if (type === 'stdio') {
      if (!command.trim()) {
        throw new Error('填写启动命令，如 npx 或 uvx');
      }
      cfg.command = command.trim();
      const list = args
        .split(/\r?\n/)
        .map(a => a.trim())
        .filter(Boolean);
      if (list.length) {
        cfg.args = list;
      }
      const envMap = kvToObject(env);
      if (Object.keys(envMap).length) {
        cfg.env = envMap;
      }
    } else {
      if (!/^https?:\/\//i.test(url.trim())) {
        throw new Error('地址需要以 http:// 或 https:// 开头');
      }
      cfg.url = url.trim();
      const headerMap = kvToObject(headers);
      if (Object.keys(headerMap).length) {
        cfg.headers = headerMap;
      }
      if (scope.trim()) {
        cfg.scope = scope.trim();
      }
    }
    return cfg;
  };

  const read = (): McpServer[] => {
    const list = mode === 'json' ? parseMcpJson(json) : [fromForm()];
    if (originalName && list.length > 1) {
      throw new Error('编辑时只能保留一个服务；要添加多个，请返回后点「添加」');
    }
    if (!originalName || list[0].name !== originalName) {
      const clash = list.filter(s => servers?.some(x => x.name === s.name)).map(s => s.name);
      if (clash.length) {
        throw new Error(`已有同名服务：${clash.join('、')}`);
      }
    }
    return list;
  };

  const probeAll = async (list: McpServer[]): Promise<Probe[]> =>
    Promise.all(
      list.map(async s => {
        try {
          return {name: s.name, ...(await testMcpServer(s))};
        } catch (e) {
          return {name: s.name, ok: false, error: describeConnectError(e), tools: []};
        }
      }),
    );

  const switchMode = (next: Mode) => {
    if (next === mode) {
      return;
    }
    setResult(null);
    setSaveAnyway(false);
    if (next === 'json') {
      try {
        setJson(mcpServersToJson([fromForm()]));
      } catch {
        // A half-filled form has nothing worth carrying over; the JSON box keeps what it had.
      }
      setMode(next);
      return;
    }
    if (json.trim()) {
      let parsed: McpServer[];
      try {
        parsed = parseMcpJson(json);
      } catch (e) {
        setResult({kind: 'error', text: (e as Error).message});
        return;
      }
      if (parsed.length > 1) {
        setResult({kind: 'error', text: `这里有 ${parsed.length} 个服务，表单一次只能编辑一个；可以直接在 JSON 里保存`});
        return;
      }
      const s = parsed[0];
      setName(originalName ?? s.name);
      setType(mcpTransport(s) as McpTransport);
      setCommand(s.command ?? '');
      setArgs((s.args ?? []).join('\n'));
      setEnv(objectToKv(s.env));
      setUrl(s.url ?? '');
      setHeaders(objectToKv(s.headers));
      setTimeoutValue(s.timeout ? String(s.timeout) : '');
      setPrefix(String(s.tool_name_prefix ?? ''));
      setScope(String(s.scope ?? ''));
      setEnabled(!s.disabled);
      if (s.timeout || s.tool_name_prefix || s.scope) {
        setAdvanced(true);
      }
    }
    setMode(next);
  };

  const test = async () => {
    let list: McpServer[];
    try {
      list = mode === 'json' ? parseMcpJson(json) : [fromForm()];
    } catch (e) {
      setResult({kind: 'error', text: (e as Error).message});
      return;
    }
    setBusy('test');
    setResult(null);
    setResult({kind: 'probes', probes: await probeAll(list)});
    setBusy(null);
  };

  const save = async () => {
    let list: McpServer[];
    try {
      list = read();
    } catch (e) {
      setResult({kind: 'error', text: (e as Error).message});
      return;
    }
    setBusy('save');
    setResult(null);
    try {
      const active = list.filter(s => !s.disabled);
      if (!saveAnyway && active.length) {
        const probes = await probeAll(active);
        // A server waiting for authorization can only be authorized once it is saved.
        if (!probes.every(p => p.ok || p.needs_auth)) {
          setResult({kind: 'probes', probes, note: '没有全部连上。检查后再试，或者直接点「仍然保存」'});
          setSaveAnyway(true);
          return;
        }
      }
      if (originalName) {
        await upsert(list[0], originalName);
      } else {
        await merge(list);
      }
      navigation.goBack();
    } catch (e) {
      setResult({kind: 'error', text: describeConnectError(e)});
    } finally {
      setBusy(null);
    }
  };

  const input = (
    value: string,
    onChange: (v: string) => void,
    opts: {placeholder: string; mono?: boolean; lines?: number; numeric?: boolean; editable?: boolean},
  ) => (
    <TextInput
      value={value}
      onChangeText={edited(onChange)}
      placeholder={opts.placeholder}
      placeholderTextColor={t.t4}
      selectionColor={t.accent}
      cursorColor={t.accent}
      autoCapitalize="none"
      autoCorrect={false}
      editable={opts.editable}
      multiline={!!opts.lines}
      keyboardType={opts.numeric ? 'number-pad' : 'default'}
      style={[
        styles.field,
        opts.mono && styles.mono,
        !!opts.lines && [styles.multi, {minHeight: 22 + opts.lines * 20}],
      ]}
    />
  );

  return (
    <View style={styles.root}>
      <PageHeader title={original ? '编辑 MCP 服务' : '添加 MCP 服务'} onBack={navigation.goBack} />
      <Segmented
        value={mode}
        onChange={switchMode}
        options={[
          {key: 'form', label: '表单'},
          {key: 'json', label: 'JSON'},
        ]}
      />
      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={[styles.body, {paddingBottom: insets.bottom + 32}]} keyboardShouldPersistTaps="handled">
          {mode === 'form' ? (
            <>
              <Text style={styles.label}>名称</Text>
              {input(name, setName, {placeholder: '例如 filesystem'})}

              <Text style={styles.label}>连接方式</Text>
              <View style={styles.chips}>
                {TRANSPORTS.map(tr => (
                  <Chip key={tr} label={MCP_TRANSPORT_LABEL[tr]} active={type === tr} onPress={() => edited(setType)(tr)} />
                ))}
              </View>

              {type === 'stdio' ? (
                <>
                  <Text style={styles.label}>命令</Text>
                  {input(command, setCommand, {placeholder: 'npx / uvx / python', mono: true})}
                  <Text style={styles.label}>参数（每行一个）</Text>
                  {input(args, setArgs, {placeholder: '-y\n@modelcontextprotocol/server-github', mono: true, lines: 3})}
                  <Text style={styles.label}>环境变量（每行 KEY=值）</Text>
                  {input(env, setEnv, {placeholder: 'API_KEY=your-key', mono: true, lines: 2})}
                </>
              ) : (
                <>
                  <Text style={styles.label}>地址</Text>
                  {input(url, setUrl, {placeholder: 'https://mcp.example.com/mcp', mono: true})}
                  <Text style={styles.label}>请求头（每行 KEY=值）</Text>
                  {input(headers, setHeaders, {placeholder: 'Authorization=Bearer YOUR_API_KEY', mono: true, lines: 2})}
                </>
              )}

              <View style={styles.switchRow}>
                <View style={styles.flex}>
                  <Text style={styles.switchTitle}>启用</Text>
                  <Text style={styles.switchHint}>关闭后保留配置，Agent 不加载它的工具</Text>
                </View>
                <Toggle value={enabled} onValueChange={edited(setEnabled)} label="启用" />
              </View>

              <Pressable
                accessibilityRole="button"
                accessibilityState={{expanded: advanced}}
                onPress={() => setAdvanced(v => !v)}
                style={styles.advanced}>
                <View style={advanced && styles.rotated}>
                  <Icon icon={faChevronRight} size={10} color={t.t3} />
                </View>
                <Text style={styles.advancedText}>高级选项</Text>
              </Pressable>
              {advanced && (
                <>
                  <Text style={styles.label}>超时（秒）</Text>
                  {input(timeout, setTimeoutValue, {placeholder: '30', numeric: true})}
                  <Text style={styles.label}>工具名前缀</Text>
                  {input(prefix, setPrefix, {placeholder: 'myserver_', mono: true})}
                  {type !== 'stdio' && (
                    <>
                      <Text style={styles.label}>OAuth scope</Text>
                      {input(scope, setScope, {placeholder: '留空使用服务默认值', mono: true})}
                    </>
                  )}
                </>
              )}
            </>
          ) : (
            <>
              <Text style={styles.jsonHint}>
                粘贴 MCP 目录里给的配置即可，支持 {'{"mcpServers": {...}}'}、名称到配置的映射或配置列表，一次可以添加多个。
              </Text>
              {input(json, setJson, {placeholder: MCP_JSON_PLACEHOLDER, mono: true, lines: 12})}
            </>
          )}

          {busy && (
            <View style={[styles.result, styles.resultInfo]}>
              <ActivityIndicator size="small" color={t.t3} />
              <Text style={styles.resultText}>{busy === 'test' || !saveAnyway ? '正在连接，最长约 45 秒…' : '正在保存…'}</Text>
            </View>
          )}
          {!busy && result?.kind === 'error' && (
            <View style={[styles.result, styles.resultFail]}>
              <Text style={[styles.resultText, styles.failText]}>{result.text}</Text>
            </View>
          )}
          {!busy && result?.kind === 'probes' && <ProbeList probes={result.probes} note={result.note} />}

          <View style={styles.actions}>
            <ActionButton label="测试连接" disabled={!!busy} onPress={test} style={styles.flex} />
            <ActionButton
              label={saveAnyway ? '仍然保存' : '保存'}
              tone="primary"
              loading={busy === 'save'}
              disabled={!!busy}
              onPress={save}
              style={styles.flex}
            />
          </View>
          <Footnote flush>保存前会先试连一次；保存后从下一条消息开始生效，不需要重启服务。</Footnote>
        </ScrollView>
      </KeyboardAvoidingView>
    </View>
  );
}

function ProbeList({probes, note}: {probes: Probe[]; note?: string}) {
  const t = useTheme();
  const styles = useStyles();
  const okCount = probes.filter(p => p.ok).length;
  const tone = okCount === probes.length ? styles.resultOk : okCount ? styles.resultInfo : styles.resultFail;
  return (
    <View style={[styles.probes, tone]}>
      {probes.map(p => (
        <View key={p.name} style={styles.probe}>
          <View style={styles.probeHead}>
            <Icon icon={p.ok ? faCircleCheck : faCircleXmark} size={13} color={p.ok ? t.accent : t.danger} />
            <Text style={styles.probeName} numberOfLines={1}>
              {probes.length > 1 ? `${p.name} · ` : ''}
              {p.ok ? `连接成功，提供 ${p.tools.length} 个工具` : '没有连上'}
            </Text>
          </View>
          {!p.ok && (
            <Text style={styles.probeDetail}>
              {p.needs_auth ? '这个服务需要授权，保存后到网页控制台完成登录授权。' : p.error || '握手失败，检查命令、参数或地址'}
            </Text>
          )}
          {p.ok && p.tools.length > 0 && (
            <View style={styles.toolChips}>
              {p.tools.slice(0, 24).map(tool => (
                <Text key={tool.name} style={styles.toolChip} numberOfLines={1}>
                  {tool.name}
                </Text>
              ))}
              {p.tools.length > 24 && <Text style={styles.probeDetail}>等 {p.tools.length} 个</Text>}
            </View>
          )}
        </View>
      ))}
      {!!note && <Text style={styles.probeNote}>{note}</Text>}
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
    color: t.t1,
  },
  mono: {fontFamily: MONO, fontSize: 13, lineHeight: 20},
  multi: {textAlignVertical: 'top'},
  chips: {flexDirection: 'row', flexWrap: 'wrap', gap: 8},
  switchRow: {flexDirection: 'row', alignItems: 'center', gap: 12, marginTop: 22},
  switchTitle: {fontSize: 15, color: t.t1},
  switchHint: {fontSize: 12, color: t.t3, marginTop: 3},
  advanced: {flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 20, paddingVertical: 4, alignSelf: 'flex-start'},
  rotated: {transform: [{rotate: '90deg'}]},
  advancedText: {fontSize: 13, color: t.t2},
  jsonHint: {fontSize: 12, lineHeight: 18, color: t.t3, marginTop: 10, marginBottom: 10},
  result: {flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 18, padding: 12, borderRadius: radius.sm, borderWidth: 1},
  resultText: {flex: 1, fontSize: 13, lineHeight: 19, color: t.t2},
  resultInfo: {backgroundColor: t.bg1, borderColor: t.line1},
  resultOk: {backgroundColor: t.accentSoft, borderColor: t.accentLine},
  resultFail: {backgroundColor: t.dangerSoft, borderColor: 'transparent'},
  failText: {color: t.danger},
  probes: {marginTop: 18, paddingHorizontal: 12, paddingVertical: 4, borderRadius: radius.sm, borderWidth: 1},
  probe: {paddingVertical: 9},
  probeHead: {flexDirection: 'row', alignItems: 'center', gap: 8},
  probeName: {flex: 1, fontSize: 13, fontWeight: '600', color: t.t1},
  probeDetail: {fontSize: 12, lineHeight: 18, color: t.t2, marginTop: 5},
  toolChips: {flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 8},
  toolChip: {
    maxWidth: '100%',
    paddingHorizontal: 7,
    paddingVertical: 2,
    borderRadius: 6,
    overflow: 'hidden',
    backgroundColor: t.bg0,
    borderWidth: 1,
    borderColor: t.line1,
    fontFamily: MONO,
    fontSize: 11,
    color: t.t2,
  },
  probeNote: {fontSize: 12, fontWeight: '500', color: t.t2, paddingVertical: 9, borderTopWidth: 1, borderTopColor: t.line1},
  actions: {flexDirection: 'row', gap: 10, marginTop: 20},
}));
