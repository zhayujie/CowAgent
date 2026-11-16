import type {StackScreenProps} from '@react-navigation/stack';
import React, {useEffect, useState} from 'react';
import {ScrollView, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {ActionButton, ConfirmSheet, Footnote, SettingRow, SwitchRow} from '../components/settings';
import {showToast, ToastHost} from '../components/Toast';
import {GroupLabel, PageHeader} from '../components/ui';
import {tr, trf} from '../i18n';
import {BUILTIN_VIEWS, menuItemIcon} from '../navigation/menuViews';
import type {RootStackParamList} from '../navigation/types';
import type {MenuItem} from '../protocol/resources';
import {MENU_REQUIRED, menuGroupLabel, useMenuStore} from '../store/menuStore';
import {describeConnectError} from '../store/serverStore';
import {makeStyles} from '../theme/theme';

type Props = StackScreenProps<RootStackParamList, 'MenuEditor'>;

/** Built-ins this app has no screen for (desktop-only pages) stay in the document but aren't offered. */
const editable = (i: MenuItem) => i.type !== 'builtin' || i.view === 'chat' || !!BUILTIN_VIEWS[i.view];

export function MenuEditorScreen({navigation}: Props) {
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const doc = useMenuStore(s => s.doc);
  const customised = useMenuStore(s => s.customised);
  const load = useMenuStore(s => s.load);
  const setHidden = useMenuStore(s => s.setHidden);
  const reset = useMenuStore(s => s.reset);
  const [confirmReset, setConfirmReset] = useState(false);

  useEffect(() => {
    load().catch(e => showToast(trf('menu_load_failed', {error: describeConnectError(e)})));
  }, [load]);

  const toggle = (view: string, shown: boolean) =>
    setHidden(view, !shown).catch(e => showToast(trf('common_save_failed_detail', {error: describeConnectError(e)})));

  return (
    <View style={styles.root}>
      <PageHeader title={tr('settings_menu')} onBack={navigation.goBack} />
      <ScrollView contentContainerStyle={{paddingBottom: insets.bottom + 32}}>
        {doc.groups.map((group, gi) => {
          const items = group.items.filter(editable);
          if (!items.length) {
            return null;
          }
          return (
            <View key={group.id}>
              <GroupLabel style={gi === 0 ? styles.firstGroup : styles.group}>{menuGroupLabel(group)}</GroupLabel>
              {items.map((item, i) => {
                const last = i === items.length - 1;
                if (item.type === 'builtin') {
                  const required = MENU_REQUIRED.has(item.view);
                  const label = item.title || (item.view === 'chat' ? tr('menu_chat') : BUILTIN_VIEWS[item.view].label);
                  return (
                    <SwitchRow
                      key={item.id}
                      icon={menuItemIcon(item)}
                      title={label}
                      detail={required ? tr('menu_required') : undefined}
                      value={!item.hidden}
                      disabled={required}
                      onValueChange={v => toggle(item.view, v)}
                      last={last}
                    />
                  );
                }
                return (
                  <SettingRow
                    key={item.id}
                    icon={menuItemIcon(item)}
                    title={item.title}
                    detail={item.type === 'url' ? item.url.replace(/^https?:\/\//, '') : item.file?.file_name ?? item.path}
                    value={
                      item.type === 'url'
                        ? tr('menu_web')
                        : item.file?.exists === false
                          ? tr('menu_file_missing')
                          : tr('menu_file')
                    }
                    dim
                    last={last}
                  />
                );
              })}
            </View>
          );
        })}

        <Footnote>{tr('menu_note')}</Footnote>
        {customised && (
          <View style={styles.reset}>
            <ActionButton label={tr('menu_reset_title')} onPress={() => setConfirmReset(true)} />
          </View>
        )}
      </ScrollView>

      <ConfirmSheet
        visible={confirmReset}
        title={tr('menu_reset_title')}
        message={tr('menu_reset_msg')}
        confirmLabel={tr('menu_reset')}
        danger
        onConfirm={async () => {
          try {
            await reset();
            showToast(tr('menu_reset_done'));
          } catch (e) {
            showToast(trf('menu_reset_failed', {error: describeConnectError(e)}));
          } finally {
            setConfirmReset(false);
          }
        }}
        onClose={() => setConfirmReset(false)}
      />
      <ToastHost bottom={insets.bottom + 28} />
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  firstGroup: {marginTop: 8},
  group: {marginTop: 26},
  reset: {paddingHorizontal: 18, marginTop: 24},
}));
