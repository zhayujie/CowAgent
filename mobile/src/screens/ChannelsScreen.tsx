import {faChevronRight, faPlus, faTowerBroadcast} from '@fortawesome/free-solid-svg-icons';
import {useFocusEffect} from '@react-navigation/native';
import type {StackScreenProps} from '@react-navigation/stack';
import React, {useCallback, useEffect, useMemo, useState, type ReactNode} from 'react';
import {Pressable, RefreshControl, ScrollView, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {ChannelIcon} from '../components/ChannelIcon';
import {Icon} from '../components/Icon';
import {Sheet} from '../components/Sheet';
import {Tile} from '../components/SkillIcon';
import {EmptyState, IconButton, PageHeader} from '../components/ui';
import {tr, trf} from '../i18n';
import type {RootStackParamList} from '../navigation/types';
import type {ChannelInfo} from '../protocol/resources';
import {useAgentStore} from '../store/agentStore';
import {useChannelStore} from '../store/channelStore';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {
  bindingSummary,
  CHANNEL_BLURB,
  channelKey,
  channelLabel,
  channelPending,
  channelStatusLabel,
  channelTitle,
  splitChannels,
} from '../utils/channels';

type Props = StackScreenProps<RootStackParamList, 'Channels'>;

/** A WeChat login settling elsewhere flips its row on its own. */
const SETTLE_POLL_MS = 3000;

export function ChannelsScreen({navigation}: Props) {
  const t = useTheme();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const data = useChannelStore(s => s.data);
  const error = useChannelStore(s => s.error);
  const load = useChannelStore(s => s.load);
  const agents = useAgentStore(s => s.agents);
  const [refreshing, setRefreshing] = useState(false);
  const [picking, setPicking] = useState(false);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  const {connected, available} = useMemo(() => (data ? splitChannels(data) : {connected: [], available: []}), [data]);
  const settling = connected.some(c => channelPending(c) !== 'none');

  useEffect(() => {
    if (!settling) {
      return;
    }
    const timer = setInterval(load, SETTLE_POLL_MS);
    return () => clearInterval(timer);
  }, [settling, load]);

  const refresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const nameOf = (id: string) => agents.find(a => a.id === id)?.name;
  const open = (c: ChannelInfo) => navigation.navigate('Channel', {name: c.name, instanceId: c.instance_id});
  const add = (c: ChannelInfo) => {
    setPicking(false);
    navigation.navigate('Channel', {name: c.name, add: true});
  };

  return (
    <View style={styles.root}>
      <PageHeader
        title={tr('channel_list_title')}
        count={connected.length || undefined}
        onBack={navigation.goBack}
        right={
          available.length ? (
            <IconButton
              icon={faPlus}
              label={tr('channel_add')}
              filled
              size={13}
              color={t.t1}
              onPress={() => setPicking(true)}
            />
          ) : undefined
        }
      />
      {!data ? (
        <EmptyState loading={!error} title={tr('common_load_failed')} hint={error ?? undefined} />
      ) : (
        <ScrollView
          contentContainerStyle={[styles.body, {paddingBottom: insets.bottom + 32}]}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={t.t3} colors={[t.green]} />}>
          {connected.length ? (
            <>
              <SectionHead title={tr('channel_section_connected')} />
              <View style={styles.group}>
                {connected.map((c, i) => {
                  const pending = channelPending(c);
                  const binding = data.multi_agent && c.instance_id ? bindingSummary(c, nameOf) : '';
                  return (
                    <Row key={channelKey(c)} first={i === 0} onPress={() => open(c)} label={trf('channel_a11y_pair', {title: channelTitle(c), value: channelStatusLabel(c)})}>
                      <ChannelIcon name={c.name} />
                      <View style={styles.rowText}>
                        <View style={styles.titleLine}>
                          <Text style={styles.rowTitle} numberOfLines={1}>
                            {channelTitle(c)}
                          </Text>
                          {!!c.instance_name && <Text style={styles.tag}>{channelLabel(c)}</Text>}
                        </View>
                        <View style={styles.statusLine}>
                          <View style={[styles.dot, pending !== 'none' ? styles.dotPending : styles.dotOn]} />
                          <Text style={[styles.statusText, pending !== 'none' && styles.pendingText]} numberOfLines={1}>
                            {channelStatusLabel(c)}
                            {!!binding && <Text style={styles.bindingText}>{`  ·  ${binding}`}</Text>}
                          </Text>
                        </View>
                      </View>
                    </Row>
                  );
                })}
              </View>
            </>
          ) : (
            <View style={styles.hero}>
              <Tile icon={faTowerBroadcast} tone="accent" size={52} />
              <Text style={styles.heroTitle}>{tr('channel_empty')}</Text>
              <Text style={styles.heroHint}>{tr('channel_empty_hint')}</Text>
            </View>
          )}

          {!!available.length && (
            <>
              <SectionHead title={connected.length ? tr('channel_section_more') : tr('channel_section_start')} />
              <View style={styles.group}>
                {available.map((c, i) => (
                  <Row
                    key={c.name}
                    first={i === 0}
                    onPress={() => add(c)}
                    label={trf('channel_add_named', {name: channelLabel(c)})}>
                    <ChannelIcon name={c.name} />
                    <View style={styles.rowText}>
                      <Text style={styles.rowTitle} numberOfLines={1}>
                        {channelLabel(c)}
                      </Text>
                      {!!CHANNEL_BLURB[c.name] && (
                        <Text style={styles.rowMeta} numberOfLines={1}>
                          {CHANNEL_BLURB[c.name]}
                        </Text>
                      )}
                    </View>
                  </Row>
                ))}
              </View>
            </>
          )}
          <Text style={styles.footnote}>{tr('channel_footnote')}</Text>
        </ScrollView>
      )}

      <Sheet visible={picking} onClose={() => setPicking(false)} title={tr('channel_add')}>
        <ScrollView style={styles.pickList} bounces={false}>
          {available.map(c => (
            <Pressable
              key={c.name}
              accessibilityRole="button"
              onPress={() => add(c)}
              style={({pressed}) => [styles.pickRow, pressed && styles.pickPressed]}>
              <ChannelIcon name={c.name} size={34} />
              <View style={styles.rowText}>
                <Text style={styles.pickName}>{channelLabel(c)}</Text>
                {!!CHANNEL_BLURB[c.name] && <Text style={styles.pickDesc}>{CHANNEL_BLURB[c.name]}</Text>}
              </View>
            </Pressable>
          ))}
        </ScrollView>
      </Sheet>
    </View>
  );
}

