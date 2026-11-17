import React, {useCallback, useEffect, useRef, useState} from 'react';
import {ActivityIndicator, Linking, Pressable, Text, View} from 'react-native';
import {create} from 'zustand';
import {parsePairLink, type PairTarget} from '../api/pairing';
import {tr, trf} from '../i18n';
import {describePairError, useServerStore} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {MONO} from './settings';
import {Sheet} from './Sheet';
import {showToast} from './Toast';

/** Redeems a pairing offer, keeping the busy flag and the error to show. */
export function usePairAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // A code is single use: a second tap before the re-render must not redeem it again.
  const running = useRef(false);
  const run = useCallback(async (target: PairTarget): Promise<boolean> => {
    if (running.current) {
      return false;
    }
    running.current = true;
    setBusy(true);
    setError(null);
    try {
      await useServerStore.getState().pair(target);
      const name = useServerStore.getState().servers[0]?.name ?? '';
      showToast(trf('connect_connected', {name}));
      return true;
    } catch (e) {
      setError(describePairError(e));
      return false;
    } finally {
      running.current = false;
      setBusy(false);
    }
  }, []);
  return {busy, error, setError, run};
}

const usePendingPair = create<{target: PairTarget | null}>(() => ({target: null}));
let launchLinkSeen = false;

/**
 * Listens for `cowagent://pair` links (a pairing QR code scanned with the
 * system camera) and asks before connecting: a link can come from anyone, and
 * connecting sends what is typed here to the server it names.
 */
export function PairLinkHost() {
  const styles = useStyles();
  const t = useTheme();
  const target = usePendingPair(s => s.target);
  const {busy, error, setError, run} = usePairAction();

  useEffect(() => {
    const offer = (url: string | null) => {
      const parsed = url ? parsePairLink(url) : null;
      if (parsed) {
        setError(null);
        usePendingPair.setState({target: parsed});
      }
    };
    // The host remounts when the language changes; the launch link is only offered once.
    if (!launchLinkSeen) {
      launchLinkSeen = true;
      Linking.getInitialURL().then(offer, () => undefined);
    }
    const sub = Linking.addEventListener('url', e => offer(e.url));
    return () => sub.remove();
  }, [setError]);

  const close = () => {
    if (!busy) {
      usePendingPair.setState({target: null});
    }
  };

  const confirm = async () => {
    if (target && (await run(target))) {
      usePendingPair.setState({target: null});
    }
  };

  return (
    <Sheet visible={!!target} onClose={close} title={tr('connect_confirm_title')}>
      <View style={styles.body}>
        <View style={styles.hosts}>
          {target?.urls.map(u => (
            <Text key={u} style={styles.host} numberOfLines={1}>
              {u.replace(/^https?:\/\//, '')}
            </Text>
          ))}
        </View>
        <Text style={styles.note}>{tr('connect_confirm_body')}</Text>
        {!!error && <Text style={styles.error}>{error}</Text>}
        <View style={styles.actions}>
          <Pressable accessibilityRole="button" onPress={close} style={[styles.btn, styles.btnGhost]}>
            <Text style={styles.btnGhostText}>{tr('common_cancel')}</Text>
          </Pressable>
          <Pressable
            accessibilityRole="button"
            disabled={busy}
            onPress={confirm}
            style={({pressed}) => [styles.btn, styles.btnPrimary, pressed && {backgroundColor: t.greenDeep}]}>
            {busy ? (
              <ActivityIndicator color={t.onAccent} />
            ) : (
              <Text style={styles.btnPrimaryText}>{tr('connect_confirm_ok')}</Text>
            )}
          </Pressable>
        </View>
      </View>
    </Sheet>
  );
}

const useStyles = makeStyles(t => ({
  body: {paddingHorizontal: 4, paddingBottom: 4},
  hosts: {backgroundColor: t.bg2, borderRadius: radius.md, paddingHorizontal: 14, paddingVertical: 12, gap: 4},
  host: {fontSize: 15, color: t.t1, fontFamily: MONO},
  note: {fontSize: 13, lineHeight: 20, color: t.t2, marginTop: 14},
  error: {
    fontSize: 13,
    lineHeight: 19,
    color: t.danger,
    backgroundColor: t.dangerSoft,
    paddingHorizontal: 12,
    paddingVertical: 9,
    borderRadius: radius.sm,
    overflow: 'hidden',
    marginTop: 12,
  },
  actions: {flexDirection: 'row', gap: 10, marginTop: 20},
  btn: {flex: 1, height: 46, borderRadius: radius.md, alignItems: 'center', justifyContent: 'center'},
  btnGhost: {backgroundColor: t.bg2},
  btnGhostText: {fontSize: 15, fontWeight: '500', color: t.t1},
  btnPrimary: {backgroundColor: t.green},
  btnPrimaryText: {fontSize: 15, fontWeight: '600', color: t.onAccent},
}));
