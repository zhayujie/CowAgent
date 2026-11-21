import {
  faArrowUp,
  faCircleExclamation,
  faCode,
  faKey,
  faLayerGroup,
  faPlug,
  faPlus,
  faXmark,
} from '@fortawesome/free-solid-svg-icons';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useMemo, useState} from 'react';
import {Pressable, RefreshControl, ScrollView, Text, View} from 'react-native';
import {useFocusEffect} from '@react-navigation/native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {deleteCustomProvider, getModels, setChatFallback, setChatModel} from '../api/cowApi';
import {Icon} from '../components/Icon';
import {describeModel, labelText, ModelPicker, modelsOf, type ModelPick} from '../components/ModelPicker';
import {compactMask, CustomProviderSheet, ProviderSheet} from '../components/ProviderSheet';
import {
  ActionButton,
  CardLabel,
  ChoiceSheet,
  ConfirmSheet,
  SettingCard,
  SettingRow,
  StatusTag,
  Toggle,
} from '../components/settings';
import {SHEET_DISMISS_MS, Sheet} from '../components/Sheet';
import {showToast, ToastHost} from '../components/Toast';
import {EmptyState, PageHeader} from '../components/ui';
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
const CUSTOM_VENDOR = '__custom__';

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

const vendorName = (p: ProviderEntry) => p.custom_name || labelText(p.label, p.id);

/**
 * Model setup in the order a newcomer needs it: a vendor key first, then the
 * model that chats, then everything optional.
 */
