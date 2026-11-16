import {faArrowDown, faArrowUp, faPlus, faTrashCan, faXmark} from '@fortawesome/free-solid-svg-icons';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useMemo, useState} from 'react';
import {Pressable, RefreshControl, ScrollView, Text, View} from 'react-native';
import {useFocusEffect} from '@react-navigation/native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {deleteCustomProvider, getModels, setChatFallback, setChatModel} from '../api/cowApi';
import {Icon} from '../components/Icon';
import {describeModel, labelText, ModelPicker, modelsOf, type ModelPick} from '../components/ModelPicker';
import {compactMask, CustomProviderSheet, ProviderSheet} from '../components/ProviderSheet';
import {ChoiceSheet, ConfirmSheet, Footnote, SettingRow, StatusTag, SwitchRow} from '../components/settings';
import {SHEET_DISMISS_MS} from '../components/Sheet';
import {showToast, ToastHost} from '../components/Toast';
import {EmptyState, GroupLabel, PageHeader} from '../components/ui';
import type {RootStackParamList} from '../navigation/types';
import type {CapabilityKey, FallbackLink, ModelsState, ProviderEntry} from '../protocol/resources';
import {useConfigStore} from '../store/configStore';
import {describeConnectError} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {CAPABILITY_META, capabilitySummary, moveItem} from '../utils/capabilities';

type Props = StackScreenProps<RootStackParamList, 'Models'>;

const OTHER_CAPABILITIES: CapabilityKey[] = ['vision', 'image', 'asr', 'tts', 'embedding'];

type LinkAction = 'up' | 'down' | 'remove';

function searchSummary(state: ModelsState): string {
  const search = state.capabilities.search;
  if (!search) {
    return '';
  }
  const configured = search.providers.filter(p => p.configured);
  if (!configured.length) {
    return '未配置';
  }
  if (search.strategy === 'fixed') {
    const fixed = search.providers.find(p => p.id === (search.fixed_provider || search.current_provider));
    return fixed ? labelText(fixed.label, fixed.id) : '指定';
  }
  return `自动 · ${configured.length} 个可用`;
}

