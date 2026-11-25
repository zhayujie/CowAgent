import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useEffect, useState} from 'react';
import {Pressable, ScrollView, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {ActionButton} from '../components/settings';
import {PageHeader} from '../components/ui';
import {getLang, tr, trf} from '../i18n';
import {openWebPage} from '../navigation/openWeb';
import type {RootStackParamList} from '../navigation/types';
import {describeConnectError} from '../store/serverStore';
import {makeStyles} from '../theme/theme';
import {
  appUpdatesSupported,
  appVersion,
  checkAppUpdate,
  compareVersions,
  installAppUpdate,
  storeButtonKey,
  testFlight,
  useAppUpdate,
} from '../update/appUpdate';
import {useAgentVersion} from '../update/useAgentVersion';

type Props = StackScreenProps<RootStackParamList, 'Version'>;

/** Chinese readers get the docs site's release page; everyone else the GitHub release. */
const releaseNotesUrl = (version: string) =>
  getLang() === 'zh'
    ? `https://docs.cowagent.ai/zh/releases/v${version}`
    : `https://github.com/zhayujie/CowAgent/releases/tag/v${version}`;

export function VersionScreen({navigation}: Props) {
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  // Always this phone's: the agent on it ships inside the app, so the app's release updates it,
  // whichever agent is connected.
  const appManaged = appUpdatesSupported();
  const appRelease = useAppUpdate(s => s.release);
  const current = useAgentVersion();
  const [checking, setChecking] = useState(false);
  const [checked, setChecked] = useState(false);
  const [checkError, setCheckError] = useState<string | null>(null);

  const runCheck = useCallback(async () => {
    setChecking(true);
    setCheckError(null);
    try {
      await checkAppUpdate();
      setChecked(true);
    } catch (e) {
      setCheckError(describeConnectError(e));
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    if (appManaged) {
      runCheck();
    }
  }, [appManaged, runCheck]);

  const newVersion = appManaged ? appRelease?.version : undefined;
  const leavingBeta = testFlight && !!appRelease && compareVersions(appRelease.version, appVersion) === 0;
  const notesVersion = newVersion ?? current;

  const summary = !appManaged
    ? ''
    : checking
      ? tr('settings_checking')
      : checkError
        ? trf('settings_check_failed', {error: checkError})
        : leavingBeta
          ? tr('app_update_store_title')
          : newVersion
            ? trf('settings_update_available', {version: newVersion})
            : checked
              ? tr('settings_up_to_date')
              : '';

  return (
    <View style={styles.root}>
      <PageHeader title={tr('settings_version')} onBack={navigation.goBack} />
      <ScrollView contentContainerStyle={{paddingBottom: insets.bottom + 32}}>
        <View style={styles.head}>
          <Text style={styles.label}>{tr('settings_current_version')}</Text>
          <Text style={styles.version}>{current ? `v${current}` : '-'}</Text>
          {!!summary && (
            <Text style={[styles.summary, !!newVersion && styles.summaryNew, !!checkError && styles.statusBad]}>
              {summary}
            </Text>
          )}
        </View>

        <View style={styles.actions}>
          {appManaged &&
            (appRelease ? (
              <ActionButton
                label={tr(
                  appRelease.storeUrl
                    ? storeButtonKey
                    : appRelease.market
                      ? 'app_update_market'
                      : 'settings_update_now',
                )}
                tone="primary"
                onPress={installAppUpdate}
              />
            ) : (
              <ActionButton
                label={checking ? tr('settings_checking') : tr('settings_check_update')}
                loading={checking}
                onPress={runCheck}
              />
            ))}
          {!!notesVersion && (
            <Pressable hitSlop={8} style={styles.notes} onPress={() => openWebPage(releaseNotesUrl(notesVersion))}>
              <Text style={styles.link}>{tr('settings_view_notes')}</Text>
            </Pressable>
          )}
        </View>
      </ScrollView>
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  head: {paddingHorizontal: 18, paddingTop: 16},
  label: {fontSize: 13, color: t.t3},
  version: {fontSize: 30, fontWeight: '600', color: t.t1, letterSpacing: -0.5, marginTop: 4, fontVariant: ['tabular-nums']},
  summary: {fontSize: 14, lineHeight: 20, color: t.t3, marginTop: 6},
  summaryNew: {color: t.t1, fontWeight: '500'},
  statusBad: {color: t.danger},
  actions: {paddingHorizontal: 18, paddingTop: 20},
  notes: {alignSelf: 'center', marginTop: 16},
  link: {fontSize: 14, color: t.accent},
}));
