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
import {tr, trf} from '../i18n';
import type {RootStackParamList} from '../navigation/types';
import type {IntegrationsState} from '../protocol/resources';
import {activeServer, describeConnectError} from '../store/serverStore';
import {makeStyles, useTheme} from '../theme/theme';
import {copyText} from '../utils/clipboard';
import {hostOf, integrationBase, isLoopback} from '../utils/integrations';

type Props = StackScreenProps<RootStackParamList, 'Access'>;

const LOCAL = '127.0.0.1';
const ALL = '0.0.0.0';
const PUBLIC_URL_RE = /^https?:\/\/[^\s/?#]+(\/[^\s?#]*)?$/i;
const IPV4_RE = /^(\d{1,3}\.){3}\d{1,3}$/;

const LISTEN_FAILURES: Record<string, string> = {
  get invalid_host() {
    return tr('access_listen_invalid_host');
  },
  get password_required() {
    return tr('access_listen_password_required');
  },
  get unavailable_host() {
    return tr('access_listen_unavailable_host');
  },
  get failed() {
    return tr('access_listen_failed');
  },
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
        <PageHeader title={tr('access_title')} onBack={navigation.goBack} />
        <EmptyState loading={!error} title={tr('common_load_failed')} hint={error ?? undefined} />
      </View>
    );
  }

  const host = state.listen.host;
  const preset = host === LOCAL || host === 'localhost' ? LOCAL : host === ALL || host === '::' ? ALL : 'custom';
  // A phone reaching the server over the network would lock itself out by moving it to loopback.
  const connected = activeServer()?.baseUrl ?? '';
  const remote = !isLoopback(hostOf(connected));
  const detected = integrationBase({public_url: '', lan_urls: state.lan_urls}, connected);

  const refresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const savePublic = async (value: string) => {
    const url = value.replace(/\/+$/, '');
    if (url && !PUBLIC_URL_RE.test(url)) {
      throw new Error(tr('access_public_url_invalid'));
    }
    await savePublicUrl(url);
    await load();
    showToast(tr(url ? 'access_public_url_saved' : 'access_public_url_auto_restored'));
  };

  const requestHost = (next: string) => {
    if (next === host) {
      return;
    }
    if (!isLoopback(next) && !state.password_set) {
      showToast(tr('access_listen_password_required'));
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
          showToast(fresh.listen.host === next ? tr('access_listen_applied') : LISTEN_FAILURES.failed);
          return;
        } catch {
          await sleep(500);
        }
      }
      showToast(tr('access_listen_unreachable'));
    } catch (e) {
      showToast(listenFailure(e));
    } finally {
      setMoving(false);
    }
  };

  const copy = async (url: string) => {
    showToast(tr((await copyText(url)) ? 'common_copied' : 'access_copy_failed'));
  };

  return (
    <View style={styles.root}>
      <PageHeader title={tr('access_title')} subtitle={tr('access_subtitle')} onBack={navigation.goBack} />
      <ScrollView
        contentContainerStyle={{paddingBottom: insets.bottom + 32}}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={t.t3} colors={[t.green]} />}>
        <Section footer={tr('access_public_url_footer')}>
          <InfoRow
            first
            title={tr('access_public_url')}
            hint={state.public_url ? undefined : tr('access_auto_detect')}
            value={state.public_url || detected}
            mono
            onPress={() => setSheet('url')}
          />
        </Section>

        <Section
          title={tr('access_listen_host')}
          action={moving ? <ActivityIndicator size="small" color={t.t3} /> : undefined}
          footer={trf(state.port_fixed ? 'access_port_fixed' : 'access_port_hint', {port: state.listen.port})}>
          <OptionRow
            first
            title={tr('access_listen_local')}
            hint={remote && preset !== LOCAL ? tr('access_listen_local_remote_hint') : LOCAL}
            selected={preset === LOCAL}
            onPress={() => (remote ? showToast(tr('access_lockout')) : requestHost(LOCAL))}
          />
          <OptionRow
            title={tr('access_listen_all')}
            hint={trf('access_listen_all_hint', {host: ALL})}
            selected={preset === ALL}
            onPress={() => requestHost(ALL)}
          />
          <OptionRow
            title={tr('access_listen_custom')}
            hint={preset === 'custom' ? host : tr('access_listen_custom_hint')}
            selected={preset === 'custom'}
            onPress={() => setSheet('custom')}
          />
        </Section>
        {!state.password_set && <Notice style={styles.notice}>{tr('access_no_password_notice')}</Notice>}

        {!!state.lan_urls.length && (
          <Section title={tr('access_lan_urls')} footer={tr('access_lan_urls_footer')}>
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
        title={tr('access_public_url')}
        initial={state.public_url}
        placeholder={detected || 'https://cow.example.com'}
        hint={tr('access_public_url_hint')}
        keyboardType="url"
        mono
        onSubmit={savePublic}
        onClose={() => setSheet(null)}
      />
      <FieldSheet
        visible={sheet === 'custom'}
        title={tr('access_custom_title')}
        initial={preset === 'custom' ? host : ''}
        placeholder={tr('access_custom_placeholder')}
        hint={tr('access_custom_hint')}
        keyboardType="numeric"
        mono
        allowEmpty={false}
        onSubmit={value => {
          if (!IPV4_RE.test(value) && !value.includes(':')) {
            throw new Error(LISTEN_FAILURES.invalid_host);
          }
          if (remote && isLoopback(value)) {
            throw new Error(tr('access_lockout'));
          }
          setTimeout(() => requestHost(value), SHEET_DISMISS_MS);
        }}
        onClose={() => setSheet(null)}
      />
      <ConfirmSheet
        visible={!!pendingHost}
        title={tr('access_switch_title')}
        message={trf('access_switch_message', {host: pendingHost ?? ''})}
        confirmLabel={tr('access_switch_confirm')}
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
