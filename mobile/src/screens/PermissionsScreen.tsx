import {
  faAddressBook,
  faBell,
  faCalendarDays,
  faCamera,
  faGear,
  faLocationDot,
  faMicrophone,
  faWifi,
} from '@fortawesome/free-solid-svg-icons';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useEffect, useState} from 'react';
import {AppState, Platform, ScrollView, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {Footnote, SettingCard, SettingRow} from '../components/settings';
import {showToast, ToastHost} from '../components/Toast';
import {PageHeader} from '../components/ui';
import {tr, type MessageKey} from '../i18n';
import {
  APP_PERMISSIONS,
  canOpenAppSettings,
  checkPermission,
  openAppSettings,
  permissionNote,
  requestPermission,
  type AppPermission,
  type PermissionState,
} from '../media/permissions';
import type {RootStackParamList} from '../navigation/types';
import {askNotifications} from '../notify/notice';
import {makeStyles, useTheme} from '../theme/theme';

type Props = StackScreenProps<RootStackParamList, 'Permissions'>;

const META: Record<AppPermission, {label: MessageKey; use: MessageKey; icon: typeof faCamera}> = {
  notifications: {label: 'perm_notifications', use: 'perm_notifications_use', icon: faBell},
  microphone: {label: 'settings_microphone', use: 'perm_microphone_use', icon: faMicrophone},
  camera: {label: 'settings_camera', use: 'perm_camera_use', icon: faCamera},
  location: {label: 'perm_location', use: 'perm_location_use', icon: faLocationDot},
  calendar: {label: 'perm_calendar', use: 'perm_calendar_use', icon: faCalendarDays},
  contacts: {label: 'perm_contacts', use: 'perm_contacts_use', icon: faAddressBook},
};

const STATE_LABEL: Record<PermissionState, MessageKey> = {
  granted: 'settings_perm_granted',
  denied: 'settings_perm_denied',
  blocked: 'settings_perm_blocked',
  unavailable: 'settings_perm_unavailable',
};

/** iOS asks before the first LAN connection and offers no way to read the answer back. */
const SHOWS_LOCAL_NETWORK = Platform.OS === 'ios';

export function PermissionsScreen({navigation}: Props) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const [states, setStates] = useState<Partial<Record<AppPermission, PermissionState>>>({});

  const refresh = useCallback(async () => {
    const next = await Promise.all(APP_PERMISSIONS.map(checkPermission));
    setStates(Object.fromEntries(APP_PERMISSIONS.map((p, i) => [p, next[i]])));
  }, []);

  // Coming back from the system settings is where these change.
  useEffect(() => {
    refresh();
    const sub = AppState.addEventListener('change', state => state === 'active' && refresh());
    return () => sub.remove();
  }, [refresh]);

  const onPress = async (p: AppPermission) => {
    if (states[p] === 'denied') {
      const next = p === 'notifications' ? await askNotifications() : await requestPermission(p);
      setStates(s => ({...s, [p]: next}));
      return;
    }
    if (canOpenAppSettings) {
      openAppSettings(p);
    } else if (states[p] === 'blocked') {
      showToast(tr('perm_browser_blocked'));
    }
  };

  return (
    <View style={styles.root}>
      <PageHeader title={tr('perm_title')} onBack={navigation.goBack} background={t.grouped} />
      <ScrollView contentContainerStyle={[styles.body, {paddingBottom: insets.bottom + 32}]}>
        <SettingCard>
          {APP_PERMISSIONS.map((p, i) => {
            const state = states[p];
            return (
              <SettingRow
                key={p}
                icon={META[p].icon}
                title={tr(META[p].label)}
                detail={tr(META[p].use)}
                value={state ? tr(STATE_LABEL[state]) : '…'}
                onPress={state && state !== 'unavailable' ? () => onPress(p) : undefined}
                last={i === APP_PERMISSIONS.length - 1 && !SHOWS_LOCAL_NETWORK}
              />
            );
          })}
          {SHOWS_LOCAL_NETWORK && (
            <SettingRow
              icon={faWifi}
              title={tr('perm_local_network')}
              detail={tr('perm_local_network_use')}
              onPress={() => openAppSettings()}
              last
            />
          )}
        </SettingCard>
        {canOpenAppSettings && (
          <SettingCard style={styles.group}>
            <SettingRow icon={faGear} title={tr('perm_open_settings')} onPress={() => openAppSettings()} last />
          </SettingCard>
        )}
        <Footnote>{tr(permissionNote)}</Footnote>
      </ScrollView>
      <ToastHost bottom={insets.bottom + 28} />
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.grouped},
  body: {paddingTop: 8},
  group: {marginTop: 18},
}));
