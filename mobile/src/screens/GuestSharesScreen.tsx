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
import {Pressable, RefreshControl, ScrollView, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {deleteGuestShare, getGuestShares, getIntegrations, guestShareAction, setGuestSharesEnabled} from '../api/cowApi';
import {ApiError} from '../api/http';
import {InfoRow, Section} from '../components/forms';
import {Icon} from '../components/Icon';
import {ChoiceSheet, ConfirmSheet, MONO, Notice, Toggle, type Choice} from '../components/settings';
import {SHEET_DISMISS_MS} from '../components/Sheet';
import {showToast, ToastHost} from '../components/Toast';
import {EmptyState, IconButton, PageHeader} from '../components/ui';
import {tr, trf, type MessageKey} from '../i18n';
import {openWebPage} from '../navigation/openWeb';
import type {RootStackParamList} from '../navigation/types';
import type {GuestShare, GuestSharesOverview} from '../protocol/resources';
import {activeServer, describeConnectError} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {copyText} from '../utils/clipboard';
import {SHARE_DEFAULT_COLOR, shareChips, shareConfig, shareFailure, shareUrl, STATUS_LABEL} from '../utils/guestShares';
import {integrationBase} from '../utils/integrations';

type Props = StackScreenProps<RootStackParamList, 'GuestShares'>;

type MenuKey = 'edit' | 'copy' | 'open' | 'reset-link' | 'disable' | 'enable' | 'delete';
type Risky = 'reset-link' | 'disable' | 'delete';

export function describeShareError(e: unknown): string {
  if (e instanceof ApiError && (e.kind === 'http' || e.kind === 'server')) {
    return shareFailure(typeof e.body?.reason === 'string' ? e.body.reason : undefined, e.message);
  }
  return describeConnectError(e);
}

const CONFIRMS: Record<Risky, {title: MessageKey; label: MessageKey; message: MessageKey}> = {
  'reset-link': {title: 'share_reset_link', label: 'share_reset', message: 'share_reset_link_confirm'},
  disable: {title: 'share_disable', label: 'share_disable', message: 'share_disable_confirm'},
  delete: {title: 'common_delete', label: 'common_delete', message: 'share_delete_confirm'},
};

const DONE: Record<string, MessageKey> = {
  confirm: 'share_done_confirm',
  'reset-link': 'share_done_reset_link',
  disable: 'share_done_disable',
  enable: 'share_done_enable',
  delete: 'common_deleted',
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
      setBase(integrationBase(access, activeServer()?.baseUrl ?? ''));
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
        <PageHeader title={tr('share_title')} onBack={navigation.goBack} />
        <EmptyState loading={!error} title={tr('common_load_failed')} hint={error ?? undefined} />
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
      showToast(tr(DONE[action]));
    } catch (e) {
      showToast(describeShareError(e));
    }
  };

  const copy = async (url: string) => {
    showToast(tr((await copyText(url)) ? 'share_link_copied' : 'access_copy_failed'));
  };

  const open = (url: string) => {
    openWebPage(url);
  };

  const edit = (share: GuestShare, focus?: 'password') => navigation.navigate('GuestShareEdit', {slug: share.slug, focus});

  const menuOptions = (share: GuestShare): Choice<MenuKey>[] => {
    const url = shareUrl(share, base);
    return [
      {key: 'edit', label: tr('common_edit'), icon: faPen},
      ...(url
        ? [
            {key: 'copy' as const, label: tr('share_copy_link'), icon: faCopy},
            {key: 'open' as const, label: tr('share_open_browser'), icon: faArrowUpRightFromSquare},
            {
              key: 'reset-link' as const,
              label: tr('share_reset_link'),
              desc: tr('share_reset_link_desc'),
              icon: faArrowRotateRight,
            },
          ]
        : []),
      share.disabled
        ? {key: 'enable' as const, label: tr('share_enable'), icon: faCirclePlay}
        : {key: 'disable' as const, label: tr('share_disable'), desc: tr('share_disable_desc'), icon: faCirclePause},
      {key: 'delete', label: tr('common_delete'), icon: faTrashCan},
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
        title={tr('share_title')}
        subtitle={tr('share_subtitle')}
        onBack={navigation.goBack}
        right={
          feature.enabled ? (
            <IconButton icon={faPlus} label={tr('share_new')} onPress={() => navigation.navigate('GuestShareEdit', {})} />
          ) : undefined
        }
      />
      <ScrollView
        contentContainerStyle={{paddingBottom: insets.bottom + 32}}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={t.t3} colors={[t.green]} />}>
        <Section footer={tr('share_feature_footer')}>
          <InfoRow
            first
            title={tr('share_feature_enable')}
            right={<Toggle value={feature.enabled} onValueChange={toggleFeature} label={tr('share_feature_enable')} />}
          />
        </Section>

        {feature.enabled && !feature.web_password_set && (
          <Notice style={styles.notice}>{tr('share_need_password')}</Notice>
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
            <Text style={styles.blankTitle}>{tr('share_new')}</Text>
            <Text style={styles.blankHint}>{tr('share_blank_hint')}</Text>
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
        title={
          confirm
            ? trf('share_confirm_title', {
                action: tr(CONFIRMS[confirm.action].title),
                name: confirm.share.name || confirm.share.slug,
              })
            : ''
        }
        message={confirm ? trf(CONFIRMS[confirm.action].message, {name: confirm.share.name || confirm.share.slug}) : ''}
        confirmLabel={confirm ? tr(CONFIRMS[confirm.action].label) : ''}
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
        accessibilityLabel={trf('share_edit_name', {name})}
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
        <IconButton icon={faEllipsis} label={trf('share_more_actions', {name})} onPress={onMenu} />
      </Pressable>

      <View style={[styles.link, !(url && live) && styles.linkDim]}>
        {/* Not selectable: Android wraps selectable text instead of ellipsizing it. */}
        <Text style={styles.linkText} numberOfLines={1} ellipsizeMode="middle">
          {url || tr('share_no_link')}
        </Text>
        {!!url && (
          <>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={tr('share_copy_link')}
              hitSlop={8}
              onPress={() => onCopy(url)}
              style={styles.linkButton}>
              <Icon icon={faCopy} size={13} color={t.t2} />
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={tr('common_open')}
              hitSlop={8}
              onPress={() => onOpen(url)}
              style={styles.linkButton}>
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
          text={tr(pending.length ? 'share_pending' : 'share_unconfirmed')}
          items={pending}
          action={tr('share_confirm_apply')}
          icon={faCircleCheck}
          onPress={onConfirm}
        />
      )}
      {share.status === 'password_missing' && (
        <Callout text={tr('share_password_missing')} action={tr('share_set_password')} onPress={() => onEdit('password')} />
      )}
      {!!share.notices?.length && <Callout text={tr('share_notices')} items={share.notices} quiet />}
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
