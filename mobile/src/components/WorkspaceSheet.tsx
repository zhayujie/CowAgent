import {faFolder, faFolderOpen} from '@fortawesome/free-regular-svg-icons';
import {
  faArrowUp,
  faCheck,
  faChevronLeft,
  faChevronRight,
  faFolderPlus,
  faHouse,
} from '@fortawesome/free-solid-svg-icons';
import type {IconDefinition} from '@fortawesome/fontawesome-svg-core';
import React, {useEffect, useRef, useState} from 'react';
import {ActivityIndicator, Pressable, ScrollView, Text, View} from 'react-native';
import {tr} from '../i18n';
import type {ProjectBrowse, ProjectRef, ProjectState} from '../protocol/resources';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {Icon} from './Icon';
import {Sheet} from './Sheet';
import {GroupLabel} from './ui';

const DRIVES = '__DRIVES__';

interface Props {
  visible: boolean;
  state?: ProjectState;
  onClose: () => void;
  onSelect: (projectDir: string | null) => void;
  onCreate: () => void;
  onBrowse: (path?: string) => Promise<ProjectBrowse>;
}

/** The web project picker, adapted to a bottom sheet. All paths belong to the server. */
export function WorkspaceSheet({visible, state, onClose, onSelect, onCreate, onBrowse}: Props) {
  const t = useTheme();
  const styles = useStyles();
  const [browsing, setBrowsing] = useState(false);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState<ProjectBrowse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const request = useRef(0);
  const lastPath = useRef('');

  useEffect(() => {
    if (!visible) {
      request.current += 1;
      setBrowsing(false);
      setPage(null);
      setError(null);
    }
  }, [visible]);

  const browse = async (path = '') => {
    const id = ++request.current;
    lastPath.current = path;
    setBrowsing(true);
    setLoading(true);
    setError(null);
    try {
      const next = await onBrowse(path);
      if (request.current === id) {
        setPage(next);
      }
    } catch (e) {
      if (request.current === id) {
        setError(e instanceof Error ? e.message : String(e));
      }
    } finally {
      if (request.current === id) {
        setLoading(false);
      }
    }
  };

  const close = () => {
    request.current += 1;
    onClose();
  };

  return (
    <Sheet
      visible={visible}
      onClose={close}
      title={tr(browsing ? 'composer_workspace_open' : 'composer_workspace_title')}
    >
      {browsing ? (
        <View style={styles.browser}>
          <View style={styles.browserBar}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={tr('common_back')}
              onPress={() => {
                request.current += 1;
                setBrowsing(false);
                setPage(null);
                setError(null);
              }}
              style={({pressed}) => [styles.smallButton, pressed && styles.pressed]}
            >
              <Icon icon={faChevronLeft} size={14} color={t.t2} />
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={tr('composer_workspace_up')}
              disabled={!page?.parent || loading}
              onPress={() => page?.parent && browse(page.parent)}
              style={({pressed}) => [
                styles.smallButton,
                pressed && styles.pressed,
                (!page?.parent || loading) && styles.dim,
              ]}
            >
              <Icon icon={faArrowUp} size={14} color={t.t2} />
            </Pressable>
            <Text style={styles.path} numberOfLines={1} ellipsizeMode="middle">
              {page?.path === DRIVES ? tr('composer_workspace_drives') : page?.path || lastPath.current}
            </Text>
          </View>

          {loading ? (
            <View style={styles.loading}>
              <ActivityIndicator color={t.t3} />
            </View>
          ) : error ? (
            <Pressable onPress={() => browse(lastPath.current)} style={styles.emptyBox}>
              <Text style={styles.error}>{error}</Text>
              <Text style={styles.retry}>{tr('common_retry')}</Text>
            </Pressable>
          ) : (
            <ScrollView style={styles.scroll} keyboardShouldPersistTaps="handled">
              {!page?.dirs.length && <Text style={styles.empty}>{tr('composer_workspace_no_subdirs')}</Text>}
              {page?.dirs.map(dir => (
                <Pressable
                  key={dir.path}
                  accessibilityRole="button"
                  onPress={() => browse(dir.path)}
                  style={({pressed}) => [styles.row, pressed && styles.rowPressed]}
                >
                  <View style={styles.rowIcon}>
                    <Icon icon={faFolder} size={14} color={t.t2} />
                  </View>
                  <Text style={styles.rowName} numberOfLines={1}>
                    {dir.name}
                  </Text>
                  <Icon icon={faChevronRight} size={11} color={t.t4} />
                </Pressable>
              ))}
            </ScrollView>
          )}

          <Pressable
            accessibilityRole="button"
            disabled={!page || page.path === DRIVES || loading}
            onPress={() => page && page.path !== DRIVES && onSelect(page.path)}
            style={({pressed}) => [
              styles.openHere,
              pressed && styles.rowPressed,
              (!page || page.path === DRIVES || loading) && styles.dim,
            ]}
          >
            <Icon icon={faFolderOpen} size={14} color={t.accent} />
            <Text style={styles.openHereText}>{tr('composer_workspace_open_here')}</Text>
          </Pressable>
        </View>
      ) : !state ? (
        <View style={styles.loading}>
          <ActivityIndicator color={t.t3} />
        </View>
      ) : (
        <ScrollView style={styles.scroll} keyboardShouldPersistTaps="handled">
          <WorkspaceRow
            icon={faHouse}
            name={tr('composer_workspace_default')}
            path={state.default_workspace}
            active={!state.current}
            onPress={() => onSelect(null)}
          />
          {!!state.recents.length && (
            <GroupLabel style={styles.groupLabel} small>
              {tr('composer_workspace_recents')}
            </GroupLabel>
          )}
          {state.recents.map(project => (
            <WorkspaceRow
              key={project.path}
              project={project}
              active={state.current?.path === project.path}
              onPress={() => onSelect(project.path)}
            />
          ))}
          <View style={styles.divider} />
          <WorkspaceRow icon={faFolderOpen} name={tr('composer_workspace_open')} onPress={() => browse()} />
          <WorkspaceRow icon={faFolderPlus} name={tr('composer_workspace_new')} onPress={onCreate} />
        </ScrollView>
      )}
    </Sheet>
  );
}