function SectionHead({title}: {title: string}) {
  const styles = useStyles();
  return <Text style={styles.sectionTitle}>{title}</Text>;
}

function Row({first, onPress, label, children}: {first: boolean; onPress: () => void; label: string; children: ReactNode}) {
  const t = useTheme();
  const styles = useStyles();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={onPress}
      style={({pressed}) => [styles.row, !first && styles.divider, pressed && styles.rowPressed]}>
      {children}
      <Icon icon={faChevronRight} size={10} color={t.t4} />
    </Pressable>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, backgroundColor: t.bg0},
  body: {paddingTop: 4, flexGrow: 1},
  sectionTitle: {fontSize: 12, fontWeight: '600', letterSpacing: 0.6, color: t.t3, paddingHorizontal: 18, marginTop: 14, marginBottom: 10},
  group: {
    marginHorizontal: 14,
    borderRadius: radius.md,
    backgroundColor: t.bg1,
    borderWidth: 1,
    borderColor: t.line1,
    overflow: 'hidden',
  },
  row: {flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 14, paddingVertical: 12},
  divider: {borderTopWidth: 1, borderTopColor: t.line1},
  rowPressed: {backgroundColor: t.bg2},
  rowText: {flex: 1, minWidth: 0},
  titleLine: {flexDirection: 'row', alignItems: 'center', gap: 6},
  rowTitle: {flexShrink: 1, fontSize: 15, fontWeight: '600', color: t.t1, letterSpacing: -0.1},
  rowMeta: {fontSize: 12.5, color: t.t3, marginTop: 3},
  tag: {
    fontSize: 10.5,
    color: t.t3,
    paddingHorizontal: 5,
    paddingVertical: 1,
    borderRadius: 5,
    overflow: 'hidden',
    backgroundColor: t.bg2,
  },
  statusLine: {flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 4},
  statusText: {flexShrink: 1, fontSize: 12.5, color: t.t3},
  bindingText: {color: t.t3},
  dot: {width: 6, height: 6, borderRadius: 3},
  dotOn: {backgroundColor: t.accent},
  dotPending: {backgroundColor: t.kind.image[1]},
  pendingText: {color: t.kind.image[1]},
  hero: {
    alignItems: 'center',
    marginHorizontal: 14,
    marginTop: 10,
    paddingHorizontal: 28,
    paddingTop: 30,
    paddingBottom: 26,
    borderRadius: radius.md,
    borderWidth: 1,
    borderStyle: 'dashed',
    borderColor: t.line2,
  },
  heroTitle: {fontSize: 16, fontWeight: '600', color: t.t1, marginTop: 16, letterSpacing: -0.2},
  heroHint: {fontSize: 13, lineHeight: 20, color: t.t3, marginTop: 6, textAlign: 'center'},
  footnote: {fontSize: 12, lineHeight: 18, color: t.t4, paddingHorizontal: 18, paddingTop: 14},
  pickList: {maxHeight: 460},
  pickRow: {flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 12, paddingVertical: 10, borderRadius: radius.md},
  pickPressed: {backgroundColor: t.bg2},
  pickName: {fontSize: 15, fontWeight: '500', color: t.t1},
  pickDesc: {fontSize: 12, lineHeight: 17, color: t.t3, marginTop: 2},
}));
