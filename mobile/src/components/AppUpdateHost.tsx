import React, {useEffect} from 'react';
import {AppState, Text, View} from 'react-native';
import {useDownloadStore} from '../files/downloadStore';
import {tr, trf} from '../i18n';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {
  allowAppInstalls,
  appVersion,
  checkAppUpdateQuietly,
  compareVersions,
  installAppUpdate,
  postponeAppUpdate,
  testFlight,
  UPDATE_ID,
  useAppUpdate,
} from '../update/appUpdate';
import {formatBytes} from '../utils/format';
import {ActionButton} from './settings';
import {Sheet} from './Sheet';

/**
 * Offers a new release on launch and on return to the app. On Android it carries the download
 * through to the installer; on iOS it points to the App Store.
 */
export function AppUpdateHost() {
  const t = useTheme();
  const styles = useStyles();
  const {release, prompt, phase, error} = useAppUpdate();
  const progress = useDownloadStore(s => s.byId[UPDATE_ID]);

  useEffect(() => {
    checkAppUpdateQuietly();
    const sub = AppState.addEventListener('change', state => state === 'active' && checkAppUpdateQuietly());
    return () => sub.remove();
  }, []);

  if (!release) {
    return null;
  }
  const total = progress?.total ?? progress?.expected ?? release.size;
  const pct = total > 0 && progress ? Math.min(100, Math.floor((progress.loaded / total) * 100)) : 0;
  const close = () => useAppUpdate.setState({prompt: false});
  // A TestFlight build moving to the App Store release of its own version.
  const leavingBeta = testFlight && compareVersions(release.version, appVersion) === 0;

  return (
    <Sheet
      visible={prompt}
      onClose={phase === 'idle' ? postponeAppUpdate : close}
      title={tr(leavingBeta ? 'app_update_store_title' : 'app_update_title')}>
      <View style={styles.body}>
        <Text style={styles.version}>
          {release.size ? `v${release.version} · ${formatBytes(release.size)}` : `v${release.version}`}
        </Text>
        {leavingBeta ? (
          <Text style={styles.hint}>{tr('app_update_store_beta')}</Text>
        ) : phase === 'downloading' ? (
          <View style={styles.progress}>
            <View style={styles.track}>
              <View style={[styles.fill, {width: `${pct}%`}]} />
            </View>
            <Text style={styles.hint}>{trf('app_update_downloading', {pct})}</Text>
          </View>
        ) : phase === 'blocked' ? (
          <Text style={styles.hint}>{tr('app_update_blocked')}</Text>
        ) : phase === 'failed' ? (
          <Text style={[styles.hint, {color: t.danger}]}>
            {error === 'corrupt' ? tr('app_update_corrupt') : trf('app_update_failed', {error: error ?? ''})}
          </Text>
        ) : null}
        <View style={styles.actions}>
          {phase === 'downloading' ? (
            <ActionButton label={tr('app_update_background')} onPress={close} style={styles.flex} />
          ) : (
            <>
              <ActionButton label={tr('app_update_later')} onPress={postponeAppUpdate} style={styles.flex} />
              <ActionButton
                label={
                  phase === 'blocked'
                    ? tr('app_update_allow')
                    : phase === 'failed'
                      ? tr('common_retry')
                      : release.storeUrl
                        ? tr('app_update_store')
                        : release.market
                          ? tr('app_update_market')
                          : tr('app_update_install')
                }
                tone="primary"
                onPress={phase === 'blocked' ? allowAppInstalls : installAppUpdate}
                style={styles.flex}
              />
            </>
          )}
        </View>
      </View>
    </Sheet>
  );
}

const useStyles = makeStyles(t => ({
  body: {paddingHorizontal: 12, paddingTop: 4},
  version: {fontSize: 15, fontWeight: '600', color: t.t1, fontVariant: ['tabular-nums']},
  progress: {gap: 6, marginTop: 14},
  track: {height: 4, borderRadius: radius.xs, backgroundColor: t.bg3, overflow: 'hidden'},
  fill: {height: 4, borderRadius: radius.xs, backgroundColor: t.green},
  hint: {fontSize: 13, lineHeight: 20, color: t.t3, marginTop: 8, fontVariant: ['tabular-nums']},
  actions: {flexDirection: 'row', gap: 10, paddingTop: 18, paddingBottom: 4},
  flex: {flex: 1},
}));