function WorkspaceRow({
  project,
  icon = faFolder,
  name,
  path,
  active = false,
  onPress,
}: {
  project?: ProjectRef;
  icon?: IconDefinition;
  name?: string;
  path?: string;
  active?: boolean;
  onPress: () => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{selected: active}}
      onPress={onPress}
      style={({pressed}) => [styles.row, pressed && styles.rowPressed]}
    >
      <View style={[styles.rowIcon, active && styles.rowIconActive]}>
        <Icon icon={icon} size={14} color={active ? t.accent : t.t2} />
      </View>
      <View style={styles.rowBody}>
        <Text style={[styles.rowName, active && styles.rowActive]} numberOfLines={1}>
          {project?.name ?? name}
        </Text>
        {!!(project?.path ?? path) && (
          <Text style={styles.rowPath} numberOfLines={1} ellipsizeMode="middle">
            {project?.path ?? path}
          </Text>
        )}
      </View>
      {active && <Icon icon={faCheck} size={13} color={t.accent} />}
    </Pressable>
  );
}

const useStyles = makeStyles(t => ({
  scroll: {flexGrow: 0, flexShrink: 1},
  loading: {height: 180, alignItems: 'center', justifyContent: 'center'},
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    minHeight: 52,
    paddingHorizontal: 12,
    paddingVertical: 8,
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
  rowName: {flex: 1, fontSize: 15, fontWeight: '500', color: t.t1},
  rowActive: {color: t.accent},
  rowPath: {fontSize: 11, lineHeight: 16, color: t.t4, marginTop: 2},
  groupLabel: {paddingHorizontal: 12, marginTop: 12, marginBottom: 4},
  divider: {
    height: 1,
    backgroundColor: t.line1,
    marginHorizontal: 12,
    marginVertical: 8,
  },
  browser: {flexShrink: 1},
  browserBar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: 8,
    paddingBottom: 8,
  },
  smallButton: {
    width: 36,
    height: 36,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 18,
  },
  pressed: {backgroundColor: t.bg2},
  dim: {opacity: 0.4},
  path: {flex: 1, fontSize: 12, color: t.t3, marginLeft: 4},
  emptyBox: {
    minHeight: 140,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 20,
    gap: 10,
  },
  empty: {
    fontSize: 13,
    color: t.t3,
    textAlign: 'center',
    paddingVertical: 48,
  },
  error: {fontSize: 13, lineHeight: 19, color: t.danger, textAlign: 'center'},
  retry: {fontSize: 14, color: t.accent, fontWeight: '500'},
  openHere: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    margin: 12,
    marginBottom: 4,
    minHeight: 42,
    borderRadius: radius.md,
    backgroundColor: t.accentSoft,
  },
  openHereText: {fontSize: 14, fontWeight: '500', color: t.accent},
}));
