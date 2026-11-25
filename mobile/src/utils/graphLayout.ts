import type {KnowledgeGraph} from '../protocol/resources';

/** d3.schemeTableau10, the palette the web console and desktop graphs use. */
const TABLEAU10 = ['#4e79a7', '#f28e2c', '#e15759', '#76b7b2', '#59a14f', '#edc949', '#af7aa1', '#ff9da7', '#9c755f', '#bab0ab'];

const REPULSION = 9000;
const LINK_LENGTH = 80;
const LINK_PULL = 0.04;
const GRAVITY = 0.012;
const COLLIDE_GAP = 14;
const MAX_STEP = 30;
/** Barnes-Hut accuracy: a cell this small against its distance counts as one body. */
const THETA2 = 1.44;

export const nodeRadius = (degree: number) => Math.max(3.5, Math.min(10, 3.5 + degree * 1.2));

export interface LaidNode {
  id: string;
  label: string;
  category: string;
  x: number;
  y: number;
  r: number;
  degree: number;
}

export interface GraphLayout {
  nodes: LaidNode[];
  links: {a: LaidNode; b: LaidNode}[];
  adjacency: Map<string, Set<string>>;
  categories: string[];
  color: (category: string) => string;
}

export interface GraphView {
  k: number;
  x: number;
  y: number;
}

/** A layout run in slices: each `step` spends about `budgetMs` and says whether it is done. */
export interface LayoutJob {
  layout: GraphLayout;
  step: (budgetMs: number) => boolean;
}

/**
 * The desktop graph's forces, cooled over a fixed number of rounds instead of
 * animated: phones pay for every frame. Repulsion goes through a quadtree and
 * collisions through a grid, so a round costs n·log n rather than n².
 */
export function startLayout(data: KnowledgeGraph): LayoutJob {
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

  const count = data.nodes.length;
  // A sunflower spiral packs the start evenly, so the forces only have to sort it out.
  const golden = Math.PI * (3 - Math.sqrt(5));
  const nodes: LaidNode[] = data.nodes.map((n, i) => {
    const d = degree.get(n.id) || 0;
    const r = 24 * Math.sqrt(0.5 + i);
    return {
      id: n.id,
      label: n.label || n.id,
      category: n.category || 'root',
      x: Math.cos(i * golden) * r,
      y: Math.sin(i * golden) * r,
      r: nodeRadius(d),
      degree: d,
    };
  });
  const byId = new Map(nodes.map((n, i) => [n.id, i]));
  const links = edges.map(l => ({a: nodes[byId.get(l.source)!], b: nodes[byId.get(l.target)!]}));
  const adjacency = new Map<string, Set<string>>();
  links.forEach(({a, b}) => {
    (adjacency.get(a.id) ?? adjacency.set(a.id, new Set()).get(a.id)!).add(b.id);
    (adjacency.get(b.id) ?? adjacency.set(b.id, new Set()).get(b.id)!).add(a.id);
  });
  const layout: GraphLayout = {nodes, links, adjacency, categories, color};

  const X = new Float64Array(count);
  const Y = new Float64Array(count);
  const R = new Float64Array(count);
  nodes.forEach((n, i) => {
    X[i] = n.x;
    Y[i] = n.y;
    R[i] = n.r;
  });
  const linkA = new Int32Array(edges.map(l => byId.get(l.source)!));
  const linkB = new Int32Array(edges.map(l => byId.get(l.target)!));
  const vx = new Float64Array(count);
  const vy = new Float64Array(count);
  const tree = new QuadTree(count);
  const grid = new Map<number, number[]>();
  let maxR = 0;
  R.forEach(r => (maxR = Math.max(maxR, r)));
  const cell = maxR * 2 + COLLIDE_GAP;

  const rounds = Math.max(100, Math.min(300, Math.floor(60000 / Math.max(1, count))));
  const decay = 1 - Math.pow(0.005, 1 / rounds);
  let alpha = 1;
  let round = 0;

  const tick = () => {
    vx.fill(0);
    vy.fill(0);
    tree.build(X, Y);
    for (let i = 0; i < count; i++) {
      tree.repel(i, X, Y, vx, vy);
    }

    grid.clear();
    for (let i = 0; i < count; i++) {
      const key = cellKey(Math.floor(X[i] / cell), Math.floor(Y[i] / cell));
      const bucket = grid.get(key);
      if (bucket) {
        bucket.push(i);
      } else {
        grid.set(key, [i]);
      }
    }
    for (let i = 0; i < count; i++) {
      const cx = Math.floor(X[i] / cell);
      const cy = Math.floor(Y[i] / cell);
      for (let gx = cx - 1; gx <= cx + 1; gx++) {
        for (let gy = cy - 1; gy <= cy + 1; gy++) {
          const bucket = grid.get(cellKey(gx, gy));
          if (!bucket) {
            continue;
          }
          for (const j of bucket) {
            if (j <= i) {
              continue;
            }
            const dx = X[i] - X[j];
            const dy = Y[i] - Y[j];
            const d = Math.sqrt(dx * dx + dy * dy) || 0.1;
            const minDist = R[i] + R[j] + COLLIDE_GAP;
            if (d < minDist) {
              const f = (minDist - d) * 0.6;
              vx[i] += (dx / d) * f;
              vy[i] += (dy / d) * f;
              vx[j] -= (dx / d) * f;
              vy[j] -= (dy / d) * f;
            }
          }
        }
      }
    }

    for (let l = 0; l < linkA.length; l++) {
      const a = linkA[l];
      const b = linkB[l];
      const dx = X[b] - X[a];
      const dy = Y[b] - Y[a];
      const d = Math.sqrt(dx * dx + dy * dy) || 1;
      const f = (d - LINK_LENGTH) * LINK_PULL;
      vx[a] += (dx / d) * f;
      vy[a] += (dy / d) * f;
      vx[b] -= (dx / d) * f;
      vy[b] -= (dy / d) * f;
    }

    for (let i = 0; i < count; i++) {
      let dx = (vx[i] - X[i] * GRAVITY) * alpha;
      let dy = (vy[i] - Y[i] * GRAVITY) * alpha;
      const m = Math.hypot(dx, dy);
      if (m > MAX_STEP) {
        dx = (dx / m) * MAX_STEP;
        dy = (dy / m) * MAX_STEP;
      }
      X[i] += dx;
      Y[i] += dy;
    }
    alpha -= alpha * decay;
    round++;
  };

  const step = (budgetMs: number) => {
    const end = Date.now() + budgetMs;
    while (round < rounds) {
      tick();
      if (Date.now() >= end) {
        break;
      }
    }
    if (round < rounds) {
      return false;
    }
    nodes.forEach((n, i) => {
      n.x = X[i];
      n.y = Y[i];
    });
    return true;
  };

  return {layout, step: count ? step : () => true};
}

