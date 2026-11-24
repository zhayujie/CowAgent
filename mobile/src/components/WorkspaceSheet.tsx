import {faFolder, faFolderOpen} from '@fortawesome/free-regular-svg-icons';
import {
  faArrowUp,
  faCheck,
  faChevronLeft,
  faChevronRight,
  faHouse,
  faPlus,
} from '@fortawesome/free-solid-svg-icons';
import type {IconDefinition} from '@fortawesome/fontawesome-svg-core';
import React, {useCallback, useEffect, useRef, useState} from 'react';
import {ActivityIndicator, Pressable, ScrollView, Text, View} from 'react-native';
import {browseFolders} from '../api/cowApi';
import {tr, trf} from '../i18n';
import type {FolderListing, ProjectState} from '../protocol/resources';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {Icon} from './Icon';
import {ActionButton} from './settings';
import {Sheet} from './Sheet';
import {GroupLabel} from './ui';

/** Windows lists its drives under this path, which is not a folder that can be opened. */
const DRIVES = '__DRIVES__';

const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** Which folder this chat works in, on the computer the agent runs on. */
export function WorkspaceSheet({
  visible,
  onClose,
  state,
  withProjects = true,
  onSelect,
  onNew,
}: {
  visible: boolean;
  onClose: () => void;
  state?: ProjectState;
  /** Off where only the default workspace exists, as on the phone's own kernel. */
  withProjects?: boolean;
  onSelect: (projectDir: string | null) => void;
  onNew: () => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  const [browsing, setBrowsing] = useState(false);

  useEffect(() => {
    if (!visible) {
      setBrowsing(false);
    }
  }, [visible]);

  const current = state?.current ?? null;
  return (
    <Sheet
      visible={visible}
      onClose={onClose}
      title={browsing ? tr('composer_ws_browse_title') : tr('composer_ws_title')}>
      {!state ? (
        <View style={styles.loading}>
          <ActivityIndicator color={t.t3} />
        </View>
      ) : browsing ? (
        <FolderBrowser onBack={() => setBrowsing(false)} onOpen={onSelect} />
      ) : (
        <ScrollView style={styles.scroll} keyboardShouldPersistTaps="handled">
          <GroupLabel style={styles.groupLabel} small>
            {tr('composer_ws_system')}
          </GroupLabel>
          <Row
            icon={faHouse}
            name={tr('composer_ws_default')}
            sub={state.default_workspace}
            active={!withProjects || !current}
            onPress={() => onSelect(null)}
          />

          {withProjects && (
            <>
              <GroupLabel style={styles.groupLabel} small>
                {tr('composer_ws_projects')}
              </GroupLabel>
              {state.recents.map(r => (
                <Row
                  key={r.path}
                  icon={faFolder}
                  name={r.name}
                  sub={r.path}
                  active={current?.path === r.path}
                  onPress={() => onSelect(r.path)}
                />
              ))}
              <Row icon={faFolderOpen} name={tr('composer_ws_open')} onPress={() => setBrowsing(true)} />
              <Row icon={faPlus} name={tr('composer_ws_new')} onPress={onNew} />
              <Text style={styles.note}>{tr('composer_ws_note')}</Text>
            </>
          )}
        </ScrollView>
      )}
    </Sheet>
  );
}

function Row({
  icon,
  name,
  sub,
  active,
  onPress,
}: {
  icon: IconDefinition;
  name: string;
  sub?: string;
  active?: boolean;
  onPress: () => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{selected: !!active}}
      onPress={onPress}
      style={({pressed}) => [styles.row, pressed && styles.rowPressed]}>
      <View style={[styles.rowIcon, active && styles.rowIconActive]}>
        <Icon icon={icon} size={13} color={active ? t.accent : t.t2} />
      </View>
      <View style={styles.rowBody}>
        <Text style={[styles.rowName, active && styles.rowNameActive]} numberOfLines={1}>
          {name}
        </Text>
        {!!sub && (
          <Text style={styles.rowDesc} numberOfLines={1} ellipsizeMode="middle">
            {sub}
          </Text>
        )}
      </View>
      {active && <Icon icon={faCheck} size={13} color={t.accent} />}
    </Pressable>
  );
}

