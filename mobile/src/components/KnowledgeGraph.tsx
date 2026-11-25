import {faCompress, faMinus, faPlus} from '@fortawesome/free-solid-svg-icons';
import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {ActivityIndicator, Pressable, ScrollView, Text, View, type LayoutChangeEvent} from 'react-native';
import {Gesture, GestureDetector} from 'react-native-gesture-handler';
import Svg, {Circle, G, Path, Text as SvgText} from 'react-native-svg';
import {tr, trf} from '../i18n';
import type {KnowledgeGraph as GraphData} from '../protocol/resources';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {
  COMFORT_K,
  fitView,
  initialView,
  LABEL_PX,
  labelText,
  placeLabels,
  startLayout,
  type GraphLayout,
  type GraphView,
  type LaidNode,
} from '../utils/graphLayout';
import {Icon} from './Icon';

const MAX_K = 4;
/** However far out the view goes, a page stays a dot this wide on screen. */
const MIN_DOT_PX = 2.5;
const ZOOM_MS = 180;
/** Slices short enough that the spinner and the back button keep answering. */
const LAYOUT_SLICE_MS = 12;

/** Laid out once per graph read: going back to the tab must not wait for it again. */
const layouts = new WeakMap<GraphData, GraphLayout>();

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi);

const circle = (x: number, y: number, r: number) =>
  `M${(x - r).toFixed(1)} ${y.toFixed(1)}a${r.toFixed(2)} ${r.toFixed(2)} 0 1 0 ${(2 * r).toFixed(2)} 0a${r.toFixed(2)} ${r.toFixed(2)} 0 1 0 ${(-2 * r).toFixed(2)} 0`;
const segment = (a: LaidNode, b: LaidNode) => `M${a.x.toFixed(1)} ${a.y.toFixed(1)}L${b.x.toFixed(1)} ${b.y.toFixed(1)}`;

/**
 * A drag or pinch only moves the drawing, at most once a frame; the dots are
 * resized and the names chosen again once it settles. Links and dots are a
 * handful of paths rather than one element each.
 *
 * The moving transform stays on the JS side on purpose: animating an SVG prop
 * from the UI thread commits the whole tree there every frame, and on Android
 * that starves the JS thread until the app stops answering.
 */
