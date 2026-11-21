import {faCopy} from '@fortawesome/free-solid-svg-icons';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useEffect, useState} from 'react';
import {RefreshControl, ScrollView, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {getIntegrations, savePublicUrl} from '../api/cowApi';
import {InfoRow, Section} from '../components/forms';
import {Icon} from '../components/Icon';
import {FieldSheet} from '../components/settings';
import {showToast, ToastHost} from '../components/Toast';
import {EmptyState, PageHeader} from '../components/ui';
import {tr} from '../i18n';
import type {RootStackParamList} from '../navigation/types';
import type {IntegrationsState} from '../protocol/resources';
import {activeServer, describeConnectError} from '../store/serverStore';
import {makeStyles, useTheme} from '../theme/theme';
import {copyText} from '../utils/clipboard';
import {integrationBase} from '../utils/integrations';

type Props = StackScreenProps<RootStackParamList, 'Access'>;

const PUBLIC_URL_RE = /^https?:\/\/[^\s/?#]+(\/[^\s?#]*)?$/i;

/** The listen address is left to the computer: changing it from a phone can lock that phone out. */
export function AccessScreen({navigation}: Props) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const [state, setState] = useState<IntegrationsState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [editing, setEditing] = useState(false);

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

  const detected = integrationBase({public_url: '', lan_urls: state.lan_urls}, activeServer()?.baseUrl ?? '');

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

  const copy = async (url: string) => {
    showToast(tr((await copyText(url)) ? 'common_copied' : 'access_copy_failed'));
  };

  return (
    <View style={styles.root}>
      <PageHeader title={tr('access_title')} onBack={navigation.goBack} />
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
            onPress={() => setEditing(true)}
          />
        </Section>

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
        visible={editing}
        title={tr('access_public_url')}
        initial={state.public_url}
        placeholder={detected || 'https://cow.example.com'}
        hint={tr('access_public_url_hint')}
        keyboardType="url"
        mono
        onSubmit={savePublic}
        onClose={() => setEditing(false)}
      />
      <ToastHost bottom={insets.bottom + 28} />
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
}));
