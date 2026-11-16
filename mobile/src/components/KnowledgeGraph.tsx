import {faCompress, faMinus, faPlus} from '@fortawesome/free-solid-svg-icons';
import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {
  ActivityIndicator,
  PanResponder,
  Pressable,
  ScrollView,
  Text,
  View,
  type GestureResponderEvent,
  type LayoutChangeEvent,
} from 'react-native';
import Svg, {Circle, G, Line, Text as SvgText} from 'react-native-svg';
import {tr, trf} from '../i18n';
import type {KnowledgeGraph as GraphData} from '../protocol/resources';
import {radius} from '../theme/palette';
import {makeStyles, useTheme} from '../theme/theme';
import {Icon} from './Icon';

/** d3.schemeTableau10, the palette the web console and desktop graphs use. */
const TABLEAU10 = ['#4e79a7', '#f28e2c', '#e15759', '#76b7b2', '#59a14f', '#edc949', '#af7aa1', '#ff9da7', '#9c755f', '#bab0ab'];
const MIN_K = 0.2;
const MAX_K = 5;
const TAP_SLOP = 8;

const nodeRadius = (degree: number) => Math.max(4, Math.min(12, 4 + degree * 1.4));
const clampK = (k: number) => Math.min(MAX_K, Math.max(MIN_K, k));

interface LaidNode {
  id: string;
  label: string;
  category: string;
  x: number;
  y: number;
  r: number;
  degree: number;
}

interface Layout {
  nodes: LaidNode[];
  links: {a: LaidNode; b: LaidNode}[];
  adjacency: Map<string, Set<string>>;
  categories: string[];
  color: (category: string) => string;
}

/**
 * The desktop graph's forces, run to rest up front instead of animated: phones
 * pay for every frame. Fewer, faster-cooling rounds keep big bases bounded.
 */
export function layoutGraph(data: GraphData): Layout {
  const degree = new Map<string, number>();
  const ids = new Set(data.nodes.map(n => n.id));
  const edges = data.links.filter(l => ids.has(l.source) && ids.has(l.target) && l.source !== l.target);
  edges.forEach(l => {
    degree.set(l.source, (degree.get(l.source) || 0) + 1);
    degree.set(l.target, (degree.get(l.target) || 0) + 1);
  });
  const catCount = new Map<string, number>();
  data.nodes.forEach(n => catCount.set(n.category || 'root', (catCount.get(n.category || 'root') || 0) + 1));
  const categories = [...catCount.keys()].sort((a, b) => catCount.get(b)! - catCount.get(a)! || a.localeCompare(b));
  const color = (c: string) => TABLEAU10[Math.max(0, categories.indexOf(c)) % TABLEAU10.length];

  const count = data.nodes.length || 1;
  const ring = Math.sqrt(count) * 40;
  const nodes: LaidNode[] = data.nodes.map((n, i) => {
    const angle = (i / count) * Math.PI * 2;
    const d = degree.get(n.id) || 0;
    return {
      id: n.id,
      label: n.label || n.id,
      category: n.category || 'root',
      x: Math.cos(angle) * ring,
      y: Math.sin(angle) * ring,
      r: nodeRadius(d),
      degree: d,
    };
  });
  const byId = new Map(nodes.map(n => [n.id, n]));
  const links = edges.map(l => ({a: byId.get(l.source)!, b: byId.get(l.target)!}));
  const adjacency = new Map<string, Set<string>>();
  links.forEach(({a, b}) => {
    (adjacency.get(a.id) ?? adjacency.set(a.id, new Set()).get(a.id)!).add(b.id);
    (adjacency.get(b.id) ?? adjacency.set(b.id, new Set()).get(b.id)!).add(a.id);
  });

  const rounds = count <= 120 ? 300 : Math.max(60, Math.floor(36000 / count));
  const decay = 1 - Math.pow(0.005, 1 / rounds);
  const vx = new Float64Array(nodes.length);
  const vy = new Float64Array(nodes.length);
  const index = new Map(nodes.map((n, i) => [n, i]));
  let alpha = 1;
  for (let round = 0; round < rounds; round++) {
    vx.fill(0);
    vy.fill(0);
    for (let i = 0; i < nodes.length; i++) {
      const a = nodes[i];
      for (let j = i + 1; j < nodes.length; j++) {
        const b = nodes[j];
        let dx = a.x - b.x;
        let dy = a.y - b.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 0.01) {
          dx = Math.random() - 0.5;
          dy = Math.random() - 0.5;
          d2 = 0.01;
        }
        const d = Math.sqrt(d2);
        let f = 9000 / d2;
        const minDist = a.r + b.r + 14;
        if (d < minDist) {
          f += (minDist - d) * 0.6;
        }
        vx[i] += (dx / d) * f;
        vy[i] += (dy / d) * f;
        vx[j] -= (dx / d) * f;
        vy[j] -= (dy / d) * f;
      }
    }
    for (const {a, b} of links) {
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 1;
      const f = (d - 80) * 0.04;
      const ia = index.get(a)!;
      const ib = index.get(b)!;
      vx[ia] += (dx / d) * f;
      vy[ia] += (dy / d) * f;
      vx[ib] -= (dx / d) * f;
      vy[ib] -= (dy / d) * f;
    }
    for (let i = 0; i < nodes.length; i++) {
      const n = nodes[i];
      let dx = (vx[i] - n.x * 0.012) * alpha;
      let dy = (vy[i] - n.y * 0.012) * alpha;
      const m = Math.hypot(dx, dy);
      if (m > 30) {
        dx = (dx / m) * 30;
        dy = (dy / m) * 30;
      }
      n.x += dx;
      n.y += dy;
    }
    alpha -= alpha * decay;
  }
  return {nodes, links, adjacency, categories, color};
}

