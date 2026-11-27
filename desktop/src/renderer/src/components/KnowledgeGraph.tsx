import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Loader2 } from 'lucide-react'
import type { KnowledgeGraph as KnowledgeGraphData } from '../types'

interface SimNode {
  id: string
  label: string
  category: string
  x: number
  y: number
  vx: number
  vy: number
  fx: number | null
  fy: number | null
  degree: number
}

interface KnowledgeGraphProps {
  data: KnowledgeGraphData
  onSelect: (id: string, label: string) => void
}

// d3.schemeTableau10 — keep the web client's palette for visual parity.
const TABLEAU10 = [
  '#4e79a7',
  '#f28e2c',
  '#e15759',
  '#76b7b2',
  '#59a14f',
  '#edc949',
  '#af7aa1',
  '#ff9da7',
  '#9c755f',
  '#bab0ab',
]

const nodeRadius = (degree: number) => Math.max(4, Math.min(12, 4 + degree * 1.4))

// Labels keep this on-screen size whatever the zoom.
const LABEL_FONT = 11
const LABEL_HEIGHT = 14
const LABEL_CELL = 40
const labelText = (label: string) => (label.length > 15 ? label.slice(0, 14) + '…' : label)
const labelWidth = (label: string) =>
  Array.from(labelText(label)).reduce((w, ch) => w + (ch.charCodeAt(0) > 255 ? LABEL_FONT : LABEL_FONT * 0.6), 0)

const ALPHA_MIN = 0.005
// Heat kept in the layout while a node is dragged: enough to pull its
// neighbours along without setting the whole settled graph in motion.
const DRAG_ALPHA = 0.1

type SimLink = { key: number; a: SimNode; b: SimNode }

// One step of the force layout around the origin, scaled by alpha.
function stepLayout(nodes: SimNode[], links: SimLink[], alpha: number) {
  const repulsion = 9000
  const springLen = 80
  const spring = 0.04
  const centering = 0.012

  // Reset accumulated velocity each tick (alpha-scaled displacement) so the
  // system can't accumulate energy and oscillate.
  nodes.forEach((node) => {
    node.vx = 0
    node.vy = 0
  })

  // Repulsion + collision: nodes push apart, never overlap their radii.
  for (let i = 0; i < nodes.length; i++) {
    const a = nodes[i]
    const ra = nodeRadius(a.degree)
    for (let j = i + 1; j < nodes.length; j++) {
      const b = nodes[j]
      let dx = a.x - b.x
      let dy = a.y - b.y
      let d2 = dx * dx + dy * dy
      if (d2 < 0.01) {
        dx = Math.random() - 0.5
        dy = Math.random() - 0.5
        d2 = 0.01
      }
      const d = Math.sqrt(d2)
      let f = repulsion / d2
      // Hard collision: strongly separate if closer than combined radii.
      const minDist = ra + nodeRadius(b.degree) + 14
      if (d < minDist) f += (minDist - d) * 0.6
      a.vx += (dx / d) * f
      a.vy += (dy / d) * f
      b.vx -= (dx / d) * f
      b.vy -= (dy / d) * f
    }
  }
  links.forEach(({ a, b }) => {
    const dx = b.x - a.x
    const dy = b.y - a.y
    const d = Math.sqrt(dx * dx + dy * dy) || 1
    const f = (d - springLen) * spring
    a.vx += (dx / d) * f
    a.vy += (dy / d) * f
    b.vx -= (dx / d) * f
    b.vy -= (dy / d) * f
  })
  // Weak centering so the graph holds together without collapsing.
  nodes.forEach((node) => {
    node.vx -= node.x * centering
    node.vy -= node.y * centering
  })

  // Apply alpha-scaled displacement; pinned nodes stay put. Cap per-tick
  // movement so strong initial forces don't fling nodes off-screen.
  const maxStep = 30
  nodes.forEach((node) => {
    if (node.fx != null) {
      node.x = node.fx
      node.y = node.fy as number
      return
    }
    let dx = node.vx * alpha
    let dy = node.vy * alpha
    const m = Math.hypot(dx, dy)
    if (m > maxStep) {
      dx = (dx / m) * maxStep
      dy = (dy / m) * maxStep
    }
    node.x += dx
    node.y += dy
  })
}

