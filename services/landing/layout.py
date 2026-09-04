"""Server-side graph layout for the hero constellation (M11.3, section 13.3).

The client must paint a settled graph. A hero that shuffles for two seconds
after load is worse than a static picture: it draws the eye to motion carrying
no information and then stops. So the force simulation runs here, pre-warmed for
the rubric's tick count, and the client receives fixed coordinates it can draw
immediately — then damps a gentle drift on top.

The simulation is the standard three forces — link springs, many-body repulsion
and collision — integrated with velocity decay, which is what ``d3-force`` does.
It is implemented here rather than imported so the coordinates are produced the
way every other number in this system is: parameterised from a rubric, seeded
from the identifiers themselves, and replayable. Two runs over the same estate
give the same picture, so a screenshot in a deck matches the page.

Agent satellites orbit the centroid of the products they consume. An agent on
two products traces an ellipse between them, which is what makes a
multi-product agent legible without a legend.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from services.common.rubrics import Rubric

FULL_TURN = math.tau
UNIT = 1.0
ZERO = 0.0

# The golden angle, which is what makes a phyllotaxis spiral fill a disc evenly
# rather than lining up along spokes. Derived, not chosen.
GOLDEN_ANGLE = FULL_TURN * (UNIT - UNIT / math.pi)

SIMULATION_KEYS = (
    "velocity_decay", "alpha_min", "centre_strength", "link_strength",
    "collide_iterations", "pair_share", "orbit_radius",
)


@dataclass(frozen=True)
class Simulation:
    """Every parameter the pre-warm runs under, resolved from the mesh rubric."""

    ticks: int
    link_distance: float
    charge_strength: float
    collide_radius: float
    extent: float
    velocity_decay: float
    alpha_min: float
    centre_strength: float
    link_strength: float
    collide_iterations: int
    pair_share: float
    orbit_radius: float
    precision: int

    @classmethod
    def from_rubric(cls, rubric: Rubric) -> Simulation:
        simulation = {
            key: float(rubric.number(f"layout.simulation.{key}")) for key in SIMULATION_KEYS
        }
        return cls(
            ticks=int(rubric.number("layout.prewarm_ticks")),
            link_distance=float(rubric.number("layout.link_distance")),
            charge_strength=float(rubric.number("layout.charge_strength")),
            collide_radius=float(rubric.number("layout.collide_radius")),
            extent=float(rubric.number("layout.svg.viewbox")),
            velocity_decay=simulation["velocity_decay"],
            alpha_min=simulation["alpha_min"],
            centre_strength=simulation["centre_strength"],
            link_strength=simulation["link_strength"],
            collide_iterations=int(simulation["collide_iterations"]),
            pair_share=simulation["pair_share"],
            orbit_radius=simulation["orbit_radius"],
            precision=int(rubric.number("presentation.precision")),
        )

    @property
    def centre(self) -> float:
        return self.extent * self.pair_share


def _unit_seed(text: str) -> float:
    """A stable number in [0, 1) derived from an identifier.

    The ceiling comes from the digest's own width rather than a written-down
    modulus, so changing the hash cannot silently change the range.
    """
    raw = hashlib.md5(text.encode("utf-8")).digest()  # noqa: S324 - a seed, not a credential
    ceiling = int.from_bytes(b"\xff" * len(raw), "big") + UNIT
    return int.from_bytes(raw, "big") / ceiling


@dataclass
class _Body:
    node_id: str
    x: float
    y: float
    vx: float = ZERO
    vy: float = ZERO


@dataclass(frozen=True)
class Placement:
    """Where a node settled."""

    node_id: str
    x: float
    y: float

    def document(self, precision: int) -> dict[str, Any]:
        return {"id": self.node_id, "x": round(self.x, precision), "y": round(self.y, precision)}


@dataclass(frozen=True)
class Orbit:
    """An agent's path around the centroid of what it consumes.

    ``radius_x`` and ``radius_y`` differ when the agent reads more than one
    product: the ellipse stretches along the line between the two furthest
    apart, so the shape of the orbit says what the agent spans.

    Speed is a seed in [0, 1) rather than a rate. How fast a satellite may turn
    is a motion decision and lives in the motion tokens; which satellite is at
    which end of that range is a property of the agent, and belongs here. The
    server never states a speed the token layer would then have to agree with.
    """

    agent_id: str
    centre_x: float
    centre_y: float
    radius_x: float
    radius_y: float
    rotation_turns: float
    phase_turns: float
    speed_seed: float
    products: tuple[str, ...]

    def document(self, precision: int) -> dict[str, Any]:
        return {
            "id": self.agent_id,
            "cx": round(self.centre_x, precision),
            "cy": round(self.centre_y, precision),
            "rx": round(self.radius_x, precision),
            "ry": round(self.radius_y, precision),
            "rotation_turns": round(self.rotation_turns, precision),
            "phase_turns": round(self.phase_turns, precision),
            "speed_seed": round(self.speed_seed, precision),
            "products": list(self.products),
        }


def _initial(node_ids: Sequence[str], sim: Simulation) -> list[_Body]:
    """A phyllotaxis spiral, seeded per node.

    d3 starts nodes on a spiral rather than at random because two random nodes
    can land in the same place, where repulsion is undefined. The seed only
    perturbs the spiral, so the arrangement stays deterministic.
    """
    step = sim.extent / (len(node_ids) + UNIT) * sim.pair_share
    bodies: list[_Body] = []
    for index, node_id in enumerate(node_ids):
        angle = (index + _unit_seed(node_id)) * GOLDEN_ANGLE
        radius = step * (index + UNIT)
        bodies.append(
            _Body(
                node_id,
                sim.centre + radius * math.cos(angle),
                sim.centre + radius * math.sin(angle),
            )
        )
    return bodies


def _apply_links(
    bodies: dict[str, _Body], links: Sequence[tuple[str, str, float]],
    sim: Simulation, alpha: float,
) -> None:
    for source, target, strength in links:
        a, b = bodies.get(source), bodies.get(target)
        if a is None or b is None:
            continue
        dx, dy = b.x - a.x, b.y - a.y
        length = math.hypot(dx, dy) or UNIT
        # A stronger edge pulls harder, so how close two products sit is the
        # mesh's own strength and the picture agrees with the table.
        force = (length - sim.link_distance) / length * alpha * sim.link_strength * strength
        share = force * sim.pair_share
        a.vx += dx * share
        a.vy += dy * share
        b.vx -= dx * share
        b.vy -= dy * share


def _apply_charge(bodies: Sequence[_Body], sim: Simulation, alpha: float) -> None:
    """Exact many-body repulsion.

    d3 approximates with a Barnes-Hut quadtree because it runs every frame in a
    browser. This runs once, over at most the featured node cap, so the exact
    calculation is both affordable and easier to be sure of.
    """
    for index, a in enumerate(bodies):
        for b in bodies[index + 1:]:
            dx, dy = b.x - a.x, b.y - a.y
            squared = dx * dx + dy * dy or UNIT
            force = sim.charge_strength * alpha / squared
            fx, fy = dx * force, dy * force
            a.vx += fx
            a.vy += fy
            b.vx -= fx
            b.vy -= fy


def _apply_collision(bodies: Sequence[_Body], sim: Simulation) -> None:
    minimum = sim.collide_radius + sim.collide_radius
    for _ in range(sim.collide_iterations):
        for index, a in enumerate(bodies):
            for b in bodies[index + 1:]:
                dx, dy = b.x - a.x, b.y - a.y
                length = math.hypot(dx, dy) or UNIT
                if length >= minimum:
                    continue
                push = (minimum - length) / length * sim.pair_share
                a.x -= dx * push
                a.y -= dy * push
                b.x += dx * push
                b.y += dy * push


def _apply_centring(bodies: Sequence[_Body], sim: Simulation, alpha: float) -> None:
    for body in bodies:
        body.vx += (sim.centre - body.x) * sim.centre_strength * alpha
        body.vy += (sim.centre - body.y) * sim.centre_strength * alpha


def settle(
    node_ids: Sequence[str],
    edges: Iterable[tuple[str, str, float]],
    sim: Simulation,
) -> list[Placement]:
    """Run the simulation to rest and return fixed coordinates.

    Nodes are sorted before they are placed. Row order is an artefact of a
    query plan, and a hero whose shape depended on it would draw a different
    estate after an index change.
    """
    if not node_ids:
        return []

    bodies = _initial(sorted(set(node_ids)), sim)
    by_id = {body.node_id: body for body in bodies}
    links = [edge for edge in edges if edge[0] in by_id and edge[1] in by_id]

    alpha = UNIT
    decay = UNIT - (sim.alpha_min ** (UNIT / sim.ticks)) if sim.ticks else UNIT
    for _ in range(sim.ticks):
        alpha -= alpha * decay
        _apply_charge(bodies, sim, alpha)
        _apply_links(by_id, links, sim, alpha)
        _apply_centring(bodies, sim, alpha)
        for body in bodies:
            body.vx *= sim.velocity_decay
            body.vy *= sim.velocity_decay
            body.x += body.vx
            body.y += body.vy
        _apply_collision(bodies, sim)

    margin = sim.collide_radius
    for body in bodies:
        body.x = min(max(body.x, margin), sim.extent - margin)
        body.y = min(max(body.y, margin), sim.extent - margin)
    return [Placement(body.node_id, body.x, body.y) for body in bodies]


def orbits(
    consumption: Mapping[str, Sequence[str]],
    placements: Sequence[Placement],
    sim: Simulation,
) -> list[Orbit]:
    """An orbit per agent around the products it actually reads.

    An agent whose products are far apart gets a long ellipse; one reading a
    single product gets a circle around it. Speed and phase are seeded from the
    agent id, so the satellites never march in step and never resynchronise.
    """
    at = {placement.node_id: placement for placement in placements}
    result: list[Orbit] = []

    for agent_id in sorted(consumption):
        points = [at[product] for product in consumption[agent_id] if product in at]
        if not points:
            continue
        centre_x = sum(point.x for point in points) / len(points)
        centre_y = sum(point.y for point in points) / len(points)

        widest, rotation = ZERO, ZERO
        for index, first in enumerate(points):
            for second in points[index + 1:]:
                dx, dy = second.x - first.x, second.y - first.y
                distance = math.hypot(dx, dy)
                if distance > widest:
                    widest, rotation = distance, math.atan2(dy, dx) / FULL_TURN

        seed = _unit_seed(agent_id)
        result.append(
            Orbit(
                agent_id=agent_id,
                centre_x=centre_x,
                centre_y=centre_y,
                radius_x=sim.orbit_radius + widest * sim.pair_share,
                radius_y=sim.orbit_radius,
                rotation_turns=rotation,
                phase_turns=seed,
                speed_seed=_unit_seed(agent_id + agent_id),
                products=tuple(point.node_id for point in points),
            )
        )
    return result
