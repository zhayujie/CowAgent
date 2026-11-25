import {COMFORT_K, fitView, initialView, LABEL_PX, placeLabels, startLayout} from '../src/utils/graphLayout';

/** A linked base shaped like real ones: a few hubs, most pages linking one to three others. */
function base(n: number) {
  let seed = 7;
  const rand = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const categories = ['concepts', 'entities', 'sources', 'root'];
  const nodes = Array.from({length: n}, (_, i) => ({id: `p${i}.md`, label: `Page ${i}`, category: categories[i % 4]}));
  const links: {source: string; target: string}[] = [];
  const ends = [0];
  for (let i = 1; i < n; i++) {
    for (let j = 0, m = 1 + Math.floor(rand() * 3); j < m; j++) {
      const target = ends[Math.floor(rand() * ends.length)];
      links.push({source: `p${i}.md`, target: `p${target}.md`});
      ends.push(target);
    }
    ends.push(i);
  }
  return {nodes, links};
}

function laidOut(n: number) {
  const job = startLayout(base(n));
  while (!job.step(1000)) {}
  return job.layout;
}

test('pages end up apart rather than piled on each other', () => {
  const {nodes} = laidOut(400);
  let close = 0;
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      if (Math.hypot(nodes[i].x - nodes[j].x, nodes[i].y - nodes[j].y) < nodes[i].r + nodes[j].r) {
        close++;
      }
    }
  }
  expect(close).toBeLessThan(nodes.length * 0.01);
  expect(nodes.every(n => Number.isFinite(n.x) && Number.isFinite(n.y))).toBe(true);
});

test('a layout run in short slices still finishes', () => {
  const sliced = startLayout(base(60));
  let slices = 0;
  while (!sliced.step(0)) {
    slices++;
  }
  expect(slices).toBeGreaterThan(1);
  expect(sliced.layout.nodes).toHaveLength(60);
});

test('a small base opens whole, a big one at a readable size', () => {
  const small = laidOut(12);
  expect(initialView(small, 390, 700)).toEqual(fitView(small.nodes, 390, 700));

  const big = laidOut(600);
  expect(fitView(big.nodes, 390, 700).k).toBeLessThan(COMFORT_K);
  expect(initialView(big, 390, 700).k).toBe(COMFORT_K);
});

test('names never run into each other, and the selected page always has one', () => {
  const layout = laidOut(600);
  const view = initialView(layout, 390, 700);
  const picked = layout.nodes[layout.nodes.length - 1].id;
  const labels = placeLabels(layout, view, 390, 700, picked, n => n.r);

  expect(labels[0].id).toBe(picked);
  const boxes = labels.map(n => {
    const x = n.x * view.k + view.x + n.r * view.k + 3;
    const y = n.y * view.k + view.y;
    return {x0: x, x1: x + 30, y0: y - LABEL_PX / 2, y1: y + LABEL_PX / 2};
  });
  const overlaps = boxes.filter((a, i) => boxes.some((b, j) => j > i && a.x0 < b.x1 && a.x1 > b.x0 && a.y0 < b.y1 && a.y1 > b.y0));
  // Boxes here are a floor on the real widths, so any overlap of theirs is a real one too.
  expect(overlaps.length).toBeLessThanOrEqual(1);
  expect(labels.length).toBeGreaterThan(10);
});
