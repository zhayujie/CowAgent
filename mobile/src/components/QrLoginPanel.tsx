import {faArrowUpRightFromSquare, faCheck, faRotateRight} from '@fortawesome/free-solid-svg-icons';
import React, {useEffect, useRef, useState} from 'react';
import {ActivityIndicator, Image, Linking, Pressable, Text, View} from 'react-native';
import {channelAction, getChannels, getFeishuRegister, getWeixinQr, pollFeishuRegister, pollWeixinQr} from '../api/cowApi';
import {describeConnectError} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {Icon} from './Icon';

type Provider = 'weixin' | 'feishu';
/** `downloading`: Feishu only, its SDK is fetched before the QR exists. */
type Phase = 'loading' | 'downloading' | 'waiting' | 'scanned' | 'success' | 'error';

export interface QrConnected {
  instanceId?: string;
  downloading?: boolean;
}

const POLL_MS = 2000;
/** A live WeChat instance may still be fetching its code; keep asking this many times. */
const PENDING_TRIES = 15;
const QR_SIZE = 188;

const COPY: Record<Provider, {loading: string; waiting: string; scanned: string; tip: string; success: string; fail: string}> = {
  weixin: {
    loading: '正在获取二维码…',
    waiting: '用微信扫一扫登录',
    scanned: '已扫码，请在手机上确认',
    tip: '二维码约 2 分钟过期，过期后自动换新',
    success: '登录成功，正在启动通道…',
    fail: '获取二维码失败',
  },
  feishu: {
    loading: '正在生成二维码…',
    waiting: '用飞书扫码授权',
    scanned: '用飞书扫码授权',
    tip: '授权后自动创建机器人，权限和事件订阅都已配好',
    success: '机器人已创建，正在连接…',
    fail: '接入失败',
  },
};

/**
 * Fetches a login QR, polls it and connects the channel once confirmed.
 * `newInstance` makes that connect create a new bot (multi-Agent mode);
 * `instanceId` re-logs an existing one.
 */
