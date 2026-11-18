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
import {tr, trf} from '../i18n';
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
    return tr('common_not_configured');
  }
  if (search.strategy === 'fixed') {
    const fixed = search.providers.find(p => p.id === (search.fixed_provider || search.current_provider));
    return fixed ? labelText(fixed.label, fixed.id) : tr('settings_search_fixed');
  }
  return trf('settings_search_auto_count', {n: configured.length});
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
        <PageHeader title={tr('settings_models')} onBack={navigation.goBack} />
        <EmptyState loading={!error} title={tr('common_load_failed')} hint={error ?? undefined} />
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
      showToast(trf('settings_model_switched', {model: pick.model}));
    } catch (e) {
      showToast(trf('settings_switch_failed', {error: describeConnectError(e)}));
    }
  };

  const saveChain = async (enabled: boolean, chain: FallbackLink[]) => {
    try {
      await setChatFallback(enabled && chain.length > 0, chain);
      await load();
    } catch (e) {
      showToast(trf('common_save_failed_detail', {error: describeConnectError(e)}));
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
      showToast(tr('common_deleted'));
    } catch (e) {
      showToast(trf('common_delete_failed', {error: describeConnectError(e)}));
    }
  };

  const linkActions = [
    ...(linkIndex ? [{key: 'up' as const, label: tr('settings_move_up'), icon: faArrowUp}] : []),
    ...(linkIndex !== null && linkIndex < fallback.chain.length - 1
      ? [{key: 'down' as const, label: tr('settings_move_down'), icon: faArrowDown}]
      : []),
    {key: 'remove' as const, label: tr('settings_remove'), icon: faTrashCan},
  ];

  return (
    <View style={styles.root}>
      <PageHeader title={tr('settings_models')} onBack={navigation.goBack} />
      <ScrollView
        contentContainerStyle={{paddingBottom: insets.bottom + 32}}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={t.t3} colors={[t.green]} />}>
        <GroupLabel style={styles.firstGroup}>{tr('settings_primary_model')}</GroupLabel>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={trf('settings_primary_a11y', {model: primary.model})}
          onPress={() => setPicker('chat')}
          style={({pressed}) => [styles.primary, pressed && styles.pressed]}>
          <View style={styles.primaryText}>
            <Text style={styles.primaryName} numberOfLines={1}>
              {primary.model || tr('common_not_configured')}
            </Text>
            <Text style={styles.primaryMeta} numberOfLines={1}>
              {[providerName(primary.provider), primaryInfo ? describeModel(primaryInfo) : ''].filter(Boolean).join(' · ')}
            </Text>
          </View>
          <Text style={styles.switchText}>{tr('settings_switch')}</Text>
        </Pressable>

        <GroupLabel style={styles.group}>{tr('settings_fallback_models')}</GroupLabel>
        <SwitchRow
          title={tr('settings_fallback_auto')}
          detail={fallback.chain.length ? tr('settings_fallback_order_hint') : tr('settings_fallback_need_one')}
          value={fallback.enabled}
          disabled={!fallback.chain.length}
          onValueChange={v => saveChain(v, fallback.chain)}
        />
        {fallback.chain.map((item, i) => (
          <SettingRow
            key={`${item.provider}/${item.model}`}
            title={item.model}
            detail={trf('settings_fallback_nth', {n: i + 1, provider: providerName(item.provider)})}
            onPress={() => setLinkIndex(i)}
            action={
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={trf('settings_remove_what', {model: item.model})}
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
          <Text style={styles.addText}>{tr('settings_add_fallback')}</Text>
        </Pressable>

        <GroupLabel style={styles.group}>{tr('settings_other_capabilities')}</GroupLabel>
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
            title={tr('settings_web_search')}
            value={searchSummary(state)}
            onPress={() => navigation.navigate('WebSearch')}
            last
          />
        )}

        <GroupLabel style={styles.group}>{tr('settings_vendors')}</GroupLabel>
        {builtins.map(p => (
          <SettingRow
            key={p.id}
            title={labelText(p.label, p.id)}
            detail={
              p.configured
                ? p.api_key_masked
                  ? compactMask(p.api_key_masked)
                  : tr('settings_vendor_connected')
                : tr('settings_vendor_need_key')
            }
            right={
              <StatusTag
                label={p.configured ? tr('settings_configured') : tr('common_not_configured')}
                on={p.configured}
              />
            }
            onPress={p.api_key_field ? () => setEditing(p) : undefined}
            chevron={false}
          />
        ))}
        {customs.map(p => (
          <SettingRow
            key={p.id}
            title={p.custom_name || labelText(p.label, p.id)}
            detail={p.api_base || tr('settings_custom_api')}
            right={<StatusTag label={tr('settings_custom')} on={p.configured} />}
            onPress={() => setCustom(p)}
            chevron={false}
          />
        ))}
        <Pressable
          accessibilityRole="button"
          onPress={() => setCustom('new')}
          style={({pressed}) => [styles.add, pressed && styles.pressedText]}>
          <Icon icon={faPlus} size={11} color={t.accent} />
          <Text style={styles.addText}>{tr('settings_add_custom_vendor')}</Text>
        </Pressable>
        <Footnote>{tr('settings_models_note')}</Footnote>
      </ScrollView>

      <ModelPicker
        visible={picker === 'chat'}
        title={tr('settings_primary_model')}
        providers={providers}
        selected={primary}
        onSelect={pickChat}
        onClose={() => setPicker(null)}
      />
      <ModelPicker
        visible={picker === 'fallback'}
        title={tr('settings_add_fallback')}
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
          showToast(tr('common_saved'));
        }}
      />
      <CustomProviderSheet
        target={custom}
        onClose={() => setCustom(null)}
        onSaved={async name => {
          setCustom(null);
          await load();
          showToast(trf('settings_named_saved', {name}));
        }}
        onDelete={p => {
          setCustom(null);
          setTimeout(() => setRemoving(p), SHEET_DISMISS_MS);
        }}
      />
      <ConfirmSheet
        visible={!!removing}
        title={trf('settings_delete_what', {name: removing?.custom_name ?? tr('settings_custom_vendor')})}
        message={tr('settings_delete_vendor_msg')}
        confirmLabel={tr('common_delete')}
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
