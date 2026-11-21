import {faCamera, faChevronDown} from '@fortawesome/free-solid-svg-icons';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useEffect, useRef, useState} from 'react';
import {Image, Pressable, ScrollView, Text, TextInput, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {createAgent, uploadAgentAvatar} from '../api/cowApi';
import {Icon} from '../components/Icon';
import {ActionButton, ChoiceSheet, ConfirmSheet} from '../components/settings';
import {showToast, ToastHost} from '../components/Toast';
import {PageHeader} from '../components/ui';
import {tr, trf} from '../i18n';
import {pickAvatar} from '../media/picker';
import type {PickedFile} from '../media/types';
import type {RootStackParamList} from '../navigation/types';
import {useAgentStore} from '../store/agentStore';
import {describeConnectError} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {newAgentId} from '../utils/agentId';
import {AvoidKeyboard} from '../components/AvoidKeyboard';

type Props = StackScreenProps<RootStackParamList, 'AgentCreate'>;

const AVATAR_EXTS = ['png', 'jpg', 'jpeg', 'webp', 'gif'];
const AVATAR_MAX_BYTES = 2 * 1024 * 1024;
/** Agent ids are slugs, so a leading colon can never collide with one. */
const NO_CLONE = ':none';

export function AgentCreateScreen({navigation}: Props) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const roster = useAgentStore(s => s.roster);
  const load = useAgentStore(s => s.load);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [cloneFrom, setCloneFrom] = useState('');
  const [clonePicker, setClonePicker] = useState(false);
  const [avatar, setAvatar] = useState<PickedFile | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [leaving, setLeaving] = useState<(() => void) | null>(null);
  const cloneSource = roster.find(a => a.id === cloneFrom);
  const dirty = !!(name.trim() || description.trim() || cloneFrom || avatar);
  const guard = useRef(dirty);
  guard.current = dirty && !busy;

  useEffect(
    () =>
      navigation.addListener('beforeRemove', e => {
        if (!guard.current) {
          return;
        }
        e.preventDefault();
        setLeaving(() => () => navigation.dispatch(e.data.action));
      }),
    [navigation],
  );

  const chooseAvatar = async () => {
    let file: PickedFile | null;
    try {
      file = await pickAvatar();
    } catch (e) {
      showToast(e instanceof Error ? e.message : String(e));
      return;
    }
    if (!file) {
      return;
    }
    if (!AVATAR_EXTS.includes(file.name.split('.').pop()?.toLowerCase() ?? '')) {
      showToast(tr('agent_avatar_unsupported'));
    } else if ((file.size ?? 0) > AVATAR_MAX_BYTES) {
      showToast(tr('agent_avatar_too_large'));
    } else {
      setAvatar(file);
    }
  };

  const submit = async () => {
    const trimmed = name.trim();
    if (!trimmed) {
      setError(tr('agent_create_name_required'));
      return;
    }
    const id = newAgentId(
      trimmed,
      roster.map(a => a.id),
    );
    setBusy(true);
    setError(null);
    try {
      await createAgent({id, name: trimmed, description: description.trim(), cloneFrom});
    } catch (e) {
      setError(describeConnectError(e));
      setBusy(false);
      return;
    }
    guard.current = false;
    // The Agent exists by now; a failed avatar is reported but doesn't undo it.
    if (avatar) {
      try {
        await uploadAgentAvatar(id, avatar);
      } catch (e) {
        showToast(trf('agent_avatar_failed', {error: describeConnectError(e)}));
      }
    }
    await load().catch(() => undefined);
    showToast(tr('agent_created'));
    navigation.replace('AgentDetail', {agentId: id});
  };

  const field = (value: string, onChange: (v: string) => void, placeholder: string, lines?: number) => (
    <TextInput
      value={value}
      onChangeText={v => {
        onChange(v);
        setError(null);
      }}
      placeholder={placeholder}
      placeholderTextColor={t.t4}
      selectionColor={t.accent}
      cursorColor={t.accent}
      autoCorrect={false}
      multiline={!!lines}
      style={[styles.field, !!lines && [styles.multi, {minHeight: 22 + lines * 21}]]}
    />
  );

  return (
    <View style={styles.root}>
      <PageHeader title={tr('agent_create')} onBack={navigation.goBack} />
      <AvoidKeyboard style={styles.flex}>
        <ScrollView contentContainerStyle={{paddingBottom: insets.bottom + 32}} keyboardShouldPersistTaps="handled">
          <View style={styles.body}>
            <View style={styles.avatarRow}>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={tr('agent_create_avatar')}
                onPress={chooseAvatar}
                style={({pressed}) => [styles.avatar, !avatar && styles.avatarEmpty, pressed && styles.pressed]}>
                {avatar ? (
                  <Image source={{uri: avatar.uri}} style={styles.avatarImage} />
                ) : (
                  <Icon icon={faCamera} size={18} color={t.t3} />
                )}
              </Pressable>
              <View style={styles.flex}>
                <Text style={styles.avatarTitle}>{tr('agent_create_avatar')}</Text>
                <Text style={styles.hint}>{tr('agent_create_avatar_hint')}</Text>
              </View>
            </View>

            <Text style={styles.label}>{tr('common_name')}</Text>
            {field(name, setName, tr('agent_name_placeholder'))}

            <Text style={styles.label}>{tr('agent_duty')}</Text>
            {field(description, setDescription, tr('agent_duty_placeholder'), 3)}
            <Text style={styles.hint}>{tr('agent_duty_hint')}</Text>

            {roster.length > 0 && (
              <>
                <Text style={styles.label}>{tr('agent_clone_from')}</Text>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel={tr('agent_clone_from')}
                  onPress={() => setClonePicker(true)}
                  style={({pressed}) => [styles.field, styles.select, pressed && styles.pressed]}>
                  <Text style={styles.selectValue} numberOfLines={1}>
                    {cloneSource ? cloneSource.name || cloneSource.id : tr('agent_clone_none')}
                  </Text>
                  <Icon icon={faChevronDown} size={11} color={t.t4} />
                </Pressable>
                <Text style={styles.hint}>{tr('agent_clone_hint')}</Text>
              </>
            )}

            {!!error && <Text style={styles.error}>{error}</Text>}
            <ActionButton label={tr('agent_create_submit')} tone="primary" loading={busy} onPress={submit} style={styles.submit} />
          </View>
        </ScrollView>
      </AvoidKeyboard>
      <ChoiceSheet
        visible={clonePicker}
        title={tr('agent_clone_from')}
        options={[
          {key: NO_CLONE, label: tr('agent_clone_none'), desc: tr('agent_clone_none_hint')},
          ...roster.map(a => ({key: a.id, label: a.name || a.id, desc: a.description || undefined})),
        ]}
        selected={cloneFrom || NO_CLONE}
        onSelect={key => {
          setCloneFrom(key === NO_CLONE ? '' : key);
          setClonePicker(false);
        }}
        onClose={() => setClonePicker(false)}
      />
      <ConfirmSheet
        visible={!!leaving}
        title={tr('agent_create_discard_title')}
        message={tr('agent_create_discard_message')}
        confirmLabel={tr('skill_discard')}
        danger
        onConfirm={() => {
          const go = leaving;
          setLeaving(null);
          guard.current = false;
          go?.();
        }}
        onClose={() => setLeaving(null)}
      />
      <ToastHost bottom={insets.bottom + 28} />
    </View>
  );
}