export function QrLoginPanel({
  provider,
  instanceId,
  newInstance,
  onConnected,
}: {
  provider: Provider;
  instanceId?: string;
  newInstance?: boolean;
  onConnected: (result: QrConnected) => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  const copy = COPY[provider];
  const instanceArg = newInstance ? '' : instanceId || undefined;
  const [phase, setPhase] = useState<Phase>('loading');
  const [qr, setQr] = useState('');
  const [link, setLink] = useState('');
  const [error, setError] = useState('');
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const alive = useRef(true);
  const done = useRef(onConnected);
  done.current = onConnected;

  const stop = () => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
  };

  const fail = (message: string) => {
    if (alive.current) {
      setPhase('error');
      setError(message);
    }
  };

  const later = (fn: () => void) => {
    timer.current = setTimeout(() => alive.current && fn(), POLL_MS);
  };

  const connect = async (config: Record<string, unknown>) => {
    setPhase('success');
    try {
      const res = await channelAction('connect', provider, config, instanceArg);
      if (alive.current) {
        done.current({instanceId: res.instance_id, downloading: res.downloading});
      }
    } catch (e) {
      fail(`连接失败：${describeConnectError(e)}`);
    }
  };

  // WeChat, console-owned QR: poll it, connect on confirm.
  const pollWeixin = () =>
    later(async () => {
      try {
        const res = await pollWeixinQr();
        if (!alive.current) {
          return;
        }
        if (res.qr_status === 'confirmed') {
          await connect({});
          return;
        }
        if (res.qr_status === 'expired' && (res.qr_image || res.qrcode_url)) {
          setQr(res.qr_image || res.qrcode_url || '');
          setPhase('waiting');
        } else if (res.qr_status === 'scaned' || res.qr_status === 'scanned') {
          setPhase('scanned');
        }
      } catch {
        // A dropped poll is not a failed login; keep watching.
      }
      pollWeixin();
    });

  // WeChat, QR owned by a running channel that lost its login: watch the
  // channel itself, and re-read the QR now and then since it swaps in new ones.
  const watchChannel = (tick = 0) =>
    later(async () => {
      let handedOver = false;
      try {
        const data = await getChannels();
        if (!alive.current) {
          return;
        }
        const wx = instanceId
          ? (data.instances ?? []).find(c => c.instance_id === instanceId)
          : data.channels.find(c => c.name === 'weixin');
        if (wx?.login_status === 'logged_in') {
          setPhase('success');
          done.current({instanceId});
          return;
        }
        setPhase(wx?.login_status === 'scanned' ? 'scanned' : 'waiting');
        if (tick % 5 === 4) {
          const res = await getWeixinQr(instanceId);
          if (res.status === 'success') {
            const img = res.qr_image || res.qrcode_url;
            if (img) {
              setQr(img);
            }
            handedOver = res.source !== 'channel';
          }
        }
      } catch {
        // Keep watching through a transient failure.
      }
      if (!alive.current) {
        return;
      }
      if (handedOver) {
        pollWeixin();
      } else {
        watchChannel(tick + 1);
      }
    });

  const startWeixin = async () => {
    try {
      let res = await getWeixinQr(instanceId);
      for (let tries = 0; res.status === 'pending' && tries < PENDING_TRIES; tries++) {
        await new Promise(r => setTimeout(r, POLL_MS));
        if (!alive.current) {
          return;
        }
        res = await getWeixinQr(instanceId);
      }
      if (!alive.current) {
        return;
      }
      if (res.status !== 'success') {
        fail(res.message || copy.fail);
        return;
      }
      setQr(res.qr_image || res.qrcode_url || '');
      setPhase('waiting');
      if (res.source === 'channel') {
        watchChannel();
      } else {
        pollWeixin();
      }
    } catch (e) {
      fail(`${copy.fail}：${describeConnectError(e)}`);
    }
  };

  const pollFeishu = () =>
    later(async () => {
      let res;
      try {
        res = await pollFeishuRegister();
      } catch {
        if (alive.current) {
          pollFeishu();
        }
        return;
      }
      if (!alive.current) {
        return;
      }
      const status = res.register_status;
      if (status === 'downloading') {
        setPhase('downloading');
        pollFeishu();
        return;
      }
      // The QR may only exist once the SDK finished downloading.
      const img = res.qr_image || res.qrcode_url;
      if (img) {
        setQr(img);
        setLink(res.qrcode_url || '');
        setPhase(p => (p === 'downloading' ? 'waiting' : p));
      }
      if (status === 'done') {
        await connect({feishu_app_id: res.app_id, feishu_app_secret: res.app_secret});
      } else if (status === 'expired') {
        fail('二维码已过期');
      } else if (status === 'denied') {
        fail('授权被拒绝');
      } else if (status === 'error') {
        fail(res.message || copy.fail);
      } else {
        pollFeishu();
      }
    });

  const startFeishu = async () => {
    try {
      const res = await getFeishuRegister();
      if (!alive.current) {
        return;
      }
      if (res.register_status === 'downloading') {
        setPhase('downloading');
        pollFeishu();
        return;
      }
      setQr(res.qr_image || res.qrcode_url || '');
      setLink(res.qrcode_url || '');
      setPhase('waiting');
      pollFeishu();
    } catch (e) {
      fail(`${copy.fail}：${describeConnectError(e)}`);
    }
  };

  const start = () => {
    stop();
    setPhase('loading');
    setError('');
    if (provider === 'weixin') {
      startWeixin();
    } else {
      startFeishu();
    }
  };

  useEffect(() => {
    alive.current = true;
    start();
    return () => {
      alive.current = false;
      stop();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider, instanceId]);

  if (phase === 'loading' || phase === 'downloading') {
    return (
      <View style={[styles.panel, styles.quiet]}>
        <ActivityIndicator color={t.t3} />
        <Text style={styles.muted}>{phase === 'loading' ? copy.loading : '正在下载飞书组件…'}</Text>
        {phase === 'downloading' && <Text style={styles.tip}>首次接入需要下载约 1 MB，完成后自动继续</Text>}
      </View>
    );
  }

  if (phase === 'success') {
    return (
      <View style={[styles.panel, styles.quiet]}>
        <View style={styles.doneMark}>
          <Icon icon={faCheck} size={18} color={t.accent} />
        </View>
        <Text style={styles.doneText}>{copy.success}</Text>
      </View>
    );
  }

  if (phase === 'error') {
    return (
      <View style={[styles.panel, styles.quiet]}>
        <Text style={styles.errorText}>{error}</Text>
        <Pressable
          accessibilityRole="button"
          onPress={start}
          style={({pressed}) => [styles.retry, pressed && styles.pressed]}>
          <Icon icon={faRotateRight} size={12} color={t.t1} />
          <Text style={styles.retryText}>重试</Text>
        </Pressable>
      </View>
    );
  }

  const scanned = phase === 'scanned' && provider === 'weixin';
  return (
    <View style={styles.panel}>
      <View style={styles.qrFrame}>
        {qr ? (
          <Image
            source={{uri: qr}}
            accessibilityLabel={provider === 'weixin' ? '微信登录二维码' : '飞书授权二维码'}
            style={[styles.qr, scanned && styles.qrFaded]}
            resizeMode="contain"
          />
        ) : (
          <View style={styles.qr} />
        )}
        {scanned && (
          <View style={styles.scannedMark}>
            <Icon icon={faCheck} size={20} color="#FFFFFF" />
          </View>
        )}
      </View>
      <View style={styles.statusRow}>
        <View style={[styles.dot, scanned && styles.dotOn]} />
        <Text style={[styles.status, scanned && styles.statusOn]}>{scanned ? copy.scanned : copy.waiting}</Text>
      </View>
      <Text style={styles.tip}>{copy.tip}</Text>
      {!!link && (
        <Pressable
          accessibilityRole="link"
          onPress={() => Linking.openURL(link).catch(() => undefined)}
          style={({pressed}) => [styles.open, pressed && styles.pressed]}>
          <Text style={styles.openText}>在飞书中打开</Text>
          <Icon icon={faArrowUpRightFromSquare} size={11} color={t.accent} />
        </Pressable>
      )}
    </View>
  );
}

const useStyles = makeStyles(t => ({
  panel: {
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingTop: 22,
    paddingBottom: 18,
    borderRadius: radius.md,
    backgroundColor: t.bg1,
    borderWidth: 1,
    borderColor: t.line1,
  },
  quiet: {gap: 10, paddingVertical: 36},
  qrFrame: {
    padding: 12,
    borderRadius: radius.md,
    backgroundColor: '#FFFFFF',
    borderWidth: t.isDark ? 0 : 1,
    borderColor: t.line1,
  },
  qr: {width: QR_SIZE, height: QR_SIZE},
  qrFaded: {opacity: 0.12},
  scannedMark: {
    position: 'absolute',
    top: 12 + QR_SIZE / 2 - 24,
    left: 12 + QR_SIZE / 2 - 24,
    width: 48,
    height: 48,
    borderRadius: 24,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: t.green,
  },
  statusRow: {flexDirection: 'row', alignItems: 'center', gap: 7, marginTop: 16},
  dot: {width: 6, height: 6, borderRadius: 3, backgroundColor: t.kind.image[1]},
  dotOn: {backgroundColor: t.accent},
  status: {fontSize: 15, fontWeight: '500', color: t.t1},
  statusOn: {color: t.accent},
  tip: {fontSize: 12, lineHeight: 18, color: t.t3, marginTop: 6, textAlign: 'center'},
  muted: {fontSize: 13, color: t.t2},
  open: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginTop: 14,
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 999,
    backgroundColor: t.accentSoft,
  },
  openText: {fontSize: 13, fontWeight: '600', color: t.accent},
  pressed: {opacity: 0.7},
  doneMark: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: t.accentSoft,
  },
  doneText: {fontSize: 14, fontWeight: '500', color: t.accent},
  errorText: {fontSize: 13, lineHeight: 20, color: t.danger, textAlign: 'center'},
  retry: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: radius.sm,
    backgroundColor: t.bg2,
    borderWidth: 1,
    borderColor: t.line1,
  },
  retryText: {fontSize: 13, fontWeight: '500', color: t.t1},
}));