// A dependency-free force-directed graph with wheel zoom, canvas pan and node
// drag. The layout is settled before anything is shown and fitted once, so the
// view never swells and shrinks while it cools. Interaction writes positions
// DIRECTLY to the DOM (like d3) instead of calling setState per frame, so React
// never re-renders while nodes move.
const KnowledgeGraph: React.FC<KnowledgeGraphProps> = ({ data, onSelect }) => {
  const wrapRef = useRef<HTMLDivElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const sizeRef = useRef({ w: 800, h: 560 })
  const [hover, setHover] = useState<string | null>(null)
  const [ready, setReady] = useState(false)

  // View transform (pan + zoom).
  const viewRef = useRef({ k: 1, x: 0, y: 0 })
  // The view refits on resize until the user zooms, pans or drags a node;
  // after that it stays where they put it.
  const autoFitRef = useRef(true)

  // Build the immutable model once per data change.
  const model = useMemo(() => {
    const degree = new Map<string, number>()
    data.links.forEach((l) => {
      degree.set(l.source, (degree.get(l.source) || 0) + 1)
      degree.set(l.target, (degree.get(l.target) || 0) + 1)
    })
    // Order categories by node count so the dominant cluster gets the most
    // salient palette entry instead of whichever colour insertion order landed
    // on. Ties break by name to keep the mapping stable across reloads.
    const catCount = new Map<string, number>()
    data.nodes.forEach((n) => {
      const c = n.category || 'default'
      catCount.set(c, (catCount.get(c) || 0) + 1)
    })
    const categories = Array.from(catCount.keys()).sort(
      (a, b) => catCount.get(b)! - catCount.get(a)! || a.localeCompare(b)
    )
    const colorOf = (cat: string) => TABLEAU10[categories.indexOf(cat) % TABLEAU10.length]

    // Positions are seeded once the pane has been measured (see below).
    const nodes: SimNode[] = data.nodes.map((nd) => {
      return {
        id: nd.id,
        label: nd.label,
        category: nd.category || 'default',
        x: 0,
        y: 0,
        vx: 0,
        vy: 0,
        fx: null,
        fy: null,
        degree: degree.get(nd.id) || 0,
      }
    })
    const valid = new Set(nodes.map((x) => x.id))
    const byId = new Map(nodes.map((x) => [x.id, x]))
    const links = data.links
      .filter((l) => valid.has(l.source) && valid.has(l.target))
      .map((l, i) => ({ key: i, a: byId.get(l.source)!, b: byId.get(l.target)! }))
    const adjacency = new Map<string, Set<string>>()
    data.links.forEach((l) => {
      if (!valid.has(l.source) || !valid.has(l.target)) return
      if (!adjacency.has(l.source)) adjacency.set(l.source, new Set())
      if (!adjacency.has(l.target)) adjacency.set(l.target, new Set())
      adjacency.get(l.source)!.add(l.target)
      adjacency.get(l.target)!.add(l.source)
    })
    // Better-connected pages claim label space first.
    const labelOrder = [...nodes].sort((a, b) => b.degree - a.degree)
    const labelWidths = new Map(nodes.map((x) => [x.id, labelWidth(x.label)]))
    return { nodes, links, adjacency, categories, colorOf, byId, labelOrder, labelWidths }
  }, [data])

  // DOM refs for imperative position updates.
  const rootRef = useRef<SVGGElement>(null)
  const lineEls = useRef(new Map<number, SVGLineElement>())
  const groupEls = useRef(new Map<string, SVGGElement>())
  const textEls = useRef(new Map<string, SVGTextElement>())

  const paint = () => {
    model.links.forEach(({ key, a, b }) => {
      const el = lineEls.current.get(key)
      if (!el) return
      el.setAttribute('x1', String(a.x))
      el.setAttribute('y1', String(a.y))
      el.setAttribute('x2', String(b.x))
      el.setAttribute('y2', String(b.y))
    })
    model.nodes.forEach((node) => {
      const el = groupEls.current.get(node.id)
      if (el) el.setAttribute('transform', `translate(${node.x},${node.y})`)
    })
  }

  // Only labels that fit are shown: a label blocked on the right of its node
  // tries the left, and one blocked on both sides waits until zooming in makes
  // room. Sparse outer pages stay labelled while the dense core thins out.
  const shownLabelsRef = useRef(new Map<string, 'right' | 'left'>())
  const labelSides = useRef(new WeakMap<SVGTextElement, 'right' | 'left' | null>())
  const labelFrameRef = useRef(0)
  const hoverRef = useRef<string | null>(null)

  // Touch only the labels whose visibility or side changed; zooming re-places
  // labels every frame.
  const showLabels = () => {
    const shown = shownLabelsRef.current
    const hovered = hoverRef.current
    const near = hovered ? model.adjacency.get(hovered) : undefined
    model.nodes.forEach((node) => {
      const el = textEls.current.get(node.id)
      if (!el) return
      const visible = shown.has(node.id) || node.id === hovered || !!near?.has(node.id)
      const side = visible ? shown.get(node.id) || 'right' : null
      if (labelSides.current.get(el) === side) return
      labelSides.current.set(el, side)
      if (!side) {
        el.setAttribute('display', 'none')
        return
      }
      el.removeAttribute('display')
      const gap = nodeRadius(node.degree) + 3
      el.setAttribute('x', String(side === 'left' ? -gap : gap))
      el.setAttribute('text-anchor', side === 'left' ? 'end' : 'start')
    })
  }

  const placeLabels = () => {
    labelFrameRef.current = 0
    const k = viewRef.current.k
    const grid = new Map<string, number[][]>()
    const cells = (x: number, y: number, w: number, fn: (key: string) => boolean) => {
      for (let cx = Math.floor(x / LABEL_CELL); cx <= Math.floor((x + w) / LABEL_CELL); cx++) {
        for (let cy = Math.floor(y / LABEL_CELL); cy <= Math.floor((y + LABEL_HEIGHT) / LABEL_CELL); cy++) {
          if (fn(`${cx},${cy}`)) return true
        }
      }
      return false
    }
    const fits = (x: number, y: number, w: number) =>
      !cells(x, y, w, (key) =>
        (grid.get(key) || []).some(
          (b) => x < b[0] + b[2] && b[0] < x + w && y < b[1] + LABEL_HEIGHT && b[1] < y + LABEL_HEIGHT,
        ),
      )
    const shown = new Map<string, 'right' | 'left'>()
    model.labelOrder.forEach((node) => {
      const gap = (nodeRadius(node.degree) + 3) * k
      const y = node.y * k - LABEL_HEIGHT / 2
      const w = model.labelWidths.get(node.id) || 0
      let x = node.x * k + gap
      let side: 'right' | 'left' = 'right'
      if (!fits(x, y, w)) {
        x = node.x * k - gap - w
        side = 'left'
        if (!fits(x, y, w)) return
      }
      const box = [x, y, w]
      cells(x, y, w, (key) => {
        if (!grid.has(key)) grid.set(key, [])
        grid.get(key)!.push(box)
        return false
      })
      shown.set(node.id, side)
    })
    shownLabelsRef.current = shown
    showLabels()
  }
  const placeLabelsRef = useRef(placeLabels)
  placeLabelsRef.current = placeLabels
  const scheduleLabels = () => {
    if (!labelFrameRef.current) labelFrameRef.current = requestAnimationFrame(() => placeLabelsRef.current())
  }
  useEffect(() => () => cancelAnimationFrame(labelFrameRef.current), [])

  // Apply the view transform imperatively (no re-render needed). Label text is
  // sized on the zoomed group, divided by the scale, so it reads the same at
  // any zoom.
  const applyView = () => {
    const v = viewRef.current
    if (!rootRef.current) return
    rootRef.current.setAttribute('transform', `translate(${v.x},${v.y}) scale(${v.k})`)
    rootRef.current.setAttribute('font-size', String(LABEL_FONT / v.k))
    scheduleLabels()
  }

  // Centre the settled graph. The scale is clamped so nodes and labels stay
  // readable: a large graph may run past the pane edges and is explored by
  // dragging and zooming instead.
  const fitView = () => {
    const { nodes } = model
    if (nodes.length === 0) return
    let minX = Infinity
    let minY = Infinity
    let maxX = -Infinity
    let maxY = -Infinity
    nodes.forEach((node) => {
      const r = nodeRadius(node.degree)
      minX = Math.min(minX, node.x - r)
      minY = Math.min(minY, node.y - r)
      maxX = Math.max(maxX, node.x + r)
      maxY = Math.max(maxY, node.y + r)
    })
    const { w, h } = sizeRef.current
    const pad = 40
    const fit = Math.min((w - pad * 2) / Math.max(1, maxX - minX), (h - pad * 2) / Math.max(1, maxY - minY))
    const k = Math.max(0.75, Math.min(1.3, fit))
    viewRef.current = { k, x: w / 2 - ((minX + maxX) / 2) * k, y: h / 2 - ((minY + maxY) / 2) * k }
    applyView()
  }
  // The resize observer is bound once; it reaches the current model through this.
  const fitViewRef = useRef(fitView)
  fitViewRef.current = fitView
  const readyRef = useRef(false)

  // Track container size in a ref; never triggers a re-render on its own.
  useLayoutEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const apply = () => {
      sizeRef.current = { w: el.clientWidth || 800, h: el.clientHeight || 560 }
      if (autoFitRef.current && readyRef.current) fitViewRef.current()
    }
    apply()
    const ro = new ResizeObserver(apply)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // Settle the layout off-screen in slices of about a frame, then paint and fit
  // it once. Seeds follow a sunflower spiral, which spreads evenly and cools
  // faster than a ring.
  useLayoutEffect(() => {
    const { nodes, links } = model
    readyRef.current = false
    setReady(false)
    nodes.forEach((node, i) => {
      const radius = 10 * Math.sqrt(i + 0.5)
      const angle = i * Math.PI * (3 - Math.sqrt(5))
      node.x = Math.cos(angle) * radius
      node.y = Math.sin(angle) * radius
    })
    let alive = true
    // Repulsion is quadratic, so large graphs get fewer, still-converging ticks.
    const ticks = Math.max(80, Math.min(300, Math.round(4e7 / Math.max(1, nodes.length * nodes.length))))
    const decay = 1 - Math.pow(ALPHA_MIN, 1 / ticks)
    let alpha = 1
    let done = 0
    const run = () => {
      if (!alive) return
      const start = performance.now()
      while (done < ticks && performance.now() - start < 16) {
        stepLayout(nodes, links, alpha)
        alpha -= alpha * decay
        done++
      }
      if (done < ticks) {
        setTimeout(run, 0)
        return
      }
      paint()
      autoFitRef.current = true
      readyRef.current = true
      fitViewRef.current()
      placeLabelsRef.current()
      setReady(true)
    }
    run()
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model])

  // Interaction loop: dragging keeps the layout gently warm, and it cools and
  // stops on release.
  const alphaRef = useRef(0)
  const rafRef = useRef(0)
  useEffect(() => {
    alphaRef.current = 0
    return () => {
      cancelAnimationFrame(rafRef.current)
      rafRef.current = 0
    }
  }, [model])
  const kick = () => {
    alphaRef.current = Math.max(alphaRef.current, DRAG_ALPHA)
    if (rafRef.current) return
    const frame = () => {
      const dragging = model.nodes.some((node) => node.fx != null)
      stepLayout(model.nodes, model.links, alphaRef.current)
      paint()
      scheduleLabels()
      alphaRef.current += ((dragging ? DRAG_ALPHA : 0) - alphaRef.current) * 0.05
      rafRef.current = alphaRef.current > ALPHA_MIN || dragging ? requestAnimationFrame(frame) : 0
    }
    rafRef.current = requestAnimationFrame(frame)
  }

  useEffect(applyView)

  useEffect(() => {
    hoverRef.current = hover
    showLabels()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hover, model])

  // Convert a pointer event to graph (pre-transform) coordinates.
  const toGraph = (clientX: number, clientY: number) => {
    const rect = svgRef.current!.getBoundingClientRect()
    const v = viewRef.current
    return { x: (clientX - rect.left - v.x) / v.k, y: (clientY - rect.top - v.y) / v.k }
  }

  // Wheel zoom centered on the cursor (matches d3.zoom scaleExtent [0.2, 5]).
  // React attaches `wheel` passively at the root, where preventDefault is a
  // no-op that only logs a warning — bind natively with `passive: false` so the
  // page does not scroll while zooming.
  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      autoFitRef.current = false
      const v = viewRef.current
      const rect = svg.getBoundingClientRect()
      const px = e.clientX - rect.left
      const py = e.clientY - rect.top
      const factor = Math.exp(-e.deltaY * 0.0015)
      const k = Math.min(5, Math.max(0.2, v.k * factor))
      viewRef.current = { k, x: px - ((px - v.x) / v.k) * k, y: py - ((py - v.y) / v.k) * k }
      applyView()
    }
    svg.addEventListener('wheel', onWheel, { passive: false })
    return () => svg.removeEventListener('wheel', onWheel)
  }, [])

  // Drag: on a node moves the node, on background pans the canvas.
  const dragRef = useRef<
    | { mode: 'node'; node: SimNode; moved: boolean }
    | { mode: 'pan'; startX: number; startY: number; ox: number; oy: number }
    | null
  >(null)
  const onPointerDownNode = (e: React.PointerEvent, node: SimNode) => {
    e.stopPropagation()
    ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
    autoFitRef.current = false
    const p = toGraph(e.clientX, e.clientY)
    node.fx = p.x
    node.fy = p.y
    dragRef.current = { mode: 'node', node, moved: false }
    kick()
  }

  const onPointerDownBg = (e: React.PointerEvent) => {
    ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
    const v = viewRef.current
    dragRef.current = { mode: 'pan', startX: e.clientX, startY: e.clientY, ox: v.x, oy: v.y }
  }

  const onPointerMove = (e: React.PointerEvent) => {
    const drag = dragRef.current
    if (!drag) return
    if (drag.mode === 'node') {
      const p = toGraph(e.clientX, e.clientY)
      drag.node.fx = p.x
      drag.node.fy = p.y
      drag.moved = true
      // Keep the loop warm for live dragging.
      const el = groupEls.current.get(drag.node.id)
      if (el) el.setAttribute('transform', `translate(${p.x},${p.y})`)
    } else {
      autoFitRef.current = false
      viewRef.current = { k: viewRef.current.k, x: drag.ox + (e.clientX - drag.startX), y: drag.oy + (e.clientY - drag.startY) }
      applyView()
    }
  }

  const onPointerUp = (e: React.PointerEvent, node?: SimNode) => {
    const drag = dragRef.current
    if (drag?.mode === 'node') {
      drag.node.fx = null
      drag.node.fy = null
      if (node && !drag.moved) onSelect(node.id, node.label)
      kick()
    }
    dragRef.current = null
    try {
      ;(e.target as Element).releasePointerCapture(e.pointerId)
    } catch {
      /* noop */
    }
  }

  const { nodes, links, adjacency, categories, colorOf } = model
  const isDimmed = (id: string) => hover != null && hover !== id && !adjacency.get(hover)?.has(id)
  const isLinkActive = (aId: string, bId: string) => hover === aId || hover === bId

  return (
    <div ref={wrapRef} className="w-full h-full relative overflow-hidden">
      {/* Sized by CSS, not by sizeRef: the ref changes without a re-render, so
          fixed attributes would keep the mount-time size and clip the graph
          after the pane grows (e.g. the window is maximized). */}
      <svg
        ref={svgRef}
        className="select-none block w-full h-full cursor-grab active:cursor-grabbing"
        onPointerDown={onPointerDownBg}
        onPointerMove={onPointerMove}
        onPointerUp={(e) => onPointerUp(e)}
      >
        <g ref={rootRef} visibility={ready ? undefined : 'hidden'}>
          {links.map(({ key, a, b }) => {
            const active = isLinkActive(a.id, b.id)
            return (
              <line
                key={key}
                ref={(el) => {
                  if (el) lineEls.current.set(key, el)
                  else lineEls.current.delete(key)
                }}
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke="#94a3b8"
                strokeOpacity={hover ? (active ? 0.8 : 0.1) : 0.3}
                strokeWidth={1}
              />
            )
          })}
          {nodes.map((n) => {
            const r = nodeRadius(n.degree)
            const dim = isDimmed(n.id)
            return (
              <g
                key={n.id}
                ref={(el) => {
                  if (el) groupEls.current.set(n.id, el)
                  else groupEls.current.delete(n.id)
                }}
                transform={`translate(${n.x},${n.y})`}
                className="cursor-pointer"
                opacity={dim ? 0.2 : 1}
                onMouseEnter={() => setHover(n.id)}
                onMouseLeave={() => setHover(null)}
                onPointerDown={(e) => onPointerDownNode(e, n)}
                onPointerUp={(e) => onPointerUp(e, n)}
              >
                <circle r={r} fill={colorOf(n.category)} stroke="#fff" strokeWidth={1.5} />
                {/* Position, side and visibility are set by placeLabels. */}
                <text
                  ref={(el) => {
                    if (el) textEls.current.set(n.id, el)
                    else textEls.current.delete(n.id)
                  }}
                  dy="0.35em"
                  className="fill-content-secondary"
                  style={{ pointerEvents: 'none' }}
                >
                  {labelText(n.label)}
                </text>
              </g>
            )
          })}
        </g>
      </svg>

      {!ready && (
        <div className="absolute inset-0 flex items-center justify-center text-content-tertiary pointer-events-none">
          <Loader2 size={18} className="animate-spin" />
        </div>
      )}

      {/* Category legend, mirrors the web client. */}
      {categories.length > 0 && (
        <div className="absolute bottom-3 left-3 flex flex-wrap gap-x-3 gap-y-1 max-w-[60%] rounded-lg bg-surface px-3 py-2 border border-subtle shadow-sm">
          {categories.map((cat) => (
            <span key={cat} className="inline-flex items-center gap-1.5 text-[11px] text-content-secondary">
              <span className="w-2.5 h-2.5 rounded-full" style={{ background: colorOf(cat) }} />
              {cat}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

export default KnowledgeGraph
