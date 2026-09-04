import type { MeshEdge, MeshNode } from '@/lib/types';

/**
 * The mesh, drawn server-side as SVG.
 *
 * Positions are computed on the server, not in the browser, for three reasons
 * that all matter more than an animation would. The layout is identical on
 * every load, so a colleague sent a link sees the same picture. There is no
 * settling animation, so the box is reserved and CLS stays at zero (13.6). And
 * the graph needs no JavaScript at all, which means it survives a failed bundle.
 *
 * The layout is a circle ordered by domain, so domain clustering is visible
 * without a force simulation: nodes in the same domain are adjacent, an edge
 * inside a domain is a short chord, and an edge across domains crosses the
 * middle. That reads at a glance, which is what a picture is for.
 *
 * Edge opacity encodes strength and stroke width encodes confidence — the same
 * two numbers the table's two numeric columns carry, so the graph and the table
 * teach one vocabulary rather than two.
 *
 * Geometry comes from the API's layout hints, which come from the mesh rubric.
 * A component that chose its own would draw something other than what the
 * server described.
 */

// A full turn, without writing the number two.
const TURN = Math.PI + Math.PI;

export interface SvgLayout {
  viewbox: number;
  centre: number;
  radius: number;
  node_radius: number;
  label_offset: number;
  min_edge_opacity: number;
  max_edge_width: number;
  start_angle_turns: number;
}

function ordered(nodes: MeshNode[]): MeshNode[] {
  return [...nodes].sort((a, b) =>
    a.domain === b.domain ? a.id.localeCompare(b.id) : a.domain.localeCompare(b.domain),
  );
}

function positions(
  nodes: MeshNode[],
  layout: SvgLayout,
): Map<string, { x: number; y: number }> {
  const map = new Map<string, { x: number; y: number }>();
  nodes.forEach((node, index) => {
    const angle = (index / nodes.length + layout.start_angle_turns) * TURN;
    map.set(node.id, {
      x: layout.centre + layout.radius * Math.cos(angle),
      y: layout.centre + layout.radius * Math.sin(angle),
    });
  });
  return map;
}

export function MeshDiagram({
  nodes,
  edges,
  title,
  layout,
}: {
  nodes: MeshNode[];
  edges: MeshEdge[];
  title: string;
  layout: SvgLayout;
}) {
  const ring = ordered(nodes);
  const at = positions(ring, layout);
  const degree = new Map<string, number>();
  for (const edge of edges) {
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
  }

  return (
    <figure className="mesh-figure">
      <svg
        viewBox={`0 0 ${layout.viewbox} ${layout.viewbox}`}
        role="img"
        aria-label={`${title}. ${nodes.length} nodes, ${edges.length} edges. The table below carries the same information.`}
        className="mesh-svg"
      >
        <g>
          {edges.map((edge) => {
            const from = at.get(edge.source);
            const to = at.get(edge.target);
            if (!from || !to) return null;
            return (
              <line
                key={edge.edge_id}
                x1={from.x}
                y1={from.y}
                x2={to.x}
                y2={to.y}
                className="mesh-edge"
                style={{
                  opacity: Math.max(edge.strength, layout.min_edge_opacity),
                  strokeWidth: edge.confidence * layout.max_edge_width,
                }}
              >
                <title>{edge.rationale}</title>
              </line>
            );
          })}
        </g>
        <g>
          {ring.map((node) => {
            const point = at.get(node.id);
            if (!point) return null;
            const rightHalf = point.x > layout.centre;
            return (
              <g
                key={node.id}
                className="mesh-node"
                data-connected={(degree.get(node.id) ?? 0) > 0}
              >
                <circle cx={point.x} cy={point.y} r={layout.node_radius} />
                <text
                  x={point.x}
                  y={point.y}
                  dx={rightHalf ? layout.label_offset : -layout.label_offset}
                  dy={layout.node_radius}
                  textAnchor={rightHalf ? 'start' : 'end'}
                >
                  {node.id}
                </text>
                <title>
                  {node.name} — {node.domain.replace(/_/g, ' ')}
                </title>
              </g>
            );
          })}
        </g>
      </svg>
      <figcaption className="mesh-caption">
        Nodes are ordered around the circle by domain, so a short chord is a link within
        a domain and a line through the middle crosses one. Line opacity is edge
        strength; line weight is confidence.
      </figcaption>
    </figure>
  );
}