const cellKey = (x: number, y: number) => (x + 32768) * 65536 + (y + 32768);

/** A Barnes-Hut quadtree rebuilt every round, kept in flat arrays to spare the allocator. */
class QuadTree {
  private cap: number;
  private x0: Float64Array;
  private y0: Float64Array;
  private size: Float64Array;
  private mass: Float64Array;
  private mx: Float64Array;
  private my: Float64Array;
  private child: Int32Array;
  /** The one body in a leaf; -1 for an empty or split cell. */
  private body: Int32Array;
  private used = 0;
  private stack: Int32Array;

  constructor(count: number) {
    this.cap = Math.max(16, count * 4 + 16);
    this.x0 = new Float64Array(this.cap);
    this.y0 = new Float64Array(this.cap);
    this.size = new Float64Array(this.cap);
    this.mass = new Float64Array(this.cap);
    this.mx = new Float64Array(this.cap);
    this.my = new Float64Array(this.cap);
    this.child = new Int32Array(this.cap * 4);
    this.body = new Int32Array(this.cap);
    this.stack = new Int32Array(this.cap);
  }

  private grow() {
    const cap = this.cap * 2;
    const more = <T extends Float64Array | Int32Array>(a: T, n: number): T => {
      const b = new (a.constructor as {new (n: number): T})(n);
      b.set(a);
      return b;
    };
    this.x0 = more(this.x0, cap);
    this.y0 = more(this.y0, cap);
    this.size = more(this.size, cap);
    this.mass = more(this.mass, cap);
    this.mx = more(this.mx, cap);
    this.my = more(this.my, cap);
    this.child = more(this.child, cap * 4);
    this.body = more(this.body, cap);
    this.stack = more(this.stack, cap);
    this.cap = cap;
  }

  private cell(x0: number, y0: number, size: number) {
    if (this.used >= this.cap) {
      this.grow();
    }
    const c = this.used++;
    this.x0[c] = x0;
    this.y0[c] = y0;
    this.size[c] = size;
    this.mass[c] = 0;
    this.mx[c] = 0;
    this.my[c] = 0;
    this.body[c] = -1;
    this.child.fill(-1, c * 4, c * 4 + 4);
    return c;
  }