export function ModelsScreen({navigation}: Props) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const reloadConfig = useConfigStore(s => s.load);
  const [state, setState] = useState<ModelsState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [picker, setPicker] = useState<'chat' | 'fallback' | null>(null);
  const [fallbackOpen, setFallbackOpen] = useState(false);
  // Switched on before any model is in the chain: nothing to save until one is added.
  const [fallbackDraft, setFallbackDraft] = useState(false);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<ProviderEntry | null>(null);
  const [custom, setCustom] = useState<ProviderEntry | 'new' | null>(null);
  const [removing, setRemoving] = useState<ProviderEntry | null>(null);

  const load = useCallback(async () => {
    try {
      const next = await getModels();
      setState(next);
      setError(null);
      return next;
    } catch (e) {
      setError(describeConnectError(e));
      return null;
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

  if (!state) {
    return (
      <View style={styles.root}>
        <PageHeader title={tr('settings_models')} onBack={navigation.goBack} background={t.grouped} />
        <EmptyState loading={!error} title={tr('common_load_failed')} hint={error ?? undefined} />
      </View>
    );
  }

  const chat = state.capabilities.chat;
  const fallback = state.capabilities.chat_fallback;
  const primary: ModelPick = {provider: chat.current_provider, model: chat.current_model};
  const primaryProvider = byId.get(primary.provider);
  const primaryInfo = primaryProvider && modelsOf(primaryProvider).find(m => m.name === primary.model);
  const providerName = (id: string) => {
    const p = byId.get(id);
    return p ? vendorName(p) : id;
  };
  const builtins = providers.filter(p => !p.is_custom && p.api_key_field);
  const customs = providers.filter(p => p.is_custom && p.id.startsWith('custom:'));
  const ready = [...builtins.filter(p => p.configured), ...customs];
  const addable = builtins.filter(p => !p.configured);
  const hasVendor = providers.some(p => p.configured);
  // The chosen model only answers once its vendor has a key.
  const chatBlocked = !!primary.model && !primaryProvider?.configured;
  // With nothing set up yet, the quickest start is a key for the model already chosen.
  const fillPrimaryKey = chatBlocked && !hasVendor && !!primaryProvider?.api_key_field;
  const capabilities = OTHER_CAPABILITIES.filter(key => state.capabilities[key]);
  const fallbackOn = fallback.enabled && fallback.chain.length > 0;
  const fallbackShown = fallbackOn || fallbackDraft;

  const refresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const later = (fn: () => void) => setTimeout(fn, SHEET_DISMISS_MS);

  const openVendor = (p: ProviderEntry) => (p.id.startsWith('custom:') ? setCustom(p) : setEditing(p));

  const onAddVendor = (key: string) => {
    setAdding(false);
    if (key === CUSTOM_VENDOR) {
      later(() => setCustom('new'));
      return;
    }
    const p = byId.get(key);
    if (p) {
      later(() => setEditing(p));
    }
  };

  const openChatPicker = () => {
    if (hasVendor) {
      setPicker('chat');
    } else {
      setAdding(true);
    }
  };

  /** After a key is saved: if chat still cannot answer, go straight to picking a model it can use. */
  const afterVendorSaved = async (message: string) => {
    const next = await load();
    reloadConfig().catch(() => undefined);
    const nextChat = next?.capabilities.chat;
    const nextProvider = next?.providers.find(p => p.id === nextChat?.current_provider);
    if (next && !(nextChat?.current_model && nextProvider?.configured)) {
      showToast(tr('settings_pick_chat_model'));
      later(() => setPicker('chat'));
      return;
    }
    showToast(message);
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

  const toggleFallback = (on: boolean) => {
    setFallbackDraft(on && !fallback.chain.length);
    if (fallback.chain.length) {
      saveChain(on, fallback.chain);
    }
  };

  const removeLink = (i: number) => {
    const chain = fallback.chain.filter((_, j) => j !== i);
    // Taking out the last one leaves the switch on with room to add another.
    setFallbackDraft(!chain.length);
    saveChain(fallback.enabled, chain);
  };

  const closeFallback = () => {
    setFallbackOpen(false);
    setFallbackDraft(false);
  };

  // The model picker is a sheet of its own, so the fallback sheet steps aside for it.
  const addFallback = () => {
    if (!hasVendor) {
      setFallbackOpen(false);
      later(() => setAdding(true));
      return;
    }
    setFallbackOpen(false);
    later(() => setPicker('fallback'));
  };

  const closeFallbackPicker = () => {
    setPicker(null);
    later(() => setFallbackOpen(true));
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

  const chatMeta = !primary.model
    ? tr('settings_chat_model_empty')
    : chatBlocked
      ? tr('settings_chat_model_blocked')
      : [providerName(primary.provider), primaryInfo ? describeModel(primaryInfo) : ''].filter(Boolean).join(' · ');

  return (
    <View style={styles.root}>
      <PageHeader title={tr('settings_models')} onBack={navigation.goBack} background={t.grouped} />
      <ScrollView
        contentContainerStyle={[styles.body, {paddingBottom: insets.bottom + 32}]}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={t.t3} colors={[t.green]} />}>
        {!hasVendor && (
          <SettingCard>
            <View style={styles.guide}>
              <View style={styles.guideHead}>
                <View style={styles.guideIcon}>
                  <Icon icon={faKey} size={14} color={t.accent} />
                </View>
                <Text style={styles.guideText}>{tr('settings_setup_text')}</Text>
              </View>
              <ActionButton
                label={tr('settings_add_vendor')}
                icon={faPlus}
                tone="primary"
                onPress={() => setAdding(true)}
                style={styles.guideButton}
              />
            </View>
          </SettingCard>
        )}

        <CardLabel
          first={hasVendor}
          action={
            <Pressable
              accessibilityRole="button"
              hitSlop={8}
              onPress={() => setFallbackOpen(true)}
              style={({pressed}) => [styles.headLink, pressed && styles.pressed]}>
              <Icon icon={faLayerGroup} size={11} color={fallbackOn ? t.accent : t.t3} />
              <Text style={[styles.headLinkText, fallbackOn && styles.headLinkOn]}>
                {fallbackOn
                  ? trf('settings_fallback_count', {n: fallback.chain.length})
                  : tr('settings_fallback_models')}
              </Text>
            </Pressable>
          }>
          {tr('settings_chat_model')}
        </CardLabel>
        <SettingCard>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={trf('settings_primary_a11y', {model: primary.model})}
            onPress={fillPrimaryKey && primaryProvider ? () => openVendor(primaryProvider) : openChatPicker}
            style={({pressed}) => [styles.primary, pressed && styles.pressed]}>
            <View style={styles.primaryText}>
              <Text style={styles.primaryName} numberOfLines={1}>
                {primary.model || tr('common_not_configured')}
              </Text>
              <View style={styles.primaryMetaRow}>
                {chatBlocked && <Icon icon={faCircleExclamation} size={11} color={t.danger} />}
                <Text style={[styles.primaryMeta, chatBlocked && styles.danger]} numberOfLines={2}>
                  {chatMeta}
                </Text>
              </View>
            </View>
            <Text style={styles.switchText}>{fillPrimaryKey ? tr('settings_fill_key') : tr('settings_switch')}</Text>
          </Pressable>
        </SettingCard>

        <CardLabel>{tr('settings_vendors')}</CardLabel>
        <SettingCard>
          {ready.map(p => (
            <SettingRow
              key={p.id}
              icon={p.id.startsWith('custom:') ? faCode : faPlug}
              title={vendorName(p)}
              detail={
                p.id.startsWith('custom:')
                  ? p.api_base || tr('settings_custom_api')
                  : p.api_key_masked
                    ? compactMask(p.api_key_masked)
                    : tr('settings_vendor_connected')
              }
              right={p.id === primary.provider ? <StatusTag label={tr('settings_vendor_in_use')} on /> : undefined}
              onPress={() => openVendor(p)}
            />
          ))}
          <SettingRow icon={faPlus} title={tr('settings_add_vendor')} onPress={() => setAdding(true)} last />
        </SettingCard>

        {(capabilities.length > 0 || !!state.capabilities.search) && (
          <>
            <CardLabel>{tr('settings_other_capabilities')}</CardLabel>
            <SettingCard>
              {capabilities.map((key, i) => (
                <SettingRow
                  key={key}
                  title={CAPABILITY_META[key].title}
                  value={capabilitySummary(state, key)}
                  onPress={() => navigation.navigate('Capability', {key})}
                  last={i === capabilities.length - 1 && !state.capabilities.search}
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
            </SettingCard>
          </>
        )}
      </ScrollView>

      <Sheet visible={fallbackOpen} onClose={closeFallback} title={tr('settings_fallback_models')}>
        <View style={styles.fbToggle}>
          <Text style={styles.fbToggleText}>{tr('settings_fallback_auto')}</Text>
          <Toggle value={fallbackShown} label={tr('settings_fallback_auto')} onValueChange={toggleFallback} />
        </View>
        {fallbackShown && fallback.chain.map((item, i) => (
          <View key={`${item.provider}/${item.model}`} style={styles.fbRow}>
            <Text style={styles.fbIndex}>{i + 1}</Text>
            <View style={styles.fbText}>
              <Text style={styles.fbName} numberOfLines={1}>
                {item.model}
              </Text>
              <Text style={styles.fbMeta} numberOfLines={1}>
                {providerName(item.provider)}
              </Text>
            </View>
            {i > 0 && (
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={tr('settings_move_up')}
                hitSlop={6}
                onPress={() => saveChain(fallback.enabled, moveItem(fallback.chain, i, -1))}
                style={styles.fbButton}>
                <Icon icon={faArrowUp} size={11} color={t.t3} />
              </Pressable>
            )}
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={trf('settings_remove_what', {model: item.model})}
              hitSlop={6}
              onPress={() => removeLink(i)}
              style={styles.fbButton}>
              <Icon icon={faXmark} size={12} color={t.t3} />
            </Pressable>
          </View>
        ))}
        {fallbackShown && (
          <Pressable
            accessibilityRole="button"
            onPress={addFallback}
            style={({pressed}) => [styles.fbAdd, pressed && styles.pressed]}>
            <Icon icon={faPlus} size={12} color={t.accent} />
            <Text style={styles.fbAddText}>{tr('settings_add_fallback')}</Text>
          </Pressable>
        )}
      </Sheet>
      <ChoiceSheet
        visible={adding}
        title={tr('settings_add_vendor')}
        options={[
          ...addable.map(p => ({key: p.id, label: vendorName(p), icon: faPlug})),
          {
            key: CUSTOM_VENDOR,
            label: tr('settings_add_custom_vendor'),
            desc: tr('settings_custom_vendor_desc'),
            icon: faCode,
          },
        ]}
        onSelect={onAddVendor}
        onClose={() => setAdding(false)}
      />
      <ModelPicker
        visible={picker === 'chat'}
        title={tr('settings_chat_model')}
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
          saveChain(true, [...fallback.chain, pick]);
          setFallbackDraft(false);
          closeFallbackPicker();
        }}
        onClose={closeFallbackPicker}
      />
      <ProviderSheet
        provider={editing}
        onClose={() => setEditing(null)}
        onSaved={async () => {
          setEditing(null);
          await afterVendorSaved(tr('common_saved'));
        }}
        onCleared={async () => {
          setEditing(null);
          await load();
          reloadConfig().catch(() => undefined);
          showToast(tr('settings_key_cleared'));
        }}
      />
      <CustomProviderSheet
        target={custom}
        onClose={() => setCustom(null)}
        onSaved={async name => {
          setCustom(null);
          await afterVendorSaved(trf('settings_named_saved', {name}));
        }}
        onDelete={p => {
          setCustom(null);
          later(() => setRemoving(p));
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
  root: {flex: 1, backgroundColor: t.grouped},
  body: {paddingTop: 8},
  pressed: {opacity: 0.6},
  guide: {paddingHorizontal: 16, paddingTop: 16, paddingBottom: 14},
  guideHead: {flexDirection: 'row', alignItems: 'center', gap: 12},
  guideIcon: {
    width: 32,
    height: 32,
    borderRadius: radius.xs,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: t.accentSoft,
  },
  guideText: {flex: 1, fontSize: 15, lineHeight: 22, color: t.t1},
  guideButton: {marginTop: 14},
  headLink: {flexDirection: 'row', alignItems: 'center', gap: 5},
  headLinkText: {fontSize: 13, color: t.t3},
  headLinkOn: {color: t.accent, fontWeight: '500'},
  primary: {flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingVertical: 16},
  primaryText: {flex: 1, minWidth: 0},
  primaryName: {fontSize: 17, fontWeight: '600', letterSpacing: -0.3, color: t.t1},
  primaryMetaRow: {flexDirection: 'row', alignItems: 'center', gap: 5, marginTop: 4},
  primaryMeta: {flexShrink: 1, fontSize: 13, color: t.t3},
  danger: {color: t.danger},
  switchText: {fontSize: 14, fontWeight: '500', color: t.accent},
  fbToggle: {flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 12, paddingVertical: 10},
  fbToggleText: {flex: 1, fontSize: 15, color: t.t1},
  fbRow: {flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 12, paddingVertical: 10},
  fbIndex: {
    width: 22,
    height: 22,
    borderRadius: 11,
    overflow: 'hidden',
    textAlign: 'center',
    lineHeight: 22,
    fontSize: 12,
    fontWeight: '600',
    color: t.t2,
    backgroundColor: t.bg2,
  },
  fbText: {flex: 1, minWidth: 0},
  fbName: {fontSize: 15, color: t.t1},
  fbMeta: {fontSize: 12, color: t.t3, marginTop: 2},
  fbButton: {width: 30, height: 30, alignItems: 'center', justifyContent: 'center', borderRadius: 15, backgroundColor: t.bg2},
  fbAdd: {flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 12, paddingVertical: 14},
  fbAddText: {fontSize: 15, fontWeight: '500', color: t.accent},
}));
