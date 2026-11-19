import {faArrowDown, faPause, faPlay} from '@fortawesome/free-solid-svg-icons';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {FlatList, Pressable, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {logDownloadUrl, openLogStream} from '../api/cowApi';
import type {EventStreamHandle} from '../api/sse';
import {Icon} from '../components/Icon';
import {MONO} from '../components/settings';
import {ToastHost} from '../components/Toast';
import {Chip, EmptyState, IconButton, PageHeader} from '../components/ui';
import {downloadUrl} from '../files/openFile';
import {tr, trf, type MessageKey} from '../i18n';
import type {RootStackParamList} from '../navigation/types';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {pad} from '../utils/format';

type Props = StackScreenProps<RootStackParamList, 'Logs'>;

type Level = 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL' | '';
type Entry = {id: number; level: Level; time: string; source: string; message: string};
type Filter = 'all' | 'warning' | 'error';

const logFileName = (d = new Date()) =>
  `cowagent-${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}.log`;

const MAX_ENTRIES = 500;
const LINE = /^\[(DEBUG|INFO|WARNING|ERROR|CRITICAL)\]\[\d{4}-\d\d-\d\d (\d\d:\d\d:\d\d)\]\[([^\]]+)\] - ([\s\S]*)$/;
const LEVEL_LABEL: Record<Exclude<Level, ''>, MessageKey> = {
  DEBUG: 'settings_log_debug',
  INFO: 'settings_log_info',
  WARNING: 'settings_log_warning',
  ERROR: 'settings_log_error',
  CRITICAL: 'settings_log_critical',
};
const FILTERS: {key: Filter; label: MessageKey}[] = [
  {key: 'all', label: 'common_all'},
  {key: 'warning', label: 'settings_log_warning'},
  {key: 'error', label: 'settings_log_error'},
];

let nextId = 0;

/** Lines without a level prefix (tracebacks, multi-line messages) belong to the entry above. */
function append(entries: Entry[], lines: string[]): Entry[] {
  const out = entries.slice();
  for (const raw of lines) {
    const line = raw.replace(/\r$/, '');
    if (!line.trim()) {
      continue;
    }
    const m = LINE.exec(line);
    if (m) {
      out.push({id: nextId++, level: m[1] as Level, time: m[2], source: m[3], message: m[4]});
    } else if (out.length) {
      const last = out[out.length - 1];
      out[out.length - 1] = {...last, message: `${last.message}\n${line}`};
    } else {
      out.push({id: nextId++, level: '', time: '', source: '', message: line});
    }
  }
  return out.length > MAX_ENTRIES ? out.slice(out.length - MAX_ENTRIES) : out;
}

const matches = (e: Entry, f: Filter) =>
  f === 'all' || (f === 'warning' ? e.level === 'WARNING' : e.level === 'ERROR' || e.level === 'CRITICAL');