  build(X: Float64Array, Y: Float64Array) {
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (let i = 0; i < X.length; i++) {
      minX = Math.min(minX, X[i]);
      minY = Math.min(minY, Y[i]);
      maxX = Math.max(maxX, X[i]);
      maxY = Math.max(maxY, Y[i]);
    }
    this.used = 0;
    this.cell(minX, minY, Math.max(maxX - minX, maxY - minY, 1) * 1.0001);
    for (let i = 0; i < X.length; i++) {
      this.insert(i, X, Y);
    }
  }

  private insert(i: number, X: Float64Array, Y: Float64Array) {
    const x = X[i];
    const y = Y[i];
    let c = 0;
    for (let depth = 0; ; depth++) {
      this.mass[c] += 1;
      this.mx[c] += x;
      this.my[c] += y;
      const half = this.size[c] / 2;
      const isLeaf = this.child[c * 4] === -1 && this.child[c * 4 + 1] === -1 && this.child[c * 4 + 2] === -1 && this.child[c * 4 + 3] === -1;
      if (isLeaf) {
        if (this.mass[c] === 1) {
          this.body[c] = i;
          return;
        }
        // Bodies on the same spot can never be split; the cell just carries them together.
        if (depth > 40) {
          return;
        }
        const other = this.body[c];
        this.body[c] = -1;
        if (other >= 0) {
          const q = this.quadrant(c, X[other], Y[other], half);
          const k = this.cell(this.x0[c] + (q % 2 ? half : 0), this.y0[c] + (q >= 2 ? half : 0), half);
          this.child[c * 4 + q] = k;
          this.mass[k] = 1;
          this.mx[k] = X[other];
          this.my[k] = Y[other];
          this.body[k] = other;
        }
      }
      const q = this.quadrant(c, x, y, half);
      let next = this.child[c * 4 + q];
      if (next === -1) {
        next = this.cell(this.x0[c] + (q % 2 ? half : 0), this.y0[c] + (q >= 2 ? half : 0), half);
        this.child[c * 4 + q] = next;
      }
      c = next;
    }
  }

  private quadrant(c: number, x: number, y: number, half: number) {
    return (x >= this.x0[c] + half ? 1 : 0) + (y >= this.y0[c] + half ? 2 : 0);
  }

  repel(i: number, X: Float64Array, Y: Float64Array, vx: Float64Array, vy: Float64Array) {
    const x = X[i];
    const y = Y[i];
    let top = 0;
    this.stack[top++] = 0;
    while (top > 0) {
      const c = this.stack[--top];
      const m = this.mass[c];
      if (m === 0 || this.body[c] === i) {
        continue;
      }
      let dx = x - this.mx[c] / m;
      let dy = y - this.my[c] / m;
      let d2 = dx * dx + dy * dy;
      const s = this.size[c];
      const leaf = this.body[c] >= 0;
      if (leaf || (s * s) / d2 < THETA2) {
        if (d2 < 0.01) {
          dx = Math.random() - 0.5;
          dy = Math.random() - 0.5;
          d2 = 0.01;
        }
        const d = Math.sqrt(d2);
        const f = (REPULSION * m) / d2;
        vx[i] += (dx / d) * f;
        vy[i] += (dy / d) * f;
        continue;
      }
      let split = false;
      for (let q = 0; q < 4; q++) {
        const k = this.child[c * 4 + q];
        if (k !== -1) {
          if (top >= this.stack.length) {
            this.stack = growInt(this.stack);
          }
          this.stack[top++] = k;
          split = true;
        }
      }
      // A cell of stacked bodies has no children to open; it pushes as one.
      if (!split && d2 >= 0.01) {
        const d = Math.sqrt(d2);
        const f = (REPULSION * m) / d2;
        vx[i] += (dx / d) * f;
        vy[i] += (dy / d) * f;
      }
    }
  }
}

function growInt(a: Int32Array) {
  const b = new Int32Array(a.length * 2);
  b.set(a);
  return b;
}

/** The whole graph on screen, however small that makes it. */
export function fitView(nodes: LaidNode[], w: number, h: number, maxK = 1.6): GraphView {
  if (!nodes.length) {
    return {k: 1, x: w / 2, y: h / 2};
  }
  const b = bounds(nodes);
  const pad = 36;
  const k = Math.min((w - pad * 2) / Math.max(1, b.maxX - b.minX), (h - pad * 2) / Math.max(1, b.maxY - b.minY), maxK);
  return {k, x: w / 2 - ((b.minX + b.maxX) / 2) * k, y: h / 2 - ((b.minY + b.maxY) / 2) * k};
}

