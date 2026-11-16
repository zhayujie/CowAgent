import {faPlus} from '@fortawesome/free-solid-svg-icons';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useEffect, useState} from 'react';
import {Pressable, RefreshControl, ScrollView, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {Footnote, Notice, StatusTag} from '../components/settings';
import {EmptyState, GroupLabel, IconButton, PageHeader} from '../components/ui';
import {tr, trf} from '../i18n';
import type {RootStackParamList} from '../navigation/types';
import type {McpServer} from '../protocol/resources';
import {MCP_STATUS, mcpTarget, useMcpStore} from '../store/mcpStore';
import {describeConnectError} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';

type Props = StackScreenProps<RootStackParamList, 'Mcp'>;

const initials = (name: string) => {
  const s = name.replace(/[-_\s]+/g, ' ').trim();
  return /^[A-Za-z0-9]/.test(s) ? s.slice(0, 2).replace(/^./, c => c.toUpperCase()) : s.slice(0, 1);
};

export function McpScreen({navigation}: Props) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const servers = useMcpStore(s => s.servers);
  const load = useMcpStore(s => s.load);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const reload = useCallback(async () => {
    try {
      await load();
      setError(null);
    } catch (e) {
      setError(describeConnectError(e));
    }
  }, [load]);

  useEffect(() => {
    reload();
  }, [reload]);

  const list = servers ?? [];
  const groups: {label: string; items: McpServer[]}[] = [
    {label: tr('mcp_group_connected'), items: list.filter(s => s.status === 'ready')},
    {label: tr('mcp_group_disconnected'), items: list.filter(s => s.status !== 'ready' && s.status !== 'disabled')},
    {label: tr('mcp_status_disabled'), items: list.filter(s => s.status === 'disabled')},
  ].filter(g => g.items.length);

  return (
    <View style={styles.root}>
      <PageHeader
        title={tr('mcp_title')}
        count={servers ? list.length : undefined}
        onBack={navigation.goBack}
        right={<IconButton icon={faPlus} label={tr('mcp_add')} onPress={() => navigation.navigate('McpEdit')} />}
      />
      <ScrollView
        contentContainerStyle={[styles.body, {paddingBottom: insets.bottom + 32}]}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={async () => {
              setRefreshing(true);
              await reload();
              setRefreshing(false);
            }}
            tintColor={t.t3}
            colors={[t.green]}
          />
        }>
        <Notice style={styles.notice}>
          <Text style={styles.strong}>{tr('mcp_notice_lead')}</Text>
          {tr('mcp_notice_rest')}
        </Notice>
        {!servers || !list.length ? (
          <EmptyState
            loading={!servers && !error}
            title={error ? tr('common_load_failed') : tr('mcp_empty')}
            hint={error ?? tr('mcp_empty_hint')}
          />
        ) : (
          groups.map(g => (
            <View key={g.label}>
              <GroupLabel style={styles.group}>{g.label}</GroupLabel>
              {g.items.map(s => {
                const status = MCP_STATUS[s.status ?? 'idle'] ?? MCP_STATUS.idle;
                return (
                  <Pressable
                    key={s.name}
                    accessibilityRole="button"
                    accessibilityLabel={trf('mcp_row_a11y', {name: s.name, status: status.label})}
                    onPress={() => navigation.navigate('McpDetail', {name: s.name})}
                    style={({pressed}) => [styles.row, pressed && styles.pressed]}>
                    <View style={styles.mark}>
                      <Text style={styles.markText}>{initials(s.name)}</Text>
                    </View>
                    <View style={styles.text}>
                      <Text style={[styles.name, s.status === 'disabled' && styles.dim]} numberOfLines={1}>
                        {s.name}
                      </Text>
                      <Text style={styles.meta} numberOfLines={1}>
                        {mcpTarget(s) || '-'}
                      </Text>
                    </View>
                    <StatusTag label={status.label} on={status.on} />
                  </Pressable>
                );
              })}
            </View>
          ))
        )}
        {!!list.length && <Footnote>{tr('mcp_footnote_isolated')}</Footnote>}
      </ScrollView>
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  body: {flexGrow: 1},
  notice: {marginTop: 8},
  strong: {color: t.t1, fontWeight: '600'},
  group: {marginTop: 22},
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    marginHorizontal: 18,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: t.line1,
  },
  pressed: {opacity: 0.6},
  mark: {
    width: 34,
    height: 34,
    borderRadius: radius.sm,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: t.bg2,
  },
  markText: {fontSize: 12, fontWeight: '600', color: t.t2},
  text: {flex: 1, minWidth: 0},
  name: {fontSize: 15, fontWeight: '500', color: t.t1},
  dim: {color: t.t3},
  meta: {fontSize: 12, color: t.t3, marginTop: 3},
}));