/** Walks the server's folders, starting at its home folder; the folder on screen is the one opened. */
function FolderBrowser({onBack, onOpen}: {onBack: () => void; onOpen: (path: string) => void}) {
  const t = useTheme();
  const styles = useStyles();
  const [listing, setListing] = useState<FolderListing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [target, setTarget] = useState('');
  // Only the folder asked for last may fill the list.
  const asked = useRef(0);

  const go = useCallback((path: string) => {
    const id = ++asked.current;
    setTarget(path);
    setLoading(true);
    setError(null);
    browseFolders(path).then(
      next => {
        if (id === asked.current) {
          setListing(next);
          setLoading(false);
        }
      },
      e => {
        if (id === asked.current) {
          setError(trf('composer_ws_browse_failed', {error: errorText(e)}));
          setLoading(false);
        }
      },
    );
  }, []);

  useEffect(() => {
    go('');
  }, [go]);

  const drives = listing?.path === DRIVES;
  const where = drives ? tr('composer_ws_browse_drives') : listing?.path ?? '';
  const tool = (icon: IconDefinition, label: string, onPress: () => void, disabled?: boolean) => (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{disabled}}
      disabled={disabled}
      onPress={onPress}
      hitSlop={4}
      style={({pressed}) => [styles.tool, pressed && styles.rowPressed, disabled && styles.dim]}>
      <Icon icon={icon} size={13} color={t.t2} />
    </Pressable>
  );

  return (
    <>
      <View style={styles.bar}>
        {tool(faChevronLeft, tr('common_back'), onBack)}
        <Text style={styles.where} numberOfLines={1} ellipsizeMode="head">
          {where}
        </Text>
        {tool(faArrowUp, tr('composer_ws_browse_up'), () => listing?.parent && go(listing.parent), !listing?.parent)}
        {tool(faHouse, tr('composer_ws_browse_home'), () => go('~'))}
      </View>

      <ScrollView style={[styles.scroll, styles.list]} keyboardShouldPersistTaps="handled">
        {loading && !listing ? (
          <View style={styles.loading}>
            <ActivityIndicator color={t.t3} />
          </View>
        ) : error ? (
          <Pressable accessibilityRole="button" onPress={() => go(target)}>
            <Text style={styles.empty}>{error}</Text>
            <Text style={styles.retry}>{tr('common_retry')}</Text>
          </Pressable>
        ) : listing && !listing.dirs.length ? (
          <Text style={styles.empty}>{tr('composer_ws_browse_empty')}</Text>
        ) : (
          listing?.dirs.map(d => (
            <Pressable
              key={d.path}
              accessibilityRole="button"
              disabled={loading}
              onPress={() => go(d.path)}
              style={({pressed}) => [styles.dirRow, pressed && styles.rowPressed, loading && styles.dim]}>
              <Icon icon={faFolder} size={14} color={t.t2} />
              <Text style={styles.dirName} numberOfLines={1}>
                {d.name}
              </Text>
              <Icon icon={faChevronRight} size={10} color={t.t4} />
            </Pressable>
          ))
        )}
      </ScrollView>

      <ActionButton
        label={tr('composer_ws_open_here')}
        tone="primary"
        icon={faFolderOpen}
        disabled={!listing || drives || loading || !!error}
        onPress={() => listing && onOpen(listing.path)}
        style={styles.openHere}
      />
    </>
  );
}

const useStyles = makeStyles(t => ({
  loading: {paddingVertical: 48, alignItems: 'center'},
  scroll: {flexGrow: 0, flexShrink: 1},
  groupLabel: {paddingHorizontal: 12, marginTop: 8, marginBottom: 4},
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: radius.md,
  },
  rowPressed: {backgroundColor: t.bg2},
  rowIcon: {
    width: 34,
    height: 34,
    borderRadius: radius.sm,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: t.bg2,
  },
  rowIconActive: {backgroundColor: t.accentSoft},
  rowBody: {flex: 1, minWidth: 0},
  rowName: {fontSize: 15, fontWeight: '500', color: t.t1, letterSpacing: -0.1},
  rowNameActive: {color: t.accent},
  rowDesc: {fontSize: 12, color: t.t3, marginTop: 2},
  note: {fontSize: 12, lineHeight: 18, color: t.t4, paddingHorizontal: 12, paddingTop: 10, paddingBottom: 4},
  bar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    marginHorizontal: 4,
    marginBottom: 6,
  },
  tool: {
    width: 36,
    height: 36,
    borderRadius: radius.sm,
    alignItems: 'center',
    justifyContent: 'center',
  },
  dim: {opacity: 0.4},
  where: {flex: 1, fontSize: 13, color: t.t2, paddingHorizontal: 4},
  list: {minHeight: 240, borderTopWidth: 1, borderTopColor: t.line1},
  dirRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 14,
    paddingVertical: 13,
    borderRadius: radius.sm,
  },
  dirName: {flex: 1, fontSize: 15, color: t.t1},
  empty: {fontSize: 13, lineHeight: 20, color: t.t3, paddingHorizontal: 12, paddingTop: 24, textAlign: 'center'},
  retry: {fontSize: 14, fontWeight: '500', color: t.accent, paddingVertical: 10, textAlign: 'center'},
  openHere: {marginHorizontal: 12, marginTop: 10},
}));
