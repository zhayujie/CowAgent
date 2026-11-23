import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useEffect, useRef, useState} from 'react';
import {Pressable, ScrollView, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {checkForUpdate, getUpdateStatus, getVersion, startUpdate} from '../api/cowApi';
import {ActionButton, ConfirmSheet, Notice} from '../components/settings';
import {showToast, ToastHost} from '../components/Toast';
import {PageHeader} from '../components/ui';
import {getLang, tr, trf, type MessageKey} from '../i18n';
import {openWebPage} from '../navigation/openWeb';
import type {RootStackParamList} from '../navigation/types';
import type {UpdateCheck, UpdateStatus, VersionInfo} from '../protocol/resources';
import {useOverviewStore} from '../store/overviewStore';
import {describeConnectError, useLocalServer} from '../store/serverStore';
import {makeStyles} from '../theme/theme';
import {
  appUpdatesSupported,
  appVersion,
  checkAppUpdate,
  compareVersions,
  installAppUpdate,
  testFlight,
  useAppUpdate,
} from '../update/appUpdate';

type Props = StackScreenProps<RootStackParamList, 'Version'>;

const STEP_LABEL: Record<string, MessageKey> = {
  starting: 'settings_step_starting',
  git_pull: 'settings_step_git_pull',
  install_deps: 'settings_step_install_deps',
  install_cli: 'settings_step_install_cli',
  self_check: 'settings_step_self_check',
  restart: 'settings_step_restart',
  done: 'common_done',
};

const stepLabel = (step?: string): string | undefined => {
  const key = STEP_LABEL[step ?? ''];
  return key ? tr(key) : undefined;
};

const POLL_MS = 2000;
/** A restart that never comes back should stop the spinner eventually. */
const POLL_LIMIT = 90;

function unsupportedHint(info: VersionInfo | null): string {
  switch (info?.install_kind) {
    case 'packaged':
      return tr('settings_update_packaged');
    case 'docker':
      return tr('settings_update_docker');
    case 'git':
      return tr('settings_update_windows');
    default:
      return tr('settings_update_unsupported');
  }
}

const tagVersion = (tag?: string) => (tag ?? '').replace(/^v/i, '');

/** Chinese readers get the docs site's release page; everyone else the GitHub release. */
const releaseNotesUrl = (version: string) =>
  getLang() === 'zh'
    ? `https://docs.cowagent.ai/zh/releases/v${version}`
    : `https://github.com/zhayujie/CowAgent/releases/tag/v${version}`;

export function VersionScreen({navigation}: Props) {
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const [info, setInfo] = useState<VersionInfo | null>(null);
  const [check, setCheck] = useState<UpdateCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  const [confirm, setConfirm] = useState(false);
  const polls = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // The agent on this phone is part of the app, so the app's own release is what updates it.
  const appManaged = useLocalServer() && appUpdatesSupported();
  const appRelease = useAppUpdate(s => s.release);
  const [appChecked, setAppChecked] = useState(false);

  const runCheck = useCallback(async () => {
    setChecking(true);
    setCheckError(null);
    try {
      if (appManaged) {
        await checkAppUpdate();
        setAppChecked(true);
      } else {
        setCheck(await checkForUpdate());
      }
    } catch (e) {
      setCheckError(describeConnectError(e));
    } finally {
      setChecking(false);
    }
  }, [appManaged]);

  useEffect(() => {
    getVersion()
      .then(setInfo)
      .catch(() => undefined);
    runCheck();
    return () => {
      if (timer.current) {
        clearTimeout(timer.current);
      }
    };
  }, [runCheck]);

  const poll = useCallback(() => {
    timer.current = setTimeout(async () => {
      polls.current += 1;
      let next: UpdateStatus;
      try {
        next = await getUpdateStatus();
      } catch {
        // The server is down for its restart; keep knocking until it answers.
        next = {state: 'restarting', step: 'restart'};
      }
      setStatus(next);
      if (next.state === 'success') {
        const fresh = await getVersion().catch(() => null);
        if (fresh) {
          setInfo(fresh);
        }
        useOverviewStore.getState().load().catch(() => undefined);
        showToast(tr('settings_update_done'));
        runCheck();
        return;
      }
      if (next.state === 'failed') {
        return;
      }
      if (polls.current >= POLL_LIMIT) {
        setStatus({state: 'failed', message: tr('settings_update_timeout')});
        return;
      }
      poll();
    }, POLL_MS);
  }, [runCheck]);

  const begin = async () => {
    setConfirm(false);
    setStatus({state: 'running', step: 'starting'});
    try {
      const res = await startUpdate();
      setStatus(res.update);
      polls.current = 0;
      poll();
    } catch (e) {
      setStatus({state: 'failed', message: describeConnectError(e)});
    }
  };

  // The app has its own version, apart from the kernel's.
  const current = appManaged ? appVersion : (info?.version ?? check?.current_version);
  const latest = check?.latest;
  const hasUpdate = appManaged ? !!appRelease : !!check && !check.up_to_date && !!latest;
  const newVersion = appManaged ? appRelease?.version : tagVersion(latest?.tag);
  const leavingBeta = testFlight && !!appRelease && compareVersions(appRelease.version, appVersion) === 0;
  const supported = info?.update_supported ?? check?.update_supported ?? false;
  const busy = status?.state === 'running' || status?.state === 'restarting';
  const checked = appManaged ? appChecked : !!check;
  const notesVersion = hasUpdate ? newVersion : current;

  const summary = checking
    ? tr('settings_checking')
    : checkError
      ? trf('settings_check_failed', {error: checkError})
      : leavingBeta
        ? tr('app_update_store_title')
        : hasUpdate
          ? trf('settings_update_available', {version: newVersion ?? ''})
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
            <Text style={[styles.summary, hasUpdate && styles.summaryNew, !!checkError && styles.statusBad]}>
              {summary}
            </Text>
          )}
        </View>

        <View style={styles.actions}>
          {appManaged && appRelease ? (
            <ActionButton
              label={tr(
                appRelease.storeUrl ? 'app_update_store' : appRelease.market ? 'app_update_market' : 'settings_update_now',
              )}
              tone="primary"
              onPress={installAppUpdate}
            />
          ) : hasUpdate && supported ? (
            <ActionButton
              label={busy ? tr('settings_updating') : tr('settings_update_now')}
              tone="primary"
              loading={busy}
              disabled={busy}
              onPress={() => setConfirm(true)}
            />
          ) : (
            <ActionButton
              label={checking ? tr('settings_checking') : tr('settings_check_update')}
              loading={checking}
              onPress={runCheck}
            />
          )}
          {!!notesVersion && (
            <Pressable hitSlop={8} style={styles.notes} onPress={() => openWebPage(releaseNotesUrl(notesVersion))}>
              <Text style={styles.link}>{tr('settings_view_notes')}</Text>
            </Pressable>
          )}
        </View>

        {!!status && status.state !== 'idle' && (
          <Text style={[styles.status, status.state === 'failed' && styles.statusBad]}>
            {status.state === 'failed'
              ? trf('settings_update_failed', {
                  error: status.message || stepLabel(status.step) || tr('settings_unknown_error'),
                })
              : status.state === 'success'
                ? tr('settings_update_success')
                : status.state === 'restarting'
                  ? tr('settings_restarting')
                  : trf('settings_updating_step', {step: stepLabel(status.step) ?? status.step ?? ''})}
          </Text>
        )}
        {hasUpdate && !supported && !appManaged && <Notice style={styles.notice}>{unsupportedHint(info)}</Notice>}
      </ScrollView>

      <ConfirmSheet
        visible={confirm}
        title={trf('settings_update_to', {version: newVersion ?? ''})}
        message={tr('settings_update_confirm')}
        confirmLabel={tr('settings_update_now')}
        onConfirm={begin}
        onClose={() => setConfirm(false)}
      />
      <ToastHost bottom={insets.bottom + 28} />
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
  actions: {paddingHorizontal: 18, paddingTop: 20},
  notes: {alignSelf: 'center', marginTop: 16},
  link: {fontSize: 14, color: t.accent},
  status: {fontSize: 13, lineHeight: 20, color: t.t2, paddingHorizontal: 18, paddingTop: 12},
  statusBad: {color: t.danger},
  notice: {marginTop: 14},
}));
