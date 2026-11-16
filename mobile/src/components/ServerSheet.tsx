import {faCheck, faMobileScreen, faPlus, faServer} from '@fortawesome/free-solid-svg-icons';
import type {IconDefinition} from '@fortawesome/fontawesome-svg-core';
import React, {useEffect, useState} from 'react';
import {ActivityIndicator, Pressable, Text, View} from 'react-native';
import {tr} from '../i18n';
import {isLocalKernelAvailable, LOCAL_SERVER_ID} from '../kernel/localKernel';
import {describeConnectError, useServerStore} from '../store/serverStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {Icon} from './Icon';
import {Sheet} from './Sheet';
import {showToast} from './Toast';

function hostOf(baseUrl: string): string {
  return baseUrl.replace(/^https?:\/\//, '');
}

/** Pick where the agent runs: the kernel on this phone or one of the saved servers. */
export function ServerSheet({visible, onClose}: {visible: boolean; onClose: () => void}) {
  const t = useTheme();
  const styles = useStyles();
  const servers = useServerStore(s => s.servers);
  const activeId = useServerStore(s => s.activeId);
  const [pending, setPending] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null);
  const remotes = servers.filter(s => !s.local);

  useEffect(() => {
    if (!visible) {
      setConfirmRemove(null);
    }
  }, [visible]);

  const select = async (id: string) => {
    if (pending) {
      return;
    }
    if (id === activeId) {
      onClose();
      return;
    }
    setPending(id);
    try {
      await useServerStore.getState().switchTo(id);
    } catch (e) {
      showToast(describeConnectError(e));
    } finally {
      setPending(null);
    }
  };

  const remove = (id: string) => {
    if (confirmRemove !== id) {
      setConfirmRemove(id);
      return;
    }
    setConfirmRemove(null);
    useServerStore.getState().removeServer(id);
  };

  const row = (id: string, icon: IconDefinition, name: string, meta: string, removable: boolean) => {
    const selected = id === activeId;
    return (
      <Pressable
        key={id}
        accessibilityRole="button"
        accessibilityState={{selected, busy: pending === id}}
        onPress={() => select(id)}
        style={({pressed}) => [styles.row, pressed && styles.pressed]}>
        <View style={[styles.badge, selected && styles.badgeActive]}>
          <Icon icon={icon} size={14} color={selected ? t.accent : t.t3} />
        </View>
        <View style={styles.text}>
          <Text style={styles.name} numberOfLines={1}>
            {name}
          </Text>
          <Text style={styles.meta} numberOfLines={1}>
            {meta}
          </Text>
        </View>
        {pending === id ? (
          <ActivityIndicator size="small" color={t.t3} />
        ) : selected ? (
          <Icon icon={faCheck} size={13} color={t.accent} />
        ) : (
          removable && (
            <Pressable accessibilityRole="button" hitSlop={8} onPress={() => remove(id)}>
              <Text style={[styles.remove, confirmRemove === id && styles.removeConfirm]}>
                {confirmRemove === id ? tr('server_remove_confirm') : tr('server_remove')}
              </Text>
            </Pressable>
          )
        )}
      </Pressable>
    );
  };

  return (
    <Sheet visible={visible} onClose={onClose} title={tr('server_sheet_title')}>
      {isLocalKernelAvailable() && row(LOCAL_SERVER_ID, faMobileScreen, tr('server_local'), tr('server_local_meta'), false)}
      {remotes.map(s => row(s.id, faServer, s.name, hostOf(s.baseUrl), true))}
      <Pressable
        accessibilityRole="button"
        onPress={() => {
          onClose();
          useServerStore.getState().addServer();
        }}
        style={({pressed}) => [styles.row, pressed && styles.pressed]}>
        <View style={styles.badge}>
          <Icon icon={faPlus} size={13} color={t.t3} />
        </View>
        <Text style={styles.add}>{tr('server_add')}</Text>
      </Pressable>
    </Sheet>
  );
}

const useStyles = makeStyles(t => ({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 12,
    paddingVertical: 11,
    borderRadius: radius.md,
  },
  pressed: {backgroundColor: t.bg2},
  badge: {
    width: 34,
    height: 34,
    borderRadius: 17,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: t.bg2,
  },
  badgeActive: {backgroundColor: t.accentSoft},
  text: {flex: 1},
  name: {fontSize: 16, fontWeight: '500', color: t.t1, letterSpacing: -0.2},
  meta: {fontSize: 12, color: t.t3, marginTop: 3},
  remove: {fontSize: 13, color: t.t4},
  removeConfirm: {color: t.danger},
  add: {flex: 1, fontSize: 15, color: t.t2},
}));
