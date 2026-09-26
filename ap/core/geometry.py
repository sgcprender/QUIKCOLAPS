"""2D plan geometry helpers. Points are (x, y) in metres."""
from __future__ import annotations

import math

TOL = 1e-6


def dist(p, q) -> float:
    return math.hypot(p[0] - q[0], p[1] - q[1])


def point_on_segment(p, a, b, tol: float = TOL) -> bool:
    cross = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
    if abs(cross) > tol * max(1.0, dist(a, b)):
        return False
    return (min(a[0], b[0]) - tol <= p[0] <= max(a[0], b[0]) + tol and
            min(a[1], b[1]) - tol <= p[1] <= max(a[1], b[1]) + tol)


def edges(poly):
    n = len(poly)
    return [(poly[i], poly[(i + 1) % n]) for i in range(n)]


def point_on_boundary(p, poly, tol: float = TOL) -> bool:
    return any(point_on_segment(p, a, b, tol) for a, b in edges(poly))


def point_in_polygon(p, poly) -> bool:
    """Ray casting; boundary points count as inside."""
    if point_on_boundary(p, poly):
        return True
    x, y = p
    inside = False
    for (x1, y1), (x2, y2) in edges(poly):
        if (y1 > y) != (y2 > y):
            xin = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xin:
                inside = not inside
    return inside


def signed_area(poly) -> float:
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in edges(poly))


def area(poly) -> float:
    return abs(signed_area(poly))


def vertex_convexity(poly) -> list[bool]:
    """True where the outline vertex is convex (a building corner), False where
    it is concave (a re-entrant corner)."""
    ccw = signed_area(poly) > 0
    n = len(poly)
    out = []
    for i in range(n):
        a, b, c = poly[i - 1], poly[i], poly[(i + 1) % n]
        cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        out.append(cross > 0 if ccw else cross < 0)
    return out


def bbox_dims(poly) -> tuple[float, float]:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return max(xs) - min(xs), max(ys) - min(ys)


def midpoint(a, b):
    return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)


def is_vertex(p, poly, tol: float = TOL) -> bool:
    return any(dist(p, v) <= tol for v in poly)
