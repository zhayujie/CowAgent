import {faPen} from '@fortawesome/free-solid-svg-icons';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useState} from 'react';
import {ScrollView, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {testMcpServer} from '../api/cowApi';
import {ActionButton, ConfirmSheet, Footnote, MONO, SettingRow, StatusTag, SwitchRow} from '../components/settings';
import {showToast, ToastHost} from '../components/Toast';
import {EmptyState, GroupLabel, IconButton, PageHeader} from '../components/ui';
import {tr, trf} from '../i18n';
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
        <EmptyState title={tr('mcp_gone')} hint={tr('mcp_gone_hint')} />
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
      showToast(trf('common_save_failed_detail', {error: describeConnectError(e)}));
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
            label={tr('common_edit')}
            filled
            size={13}
            color={t.t1}
            onPress={() => navigation.navigate('McpEdit', {name: server.name})}
          />
        }
      />
      <ScrollView contentContainerStyle={{paddingBottom: insets.bottom + 32}}>
        <GroupLabel style={styles.firstGroup}>{tr('mcp_connection')}</GroupLabel>
        <SettingRow title={tr('mcp_status')} right={<StatusTag label={status.label} on={status.on} />} />
        <SettingRow title={tr('mcp_transport')} value={MCP_TRANSPORT_LABEL[transport] ?? transport} />
        {stdio ? (
          <>
            <SettingRow title={tr('mcp_command')} value={server.command} mono />
            <SettingRow
              title={tr('mcp_args')}
              detail={server.args?.length ? server.args.join(' ') : undefined}
              value={server.args?.length ? trf('mcp_item_count', {n: server.args.length}) : tr('mcp_none')}
            />
            {count(server.env) > 0 && (
              <SettingRow
                title={tr('mcp_env')}
                detail={Object.keys(server.env ?? {}).join(tr('mcp_list_sep'))}
                value={trf('mcp_item_count', {n: count(server.env)})}
              />
            )}
          </>
        ) : (
          <>
            <SettingRow title={tr('mcp_url')} detail={server.url} />
            {count(server.headers) > 0 && (
              <SettingRow
                title={tr('mcp_headers')}
                detail={Object.keys(server.headers ?? {}).join(tr('mcp_list_sep'))}
                value={trf('mcp_item_count', {n: count(server.headers)})}
              />
            )}
          </>
        )}
        {!!server.tool_name_prefix && <SettingRow title={tr('mcp_prefix')} value={String(server.tool_name_prefix)} mono />}
        <SettingRow
          title={tr('mcp_timeout')}
          value={server.timeout ? trf('mcp_seconds', {n: server.timeout}) : tr('mcp_default')}
        />
        <SwitchRow
          title={tr('mcp_enable')}
          detail={tr('mcp_enable_detail')}
          value={!server.disabled}
          onValueChange={toggle}
          last
        />

        <GroupLabel style={styles.group}>{tr('mcp_tools')}</GroupLabel>
        <View style={styles.testWrap}>
          <ActionButton label={probe ? tr('mcp_retest') : tr('mcp_test')} loading={probing} onPress={test} />
        </View>
        {probe && !probe.ok && (
          <Text style={styles.probeError}>
            {probe.needs_auth
              ? tr('mcp_needs_auth_console')
              : trf('mcp_connect_failed_detail', {error: probe.error || tr('mcp_handshake_failed')})}
          </Text>
        )}
        {probe?.ok && !probe.tools.length && <Text style={styles.probeNote}>{tr('mcp_no_tools')}</Text>}
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
        {!probe && <Footnote>{tr('mcp_test_footnote')}</Footnote>}

        <View style={styles.danger}>
          <ActionButton label={tr('mcp_delete_this')} tone="danger" onPress={() => setConfirmDelete(true)} />
        </View>
      </ScrollView>

      <ConfirmSheet
        visible={confirmDelete}
        title={trf('mcp_delete_title', {name: server.name})}
        message={tr('mcp_delete_message')}
        confirmLabel={tr('common_delete')}
        danger
        onConfirm={async () => {
          try {
            await remove(server.name);
            setConfirmDelete(false);
            navigation.goBack();
          } catch (e) {
            setConfirmDelete(false);
            showToast(trf('common_delete_failed', {error: describeConnectError(e)}));
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
