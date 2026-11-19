import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useEffect, useRef, useState} from 'react';
import {Pressable, ScrollView, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {checkForUpdate, getUpdateStatus, getVersion, startUpdate} from '../api/cowApi';
import {Markdown} from '../components/Markdown';
import {ActionButton, ConfirmSheet, Footnote, Kpis, Notice} from '../components/settings';
import {showToast, ToastHost} from '../components/Toast';
import {GroupLabel, PageHeader} from '../components/ui';
import {tr, trf, type MessageKey} from '../i18n';
import {openWebPage} from '../navigation/openWeb';
import type {RootStackParamList} from '../navigation/types';
import type {UpdateCheck, UpdateStatus, VersionInfo} from '../protocol/resources';
import {useOverviewStore} from '../store/overviewStore';
import {describeConnectError} from '../store/serverStore';
import {makeStyles} from '../theme/theme';
import {fullTime} from '../utils/format';

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

/** GitHub release bodies open with an "English | 中文" docs line and embed screenshots as raw <img> HTML. */
function releaseNotes(body: string): {markdown: string; zhUrl?: string} {
  let zhUrl: string | undefined;
  const markdown = body
    .replace(/^.*\[English\]\([^)]*\)\s*\|\s*\[中文\]\(([^)]+)\).*$/m, (_line, url: string) => {
      zhUrl = url;
      return '';
    })
    .replace(/<[^>]+>/g, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
  return {markdown, zhUrl};
}

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

  const runCheck = useCallback(async () => {
    setChecking(true);
    setCheckError(null);
    try {
      setCheck(await checkForUpdate());
    } catch (e) {
      setCheckError(describeConnectError(e));
    } finally {
      setChecking(false);
    }
  }, []);

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

  const current = info?.version ?? check?.current_version;
  const latest = check?.latest;
  const hasUpdate = !!check && !check.up_to_date && !!latest;
  const supported = info?.update_supported ?? check?.update_supported ?? false;
  const busy = status?.state === 'running' || status?.state === 'restarting';
  const releases = hasUpdate && check?.newer_releases?.length ? check.newer_releases : latest ? [latest] : [];

  return (
    <View style={styles.root}>
      <PageHeader title={tr('settings_version')} onBack={navigation.goBack} />
      <ScrollView contentContainerStyle={{paddingBottom: insets.bottom + 32}}>
        <View style={styles.kpis}>
          <Kpis
            items={[
              {value: current ? `v${current}` : '-', label: tr('settings_current_version')},
              {
                value: latest ? `v${tagVersion(latest.tag)}` : checking ? '…' : '-',
                label: hasUpdate
                  ? tr('settings_new_version')
                  : check
                    ? tr('settings_up_to_date')
                    : tr('settings_latest_version'),
              },
            ]}
          />
        </View>

        <View style={styles.actions}>
          {hasUpdate && supported ? (
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
        {!!checkError && (
          <Text style={[styles.status, styles.statusBad]}>{trf('settings_check_failed', {error: checkError})}</Text>
        )}
        {hasUpdate && !supported && <Notice style={styles.notice}>{unsupportedHint(info)}</Notice>}

        {releases.length > 0 && (
          <>
            <GroupLabel style={styles.group}>{tr('settings_release_notes')}</GroupLabel>
            {releases.map(r => {
              const notes = releaseNotes(r.body ?? '');
              const links = [
                notes.zhUrl ? {label: tr('settings_zh_notes'), url: notes.zhUrl} : null,
                r.html_url ? {label: tr('settings_view_on_github'), url: r.html_url} : null,
              ].filter((l): l is {label: string; url: string} => !!l);
              return (
                <View key={r.tag} style={styles.release}>
                  <View style={styles.releaseHead}>
                    <Text style={styles.releaseTag}>
                      {r.name && tagVersion(r.name) !== tagVersion(r.tag) ? r.name : `v${tagVersion(r.tag)}`}
                    </Text>
                    {!!r.published_at && <Text style={styles.releaseDate}>{fullTime(r.published_at)}</Text>}
                  </View>
                  {notes.markdown ? (
                    <Markdown value={notes.markdown} />
                  ) : (
                    <Text style={styles.none}>{tr('settings_no_notes')}</Text>
                  )}
                  {links.length > 0 && (
                    <View style={styles.links}>
                      {links.map(l => (
                        <Pressable key={l.url} hitSlop={8} onPress={() => openWebPage(l.url)}>
                          <Text style={styles.link}>{l.label}</Text>
                        </Pressable>
                      ))}
                    </View>
                  )}
                </View>
              );
            })}
          </>
        )}
        <Footnote>{tr('settings_version_note')}</Footnote>
      </ScrollView>

      <ConfirmSheet
        visible={confirm}
        title={trf('settings_update_to', {version: tagVersion(latest?.tag)})}
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
  kpis: {paddingTop: 8},
  actions: {paddingHorizontal: 18, paddingTop: 10},
  status: {fontSize: 13, lineHeight: 20, color: t.t2, paddingHorizontal: 18, paddingTop: 12},
  statusBad: {color: t.danger},
  notice: {marginTop: 14},
  group: {marginTop: 28},
  release: {paddingHorizontal: 18, paddingBottom: 20},
  releaseHead: {flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 8},
  releaseTag: {fontSize: 16, fontWeight: '600', color: t.t1, letterSpacing: -0.2},
  releaseDate: {fontSize: 12, color: t.t4},
  none: {fontSize: 13, color: t.t4},
  links: {flexDirection: 'row', gap: 20, marginTop: 10},
  link: {fontSize: 13, color: t.accent},
}));
