import {
  faArrowRotateRight,
  faArrowUpRightFromSquare,
  faCircleCheck,
  faCirclePause,
  faCirclePlay,
  faCopy,
  faEllipsis,
  faPen,
  faPlus,
  faTrashCan,
} from '@fortawesome/free-solid-svg-icons';
import {useFocusEffect} from '@react-navigation/native';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useState} from 'react';
import {Linking, Pressable, RefreshControl, ScrollView, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {deleteGuestShare, getGuestShares, getIntegrations, guestShareAction, setGuestSharesEnabled} from '../api/cowApi';
import {ApiError} from '../api/http';
import {InfoRow, Section} from '../components/forms';
import {Icon} from '../components/Icon';
import {ChoiceSheet, ConfirmSheet, MONO, Notice, Toggle, type Choice} from '../components/settings';
import {SHEET_DISMISS_MS} from '../components/Sheet';
import {showToast, ToastHost} from '../components/Toast';
import {EmptyState, IconButton, PageHeader} from '../components/ui';
import type {RootStackParamList} from '../navigation/types';
import type {GuestShare, GuestSharesOverview} from '../protocol/resources';
import {activeServer, describeConnectError} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {copyText} from '../utils/clipboard';
import {SHARE_DEFAULT_COLOR, shareChips, shareConfig, shareFailure, shareUrl, STATUS_LABEL} from '../utils/guestShares';

type Props = StackScreenProps<RootStackParamList, 'GuestShares'>;

type MenuKey = 'edit' | 'copy' | 'open' | 'reset-link' | 'disable' | 'enable' | 'delete';
type Risky = 'reset-link' | 'disable' | 'delete';

export function describeShareError(e: unknown): string {
  if (e instanceof ApiError && (e.kind === 'http' || e.kind === 'server')) {
    return shareFailure(typeof e.body?.reason === 'string' ? e.body.reason : undefined, e.message);
  }
  return describeConnectError(e);
}

const CONFIRMS: Record<Risky, {title: string; label: string; message: (name: string) => string}> = {
  'reset-link': {
    title: '重置链接',
    label: '重置',
    message: name => `重置后「${name}」的旧链接和嵌入代码立即失效，正在对话的访客也会断开。`,
  },
  disable: {
    title: '停用',
    label: '停用',
    message: name => `停用后「${name}」的链接暂时无法访问，可以随时重新启用。`,
  },
  delete: {
    title: '删除',
    label: '删除',
    message: name => `「${name}」的配置、访客文件和对话记录都会被删除，且无法恢复。`,
  },
};

const DONE: Record<string, string> = {
  confirm: '已确认',
  'reset-link': '链接已重置',
  disable: '已停用',
  enable: '已启用',
  delete: '已删除',
};

export function GuestSharesScreen({navigation}: Props) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const [data, setData] = useState<GuestSharesOverview | null>(null);
  const [base, setBase] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [menu, setMenu] = useState<GuestShare | null>(null);
  const [confirm, setConfirm] = useState<{share: GuestShare; action: Risky} | null>(null);

  const load = useCallback(async () => {
    try {
      const [overview, access] = await Promise.all([getGuestShares(), getIntegrations().catch(() => null)]);
      setData(overview);
      setBase(access?.public_url || access?.lan_urls[0] || activeServer()?.baseUrl || '');
      setError(null);
    } catch (e) {
      setError(describeConnectError(e));
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  if (!data) {
    return (
      <View style={styles.root}>
        <PageHeader title="访客页面" onBack={navigation.goBack} />
        <EmptyState loading={!error} title="加载失败" hint={error ?? undefined} />
      </View>
    );
  }

  const {feature, shares} = data;

  const refresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const replace = (share: GuestShare) =>
    setData(prev => (prev ? {...prev, shares: prev.shares.map(s => (s.slug === share.slug ? share : s))} : prev));

  const toggleFeature = async (enabled: boolean) => {
    try {
      const res = await setGuestSharesEnabled(enabled);
      setData(prev => (prev ? {...prev, feature: res.feature} : prev));
      if (enabled) {
        load();
      }
    } catch (e) {
      showToast(describeShareError(e));
    }
  };

  const run = async (share: GuestShare, action: 'confirm' | 'enable' | Risky) => {
    try {
      if (action === 'delete') {
        await deleteGuestShare(share.slug);
        setData(prev => (prev ? {...prev, shares: prev.shares.filter(s => s.slug !== share.slug)} : prev));
      } else {
        replace((await guestShareAction(share.slug, action)).share);
      }
      setConfirm(null);
      showToast(DONE[action]);
    } catch (e) {
      showToast(describeShareError(e));
    }
  };

  const copy = async (url: string) => {
    showToast((await copyText(url)) ? '链接已复制' : '复制失败');
  };

  const open = (url: string) => {
    Linking.openURL(url).catch(() => showToast('无法打开链接'));
  };

  const edit = (share: GuestShare, focus?: 'password') => navigation.navigate('GuestShareEdit', {slug: share.slug, focus});

  const menuOptions = (share: GuestShare): Choice<MenuKey>[] => {
    const url = shareUrl(share, base);
    return [
      {key: 'edit', label: '编辑', icon: faPen},
      ...(url
        ? [
            {key: 'copy' as const, label: '复制链接', icon: faCopy},
            {key: 'open' as const, label: '在浏览器打开', icon: faArrowUpRightFromSquare},
            {key: 'reset-link' as const, label: '重置链接', desc: '旧链接和嵌入代码立即失效', icon: faArrowRotateRight},
          ]
        : []),
      share.disabled
        ? {key: 'enable' as const, label: '启用', icon: faCirclePlay}
        : {key: 'disable' as const, label: '停用', desc: '链接暂时无法访问', icon: faCirclePause},
      {key: 'delete', label: '删除', icon: faTrashCan},
    ];
  };

  const onMenu = (key: MenuKey) => {
    const share = menu;
    setMenu(null);
    if (!share) {
      return;
    }
    const url = shareUrl(share, base);
    if (key === 'edit') {
      edit(share);
    } else if (key === 'copy') {
      copy(url);
    } else if (key === 'open') {
      open(url);
    } else if (key === 'enable') {
      run(share, 'enable');
    } else {
      setTimeout(() => setConfirm({share, action: key}), SHEET_DISMISS_MS);
    }
  };

  return (
    <View style={styles.root}>
      <PageHeader
        title="访客页面"
        subtitle="把 Agent 分享成独立的对话页面"
        onBack={navigation.goBack}
        right={
          feature.enabled ? (
            <IconButton icon={faPlus} label="新建访客页面" onPress={() => navigation.navigate('GuestShareEdit', {})} />
          ) : undefined
        }
      />
      <ScrollView
        contentContainerStyle={{paddingBottom: insets.bottom + 32}}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={t.t3} colors={[t.green]} />}>
        <Section footer="访客无需登录，打开链接即可和 Agent 对话，也可以嵌入你的网站。">
          <InfoRow
            first
            title="启用访客页面"
            right={<Toggle value={feature.enabled} onValueChange={toggleFeature} label="启用访客页面" />}
          />
        </Section>

        {feature.enabled && !feature.web_password_set && (
          <Notice style={styles.notice}>还没有设置访问密码，访客页面暂不可用。先在「设置 › 访问密码」里设置一个。</Notice>
        )}

        {feature.enabled &&
          shares.map(share => (
            <ShareCard
              key={share.slug}
              share={share}
              url={shareUrl(share, base)}
              onEdit={focus => edit(share, focus)}
              onMenu={() => setMenu(share)}
              onConfirm={() => run(share, 'confirm')}
              onCopy={copy}
              onOpen={open}
            />
          ))}

        {feature.enabled && !shares.length && (
          <Pressable
            accessibilityRole="button"
            onPress={() => navigation.navigate('GuestShareEdit', {})}
            style={({pressed}) => [styles.blank, pressed && styles.pressed]}>
            <Icon icon={faPlus} size={14} color={t.accent} />
            <Text style={styles.blankTitle}>新建访客页面</Text>
            <Text style={styles.blankHint}>选好模型、写一句欢迎语，就能把链接发给别人</Text>
          </Pressable>
        )}
      </ScrollView>

      <ChoiceSheet
        visible={!!menu}
        title={menu?.name || menu?.slug || ''}
        options={menu ? menuOptions(menu) : []}
        onSelect={onMenu}
        onClose={() => setMenu(null)}
      />
      <ConfirmSheet
        visible={!!confirm}
        title={confirm ? `${CONFIRMS[confirm.action].title}「${confirm.share.name || confirm.share.slug}」` : ''}
        message={confirm ? CONFIRMS[confirm.action].message(confirm.share.name || confirm.share.slug) : ''}
        confirmLabel={confirm ? CONFIRMS[confirm.action].label : ''}
        danger
        onConfirm={() => (confirm ? run(confirm.share, confirm.action) : undefined)}
        onClose={() => setConfirm(null)}
      />
      <ToastHost bottom={insets.bottom + 28} />
    </View>
  );
}

function ShareCard({
  share,
  url,
  onEdit,
  onMenu,
  onConfirm,
  onCopy,
  onOpen,
}: {
  share: GuestShare;
  url: string;
  onEdit: (focus?: 'password') => void;
  onMenu: () => void;
  onConfirm: () => void;
  onCopy: (url: string) => void;
  onOpen: (url: string) => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  const name = share.name || share.slug;
  const color = shareConfig(share).branding?.color || SHARE_DEFAULT_COLOR;
  const live = share.status === 'active';
  const warn = share.status === 'unconfirmed' || share.status === 'password_missing';
  const pending = share.pending ?? [];
  return (
    <View style={styles.card}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`编辑 ${name}`}
        onPress={() => onEdit()}
        style={({pressed}) => [styles.cardHead, pressed && styles.pressed]}>
        <View style={[styles.mark, {backgroundColor: color}]}>
          <Text style={styles.markText}>{name.slice(0, 1).toUpperCase()}</Text>
        </View>
        <View style={styles.flex}>
          <Text style={styles.cardName} numberOfLines={1}>
            {name}
          </Text>
          <View style={styles.statusLine}>
            <View style={[styles.dot, live ? styles.dotOn : warn ? styles.dotWarn : styles.dotOff]} />
            <Text style={[styles.statusText, live ? styles.on : warn ? styles.warn : styles.off]}>{STATUS_LABEL[share.status]}</Text>
          </View>
        </View>
        <IconButton icon={faEllipsis} label={`${name} 的更多操作`} onPress={onMenu} />
      </Pressable>

      <View style={[styles.link, !(url && live) && styles.linkDim]}>
        <Text style={styles.linkText} numberOfLines={1} selectable={!!url}>
          {url || '确认后生成链接'}
        </Text>
        {!!url && (
          <>
            <Pressable accessibilityRole="button" accessibilityLabel="复制链接" hitSlop={8} onPress={() => onCopy(url)} style={styles.linkButton}>
              <Icon icon={faCopy} size={13} color={t.t2} />
            </Pressable>
            <Pressable accessibilityRole="button" accessibilityLabel="打开" hitSlop={8} onPress={() => onOpen(url)} style={styles.linkButton}>
              <Icon icon={faArrowUpRightFromSquare} size={12} color={t.t2} />
            </Pressable>
          </>
        )}
      </View>

      <View style={styles.chips}>
        {shareChips(share).map(c => (
          <Text key={c} style={styles.chip}>
            {c}
          </Text>
        ))}
      </View>

      {(share.status === 'unconfirmed' || pending.length > 0) && (
        <Callout
          text={pending.length ? '配置文件的改动放宽了访客权限，确认后生效：' : '这个访客页面是在配置文件中创建的，确认后才会生成链接。'}
          items={pending}
          action="确认生效"
          icon={faCircleCheck}
          onPress={onConfirm}
        />
      )}
      {share.status === 'password_missing' && (
        <Callout text="已开启访问密码但还没有设置，访客暂时无法进入。" action="设置密码" onPress={() => onEdit('password')} />
      )}
      {!!share.notices?.length && <Callout text="配置提示" items={share.notices} quiet />}
    </View>
  );
}

function Callout({
  text,
  items,
  action,
  icon,
  quiet,
  onPress,
}: {
  text: string;
  items?: string[];
  action?: string;
  icon?: typeof faCircleCheck;
  quiet?: boolean;
  onPress?: () => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  return (
    <View style={[styles.callout, quiet && styles.calloutQuiet]}>
      <Text style={[styles.calloutText, quiet && styles.calloutTextQuiet]}>{text}</Text>
      {items?.map(item => (
        <Text key={item} style={[styles.calloutItem, quiet && styles.calloutTextQuiet]}>
          · {item}
        </Text>
      ))}
      {!!action && (
        <Pressable accessibilityRole="button" onPress={onPress} style={({pressed}) => [styles.calloutAction, pressed && styles.pressedText]}>
          {icon && <Icon icon={icon} size={12} color={t.kind.image[1]} />}
          <Text style={styles.calloutActionText}>{action}</Text>
        </Pressable>
      )}
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  flex: {flex: 1, minWidth: 0},
  notice: {marginHorizontal: 14, marginTop: 14},
  pressed: {backgroundColor: t.bg2},
  pressedText: {opacity: 0.6},
  card: {
    marginHorizontal: 14,
    marginTop: 14,
    paddingBottom: 14,
    borderRadius: radius.md,
    backgroundColor: t.bg1,
    borderWidth: 1,
    borderColor: t.line1,
    overflow: 'hidden',
  },
  cardHead: {flexDirection: 'row', alignItems: 'center', gap: 12, paddingLeft: 14, paddingRight: 6, paddingVertical: 12},
  mark: {width: 38, height: 38, borderRadius: radius.sm, alignItems: 'center', justifyContent: 'center'},
  markText: {fontSize: 16, fontWeight: '700', color: '#fff'},
  cardName: {fontSize: 16, fontWeight: '600', letterSpacing: -0.2, color: t.t1},
  statusLine: {flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 4},
  dot: {width: 6, height: 6, borderRadius: 3},
  dotOn: {backgroundColor: t.accent},
  dotWarn: {backgroundColor: t.kind.image[1]},
  dotOff: {backgroundColor: t.t4},
  statusText: {fontSize: 12},
  on: {color: t.accent},
  warn: {color: t.kind.image[1]},
  off: {color: t.t3},
  link: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    marginHorizontal: 14,
    paddingLeft: 12,
    paddingRight: 4,
    minHeight: 38,
    borderRadius: radius.sm,
    backgroundColor: t.bg2,
  },
  linkDim: {opacity: 0.6},
  linkText: {flex: 1, fontFamily: MONO, fontSize: 12, color: t.t2},
  linkButton: {width: 32, height: 32, alignItems: 'center', justifyContent: 'center'},
  chips: {flexDirection: 'row', flexWrap: 'wrap', gap: 6, paddingHorizontal: 14, paddingTop: 10},
  chip: {
    fontSize: 11.5,
    color: t.t3,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: t.line1,
    overflow: 'hidden',
  },
  callout: {
    marginHorizontal: 14,
    marginTop: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: radius.sm,
    backgroundColor: t.kind.image[0],
  },
  calloutQuiet: {backgroundColor: t.bg2},
  calloutText: {fontSize: 12.5, lineHeight: 19, color: t.kind.image[1]},
  calloutItem: {fontSize: 12, lineHeight: 18, color: t.kind.image[1], marginTop: 2},
  calloutTextQuiet: {color: t.t2},
  calloutAction: {flexDirection: 'row', alignItems: 'center', gap: 6, alignSelf: 'flex-start', marginTop: 8},
  calloutActionText: {fontSize: 13, fontWeight: '600', color: t.kind.image[1]},
  blank: {
    alignItems: 'center',
    gap: 6,
    marginHorizontal: 14,
    marginTop: 14,
    paddingVertical: 26,
    borderRadius: radius.md,
    borderWidth: 1,
    borderStyle: 'dashed',
    borderColor: t.line2,
  },
  blankTitle: {fontSize: 15, fontWeight: '500', color: t.accent, marginTop: 4},
  blankHint: {fontSize: 12, color: t.t3},
}));
