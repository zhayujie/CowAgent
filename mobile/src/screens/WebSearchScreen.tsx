import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useEffect, useState} from 'react';
import {RefreshControl, ScrollView, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {getModels, setSearchCredential, setSearchStrategy} from '../api/cowApi';
import {InfoRow, OptionRow, Section} from '../components/forms';
import {labelText} from '../components/ModelPicker';
import {compactMask, ProviderSheet} from '../components/ProviderSheet';
import {FieldSheet, StatusTag} from '../components/settings';
import {showToast, ToastHost} from '../components/Toast';
import {EmptyState, PageHeader} from '../components/ui';
import {tr, trf} from '../i18n';
import type {RootStackParamList} from '../navigation/types';
import type {ModelsState, ProviderEntry, SearchProviderMeta} from '../protocol/resources';
import {describeConnectError} from '../store/serverStore';
import {makeStyles, useTheme} from '../theme/theme';
import {searchAllowsAnonymous, searchEditor, searchHelp} from '../utils/capabilities';

type Props = StackScreenProps<RootStackParamList, 'WebSearch'>;

function providerDetail(p: SearchProviderMeta): string {
  if (!p.configured) {
    return searchEditor(p) === 'vendor' ? tr('settings_search_shared_key') : tr('common_not_configured');
  }
  if (p.anonymous) {
    return tr('settings_anonymous_mode');
  }
  if (p.needs_url) {
    return p.url_masked || tr('settings_configured');
  }
  return p.api_key_masked ? compactMask(p.api_key_masked) : tr('settings_configured');
}

export function WebSearchScreen({navigation}: Props) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const [data, setData] = useState<ModelsState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [keyTarget, setKeyTarget] = useState<SearchProviderMeta | null>(null);
  const [vendor, setVendor] = useState<{provider: ProviderEntry; note?: string} | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await getModels());
      setError(null);
    } catch (e) {
      setError(describeConnectError(e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const search = data?.capabilities.search;
  if (!data || !search) {
    return (
      <View style={styles.root}>
        <PageHeader title={tr('settings_web_search')} onBack={navigation.goBack} />
        <EmptyState loading={!error} title={tr('common_load_failed')} hint={error ?? tr('settings_search_missing')} />
      </View>
    );
  }

  const configured = search.providers.filter(p => p.configured);
  const missing = search.providers.filter(p => !p.configured);
  const fixedId = search.fixed_provider || (search.strategy === 'fixed' ? search.current_provider : '');
  const current = search.providers.find(p => p.id === search.current_provider);

  const refresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const saveStrategy = async (strategy: 'auto' | 'fixed', provider?: string) => {
    try {
      await setSearchStrategy(strategy, provider);
      await load();
      showToast(strategy === 'auto' ? tr('settings_search_auto_saved') : tr('common_saved'));
    } catch (e) {
      showToast(trf('common_save_failed_detail', {error: describeConnectError(e)}));
    }
  };

  const chooseFixed = () => {
    const target = configured.find(p => p.id === fixedId) ?? configured[0];
    if (!target) {
      showToast(tr('settings_search_need_vendor'));
      return;
    }
    saveStrategy('fixed', target.id);
  };

  const open = (p: SearchProviderMeta) => {
    const kind = searchEditor(p);
    if (kind === 'key' || kind === 'url') {
      setKeyTarget(p);
      return;
    }
    const entry = data.providers.find(x => x.id === p.id);
    if (!entry) {
      showToast(tr('settings_vendor_not_found'));
      return;
    }
    setVendor({
      provider: entry,
      note: kind === 'deepseek' ? searchHelp('deepseek') : tr('settings_search_vendor_note'),
    });
  };

  const saveKey = async (value: string) => {
    const p = keyTarget;
    if (!p) {
      return;
    }
    if (p.needs_url) {
      if (!/^https?:\/\//i.test(value)) {
        throw new Error(tr('settings_url_invalid'));
      }
      await setSearchCredential(p.id, {url: value});
    } else if (!value) {
      if (!searchAllowsAnonymous(p.id)) {
        throw new Error(tr('settings_need_api_key'));
      }
      await setSearchCredential(p.id, {api_key: '', anonymous: true});
    } else {
      await setSearchCredential(p.id, {api_key: value});
    }
    await load();
    showToast(trf('settings_named_saved', {name: labelText(p.label, p.id)}));
  };

  const renderProvider = (p: SearchProviderMeta, i: number) => (
    <InfoRow
      key={p.id}
      first={i === 0}
      title={labelText(p.label, p.id)}
      hint={providerDetail(p)}
      right={
        <StatusTag
          label={
            p.configured
              ? p.anonymous
                ? tr('settings_anonymous')
                : tr('settings_configured')
              : tr('common_not_configured')
          }
          on={p.configured}
        />
      }
      onPress={() => open(p)}
    />
  );

  return (
    <View style={styles.root}>
      <PageHeader title={tr('settings_web_search')} subtitle={tr('settings_search_subtitle')} onBack={navigation.goBack} />
      <ScrollView
        contentContainerStyle={{paddingBottom: insets.bottom + 32}}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={t.t3} colors={[t.green]} />}>
        <Section title={tr('settings_strategy')}>
          <OptionRow
            first
            title={tr('settings_auto')}
            hint={
              current && search.strategy === 'auto'
                ? trf('settings_currently_using', {name: labelText(current.label, current.id)})
                : tr('settings_search_auto_hint')
            }
            selected={search.strategy !== 'fixed'}
            onPress={() => search.strategy === 'fixed' && saveStrategy('auto')}
          />
          <OptionRow
            title={tr('settings_search_fixed')}
            hint={tr('settings_search_fixed_hint')}
            selected={search.strategy === 'fixed'}
            onPress={() => search.strategy !== 'fixed' && chooseFixed()}
          />
        </Section>

        {search.strategy === 'fixed' && !!configured.length && (
          <Section title={tr('settings_search_used_vendor')} footer={tr('settings_search_fixed_footer')}>
            {configured.map((p, i) => (
              <OptionRow
                key={p.id}
                first={i === 0}
                title={labelText(p.label, p.id)}
                selected={fixedId === p.id}
                onPress={() => fixedId !== p.id && saveStrategy('fixed', p.id)}
              />
            ))}
          </Section>
        )}

        {!!configured.length && <Section title={tr('settings_configured')}>{configured.map(renderProvider)}</Section>}
        {!!missing.length && (
          <Section title={tr('settings_search_addable')} footer={tr('settings_search_addable_footer')}>
            {missing.map(renderProvider)}
          </Section>
        )}
      </ScrollView>

      <FieldSheet
        visible={!!keyTarget}
        title={
          keyTarget
            ? trf(keyTarget.needs_url ? 'settings_instance_url_title' : 'settings_api_key_title', {
                name: labelText(keyTarget.label, keyTarget.id),
              })
            : ''
        }
        placeholder={
          keyTarget?.needs_url
            ? keyTarget.url_masked || 'https://searx.example.com'
            : keyTarget?.api_key_masked
              ? compactMask(keyTarget.api_key_masked)
              : keyTarget && searchAllowsAnonymous(keyTarget.id)
                ? tr('settings_anonymous_ph')
                : tr('settings_paste_api_key')
        }
        hint={keyTarget ? searchHelp(keyTarget.id) : undefined}
        secure={!keyTarget?.needs_url}
        keyboardType={keyTarget?.needs_url ? 'url' : 'default'}
        mono
        allowEmpty={!!keyTarget && searchAllowsAnonymous(keyTarget.id)}
        onSubmit={saveKey}
        onClose={() => setKeyTarget(null)}
      />
      <ProviderSheet
        provider={vendor?.provider ?? null}
        note={vendor?.note}
        onClose={() => setVendor(null)}
        onSaved={async () => {
          setVendor(null);
          await load();
          showToast(tr('common_saved'));
        }}
      />
      <ToastHost bottom={insets.bottom + 28} />
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
}));