export function LogsScreen({navigation}: Props) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const [entries, setEntries] = useState<Entry[]>([]);
  const [state, setState] = useState<'connecting' | 'live' | 'closed'>('connecting');
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>('all');
  const [paused, setPaused] = useState(false);
  const [frozen, setFrozen] = useState<Entry[]>([]);
  const [atBottom, setAtBottom] = useState(true);
  const stream = useRef<EventStreamHandle | null>(null);
  const list = useRef<FlatList<Entry>>(null);
  const connectRef = useRef<() => void>(() => {});

  useEffect(() => {
    let alive = true;
    const open = () => {
      stream.current?.close();
      setState('connecting');
      setError(null);
      // A stream the server refuses (no run.log) also ends cleanly; resuming that one would spin.
      let started = false;
      stream.current = openLogStream(
        event => {
          if (event.type === 'init') {
            started = true;
            setEntries(append([], event.content.split('\n')));
            setState('live');
          } else if (event.type === 'line') {
            setEntries(prev => append(prev, event.content.split('\n')));
          } else {
            setError(event.message);
          }
        },
        err => {
          if (!alive) {
            return;
          }
          if (err || !started) {
            setState('closed');
            if (err) {
              setError(err.message);
            }
          } else {
            // The server ends each stream after ten minutes; pick it straight back up.
            open();
          }
        },
      );
    };
    connectRef.current = open;
    open();
    return () => {
      alive = false;
      stream.current?.close();
    };
  }, []);
  const connect = useCallback(() => connectRef.current(), []);

  const source = paused ? frozen : entries;
  const data = useMemo(() => source.filter(e => matches(e, filter)).reverse(), [source, filter]);
  const pending = paused ? entries.filter(e => e.id > (frozen[frozen.length - 1]?.id ?? -1)).length : 0;

  const togglePause = () => {
    if (paused) {
      setPaused(false);
    } else {
      setFrozen(entries);
      setPaused(true);
    }
  };

  const renderItem = ({item}: {item: Entry}) => {
    const loud = item.level === 'ERROR' || item.level === 'CRITICAL';
    return (
      <View style={styles.entry}>
        <View style={styles.entryHead}>
          {!!item.time && <Text style={styles.time}>{item.time}</Text>}
          {!!item.level && (
            <Text style={[styles.level, item.level === 'WARNING' && styles.levelWarn, loud && styles.levelError]}>
              {tr(LEVEL_LABEL[item.level])}
            </Text>
          )}
          {!!item.source && (
            <Text style={styles.source} numberOfLines={1}>
              {item.source}
            </Text>
          )}
        </View>
        <Text style={[styles.message, loud && styles.messageError]} selectable>
          {item.message}
        </Text>
      </View>
    );
  };

  const status =
    state === 'live'
      ? paused
        ? `${tr('settings_log_paused')}${pending ? ` · ${trf('settings_log_new', {n: pending})}` : ''}`
        : tr('settings_log_live')
      : state === 'connecting'
        ? tr('settings_realtime_connecting')
        : tr('settings_log_disconnected');

  return (
    <View style={styles.root}>
      <PageHeader
        title={tr('settings_logs')}
        onBack={navigation.goBack}
        right={
          <IconButton
            icon={paused ? faPlay : faPause}
            label={paused ? tr('settings_log_resume') : tr('settings_log_pause')}
            onPress={togglePause}
            size={13}
          />
        }
      />
      <View style={styles.bar}>
        <View style={styles.chips}>
          {FILTERS.map(f => (
            <Chip key={f.key} label={tr(f.label)} active={filter === f.key} onPress={() => setFilter(f.key)} />
          ))}
        </View>
        <View style={styles.status}>
          <View style={[styles.dot, state === 'live' && !paused && styles.dotLive]} />
          <Text style={styles.statusText}>{status}</Text>
        </View>
      </View>

      {state === 'closed' && (
        <Pressable onPress={connect} style={({pressed}) => [styles.banner, pressed && styles.pressed]}>
          <Text style={styles.bannerText} numberOfLines={2}>
            {error ? trf('settings_log_closed_detail', {error}) : tr('settings_log_closed')}
          </Text>
        </Pressable>
      )}

      <FlatList
        ref={list}
        style={styles.list}
        data={data}
        inverted
        keyExtractor={e => String(e.id)}
        renderItem={renderItem}
        onScroll={e => setAtBottom(e.nativeEvent.contentOffset.y < 40)}
        scrollEventThrottle={64}
        contentContainerStyle={data.length ? styles.listContent : styles.listEmpty}
        ListEmptyComponent={
          <EmptyState
            loading={state === 'connecting' && !entries.length}
            title={
              filter === 'all'
                ? tr('settings_log_empty')
                : filter === 'warning'
                  ? tr('settings_log_no_warnings')
                  : tr('settings_log_no_errors')
            }
            hint={filter === 'all' ? undefined : trf('settings_log_search_scope', {n: MAX_ENTRIES})}
          />
        }
        ListFooterComponent={<Text style={styles.head}>{trf('settings_log_footer', {n: MAX_ENTRIES})}</Text>}
      />

      {!atBottom && !!data.length && (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={tr('settings_log_jump_latest')}
          onPress={() => list.current?.scrollToOffset({offset: 0, animated: true})}
          style={({pressed}) => [styles.jump, {bottom: insets.bottom + 62}, pressed && styles.pressed]}>
          <Icon icon={faArrowDown} size={12} color={t.t1} />
          <Text style={styles.jumpText}>{tr('settings_log_latest')}</Text>
        </Pressable>
      )}

      <View style={[styles.footer, {paddingBottom: insets.bottom + 10}]}>
        <Pressable accessibilityRole="button" hitSlop={8} onPress={() => downloadUrl(logDownloadUrl(), logFileName())}>
          <Text style={styles.footerLink}>{tr('settings_log_download')}</Text>
        </Pressable>
      </View>
      <ToastHost bottom={insets.bottom + 56} />
    </View>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  bar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 18,
    paddingTop: 2,
    paddingBottom: 10,
    borderBottomWidth: 1,
    borderBottomColor: t.line1,
  },
  chips: {flexDirection: 'row', gap: 6},
  status: {flexDirection: 'row', alignItems: 'center', gap: 6},
  dot: {width: 6, height: 6, borderRadius: 3, backgroundColor: t.t4},
  dotLive: {backgroundColor: t.green},
  statusText: {fontSize: 12, color: t.t3, fontVariant: ['tabular-nums']},
  banner: {
    marginHorizontal: 18,
    marginTop: 10,
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: radius.sm,
    backgroundColor: t.dangerSoft,
  },
  bannerText: {fontSize: 13, lineHeight: 19, color: t.danger},
  pressed: {opacity: 0.7},
  list: {flex: 1},
  listContent: {paddingVertical: 6},
  listEmpty: {flexGrow: 1},
  entry: {
    paddingHorizontal: 18,
    paddingVertical: 9,
    borderBottomWidth: 1,
    borderBottomColor: t.line1,
  },
  entryHead: {flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 3},
  time: {fontFamily: MONO, fontSize: 11, color: t.t4, fontVariant: ['tabular-nums']},
  level: {fontSize: 11, color: t.t4},
  levelWarn: {color: t.t1, fontWeight: '600'},
  levelError: {color: t.danger, fontWeight: '600'},
  source: {flexShrink: 1, fontFamily: MONO, fontSize: 11, color: t.t4},
  message: {fontFamily: MONO, fontSize: 12, lineHeight: 18, color: t.t2},
  messageError: {color: t.t1},
  head: {fontSize: 12, color: t.t4, textAlign: 'center', paddingVertical: 16, paddingHorizontal: 18},
  jump: {
    position: 'absolute',
    alignSelf: 'center',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 14,
    height: 32,
    borderRadius: 16,
    backgroundColor: t.bg2,
    borderWidth: 1,
    borderColor: t.line2,
  },
  jumpText: {fontSize: 13, color: t.t1},
  footer: {
    alignItems: 'center',
    paddingTop: 10,
    borderTopWidth: 1,
    borderTopColor: t.line1,
    backgroundColor: t.bg0,
  },
  footerLink: {fontSize: 13, color: t.t3},
}));
