import {faCheck, faMobileScreen, faServer} from '@fortawesome/free-solid-svg-icons';
import React, {useEffect, useState} from 'react';
import {ActivityIndicator, Pressable, Text, View} from 'react-native';
import {tr} from '../i18n';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {Icon} from './Icon';
import {useServerPicker, type ServerEntry} from './ServerPicker';
import {TileButtons} from './settings';
import {SHEET_DISMISS_MS, Sheet} from './Sheet';

/** Switch where the agent runs, pair another device, or go on to manage them all. */
export function ServerSheet({
  visible,
  onClose,
  onManage,
}: {
  visible: boolean;
  onClose: () => void;
  /** Opens the devices page. */
  onManage?: () => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  const picker = useServerPicker();
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null);

  useEffect(() => {
    if (!visible) {
      setConfirmRemove(null);
    }
  }, [visible]);

  const select = (id: string) => {
    if (id === picker.activeId) {
      onClose();
      return;
    }
    picker.select(id);
  };

  const remove = (id: string) => {
    if (confirmRemove !== id) {
      setConfirmRemove(id);
      return;
    }
    setConfirmRemove(null);
    picker.remove(id);
  };

  const leaveTo = (next: () => void) => {
    onClose();
    setTimeout(next, SHEET_DISMISS_MS);
  };

  const row = (s: ServerEntry) => {
    const selected = s.id === picker.activeId;
    const busy = picker.pending === s.id;
    // Two sibling buttons: on the web a button inside a button is invalid HTML.
    return (
      <View key={s.id} style={[styles.row, selected && styles.rowActive]}>
        <Pressable
          accessibilityRole="button"
          accessibilityState={{selected, busy}}
          onPress={() => select(s.id)}
          style={({pressed}) => [styles.rowMain, pressed && styles.pressed]}>
          <View style={[styles.badge, selected && styles.badgeActive]}>
            <Icon icon={s.local ? faMobileScreen : faServer} size={14} color={selected ? t.accent : t.t3} />
          </View>
          <View style={styles.text}>
            <Text style={styles.name} numberOfLines={1}>
              {s.name}
            </Text>
            <Text style={styles.meta} numberOfLines={1}>
              {s.meta}
            </Text>
          </View>
          {busy ? (
            <ActivityIndicator size="small" color={t.t3} />
          ) : (
            selected && <Icon icon={faCheck} size={13} color={t.accent} />
          )}
        </Pressable>
        {!s.local && !selected && !busy && (
          <Pressable accessibilityRole="button" hitSlop={8} onPress={() => remove(s.id)} style={styles.removeButton}>
            <Text style={[styles.remove, confirmRemove === s.id && styles.removeConfirm]}>
              {confirmRemove === s.id ? tr('server_remove_confirm') : tr('server_remove')}
            </Text>
          </Pressable>
        )}
      </View>
    );
  };

  return (
    <>
      <Sheet
        visible={visible}
        onClose={onClose}
        title={tr('server_sheet_title')}
        action={onManage ? {label: tr('devices_manage'), onPress: () => leaveTo(onManage)} : undefined}>
        {picker.entries.map(row)}
        <Text style={styles.group}>{tr('devices_connect_new')}</Text>
        <TileButtons items={picker.connectActions(onClose)} inSheet style={styles.connect} />
      </Sheet>
      {picker.overlays}
    </>
  );
}

const useStyles = makeStyles(t => ({
  group: {fontSize: 13, fontWeight: '600', color: t.t2, paddingHorizontal: 12, marginTop: 18, marginBottom: 8},
  connect: {marginHorizontal: 4},
  row: {flexDirection: 'row', alignItems: 'center', borderRadius: radius.md},
  rowActive: {backgroundColor: t.bg2},
  rowMain: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 12,
    paddingVertical: 11,
  },
  removeButton: {paddingRight: 12},
  pressed: {opacity: 0.7},
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
  meta: {fontSize: 13, color: t.t3, marginTop: 3},
  remove: {fontSize: 13, color: t.t3},
  removeConfirm: {color: t.danger},
}));
