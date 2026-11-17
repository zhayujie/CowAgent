import {faMagnifyingGlass} from '@fortawesome/free-solid-svg-icons';
import React, {useEffect, useRef, useState} from 'react';
import {ActivityIndicator, Pressable, ScrollView, Text, TextInput, View} from 'react-native';
import {getArtifacts} from '../api/cowApi';
import {tr, trf} from '../i18n';
import type {Artifact} from '../protocol/events';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {KindTile} from './ArtifactStrip';
import {Icon} from './Icon';
import {ActionButton} from './settings';
import {Sheet} from './Sheet';

const SEARCH_DELAY_MS = 220;
const PICK_LIMIT = 40;
const URL_RE = /^https?:\/\/[^\s/?#]+/i;

/** Pages and documents the menu can hold (the server takes only html and markdown), as the web console offers them. */
export function ArtifactPickSheet({
  visible,
  inMenu,
  onPick,
  onClose,
}: {
  visible: boolean;
  /** Paths already in the menu; they are listed but can't be picked again. */
  inMenu: Set<string>;
  onPick: (artifact: Artifact) => void;
  onClose: () => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  const [query, setQuery] = useState('');
  const [items, setItems] = useState<Artifact[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const request = useRef(0);

  useEffect(() => {
    if (visible) {
      setQuery('');
      setItems(null);
      setError(null);
    }
  }, [visible]);

  useEffect(() => {
    if (!visible) {
      return;
    }
    const id = ++request.current;
    const timer = setTimeout(
      () => {
        getArtifacts({kind: 'page', q: query.trim(), limit: PICK_LIMIT})
          .then(res => {
            if (id === request.current) {
              setItems(res.items.filter(a => a.exists !== false && !!a.abs_path));
              setError(null);
            }
          })
          .catch(e => {
            if (id === request.current) {
              setError(e instanceof Error ? e.message : String(e));
            }
          });
      },
      query ? SEARCH_DELAY_MS : 0,
    );
    return () => clearTimeout(timer);
  }, [visible, query]);

  return (
    <Sheet visible={visible} onClose={onClose} title={tr('menu_add_artifact')}>
      <View style={styles.search}>
        <Icon icon={faMagnifyingGlass} size={13} color={t.t4} />
        <TextInput
          value={query}
          onChangeText={setQuery}
          placeholder={tr('menu_artifact_search')}
          placeholderTextColor={t.t4}
          selectionColor={t.accent}
          cursorColor={t.accent}
          autoCapitalize="none"
          autoCorrect={false}
          style={styles.searchInput}
        />
      </View>
      <ScrollView style={styles.list} keyboardShouldPersistTaps="handled">
        {error ? (
          <Text style={styles.empty}>{trf('menu_artifact_load_failed', {error})}</Text>
        ) : !items ? (
          <ActivityIndicator style={styles.loading} color={t.t3} />
        ) : !items.length ? (
          <Text style={styles.empty}>{tr('menu_artifact_empty')}</Text>
        ) : (
          items.map(a => {
            const added = inMenu.has(a.abs_path!);
            return (
              <Pressable
                key={a.id}
                accessibilityRole="button"
                accessibilityState={{disabled: added}}
                disabled={added}
                onPress={() => onPick(a)}
                style={({pressed}) => [styles.item, pressed && styles.pressed, added && styles.added]}>
                <KindTile kind={a.kind} />
                <View style={styles.itemText}>
                  <Text style={styles.itemName} numberOfLines={1}>
                    {a.title || a.file_name}
                  </Text>
                  <Text style={styles.itemPath} numberOfLines={1}>
                    {added ? tr('menu_already_added') : a.rel_path || a.file_name}
                  </Text>
                </View>
              </Pressable>
            );
          })
        )}
      </ScrollView>
    </Sheet>
  );
}

export interface NewLink {
  title: string;
  url: string;
  open: 'embed' | 'tab';
}

/** A web address for the menu: its name, the address, and whether it leaves the app. */
export function LinkSheet({
  visible,
  onSubmit,
  onClose,
}: {
  visible: boolean;
  onSubmit: (link: NewLink) => Promise<void>;
  onClose: () => void;
}) {
  const t = useTheme();
  const styles = useStyles();
  const [title, setTitle] = useState('');
  const [url, setUrl] = useState('');
  const [open, setOpen] = useState<NewLink['open']>('embed');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (visible) {
      setTitle('');
      setUrl('');
      setOpen('embed');
      setError(null);
    }
  }, [visible]);

  const submit = async () => {
    const link = {title: title.trim(), url: url.trim(), open};
    if (!link.title) {
      setError(tr('menu_need_title'));
      return;
    }
    if (!URL_RE.test(link.url)) {
      setError(tr('menu_need_url'));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onSubmit(link);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const input = {
    placeholderTextColor: t.t4,
    selectionColor: t.accent,
    cursorColor: t.accent,
    autoCapitalize: 'none' as const,
    autoCorrect: false,
    style: styles.field,
  };

  return (
    <Sheet visible={visible} onClose={onClose} title={tr('menu_add_url')}>
      <View style={styles.body}>
        <Text style={styles.label}>{tr('menu_link_title')}</Text>
        <TextInput {...input} value={title} onChangeText={setTitle} placeholder={tr('menu_title_ph')} maxLength={40} autoFocus />
        <Text style={styles.label}>{tr('menu_link_url')}</Text>
        <TextInput {...input} value={url} onChangeText={setUrl} placeholder="https://" keyboardType="url" />
        <View style={styles.segment} accessibilityRole="tablist">
          {(['embed', 'tab'] as const).map(mode => {
            const active = mode === open;
            return (
              <Pressable
                key={mode}
                accessibilityRole="tab"
                accessibilityState={{selected: active}}
                onPress={() => setOpen(mode)}
                style={[styles.segmentItem, active && styles.segmentActive]}>
                <Text style={[styles.segmentText, active && styles.segmentTextActive]}>
                  {tr(mode === 'embed' ? 'menu_open_embed' : 'menu_open_tab')}
                </Text>
              </Pressable>
            );
          })}
        </View>
        {!!error && <Text style={styles.error}>{error}</Text>}
        <ActionButton label={tr('common_save')} tone="primary" loading={busy} onPress={submit} style={styles.button} />
      </View>
    </Sheet>
  );
}

const useStyles = makeStyles(t => ({
  search: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginHorizontal: 12,
    marginBottom: 6,
    paddingHorizontal: 12,
    height: 40,
    borderRadius: radius.sm,
    backgroundColor: t.bg2,
    borderWidth: 1,
    borderColor: t.line1,
  },
  searchInput: {flex: 1, fontSize: 14, color: t.t1, paddingVertical: 0},
  list: {maxHeight: 380},
  loading: {paddingVertical: 28},
  empty: {fontSize: 13, lineHeight: 20, color: t.t3, textAlign: 'center', paddingVertical: 28, paddingHorizontal: 16},
  item: {flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 12, paddingVertical: 9, borderRadius: radius.md},
  pressed: {opacity: 0.6},
  added: {opacity: 0.45},
  itemText: {flex: 1, minWidth: 0},
  itemName: {fontSize: 15, color: t.t1},
  itemPath: {fontSize: 12, color: t.t3, marginTop: 2},
  body: {paddingHorizontal: 12, paddingTop: 4},
  label: {fontSize: 12, color: t.t3, paddingTop: 6, paddingBottom: 6},
  field: {
    minHeight: 46,
    paddingHorizontal: 14,
    paddingVertical: 12,
    borderRadius: radius.sm,
    backgroundColor: t.bg2,
    borderWidth: 1,
    borderColor: t.line1,
    fontSize: 15,
    color: t.t1,
  },
  segment: {flexDirection: 'row', marginTop: 14, padding: 3, borderRadius: radius.sm, backgroundColor: t.bg2},
  segmentItem: {flex: 1, alignItems: 'center', paddingVertical: 8, borderRadius: radius.sm - 2},
  segmentActive: {backgroundColor: t.bg0},
  segmentText: {fontSize: 13, color: t.t3},
  segmentTextActive: {color: t.t1, fontWeight: '500'},
  error: {fontSize: 12, lineHeight: 18, color: t.danger, paddingTop: 10},
  button: {marginTop: 14, marginBottom: 4},
}));