/** Below this the dots and their names get too small to tell apart. */
export const COMFORT_K = 0.7;

/**
 * Where the graph opens: all of it when that still reads well, otherwise its
 * busiest part at a readable size, with the rest a drag or a pinch away.
 */
export function initialView(layout: GraphLayout, w: number, h: number): GraphView {
  const fit = fitView(layout.nodes, w, h);
  if (fit.k >= COMFORT_K || !layout.nodes.length) {
    return fit;
  }
  let hub = layout.nodes[0];
  for (const n of layout.nodes) {
    if (n.degree > hub.degree) {
      hub = n;
    }
  }
  // Halfway between the middle of the graph and its best-linked page, so the view starts where it is busy.
  const b = bounds(layout.nodes);
  const cx = ((b.minX + b.maxX) / 2 + hub.x) / 2;
  const cy = ((b.minY + b.maxY) / 2 + hub.y) / 2;
  return {k: COMFORT_K, x: w / 2 - cx * COMFORT_K, y: h / 2 - cy * COMFORT_K};
}

function bounds(nodes: LaidNode[]) {
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
  return {minX, minY, maxX, maxY};
}

export const LABEL_PX = 11.5;
const LABEL_CHARS = 16;
const MAX_LABELS = 160;

export const labelText = (s: string) => (s.length > LABEL_CHARS ? `${s.slice(0, LABEL_CHARS - 1)}…` : s);

/** Rough on-screen width of a label: CJK glyphs are square, Latin ones about half as wide. */
function labelWidth(s: string, px: number) {
  let w = 0;
  for (const ch of s) {
    w += ch.charCodeAt(0) > 0x2e80 ? px : px * 0.56;
  }
  return w;
}

/**
 * Which names to draw for `view`: the selected page and its neighbours first,
 * then the best-linked pages, each only where it does not run into one already
 * placed. Only what is on screen, or just off it, is considered.
 */
export function placeLabels(
  layout: GraphLayout,
  view: GraphView,
  w: number,
  h: number,
  selected: string | null,
  radiusAt: (n: LaidNode) => number,
): LaidNode[] {
  const marginX = w * 0.5;
  const marginY = h * 0.5;
  const near = selected ? layout.adjacency.get(selected) : undefined;
  const rank = (n: LaidNode) => (n.id === selected ? 2 : near?.has(n.id) ? 1 : 0);
  const candidates: {n: LaidNode; sx: number; sy: number}[] = [];
  for (const n of layout.nodes) {
    const sx = n.x * view.k + view.x;
    const sy = n.y * view.k + view.y;
    if (sx > -marginX && sx < w + marginX && sy > -marginY && sy < h + marginY) {
      candidates.push({n, sx, sy});
    }
  }
  candidates.sort((a, b) => rank(b.n) - rank(a.n) || b.n.degree - a.n.degree || a.n.label.length - b.n.label.length);

  const height = LABEL_PX * 1.35;
  const bucket = 48;
  const taken = new Map<number, {x0: number; y0: number; x1: number; y1: number}[]>();
  const placed: LaidNode[] = [];
  for (const {n, sx, sy} of candidates) {
    if (placed.length >= MAX_LABELS) {
      break;
    }
    const x0 = sx + radiusAt(n) * view.k + 3;
    const box = {x0, y0: sy - height / 2, x1: x0 + labelWidth(labelText(n.label), LABEL_PX), y1: sy + height / 2};
    const keys: number[] = [];
    let clash = false;
    for (let bx = Math.floor(box.x0 / bucket); bx <= Math.floor(box.x1 / bucket) && !clash; bx++) {
      for (let by = Math.floor(box.y0 / bucket); by <= Math.floor(box.y1 / bucket) && !clash; by++) {
        const key = cellKey(bx, by);
        keys.push(key);
        clash = !!taken.get(key)?.some(o => box.x0 < o.x1 && box.x1 > o.x0 && box.y0 < o.y1 && box.y1 > o.y0);
      }
    }
    if (clash && rank(n) < 2) {
      continue;
    }
    keys.forEach(key => (taken.get(key) ?? taken.set(key, []).get(key)!).push(box));
    placed.push(n);
  }
  return placed;
}