export function ModelsScreen({navigation}: Props) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const reloadConfig = useConfigStore(s => s.load);
  const [state, setState] = useState<ModelsState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [picker, setPicker] = useState<'chat' | 'fallback' | null>(null);
  const [editing, setEditing] = useState<ProviderEntry | null>(null);
  const [custom, setCustom] = useState<ProviderEntry | 'new' | null>(null);
  const [removing, setRemoving] = useState<ProviderEntry | null>(null);
  const [linkIndex, setLinkIndex] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      setState(await getModels());
      setError(null);
    } catch (e) {
      setError(describeConnectError(e));
    }
  }, []);

  // Capability and search screens save on their own; pick that up on return.
  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  const providers = useMemo(() => state?.providers ?? [], [state]);
  const byId = useMemo(() => new Map(providers.map(p => [p.id, p])), [providers]);
  const providerName = (id: string) => labelText(byId.get(id)?.label, id);

  if (!state) {
    return (
      <View style={styles.root}>
        <PageHeader title="模型与接口" onBack={navigation.goBack} />
        <EmptyState loading={!error} title="加载失败" hint={error ?? undefined} />
      </View>
    );
  }

  const chat = state.capabilities.chat;
  const fallback = state.capabilities.chat_fallback;
  const primary: ModelPick = {provider: chat.current_provider, model: chat.current_model};
  const primaryProvider = byId.get(primary.provider);
  const primaryInfo = primaryProvider && modelsOf(primaryProvider).find(m => m.name === primary.model);
  const builtins = providers.filter(p => !p.is_custom).sort((a, b) => Number(b.configured) - Number(a.configured));
  const customs = providers.filter(p => p.is_custom && p.id.startsWith('custom:'));
  const capabilities = OTHER_CAPABILITIES.filter(key => state.capabilities[key]);
  const link = linkIndex === null ? null : fallback.chain[linkIndex];

  const refresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const pickChat = async (pick: ModelPick) => {
    setPicker(null);
    if (pick.provider === primary.provider && pick.model === primary.model) {
      return;
    }
    try {
      await setChatModel(pick.provider, pick.model);
      await load();
      reloadConfig().catch(() => undefined);
      showToast(`主模型已切换为 ${pick.model}，从下一条消息开始生效`);
    } catch (e) {
      showToast(`切换失败：${describeConnectError(e)}`);
    }
  };

  const saveChain = async (enabled: boolean, chain: FallbackLink[]) => {
    try {
      await setChatFallback(enabled && chain.length > 0, chain);
      await load();
    } catch (e) {
      showToast(`保存失败：${describeConnectError(e)}`);
    }
  };

  const onLinkAction = (action: LinkAction) => {
    const i = linkIndex;
    setLinkIndex(null);
    if (i === null) {
      return;
    }
    const chain =
      action === 'remove' ? fallback.chain.filter((_, j) => j !== i) : moveItem(fallback.chain, i, action === 'up' ? -1 : 1);
    saveChain(fallback.enabled, chain);
  };

  const removeCustom = async () => {
    const target = removing;
    if (!target?.custom_id) {
      return;
    }
    try {
      await deleteCustomProvider(target.custom_id);
      setRemoving(null);
      await load();
      showToast('已删除');
    } catch (e) {
      showToast(`删除失败：${describeConnectError(e)}`);
    }
  };

  const linkActions = [
    ...(linkIndex ? [{key: 'up' as const, label: '上移', icon: faArrowUp}] : []),
    ...(linkIndex !== null && linkIndex < fallback.chain.length - 1
      ? [{key: 'down' as const, label: '下移', icon: faArrowDown}]
      : []),
    {key: 'remove' as const, label: '移除', icon: faTrashCan},
  ];

  return (
    <View style={styles.root}>
      <PageHeader title="模型与接口" onBack={navigation.goBack} />
      <ScrollView
        contentContainerStyle={{paddingBottom: insets.bottom + 32}}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={t.t3} colors={[t.green]} />}>
        <GroupLabel style={styles.firstGroup}>主模型</GroupLabel>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`主模型 ${primary.model}，点按切换`}
          onPress={() => setPicker('chat')}
          style={({pressed}) => [styles.primary, pressed && styles.pressed]}>
          <View style={styles.primaryText}>
            <Text style={styles.primaryName} numberOfLines={1}>
              {primary.model || '未配置'}
            </Text>
            <Text style={styles.primaryMeta} numberOfLines={1}>
              {[providerName(primary.provider), primaryInfo ? describeModel(primaryInfo) : ''].filter(Boolean).join(' · ')}
            </Text>
          </View>
          <Text style={styles.switchText}>切换</Text>
        </Pressable>

        <GroupLabel style={styles.group}>备用模型</GroupLabel>
        <SwitchRow
          title="主模型失败时自动切换"
          detail={fallback.chain.length ? '按下面的顺序依次尝试，点按调整顺序' : '先添加至少一个备用模型'}
          value={fallback.enabled}
          disabled={!fallback.chain.length}
          onValueChange={v => saveChain(v, fallback.chain)}
        />
        {fallback.chain.map((item, i) => (
          <SettingRow
            key={`${item.provider}/${item.model}`}
            title={item.model}
            detail={`第 ${i + 1} 备选 · ${providerName(item.provider)}`}
            onPress={() => setLinkIndex(i)}
            right={
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={`移除 ${item.model}`}
                hitSlop={10}
                onPress={() => saveChain(fallback.enabled, fallback.chain.filter((_, j) => j !== i))}
                style={styles.remove}>
                <Icon icon={faXmark} size={12} color={t.t3} />
              </Pressable>
            }
          />
        ))}
        <Pressable
          accessibilityRole="button"
          onPress={() => setPicker('fallback')}
          style={({pressed}) => [styles.add, pressed && styles.pressedText]}>
          <Icon icon={faPlus} size={11} color={t.accent} />
          <Text style={styles.addText}>添加备用模型</Text>
        </Pressable>

        <GroupLabel style={styles.group}>其他能力</GroupLabel>
        {capabilities.map(key => (
          <SettingRow
            key={key}
            title={CAPABILITY_META[key].title}
            value={capabilitySummary(state, key)}
            onPress={() => navigation.navigate('Capability', {key})}
          />
        ))}
        {!!state.capabilities.search && (
          <SettingRow
            title="联网搜索"
            value={searchSummary(state)}
            onPress={() => navigation.navigate('WebSearch')}
            last
          />
        )}

        <GroupLabel style={styles.group}>模型厂商</GroupLabel>
        {builtins.map(p => (
          <SettingRow
            key={p.id}
            title={labelText(p.label, p.id)}
            detail={p.configured ? (p.api_key_masked ? compactMask(p.api_key_masked) : '已接入') : '填入 API Key 后可用'}
            right={<StatusTag label={p.configured ? '已配置' : '未配置'} on={p.configured} />}
            onPress={p.api_key_field ? () => setEditing(p) : undefined}
            chevron={false}
          />
        ))}
        {customs.map(p => (
          <SettingRow
            key={p.id}
            title={p.custom_name || labelText(p.label, p.id)}
            detail={p.api_base || '自定义接口'}
            right={<StatusTag label="自定义" on={p.configured} />}
            onPress={() => setCustom(p)}
            chevron={false}
          />
        ))}
        <Pressable
          accessibilityRole="button"
          onPress={() => setCustom('new')}
          style={({pressed}) => [styles.add, pressed && styles.pressedText]}>
          <Icon icon={faPlus} size={11} color={t.accent} />
          <Text style={styles.addText}>添加自定义厂商</Text>
        </Pressable>
        <Footnote>切换主模型不会打断进行中的回复，从下一条消息开始生效。自定义厂商可接入任何兼容 OpenAI 协议的接口。</Footnote>
      </ScrollView>

      <ModelPicker
        visible={picker === 'chat'}
        title="主模型"
        providers={providers}
        selected={primary}
        onSelect={pickChat}
        onClose={() => setPicker(null)}
      />
      <ModelPicker
        visible={picker === 'fallback'}
        title="添加备用模型"
        providers={providers}
        exclude={[primary, ...fallback.chain]}
        onSelect={pick => {
          setPicker(null);
          saveChain(fallback.enabled || !fallback.chain.length, [...fallback.chain, pick]);
        }}
        onClose={() => setPicker(null)}
      />
      <ChoiceSheet
        visible={!!link}
        title={link?.model ?? ''}
        options={linkActions}
        onSelect={onLinkAction}
        onClose={() => setLinkIndex(null)}
      />
      <ProviderSheet
        provider={editing}
        onClose={() => setEditing(null)}
        onSaved={async () => {
          setEditing(null);
          await load();
          showToast('已保存');
        }}
      />
      <CustomProviderSheet
        target={custom}
        onClose={() => setCustom(null)}
        onSaved={async name => {
          setCustom(null);
          await load();
          showToast(`${name} 已保存`);
        }}
        onDelete={p => {
          setCustom(null);
          setTimeout(() => setRemoving(p), SHEET_DISMISS_MS);
        }}
      />
      <ConfirmSheet
        visible={!!removing}
        title={`删除${removing?.custom_name ?? '自定义厂商'}`}
        message="厂商的接口地址、Key 和模型列表都会移除；正在用它的能力需要重新选择厂商。"
        confirmLabel="删除"
        danger
        onConfirm={removeCustom}
        onClose={() => setRemoving(null)}
      />
      <ToastHost bottom={insets.bottom + 28} />
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  firstGroup: {marginTop: 8},
  group: {marginTop: 26},
  primary: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    marginHorizontal: 18,
    paddingHorizontal: 16,
    paddingVertical: 15,
    borderRadius: radius.md,
    backgroundColor: t.accentSoft,
    borderWidth: 1,
    borderColor: t.accentLine,
  },
  pressed: {opacity: 0.75},
  primaryText: {flex: 1, minWidth: 0},
  primaryName: {fontSize: 17, fontWeight: '600', letterSpacing: -0.3, color: t.t1},
  primaryMeta: {fontSize: 12, color: t.t2, marginTop: 4},
  switchText: {fontSize: 13, fontWeight: '500', color: t.accent},
  remove: {width: 28, height: 28, alignItems: 'center', justifyContent: 'center', borderRadius: 14, backgroundColor: t.bg2},
  add: {flexDirection: 'row', alignItems: 'center', gap: 8, marginHorizontal: 18, paddingVertical: 14},
  pressedText: {opacity: 0.6},
  addText: {fontSize: 14, fontWeight: '500', color: t.accent},
}));
