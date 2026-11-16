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
import type {RootStackParamList} from '../navigation/types';
import type {ModelsState, ProviderEntry, SearchProviderMeta} from '../protocol/resources';
import {describeConnectError} from '../store/serverStore';
import {makeStyles, useTheme} from '../theme/theme';
import {searchAllowsAnonymous, searchEditor, searchHelp} from '../utils/capabilities';

type Props = StackScreenProps<RootStackParamList, 'WebSearch'>;

function providerDetail(p: SearchProviderMeta): string {
  if (!p.configured) {
    return searchEditor(p) === 'vendor' ? '与同名模型厂商共用 API Key' : '未配置';
  }
  if (p.anonymous) {
    return '匿名模式';
  }
  if (p.needs_url) {
    return p.url_masked || '已配置';
  }
  return p.api_key_masked ? compactMask(p.api_key_masked) : '已配置';
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
        <PageHeader title="联网搜索" onBack={navigation.goBack} />
        <EmptyState loading={!error} title="加载失败" hint={error ?? '服务端没有返回搜索配置'} />
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
      showToast(strategy === 'auto' ? '已改为自动选择' : '已保存');
    } catch (e) {
      showToast(`保存失败：${describeConnectError(e)}`);
    }
  };

  const chooseFixed = () => {
    const target = configured.find(p => p.id === fixedId) ?? configured[0];
    if (!target) {
      showToast('先配置一个搜索厂商');
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
      showToast('找不到对应的模型厂商');
      return;
    }
    setVendor({provider: entry, note: kind === 'deepseek' ? searchHelp('deepseek') : '搜索与这个模型厂商共用 API Key'});
  };

  const saveKey = async (value: string) => {
    const p = keyTarget;
    if (!p) {
      return;
    }
    if (p.needs_url) {
      if (!/^https?:\/\//i.test(value)) {
        throw new Error('请填写以 http:// 或 https:// 开头的地址');
      }
      await setSearchCredential(p.id, {url: value});
    } else if (!value) {
      if (!searchAllowsAnonymous(p.id)) {
        throw new Error('请填写 API Key');
      }
      await setSearchCredential(p.id, {api_key: '', anonymous: true});
    } else {
      await setSearchCredential(p.id, {api_key: value});
    }
    await load();
    showToast(`${labelText(p.label, p.id)} 已保存`);
  };

  const renderProvider = (p: SearchProviderMeta, i: number) => (
    <InfoRow
      key={p.id}
      first={i === 0}
      title={labelText(p.label, p.id)}
      hint={providerDetail(p)}
      right={<StatusTag label={p.configured ? (p.anonymous ? '匿名' : '已配置') : '未配置'} on={p.configured} />}
      onPress={() => open(p)}
    />
  );

  return (
    <View style={styles.root}>
      <PageHeader title="联网搜索" subtitle="实时网页检索，用于搜索工具" onBack={navigation.goBack} />
      <ScrollView
        contentContainerStyle={{paddingBottom: insets.bottom + 32}}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={t.t3} colors={[t.green]} />}>
        <Section title="策略">
          <OptionRow
            first
            title="自动"
            hint={current && search.strategy === 'auto' ? `当前使用 ${labelText(current.label, current.id)}` : '从已配置的厂商中自动选择'}
            selected={search.strategy !== 'fixed'}
            onPress={() => search.strategy === 'fixed' && saveStrategy('auto')}
          />
          <OptionRow
            title="指定"
            hint="始终使用下面选定的一个厂商"
            selected={search.strategy === 'fixed'}
            onPress={() => search.strategy !== 'fixed' && chooseFixed()}
          />
        </Section>

        {search.strategy === 'fixed' && !!configured.length && (
          <Section title="使用的厂商" footer="只能指定已配置的厂商">
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

        {!!configured.length && <Section title="已配置">{configured.map(renderProvider)}</Section>}
        {!!missing.length && (
          <Section title="可添加" footer="点按厂商填写密钥。AnySearch 和 Keenable 留空即可匿名使用。">
            {missing.map(renderProvider)}
          </Section>
        )}
      </ScrollView>

      <FieldSheet
        visible={!!keyTarget}
        title={keyTarget ? `${labelText(keyTarget.label, keyTarget.id)}${keyTarget.needs_url ? ' 实例地址' : ' API Key'}` : ''}
        placeholder={
          keyTarget?.needs_url
            ? keyTarget.url_masked || 'https://searx.example.com'
            : keyTarget?.api_key_masked
              ? compactMask(keyTarget.api_key_masked)
              : keyTarget && searchAllowsAnonymous(keyTarget.id)
                ? '留空使用匿名模式'
                : '粘贴 API Key'
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
          showToast('已保存');
        }}
      />
      <ToastHost bottom={insets.bottom + 28} />
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
}));