interface View2D {
  k: number;
  x: number;
  y: number;
}

function fitView(nodes: LaidNode[], w: number, h: number): View2D {
  if (!nodes.length) {
    return {k: 1, x: w / 2, y: h / 2};
  }
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const n of nodes) {
    minX = Math.min(minX, n.x - n.r);
    minY = Math.min(minY, n.y - n.r);
    maxX = Math.max(maxX, n.x + n.r);
    maxY = Math.max(maxY, n.y + n.r);
  }
  const pad = 36;
  const k = clampK(Math.min((w - pad * 2) / Math.max(1, maxX - minX), (h - pad * 2) / Math.max(1, maxY - minY), 1.6));
  return {k, x: w / 2 - ((minX + maxX) / 2) * k, y: h / 2 - ((minY + maxY) / 2) * k};
}

const truncate = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

export function KnowledgeGraph({data, onOpen}: {data: GraphData; onOpen: (id: string, label: string) => void}) {
  const t = useTheme();
  const styles = useStyles();
  const [size, setSize] = useState<{w: number; h: number} | null>(null);
  const [layout, setLayout] = useState<Layout | null>(null);
  const [view, setView] = useState<View2D>({k: 1, x: 0, y: 0});
  const [selected, setSelected] = useState<string | null>(null);
  const viewRef = useRef(view);
  viewRef.current = view;
  const originRef = useRef({x: 0, y: 0});
  const boxRef = useRef<View>(null);

  // Deferred a tick so the spinner paints before the layout blocks the JS thread.
  useEffect(() => {
    setLayout(null);
    setSelected(null);
    const timer = setTimeout(() => setLayout(layoutGraph(data)), 16);
    return () => clearTimeout(timer);
  }, [data]);

  useEffect(() => {
    if (layout && size) {
      setView(fitView(layout.nodes, size.w, size.h));
    }
  }, [layout, size]);

  const onLayout = (e: LayoutChangeEvent) => {
    const {width, height} = e.nativeEvent.layout;
    setSize(prev => (prev && prev.w === width && prev.h === height ? prev : {w: width, h: height}));
    boxRef.current?.measureInWindow((x, y) => {
      originRef.current = {x, y};
    });
  };

  const frame = useRef<number | null>(null);
  const pending = useRef<View2D | null>(null);
  const schedule = useCallback((v: View2D) => {
    pending.current = v;
    viewRef.current = v;
    if (frame.current == null) {
      frame.current = requestAnimationFrame(() => {
        frame.current = null;
        if (pending.current) {
          setView(pending.current);
        }
      });
    }
  }, []);
  useEffect(() => () => {
    if (frame.current != null) {
      cancelAnimationFrame(frame.current);
    }
  }, []);

  const layoutRef = useRef(layout);
  layoutRef.current = layout;

  const gesture = useRef<{
    mode: 'pan' | 'pinch';
    base: View2D;
    startX: number;
    startY: number;
    dist0?: number;
    anchor?: {x: number; y: number};
    moved: boolean;
  } | null>(null);

  const local = (e: GestureResponderEvent, i = 0) => {
    const touch = e.nativeEvent.touches[i] ?? e.nativeEvent;
    return {x: touch.pageX - originRef.current.x, y: touch.pageY - originRef.current.y};
  };

  const beginPinch = (e: GestureResponderEvent) => {
    const p1 = local(e, 0);
    const p2 = local(e, 1);
    const v = viewRef.current;
    const mid = {x: (p1.x + p2.x) / 2, y: (p1.y + p2.y) / 2};
    gesture.current = {
      mode: 'pinch',
      base: v,
      startX: mid.x,
      startY: mid.y,
      dist0: Math.hypot(p1.x - p2.x, p1.y - p2.y) || 1,
      anchor: {x: (mid.x - v.x) / v.k, y: (mid.y - v.y) / v.k},
      moved: true,
    };
  };

  const beginPan = (e: GestureResponderEvent, moved: boolean) => {
    const p = local(e);
    gesture.current = {mode: 'pan', base: viewRef.current, startX: p.x, startY: p.y, moved};
  };

  const tapAt = (p: {x: number; y: number}) => {
    const lay = layoutRef.current;
    if (!lay) {
      return;
    }
    const v = viewRef.current;
    const gx = (p.x - v.x) / v.k;
    const gy = (p.y - v.y) / v.k;
    let best: LaidNode | null = null;
    let bestD = Infinity;
    for (const n of lay.nodes) {
      const d = Math.hypot(n.x - gx, n.y - gy);
      if (d < bestD) {
        best = n;
        bestD = d;
      }
    }
    // Small dots get a finger-sized target at any zoom.
    setSelected(best && bestD * v.k <= best.r * v.k + 14 ? best.id : null);
  };

  const responder = useMemo(
    () =>
      PanResponder.create({
        onStartShouldSetPanResponder: () => true,
        onMoveShouldSetPanResponder: () => true,
        onPanResponderTerminationRequest: () => false,
        onPanResponderGrant: e => {
          if (e.nativeEvent.touches.length >= 2) {
            beginPinch(e);
          } else {
            beginPan(e, false);
          }
        },
        onPanResponderMove: e => {
          const g = gesture.current;
          const touches = e.nativeEvent.touches.length;
          if (!g) {
            return;
          }
          if (touches >= 2) {
            if (g.mode !== 'pinch') {
              beginPinch(e);
              return;
            }
            const p1 = local(e, 0);
            const p2 = local(e, 1);
            const mid = {x: (p1.x + p2.x) / 2, y: (p1.y + p2.y) / 2};
            const k = clampK((g.base.k * Math.hypot(p1.x - p2.x, p1.y - p2.y)) / (g.dist0 ?? 1));
            schedule({k, x: mid.x - g.anchor!.x * k, y: mid.y - g.anchor!.y * k});
            return;
          }
          if (g.mode === 'pinch') {
            // One finger lifted: carry on panning from where the pinch left off.
            beginPan(e, true);
            return;
          }
          const p = local(e);
          const dx = p.x - g.startX;
          const dy = p.y - g.startY;
          if (!g.moved && Math.hypot(dx, dy) < TAP_SLOP) {
            return;
          }
          g.moved = true;
          schedule({k: g.base.k, x: g.base.x + dx, y: g.base.y + dy});
        },
        onPanResponderRelease: e => {
          const g = gesture.current;
          gesture.current = null;
          if (g && !g.moved) {
            tapAt(local(e));
          }
        },
        onPanResponderTerminate: () => {
          gesture.current = null;
        },
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [schedule],
  );

  const zoomBy = (factor: number) => {
    if (!size) {
      return;
    }
    const v = viewRef.current;
    const k = clampK(v.k * factor);
    const cx = size.w / 2;
    const cy = size.h / 2;
    setView({k, x: cx - ((cx - v.x) / v.k) * k, y: cy - ((cy - v.y) / v.k) * k});
  };

  // Strokes and type keep their on-screen size; re-derived only when zoom crosses a step.
  const kStep = Math.round(view.k * 8) / 8;
  const content = useMemo(() => {
    if (!layout) {
      return null;
    }
    const {nodes, links, adjacency, color} = layout;
    const near = selected ? adjacency.get(selected) ?? new Set<string>() : null;
    const lit = (id: string) => !near || id === selected || near.has(id);
    const many = nodes.length > 150;
    const showLabel = (n: LaidNode) =>
      (near ? lit(n.id) : false) || kStep >= 1.4 || n.degree >= (many ? 5 : 3);
    const s = 1 / kStep;
    return (
      <>
        {links.map(({a, b}, i) => {
          const active = !!selected && (a.id === selected || b.id === selected);
          return (
            <Line
              key={i}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              stroke={active ? t.accent : t.t4}
              strokeOpacity={selected ? (active ? 0.9 : 0.12) : 0.45}
              strokeWidth={(active ? 1.6 : 1) * s}
            />
          );
        })}
        {nodes.map(n => (
          <Circle
            key={n.id}
            cx={n.x}
            cy={n.y}
            r={n.id === selected ? n.r + 2 : n.r}
            fill={color(n.category)}
            opacity={lit(n.id) ? 1 : 0.2}
            stroke={n.id === selected ? t.t1 : t.bg0}
            strokeWidth={1.5 * s}
          />
        ))}
        {nodes.filter(showLabel).map(n => (
          <SvgText
            key={`l${n.id}`}
            x={n.x + n.r + 4 * s}
            y={n.y + 3.5 * s}
            fontSize={11 * s}
            fill={n.id === selected ? t.t1 : t.t2}
            opacity={lit(n.id) ? 1 : 0.25}>
            {truncate(n.label, 16)}
          </SvgText>
        ))}
      </>
    );
  }, [layout, selected, kStep, t]);

  const picked = selected && layout ? layout.nodes.find(n => n.id === selected) : null;

  return (
    <View ref={boxRef} style={styles.root} onLayout={onLayout}>
      {!layout || !size ? (
        <View style={styles.center}>
          <ActivityIndicator color={t.t3} />
        </View>
      ) : (
        <>
          <View style={styles.fill} {...responder.panHandlers}>
            <Svg width={size.w} height={size.h}>
              <G transform={`translate(${view.x}, ${view.y}) scale(${view.k})`}>{content}</G>
            </Svg>
          </View>
          <View style={styles.zoom}>
            <ZoomButton icon={faPlus} label={tr('knowledge_zoom_in')} onPress={() => zoomBy(1.4)} />
            <ZoomButton icon={faMinus} label={tr('knowledge_zoom_out')} onPress={() => zoomBy(1 / 1.4)} />
            <ZoomButton
              icon={faCompress}
              label={tr('knowledge_zoom_fit')}
              onPress={() => setView(fitView(layout.nodes, size.w, size.h))}
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
