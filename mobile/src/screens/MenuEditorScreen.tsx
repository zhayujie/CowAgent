import {faFileLines, faGlobe, faPen, faPlus, faXmark} from '@fortawesome/free-solid-svg-icons';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useEffect, useMemo, useState} from 'react';
import {ScrollView, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {ArtifactPickSheet, LinkSheet} from '../components/MenuAddSheets';
import {
  ActionButton,
  ChoiceSheet,
  ConfirmSheet,
  FieldSheet,
  Footnote,
  SettingRow,
  SwitchRow,
} from '../components/settings';
import {SHEET_DISMISS_MS} from '../components/Sheet';
import {showToast, ToastHost} from '../components/Toast';
import {GroupLabel, PageHeader} from '../components/ui';
import {tr, trf} from '../i18n';
import {
  BUILTIN_VIEWS,
  isPinnedAnchor,
  isPinnedMenuItem,
  menuItemIcon,
  pinnedGroupId,
  pinnedGroupLabel,
} from '../navigation/menuViews';
import type {RootStackParamList} from '../navigation/types';
import type {MenuItem} from '../protocol/resources';
import {
  type CustomMenuItem,
  MENU_REQUIRED,
  menuGroupLabel,
  newMenuItemId,
  useMenuStore,
} from '../store/menuStore';
import {describeConnectError} from '../store/serverStore';
import {makeStyles} from '../theme/theme';

type Props = StackScreenProps<RootStackParamList, 'MenuEditor'>;

/** Built-ins this app has no screen for (desktop-only pages) stay in the document but aren't offered. */
const editable = (i: MenuItem) =>
  !isPinnedMenuItem(i) && (i.type !== 'builtin' || i.view === 'chat' || !!BUILTIN_VIEWS[i.view]);

/** The server's limit on a title. */
const TITLE_MAX = 40;

export function MenuEditorScreen({navigation}: Props) {
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const doc = useMenuStore(s => s.doc);
  const customised = useMenuStore(s => s.customised);
  const load = useMenuStore(s => s.load);
  const setHidden = useMenuStore(s => s.setHidden);
  const renameItem = useMenuStore(s => s.renameItem);
  const removeItem = useMenuStore(s => s.removeItem);
  const addItem = useMenuStore(s => s.addItem);
  const reset = useMenuStore(s => s.reset);
  const artifactsHidden = useMenuStore(s => s.artifactsHidden);
  const setArtifactsHidden = useMenuStore(s => s.setArtifactsHidden);
  const [confirmReset, setConfirmReset] = useState(false);
  const [picked, setPicked] = useState<CustomMenuItem | null>(null);
  const [action, setAction] = useState<'menu' | 'rename' | 'remove' | null>(null);
  const [addTo, setAddTo] = useState<string | null>(null);
  const [adding, setAdding] = useState<'choose' | 'artifact' | 'url' | null>(null);
  const inMenu = useMemo(
    () => new Set(doc.groups.flatMap(g => g.items.flatMap(i => (i.type === 'artifact' ? [i.path] : [])))),
    [doc],
  );

  useEffect(() => {
    load().catch(e => showToast(trf('menu_load_failed', {error: describeConnectError(e)})));
  }, [load]);

  const toggle = (view: string, shown: boolean) =>
    setHidden(view, !shown).catch(e => showToast(trf('common_save_failed_detail', {error: describeConnectError(e)})));

  const closeAction = () => setAction(null);
  const closeAdding = () => setAdding(null);

  const add = async (item: CustomMenuItem) => {
    if (addTo) {
      await addItem(addTo, item);
      showToast(tr('menu_added'));
    }
  };

  const pinnedHome = pinnedGroupId(doc);
  const artifactsRow = (last: boolean) => (
    <SwitchRow
      icon={BUILTIN_VIEWS.artifacts.icon}
      title={BUILTIN_VIEWS.artifacts.label}
      value={!artifactsHidden}
      onValueChange={v => setArtifactsHidden(!v)}
      last={last}
    />
  );

  const itemRow = (item: MenuItem) => {
    if (item.type === 'builtin') {
      const required = MENU_REQUIRED.has(item.view);
      const label = item.title || (item.view === 'chat' ? tr('menu_chat') : BUILTIN_VIEWS[item.view].label);
      return (
        <SwitchRow
          icon={menuItemIcon(item)}
          title={label}
          detail={required ? tr('menu_required') : undefined}
          value={!item.hidden}
          disabled={required}
          onValueChange={v => toggle(item.view, v)}
        />
      );
    }
    return (
      <SettingRow
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
        onPress={() => {
          setPicked(item);
          setAction('menu');
        }}
      />
    );
  };

  return (
    <View style={styles.root}>
      <PageHeader title={tr('settings_menu')} onBack={navigation.goBack} />
      <ScrollView contentContainerStyle={{paddingBottom: insets.bottom + 32}}>
        {doc.groups.map((group, gi) => {
          const items = group.items.filter(editable);
          const pinnedHere = group.id === pinnedHome;
          return (
            <View key={group.id}>
              <GroupLabel style={gi === 0 ? styles.firstGroup : styles.group}>{menuGroupLabel(group)}</GroupLabel>
              {pinnedHere && !items.some(isPinnedAnchor) && artifactsRow(false)}
              {items.map(item => (
                <React.Fragment key={item.id}>
                  {itemRow(item)}
                  {pinnedHere && isPinnedAnchor(item) && artifactsRow(false)}
                </React.Fragment>
              ))}
              <SettingRow
                icon={faPlus}
                title={tr('menu_add')}
                dim
                onPress={() => {
                  setAddTo(group.id);
                  setAdding('choose');
                }}
                last
              />
            </View>
          );
        })}
        {!pinnedHome && (
          <View>
            <GroupLabel style={styles.group}>{pinnedGroupLabel()}</GroupLabel>
            {artifactsRow(true)}
          </View>
        )}

        <Footnote>{tr('menu_note')}</Footnote>
        {customised && (
          <View style={styles.reset}>
            <ActionButton label={tr('menu_reset_title')} onPress={() => setConfirmReset(true)} />
          </View>
        )}
      </ScrollView>

      <ChoiceSheet
        visible={adding === 'choose'}
        title={tr('menu_add')}
        options={[
          {key: 'artifact', label: tr('menu_add_artifact'), desc: tr('menu_add_artifact_desc'), icon: faFileLines},
          {key: 'url', label: tr('menu_add_url'), desc: tr('menu_add_url_desc'), icon: faGlobe},
        ]}
        onSelect={key => {
          closeAdding();
          setTimeout(() => setAdding(key), SHEET_DISMISS_MS);
        }}
        onClose={closeAdding}
      />
      <ArtifactPickSheet
        visible={adding === 'artifact'}
        inMenu={inMenu}
        onPick={a => {
          closeAdding();
          add({
            id: newMenuItemId(),
            type: 'artifact',
            title: (a.title || a.file_name).slice(0, TITLE_MAX),
            icon: '',
            path: a.abs_path!,
            file: {
              file_name: a.file_name,
              kind: a.kind,
              exists: true,
              preview_url: a.preview_url ?? '',
              raw_url: a.raw_url ?? '',
            },
          }).catch(e => showToast(trf('common_save_failed_detail', {error: describeConnectError(e)})));
        }}
        onClose={closeAdding}
      />
      <LinkSheet
        visible={adding === 'url'}
        onSubmit={link =>
          add({id: newMenuItemId(), type: 'url', icon: '', ...link}).catch(e => {
            throw new Error(describeConnectError(e));
          })
        }
        onClose={closeAdding}
      />
      <ChoiceSheet
        visible={action === 'menu'}
        title={picked?.title ?? ''}
        options={[
          {key: 'rename', label: tr('common_rename'), icon: faPen},
          {key: 'remove', label: tr('menu_remove'), icon: faXmark},
        ]}
        onSelect={key => {
          closeAction();
          setTimeout(() => setAction(key), SHEET_DISMISS_MS);
        }}
        onClose={closeAction}
      />
      <FieldSheet
        visible={action === 'rename'}
        title={tr('common_rename')}
        initial={picked?.title ?? ''}
        placeholder={tr('menu_title_ph')}
        allowEmpty={false}
        onSubmit={async title => {
          if (picked && title !== picked.title) {
            await renameItem(picked.id, title).catch(e => {
              throw new Error(describeConnectError(e));
            });
          }
        }}
        onClose={closeAction}
      />
      <ConfirmSheet
        visible={action === 'remove'}
        title={trf('menu_remove_title', {name: picked?.title ?? ''})}
        message={tr('menu_remove_msg')}
        confirmLabel={tr('menu_remove')}
        danger
        onConfirm={async () => {
          if (!picked) {
            return;
          }
          try {
            await removeItem(picked.id);
            showToast(tr('menu_removed'));
          } catch (e) {
            showToast(trf('common_save_failed_detail', {error: describeConnectError(e)}));
          } finally {
            closeAction();
          }
        }}
        onClose={closeAction}
      />
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