const AVATAR_SIZE = 64;

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  flex: {flex: 1},
  body: {paddingHorizontal: 18},
  avatarRow: {flexDirection: 'row', alignItems: 'center', gap: 14, marginTop: 12},
  avatar: {
    width: AVATAR_SIZE,
    height: AVATAR_SIZE,
    borderRadius: AVATAR_SIZE / 2,
    overflow: 'hidden',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: t.bg1,
  },
  avatarEmpty: {borderWidth: 1, borderStyle: 'dashed', borderColor: t.line2},
  avatarImage: {width: AVATAR_SIZE, height: AVATAR_SIZE},
  avatarTitle: {fontSize: 14, fontWeight: '500', color: t.t2},
  pressed: {opacity: 0.7},
  label: {fontSize: 12, color: t.t3, marginTop: 18, marginBottom: 7},
  field: {
    minHeight: 46,
    paddingHorizontal: 14,
    paddingVertical: 12,
    borderRadius: radius.sm,
    backgroundColor: t.bg1,
    borderWidth: 1,
    borderColor: t.line1,
    fontSize: 15,
    lineHeight: 21,
    color: t.t1,
  },
  multi: {textAlignVertical: 'top'},
  select: {flexDirection: 'row', alignItems: 'center', gap: 10},
  selectValue: {flex: 1, fontSize: 15, lineHeight: 21, color: t.t1},
  hint: {fontSize: 12, lineHeight: 18, color: t.t4, marginTop: 6},
  error: {fontSize: 13, lineHeight: 20, color: t.danger, marginTop: 16},
  submit: {marginTop: 22},
}));
