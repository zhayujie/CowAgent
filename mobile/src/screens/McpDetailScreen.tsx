import {faPen} from '@fortawesome/free-solid-svg-icons';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useState} from 'react';
import {ScrollView, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {testMcpServer} from '../api/cowApi';
import {ActionButton, ConfirmSheet, Footnote, MONO, SettingRow, StatusTag, SwitchRow} from '../components/settings';
import {showToast, ToastHost} from '../components/Toast';
import {EmptyState, GroupLabel, IconButton, PageHeader} from '../components/ui';
import type {RootStackParamList} from '../navigation/types';
import type {McpProbe} from '../protocol/resources';
import {MCP_STATUS, MCP_TRANSPORT_LABEL, mcpTransport, useMcpStore} from '../store/mcpStore';
import {describeConnectError} from '../store/serverStore';
import {makeStyles, useTheme} from '../theme/theme';
import {omit} from '../utils/object';

type Props = StackScreenProps<RootStackParamList, 'McpDetail'>;

const count = (o?: Record<string, string>) => Object.keys(o ?? {}).length;

export function McpDetailScreen({route, navigation}: Props) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const server = useMcpStore(s => s.servers?.find(x => x.name === route.params.name));
  const upsert = useMcpStore(s => s.upsert);
  const remove = useMcpStore(s => s.remove);
  const [probing, setProbing] = useState(false);
  const [probe, setProbe] = useState<McpProbe | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  if (!server) {
    return (
      <View style={styles.root}>
        <PageHeader title={route.params.name} onBack={navigation.goBack} />
        <EmptyState title="这个服务已不存在" hint="可能已在别处删除" />
      </View>
    );
  }

  const status = MCP_STATUS[server.status ?? 'idle'] ?? MCP_STATUS.idle;
  const transport = mcpTransport(server);
  const stdio = transport === 'stdio';

  const test = async () => {
    setProbing(true);
    setProbe(null);
    try {
      setProbe(await testMcpServer(server));
    } catch (e) {
      setProbe({ok: false, error: describeConnectError(e), tools: []});
    } finally {
      setProbing(false);
    }
  };

  const toggle = async (enabled: boolean) => {
    try {
      const rest = omit(server, ['disabled']);
      await upsert(enabled ? rest : {...rest, disabled: true});
    } catch (e) {
      showToast(`保存失败：${describeConnectError(e)}`);
    }
  };

  return (
    <View style={styles.root}>
      <PageHeader
        title={server.name}
        onBack={navigation.goBack}
        right={
          <IconButton
            icon={faPen}
            label="编辑"
            filled
            size={13}
            color={t.t1}
            onPress={() => navigation.navigate('McpEdit', {name: server.name})}
          />
        }
      />
      <ScrollView contentContainerStyle={{paddingBottom: insets.bottom + 32}}>
        <GroupLabel style={styles.firstGroup}>连接</GroupLabel>
        <SettingRow title="状态" right={<StatusTag label={status.label} on={status.on} />} />
        <SettingRow title="方式" value={MCP_TRANSPORT_LABEL[transport] ?? transport} />
        {stdio ? (
          <>
            <SettingRow title="命令" value={server.command} mono />
            <SettingRow
              title="参数"
              detail={server.args?.length ? server.args.join(' ') : undefined}
              value={server.args?.length ? `${server.args.length} 项` : '无'}
            />
            {count(server.env) > 0 && (
              <SettingRow title="环境变量" detail={Object.keys(server.env ?? {}).join('、')} value={`${count(server.env)} 项`} />
            )}
          </>
        ) : (
          <>
            <SettingRow title="地址" detail={server.url} />
            {count(server.headers) > 0 && (
              <SettingRow title="请求头" detail={Object.keys(server.headers ?? {}).join('、')} value={`${count(server.headers)} 项`} />
            )}
          </>
        )}
        {!!server.tool_name_prefix && <SettingRow title="工具名前缀" value={String(server.tool_name_prefix)} mono />}
        <SettingRow title="超时" value={server.timeout ? `${server.timeout} 秒` : '默认'} />
        <SwitchRow
          title="启用"
          detail="停用后保留配置，Agent 不再加载它的工具"
          value={!server.disabled}
          onValueChange={toggle}
          last
        />

        <GroupLabel style={styles.group}>工具</GroupLabel>
        <View style={styles.testWrap}>
          <ActionButton label={probe ? '重新测试' : '测试连接'} loading={probing} onPress={test} />
        </View>
        {probe && !probe.ok && (
          <Text style={styles.probeError}>
            {probe.needs_auth ? '这个服务需要授权，请在网页控制台完成登录授权。' : `没有连上：${probe.error || '握手失败，检查命令、参数或地址'}`}
          </Text>
        )}
        {probe?.ok && !probe.tools.length && <Text style={styles.probeNote}>连接成功，但这个服务没有提供工具。</Text>}
        {probe?.ok &&
          probe.tools.map((tool, i) => (
            <View key={tool.name} style={[styles.tool, i === probe.tools.length - 1 && styles.toolLast]}>
              <Text style={styles.toolName}>{tool.name}</Text>
              {!!tool.description && (
                <Text style={styles.toolDesc} numberOfLines={2}>
                  {tool.description}
                </Text>
              )}
            </View>
          ))}
        {!probe && <Footnote>测试只做一次握手并列出工具，不会写入配置，也不影响正在运行的连接。</Footnote>}

        <View style={styles.danger}>
          <ActionButton label="删除这个服务" tone="danger" onPress={() => setConfirmDelete(true)} />
        </View>
      </ScrollView>

      <ConfirmSheet
        visible={confirmDelete}
        title={`删除 ${server.name}`}
        message="删除后 Agent 不能再调用它提供的工具，从下一条消息开始生效。"
        confirmLabel="删除"
        danger
        onConfirm={async () => {
          try {
            await remove(server.name);
            setConfirmDelete(false);
            navigation.goBack();
          } catch (e) {
            setConfirmDelete(false);
            showToast(`删除失败：${describeConnectError(e)}`);
          }
        }}
        onClose={() => setConfirmDelete(false)}
      />
      <ToastHost bottom={insets.bottom + 28} />
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  firstGroup: {marginTop: 8},
  group: {marginTop: 26},
  testWrap: {paddingHorizontal: 18, paddingBottom: 6},
  probeError: {fontSize: 13, lineHeight: 20, color: t.danger, paddingHorizontal: 18, paddingTop: 8},
  probeNote: {fontSize: 13, color: t.t3, paddingHorizontal: 18, paddingTop: 8},
  tool: {marginHorizontal: 18, paddingVertical: 11, borderBottomWidth: 1, borderBottomColor: t.line1},
  toolLast: {borderBottomWidth: 0},
  toolName: {fontFamily: MONO, fontSize: 13, color: t.t1},
  toolDesc: {fontSize: 12, lineHeight: 17, color: t.t3, marginTop: 3},
  danger: {paddingHorizontal: 18, marginTop: 36},
}));
