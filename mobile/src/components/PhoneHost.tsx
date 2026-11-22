import React, {useEffect, useRef} from 'react';
import {Linking, Platform, Pressable, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {tr, trf, type MessageKey} from '../i18n';
import {openAppSettings, type AppPermission} from '../media/permissions';
import {usePhoneBridge} from '../phone/bridge';
import {closePrompt, loadTrusted, usePhonePrompts, type PhonePrompt} from '../phone/prompts';
import {radius} from '../theme/palette';
import {makeStyles} from '../theme/theme';
import {MONO, ActionButton} from './settings';
import {Sheet} from './Sheet';

const PERMISSION_LABEL: Record<AppPermission, MessageKey> = {
  notifications: 'perm_notifications',
  microphone: 'settings_microphone',
  camera: 'settings_camera',
  location: 'perm_location',
  calendar: 'perm_calendar',
  contacts: 'perm_contacts',
};

/** iOS has no public way into Location Services; the app's own page is the closest. */
const openLocationSettings = () =>
  (Platform.OS === 'android'
    ? Linking.sendIntent('android.settings.LOCATION_SOURCE_SETTINGS')
    : Linking.openSettings()
  ).catch(() => undefined);

const PERMISSION_USE: Partial<Record<AppPermission, MessageKey>> = {
  location: 'perm_location_use',
  calendar: 'perm_calendar_use',
  contacts: 'perm_contacts_use',
};

const ACTION_LABEL: Record<string, MessageKey> = {
  url: 'phone_ask_url',
  app: 'phone_ask_app',
  navigate: 'phone_ask_navigate',
  call: 'phone_ask_call',
  sms: 'phone_ask_sms',
  email: 'phone_ask_email',
  location: 'phone_ask_location',
  calendar_list: 'phone_ask_calendar_list',
  calendar_create: 'phone_ask_calendar_create',
  contacts: 'phone_ask_contacts',
};

/** Runs the phone tools for the agent and asks the user what they need asked. */
export function PhoneHost() {
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const current = usePhonePrompts(s => s.prompts[0]);
  const purpose = usePhonePrompts(s => s.purpose);
  // The sheet keeps showing the last prompt while it slides away.
  const last = useRef<PhonePrompt | undefined>(undefined);
  if (current) {
    last.current = current;
  }
  const shown = current ?? last.current;

  usePhoneBridge();
  useEffect(() => {
    loadTrusted();
  }, []);

  const close = () => {
    if (current?.kind === 'confirm') {
      current.settle('deny');
    } else if (current) {
      closePrompt(current.id);
    }
  };

  // Something only the system settings can change, and the way there.
  const settings =
    shown?.kind === 'blocked'
      ? {
          title: trf('phone_blocked_title', {permission: tr(PERMISSION_LABEL[shown.permission])}),
          hint: tr('phone_blocked_hint'),
          open: () => openAppSettings(shown.permission),
        }
      : shown?.kind === 'location_off'
        ? {title: tr('phone_location_off_title'), hint: tr('phone_location_off_hint'), open: openLocationSettings}
        : null;
  const purposeUse = purpose && PERMISSION_USE[purpose];

  return (
    <>
      <Sheet
        visible={!!current}
        onClose={close}
        title={
          shown?.kind === 'confirm'
            ? trf('phone_ask_title', {action: tr(ACTION_LABEL[shown.action] ?? 'phone_ask_app')})
            : settings?.title
        }>
        {shown?.kind === 'confirm' ? (
          <View style={styles.body}>
            {!!shown.target && (
              <Text style={styles.target} selectable numberOfLines={4}>
                {shown.target}
              </Text>
            )}
            <View style={[styles.actions, !shown.target && styles.actionsFirst]}>
              <ActionButton label={tr('phone_deny')} onPress={() => shown.settle('deny')} style={styles.flex} />
              <ActionButton label={tr('phone_allow')} tone="primary" onPress={() => shown.settle('once')} style={styles.flex} />
            </View>
            <Pressable accessibilityRole="button" onPress={() => shown.settle('always')} style={styles.always} hitSlop={8}>
              <Text style={styles.alwaysText}>{tr('phone_always')}</Text>
            </Pressable>
          </View>
        ) : settings ? (
          <View style={styles.body}>
            <Text style={styles.hint}>{settings.hint}</Text>
            <View style={styles.actions}>
              <ActionButton label={tr('common_cancel')} onPress={close} style={styles.flex} />
              <ActionButton
                label={tr('phone_blocked_open')}
                tone="primary"
                onPress={() => {
                  close();
                  settings.open();
                }}
                style={styles.flex}
              />
            </View>
          </View>
        ) : null}
      </Sheet>
      {purposeUse && (
        <View pointerEvents="none" style={[styles.purpose, {top: insets.top + 8}]}>
          <Text style={styles.purposeTitle}>{trf('phone_purpose_title', {permission: tr(PERMISSION_LABEL[purpose])})}</Text>
          <Text style={styles.purposeText}>{tr(purposeUse)}</Text>
        </View>
      )}
    </>
  );
}

const useStyles = makeStyles(t => ({
  body: {paddingHorizontal: 12, paddingTop: 4},
  target: {
    fontFamily: MONO,
    fontSize: 13,
    lineHeight: 19,
    color: t.t1,
    backgroundColor: t.bg2,
    borderRadius: radius.sm,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  hint: {fontSize: 14, lineHeight: 20, color: t.t2},
  actions: {flexDirection: 'row', gap: 10, marginTop: 16},
  actionsFirst: {marginTop: 4},
  flex: {flex: 1},
  always: {alignSelf: 'center', paddingVertical: 12, marginTop: 2},
  alwaysText: {fontSize: 14, fontWeight: '600', color: t.accent},
  purpose: {
    position: 'absolute',
    left: 12,
    right: 12,
    padding: 14,
    borderRadius: radius.md,
    backgroundColor: t.bg1,
    borderWidth: 1,
    borderColor: t.line1,
    elevation: 6,
    shadowColor: '#000',
    shadowOpacity: 0.12,
    shadowRadius: 12,
    shadowOffset: {width: 0, height: 4},
  },
  purposeTitle: {fontSize: 14, fontWeight: '600', color: t.t1},
  purposeText: {fontSize: 13, lineHeight: 19, color: t.t2, marginTop: 4},
}));
