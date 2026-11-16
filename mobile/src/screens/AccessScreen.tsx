import {faCopy} from '@fortawesome/free-solid-svg-icons';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useEffect, useState} from 'react';
import {ActivityIndicator, RefreshControl, ScrollView, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {ApiError} from '../api/http';
import {getIntegrations, saveListenHost, savePublicUrl} from '../api/cowApi';
import {InfoRow, OptionRow, Section} from '../components/forms';
import {Icon} from '../components/Icon';
import {ConfirmSheet, FieldSheet, Notice} from '../components/settings';
import {SHEET_DISMISS_MS} from '../components/Sheet';
import {showToast, ToastHost} from '../components/Toast';
import {EmptyState, PageHeader} from '../components/ui';
import type {RootStackParamList} from '../navigation/types';
import type {IntegrationsState} from '../protocol/resources';
import {activeServer, describeConnectError} from '../store/serverStore';
import {makeStyles, useTheme} from '../theme/theme';
import {copyText} from '../utils/clipboard';

type Props = StackScreenProps<RootStackParamList, 'Access'>;

const LOCAL = '127.0.0.1';
const ALL = '0.0.0.0';
const PUBLIC_URL_RE = /^https?:\/\/[^\s/?#]+(\/[^\s?#]*)?$/i;
const IPV4_RE = /^(\d{1,3}\.){3}\d{1,3}$/;

const isLoopback = (host: string) => host === 'localhost' || host === '::1' || host.startsWith('127.');

function hostOf(url: string): string {
  const m = /^[a-z]+:\/\/(\[[^\]]+\]|[^/:?#]+)/i.exec(url);
  return m ? m[1].replace(/^\[|\]$/g, '') : '';
}

const LISTEN_FAILURES: Record<string, string> = {
  invalid_host: '请填写 IP 地址，如 127.0.0.1 或 0.0.0.0',
  password_required: '允许其他设备访问前，需先设置访问密码',
  unavailable_host: '电脑上没有这个 IP 地址',
  failed: '无法在新地址启动，已恢复原地址',
};

function listenFailure(e: unknown): string {
  const reason = e instanceof ApiError ? String(e.body?.reason ?? e.message) : '';
  return LISTEN_FAILURES[reason] ?? describeConnectError(e);
}

const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

export function AccessScreen({navigation}: Props) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const [state, setState] = useState<IntegrationsState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [sheet, setSheet] = useState<'url' | 'custom' | null>(null);
  const [pendingHost, setPendingHost] = useState<string | null>(null);
  const [moving, setMoving] = useState(false);

  const load = useCallback(async () => {
    try {
      setState(await getIntegrations());
      setError(null);
    } catch (e) {
      setError(describeConnectError(e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (!state) {
    return (
      <View style={styles.root}>
        <PageHeader title="访问地址" onBack={navigation.goBack} />
        <EmptyState loading={!error} title="加载失败" hint={error ?? undefined} />
      </View>
    );
  }

  const host = state.listen.host;
  const preset = host === LOCAL || host === 'localhost' ? LOCAL : host === ALL || host === '::' ? ALL : 'custom';
  // A phone reaching the server over the network would lock itself out by moving it to loopback.
  const remote = !isLoopback(hostOf(activeServer()?.baseUrl ?? ''));

  const refresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const savePublic = async (value: string) => {
    const url = value.replace(/\/+$/, '');
    if (url && !PUBLIC_URL_RE.test(url)) {
      throw new Error('请填写以 http:// 或 https:// 开头的地址');
    }
    await savePublicUrl(url);
    await load();
    showToast(url ? '展示地址已保存' : '已恢复自动识别');
  };

  const requestHost = (next: string) => {
    if (next === host) {
      return;
    }
    if (!isLoopback(next) && !state.password_set) {
      showToast('允许其他设备访问前，需先设置访问密码');
      return;
    }
    setPendingHost(next);
  };

  const move = async () => {
    const next = pendingHost;
    if (!next) {
      return;
    }
    setPendingHost(null);
    setMoving(true);
    try {
      await saveListenHost(next);
      // The server answers before rebinding, then briefly drops connections.
      await sleep(1500);
      for (let i = 0; i < 20; i++) {
        try {
          const fresh = await getIntegrations();
          setState(fresh);
          showToast(fresh.listen.host === next ? '已生效' : LISTEN_FAILURES.failed);
          return;
        } catch {
          await sleep(500);
        }
      }
      showToast('暂时连不上服务，稍后下拉刷新看看');
    } catch (e) {
      showToast(listenFailure(e));
    } finally {
      setMoving(false);
    }
  };

  const copy = async (url: string) => {
    showToast((await copyText(url)) ? '已复制' : '复制失败');
  };

  return (
    <View style={styles.root}>
      <PageHeader title="访问地址" subtitle="对外展示的地址，以及服务监听的地址" onBack={navigation.goBack} />
      <ScrollView
        contentContainerStyle={{paddingBottom: insets.bottom + 32}}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={t.t3} colors={[t.green]} />}>
        <Section footer="用于接口地址、分享链接和嵌入代码，仅供展示；留空则自动识别。">
          <InfoRow first title="展示地址" value={state.public_url || '自动识别'} mono={!!state.public_url} onPress={() => setSheet('url')} />
        </Section>

        <Section
          title="监听地址"
          action={moving ? <ActivityIndicator size="small" color={t.t3} /> : undefined}
          footer={
            state.port_fixed
              ? `端口 ${state.listen.port} 由桌面客户端管理。`
              : `端口 ${state.listen.port}。修改端口会断开这台手机的连接，请在电脑上操作。`
          }>
          <OptionRow
            first
            title="仅本机可访问"
            hint={remote && preset !== LOCAL ? '这台手机通过网络连接，切换后将无法访问，请在电脑上操作' : LOCAL}
            selected={preset === LOCAL}
            onPress={() => (remote ? showToast('切换后这台手机将无法访问，请在电脑上操作') : requestHost(LOCAL))}
          />
          <OptionRow title="所有网卡" hint={`${ALL}，允许局域网内的其他设备访问`} selected={preset === ALL} onPress={() => requestHost(ALL)} />
          <OptionRow
            title="自定义"
            hint={preset === 'custom' ? host : '只在指定的本机 IP 上监听'}
            selected={preset === 'custom'}
            onPress={() => setSheet('custom')}
          />
        </Section>
        {!state.password_set && (
          <Notice style={styles.notice}>还没有设置访问密码，暂时不能开放给其他设备。先在「设置 › 访问密码」里设置一个。</Notice>
        )}

        {!!state.lan_urls.length && (
          <Section title="本机地址" footer="同一局域网内的设备可以用这些地址连接，点按复制。">
            {state.lan_urls.map((url, i) => (
              <InfoRow
                key={url}
                first={i === 0}
                title={url}
                right={<Icon icon={faCopy} size={13} color={t.t3} />}
                onPress={() => copy(url)}
              />
            ))}
          </Section>
        )}
      </ScrollView>

      <FieldSheet
        visible={sheet === 'url'}
        title="展示地址"
        initial={state.public_url}
        placeholder="https://cow.example.com"
        hint="留空则自动识别"
        keyboardType="url"
        mono
        onSubmit={savePublic}
        onClose={() => setSheet(null)}
      />
      <FieldSheet
        visible={sheet === 'custom'}
        title="自定义监听地址"
        initial={preset === 'custom' ? host : ''}
        placeholder="电脑上的 IP 地址"
        hint="127.0.0.1 仅本机可访问，0.0.0.0 允许其他设备访问"
        keyboardType="numeric"
        mono
        allowEmpty={false}
        onSubmit={value => {
          if (!IPV4_RE.test(value) && !value.includes(':')) {
            throw new Error(LISTEN_FAILURES.invalid_host);
          }
          if (remote && isLoopback(value)) {
            throw new Error('切换后这台手机将无法访问，请在电脑上操作');
          }
          setTimeout(() => requestHost(value), SHEET_DISMISS_MS);
        }}
        onClose={() => setSheet(null)}
      />
      <ConfirmSheet
        visible={!!pendingHost}
        title="切换监听地址"
        message={`服务将改为监听 ${pendingHost ?? ''}，连接会短暂断开，几秒后自动恢复。`}
        confirmLabel="保存并生效"
        onConfirm={move}
        onClose={() => setPendingHost(null)}
      />
      <ToastHost bottom={insets.bottom + 28} />
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  notice: {marginHorizontal: 14, marginTop: 14},
}));