export function KnowledgeGraph({data, onOpen}: {data: GraphData; onOpen: (id: string, label: string) => void}) {
  const t = useTheme();
  const styles = useStyles();
  const [size, setSize] = useState<{w: number; h: number} | null>(null);
  const [layout, setLayout] = useState<GraphLayout | null>(() => layouts.get(data) ?? null);
  /** Where the dots and names were last worked out for. */
  const [view, setView] = useState<GraphView | null>(null);
  /** Where the drawing is right now, mid-gesture included. */
  const [live, setLive] = useState<GraphView | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const current = useRef<GraphView>({k: 1, x: 0, y: 0});
  const minK = useRef(0.2);
  const frame = useRef<number | null>(null);
  const tween = useRef<number | null>(null);

  useEffect(() => {
    setSelected(null);
    const cached = layouts.get(data);
    if (cached) {
      setLayout(cached);
      return;
    }
    setLayout(null);
    const job = startLayout(data);
    let timer: ReturnType<typeof setTimeout>;
    const run = () => {
      if (job.step(LAYOUT_SLICE_MS)) {
        layouts.set(data, job.layout);
        setLayout(job.layout);
      } else {
        timer = setTimeout(run, 0);
      }
    };
    // Deferred a tick so the spinner paints first.
    timer = setTimeout(run, 16);
    return () => clearTimeout(timer);
  }, [data]);

  useEffect(
    () => () => {
      if (frame.current != null) {
        cancelAnimationFrame(frame.current);
      }
      if (tween.current != null) {
        cancelAnimationFrame(tween.current);
      }
    },
    [],
  );

  const show = useCallback((v: GraphView) => {
    current.current = v;
    if (frame.current == null) {
      frame.current = requestAnimationFrame(() => {
        frame.current = null;
        setLive(current.current);
      });
    }
  }, []);

  const settle = useCallback(() => {
    if (frame.current != null) {
      cancelAnimationFrame(frame.current);
      frame.current = null;
    }
    setLive(current.current);
    setView(current.current);
  }, []);

  const stopTween = useCallback(() => {
    if (tween.current != null) {
      cancelAnimationFrame(tween.current);
      tween.current = null;
    }
  }, []);

  const moveTo = useCallback(
    (to: GraphView, animate: boolean) => {
      stopTween();
      if (!animate) {
        current.current = to;
        settle();
        return;
      }
      const from = current.current;
      const start = Date.now();
      const step = () => {
        const p = Math.min(1, (Date.now() - start) / ZOOM_MS);
        const e = 1 - (1 - p) * (1 - p);
        current.current = {k: from.k + (to.k - from.k) * e, x: from.x + (to.x - from.x) * e, y: from.y + (to.y - from.y) * e};
        if (p < 1) {
          setLive(current.current);
          tween.current = requestAnimationFrame(step);
        } else {
          tween.current = null;
          settle();
        }
      };
      tween.current = requestAnimationFrame(step);
    },
    [settle, stopTween],
  );

  useEffect(() => {
    if (layout && size) {
      // Far enough out to take in the whole graph, and a little more.
      minK.current = Math.min(fitView(layout.nodes, size.w, size.h).k, COMFORT_K) * 0.8;
      moveTo(initialView(layout, size.w, size.h), false);
    }
  }, [layout, size, moveTo]);

  const onLayout = (e: LayoutChangeEvent) => {
    const {width, height} = e.nativeEvent.layout;
    setSize(prev => (prev && prev.w === width && prev.h === height ? prev : {w: width, h: height}));
  };

  const layoutRef = useRef(layout);
  layoutRef.current = layout;
  const dotRadius = useCallback((n: LaidNode, vk: number) => Math.max(n.r, MIN_DOT_PX / vk), []);

  const tapAt = useCallback(
    (x: number, y: number) => {
      const lay = layoutRef.current;
      if (!lay) {
        return;
      }
      const v = current.current;
      const gx = (x - v.x) / v.k;
      const gy = (y - v.y) / v.k;
      let best: LaidNode | null = null;
      let bestD = Infinity;
      for (const n of lay.nodes) {
        const d = Math.hypot(n.x - gx, n.y - gy) - dotRadius(n, v.k);
        if (d < bestD) {
          best = n;
          bestD = d;
        }
      }
      // Small dots get a finger-sized target at any zoom.
      setSelected(best && bestD * v.k <= 14 ? best.id : null);
    },
    [dotRadius],
  );

  // Built once: a detector handed new gestures on a re-render can stop answering touches.
  const gesture = useMemo(() => {
    const base = {k: 1, x: 0, y: 0, anchorX: 0, anchorY: 0};
    // Set by a pinch, so a finger left on the glass carries on from where the pinch put the graph.
    let rebase = false;

    const pan = Gesture.Pan()
      .runOnJS(true)
      .onStart(() => {
        stopTween();
        rebase = false;
        base.x = current.current.x;
        base.y = current.current.y;
      })
      .onUpdate(e => {
        if (e.numberOfPointers > 1) {
          return;
        }
        if (rebase) {
          rebase = false;
          base.x = current.current.x - e.translationX;
          base.y = current.current.y - e.translationY;
        }
        show({k: current.current.k, x: base.x + e.translationX, y: base.y + e.translationY});
      })
      .onEnd(() => settle());

    const pinch = Gesture.Pinch()
      .runOnJS(true)
      .onStart(e => {
        stopTween();
        rebase = true;
        const v = current.current;
        base.k = v.k;
        // The graph point under the fingers, which stays under them as they spread or move.
        base.anchorX = (e.focalX - v.x) / v.k;
        base.anchorY = (e.focalY - v.y) / v.k;
      })
      .onUpdate(e => {
        const k = clamp(base.k * e.scale, minK.current, MAX_K);
        show({k, x: e.focalX - base.anchorX * k, y: e.focalY - base.anchorY * k});
      })
      .onEnd(() => settle());

    const tap = Gesture.Tap()
      .runOnJS(true)
      .maxDistance(8)
      .onEnd((e, success) => {
        if (success) {
          tapAt(e.x, e.y);
        }
      });

    return Gesture.Race(Gesture.Simultaneous(pan, pinch), tap);
  }, [show, settle, stopTween, tapAt]);

  const zoomBy = (factor: number) => {
    if (!size) {
      return;
    }
    const v = current.current;
    const k = clamp(v.k * factor, minK.current, MAX_K);
    const cx = size.w / 2;
    const cy = size.h / 2;
    moveTo({k, x: cx - ((cx - v.x) / v.k) * k, y: cy - ((cy - v.y) / v.k) * k}, true);
  };

  const content = useMemo(() => {
    if (!layout || !view || !size) {
      return null;
    }
    const {nodes, links, adjacency, color} = layout;
    const near = selected ? adjacency.get(selected) ?? new Set<string>() : null;
    const lit = (id: string) => !near || id === selected || near.has(id);
    const r = (n: LaidNode) => dotRadius(n, view.k);

    let quiet = '';
    let active = '';
    for (const {a, b} of links) {
      if (selected && (a.id === selected || b.id === selected)) {
        active += segment(a, b);
      } else {
        quiet += segment(a, b);
      }
    }
    const dots = new Map<string, {lit: string; dim: string}>();
    for (const n of nodes) {
      const group = dots.get(n.category) ?? dots.set(n.category, {lit: '', dim: ''}).get(n.category)!;
      if (lit(n.id)) {
        group.lit += circle(n.x, n.y, r(n));
      } else {
        group.dim += circle(n.x, n.y, r(n));
      }
    }
    const picked = selected ? nodes.find(n => n.id === selected) : undefined;
    const labels = placeLabels(layout, view, size.w, size.h, selected, r);
    const s = 1 / view.k;
    return (
      <>
        <Path d={quiet} fill="none" stroke={t.t4} strokeOpacity={selected ? 0.12 : 0.45} strokeWidth={1} vectorEffect="non-scaling-stroke" />
        {!!active && (
          <Path d={active} fill="none" stroke={t.accent} strokeOpacity={0.9} strokeWidth={1.6} vectorEffect="non-scaling-stroke" />
        )}
        {[...dots].map(([category, group]) => (
          <React.Fragment key={category}>
            {!!group.dim && (
              <Path d={group.dim} fill={color(category)} opacity={0.2} stroke={t.bg0} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
            )}
            {!!group.lit && (
              <Path d={group.lit} fill={color(category)} stroke={t.bg0} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
            )}
          </React.Fragment>
        ))}
        {picked && (
          <Circle
            cx={picked.x}
            cy={picked.y}
            r={r(picked) + 2 * s}
            fill={color(picked.category)}
            stroke={t.t1}
            strokeWidth={1.5}
            vectorEffect="non-scaling-stroke"
          />
        )}
        {labels.map(n => (
          <SvgText
            key={n.id}
            x={n.x + r(n) + 3 * s}
            y={n.y + LABEL_PX * 0.35 * s}
            fontSize={LABEL_PX * s}
            fill={n.id === selected ? t.t1 : t.t2}
            opacity={lit(n.id) ? 1 : 0.25}>
            {labelText(n.label)}
          </SvgText>
        ))}
      </>
    );
  }, [layout, view, size, selected, dotRadius, t]);

  const picked = selected && layout ? layout.nodes.find(n => n.id === selected) : null;

  return (
    <View style={styles.root} onLayout={onLayout}>
      {!layout || !size || !view || !live ? (
        <View style={styles.center}>
          <ActivityIndicator color={t.t3} />
        </View>
      ) : (
        <>
          <GestureDetector gesture={gesture}>
            <View style={styles.fill} collapsable={false}>
              <Svg width={size.w} height={size.h}>
                <G transform={`translate(${live.x}, ${live.y}) scale(${live.k})`}>{content}</G>
              </Svg>
            </View>
          </GestureDetector>
          <View style={styles.zoom}>
            <ZoomButton icon={faPlus} label={tr('knowledge_zoom_in')} onPress={() => zoomBy(1.5)} />
            <ZoomButton icon={faMinus} label={tr('knowledge_zoom_out')} onPress={() => zoomBy(1 / 1.5)} />
            <ZoomButton
              icon={faCompress}
              label={tr('knowledge_zoom_fit')}
              onPress={() => moveTo(fitView(layout.nodes, size.w, size.h), true)}
            />
          </View>
          {picked ? (
            <View style={styles.card}>
              <View style={[styles.dot, {backgroundColor: layout.color(picked.category)}]} />
              <View style={styles.cardText}>
                <Text style={styles.cardTitle} numberOfLines={1}>
                  {picked.label}
                </Text>
                <Text style={styles.cardMeta} numberOfLines={1}>
                  {picked.category === 'root' ? tr('knowledge_root') : picked.category} ·{' '}
                  {trf('knowledge_links', {n: picked.degree})}
                </Text>
              </View>
              <Pressable
                accessibilityRole="button"
                onPress={() => onOpen(picked.id, picked.label)}
                style={({pressed}) => [styles.open, pressed && styles.pressed]}>
                <Text style={styles.openText}>{tr('common_open')}</Text>
              </Pressable>
            </View>
          ) : (
            layout.categories.length > 0 && (
              <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.legend} contentContainerStyle={styles.legendRow}>
                {layout.categories.map(c => (
                  <View key={c} style={styles.legendItem}>
                    <View style={[styles.legendDot, {backgroundColor: layout.color(c)}]} />
                    <Text style={styles.legendText}>{c === 'root' ? tr('knowledge_root') : c}</Text>
                  </View>
                ))}
              </ScrollView>
            )
          )}
        </>
      )}
    </View>
  );
}

