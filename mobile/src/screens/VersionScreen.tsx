import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useEffect, useRef, useState} from 'react';
import {Linking, Pressable, ScrollView, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {checkForUpdate, getUpdateStatus, getVersion, startUpdate} from '../api/cowApi';
import {Markdown} from '../components/Markdown';
import {ActionButton, ConfirmSheet, Footnote, Kpis, Notice} from '../components/settings';
import {showToast, ToastHost} from '../components/Toast';
import {GroupLabel, PageHeader} from '../components/ui';
import type {RootStackParamList} from '../navigation/types';
import type {UpdateCheck, UpdateStatus, VersionInfo} from '../protocol/resources';
import {useOverviewStore} from '../store/overviewStore';
import {describeConnectError} from '../store/serverStore';
import {makeStyles} from '../theme/theme';
import {fullTime} from '../utils/format';

type Props = StackScreenProps<RootStackParamList, 'Version'>;

const STEP_LABEL: Record<string, string> = {
  starting: '准备更新',
  git_pull: '拉取最新代码',
  install_deps: '安装依赖',
  install_cli: '重装 CLI',
  self_check: '检查新代码',
  restart: '重启服务',
  done: '完成',
};

const POLL_MS = 2000;
/** A restart that never comes back should stop the spinner eventually. */
const POLL_LIMIT = 90;

function unsupportedHint(info: VersionInfo | null): string {
  switch (info?.install_kind) {
    case 'packaged':
      return '桌面客户端由应用自带的更新器升级，不需要在这里操作。';
    case 'docker':
      return 'Docker 部署请在服务器上执行 docker compose pull，再执行 docker compose up -d。';
    case 'git':
      return '当前服务运行在 Windows 上，网页无法替它重启。请在服务器终端执行 cow update。';
    default:
      return '当前安装方式不支持在线更新，请在服务器终端执行 cow update，或按安装方式手动升级。';
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
        showToast('更新完成');
        runCheck();
        return;
      }
      if (next.state === 'failed') {
        return;
      }
      if (polls.current >= POLL_LIMIT) {
        setStatus({state: 'failed', message: '等待服务重启超时，请到服务器上确认运行状态'});
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
      <PageHeader title="版本更新" onBack={navigation.goBack} />
      <ScrollView contentContainerStyle={{paddingBottom: insets.bottom + 32}}>
        <View style={styles.kpis}>
          <Kpis
            items={[
              {value: current ? `v${current}` : '-', label: '当前版本'},
              {
                value: latest ? `v${tagVersion(latest.tag)}` : checking ? '…' : '-',
                label: hasUpdate ? '有新版本' : check ? '已是最新版本' : '最新版本',
              },
            ]}
          />
        </View>

        <View style={styles.actions}>
          {hasUpdate && supported ? (
            <ActionButton
              label={busy ? '正在更新…' : '立即更新'}
              tone="primary"
              loading={busy}
              disabled={busy}
              onPress={() => setConfirm(true)}
            />
          ) : (
            <ActionButton label={checking ? '正在检查…' : '检查更新'} loading={checking} onPress={runCheck} />
          )}
        </View>

        {!!status && status.state !== 'idle' && (
          <Text style={[styles.status, status.state === 'failed' && styles.statusBad]}>
            {status.state === 'failed'
              ? `更新失败：${status.message || STEP_LABEL[status.step ?? ''] || '未知错误'}`
              : status.state === 'success'
                ? '更新完成，服务已重启'
                : status.state === 'restarting'
                  ? '服务重启中，正在重新连接…'
                  : `正在更新 · ${STEP_LABEL[status.step ?? ''] ?? status.step ?? ''}`}
          </Text>
        )}
        {!!checkError && <Text style={[styles.status, styles.statusBad]}>检查更新失败：{checkError}</Text>}
        {hasUpdate && !supported && <Notice style={styles.notice}>{unsupportedHint(info)}</Notice>}

        {releases.length > 0 && (
          <>
            <GroupLabel style={styles.group}>版本说明</GroupLabel>
            {releases.map(r => {
              const notes = releaseNotes(r.body ?? '');
              const links = [
                notes.zhUrl ? {label: '中文说明', url: notes.zhUrl} : null,
                r.html_url ? {label: '在 GitHub 查看', url: r.html_url} : null,
              ].filter((l): l is {label: string; url: string} => !!l);
              return (
                <View key={r.tag} style={styles.release}>
                  <View style={styles.releaseHead}>
                    <Text style={styles.releaseTag}>
                      {r.name && tagVersion(r.name) !== tagVersion(r.tag) ? r.name : `v${tagVersion(r.tag)}`}
                    </Text>
                    {!!r.published_at && <Text style={styles.releaseDate}>{fullTime(r.published_at)}</Text>}
                  </View>
                  {notes.markdown ? <Markdown value={notes.markdown} /> : <Text style={styles.none}>没有填写说明</Text>}
                  {links.length > 0 && (
                    <View style={styles.links}>
                      {links.map(l => (
                        <Pressable key={l.url} hitSlop={8} onPress={() => Linking.openURL(l.url).catch(() => undefined)}>
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
        <Footnote>检查更新会访问 GitHub 获取发布信息；更新会拉取最新代码并重启服务，期间对话会短暂中断。</Footnote>
      </ScrollView>

      <ConfirmSheet
        visible={confirm}
        title={`更新到 v${tagVersion(latest?.tag)}`}
        message="将拉取最新代码并重启服务，正在进行的对话会被打断。确认继续？"
        confirmLabel="立即更新"
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