function ZoomButton({icon, label, onPress}: {icon: typeof faPlus; label: string; onPress: () => void}) {
  const t = useTheme();
  const styles = useStyles();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      hitSlop={4}
      onPress={onPress}
      style={({pressed}) => [styles.zoomButton, pressed && styles.pressed]}>
      <Icon icon={icon} size={12} color={t.t2} />
    </Pressable>
  );
}

const useStyles = makeStyles(t => ({
  root: {flex: 1, overflow: 'hidden'},
  fill: {flex: 1},
  center: {flex: 1, alignItems: 'center', justifyContent: 'center'},
  zoom: {position: 'absolute', top: 10, right: 12, gap: 6},
  zoomButton: {
    width: 34,
    height: 34,
    borderRadius: radius.sm,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: t.isDark ? t.bg2 : t.bg0,
    borderWidth: 1,
    borderColor: t.line1,
  },
  pressed: {opacity: 0.7},
  card: {
    position: 'absolute',
    left: 12,
    right: 12,
    bottom: 12,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingLeft: 14,
    paddingRight: 8,
    paddingVertical: 10,
    borderRadius: radius.md,
    backgroundColor: t.isDark ? t.bg2 : t.bg0,
    borderWidth: 1,
    borderColor: t.line1,
  },
  dot: {width: 10, height: 10, borderRadius: 5},
  cardText: {flex: 1, minWidth: 0},
  cardTitle: {fontSize: 15, fontWeight: '500', color: t.t1},
  cardMeta: {fontSize: 12, color: t.t3, marginTop: 2},
  open: {paddingHorizontal: 14, paddingVertical: 8, borderRadius: radius.sm, backgroundColor: t.accentSoft},
  openText: {fontSize: 14, fontWeight: '600', color: t.accent},
  legend: {position: 'absolute', left: 0, right: 0, bottom: 12, flexGrow: 0},
  legendRow: {paddingHorizontal: 12, gap: 6},
  legendItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 999,
    backgroundColor: t.isDark ? t.bg2 : t.bg0,
    borderWidth: 1,
    borderColor: t.line1,
  },
  legendDot: {width: 8, height: 8, borderRadius: 4},
  legendText: {fontSize: 12, color: t.t2},
}));
