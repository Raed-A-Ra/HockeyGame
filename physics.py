"""
physics.py — CV Air Hockey
===========================
Pure physics and collision resolution.  NO rendering code lives here.

Functions
---------
check_paddle_puck(paddle, puck) → bool
    Circle-circle overlap test between a paddle and the puck.
    If overlapping: separates them and applies the hit force.
    Returns True if a collision occurred (caller can trigger sound/particles).

Design notes
------------
Both paddles (player and AI) are circles with radius PADDLE_R.
The puck is also a circle with radius PUCK_R.
Two circles overlap when:
    distance_between_centres < PADDLE_R + PUCK_R

On collision we do two things:
  1. Positional correction — push the puck out so the circles no longer overlap.
     Without this the puck can get stuck inside the paddle and vibrate or tunnel.
  2. Velocity response — reflect the puck's velocity around the collision normal
     and add the paddle's own velocity (fast swing = harder hit).
     The actual reflection formula lives in puck.apply_hit().
"""

import math

from config import PADDLE_R, PUCK_R


def check_paddle_puck(paddle, puck):
    """
    Test whether `paddle` overlaps `puck` and, if so, resolve the collision.

    Works for BOTH PlayerPaddle and AIPaddle — they are both circular objects
    with PADDLE_R radius, so the same maths applies to both.

    Parameters
    ----------
    paddle : PlayerPaddle | AIPaddle
        Must expose .x, .y  (position) and .vx, .vy (velocity this frame).
    puck : Puck
        Must expose .x, .y, .vx, .vy and an apply_hit() method.

    Returns
    -------
    bool
        True  — a collision was detected and resolved.
                 Caller should trigger a sound effect and particle burst.
        False — no overlap; nothing was changed.
    """

    # Vector from paddle centre → puck centre
    dx   = puck.x - paddle.x
    dy   = puck.y - paddle.y
    dist = math.hypot(dx, dy)   # Euclidean distance between the two centres

    # Collision: the circles overlap when centre-distance < sum of radii
    if dist < PADDLE_R + PUCK_R:

        # Safety guard: if both centres are exactly coincident (dist = 0),
        # the normalisation below would divide by zero.  Give it a safe default.
        if dist == 0:
            dx, dy, dist = 1, 0, 1

        # ── Step 1: Positional correction (separate the circles) ──────────────
        # Calculate overlap depth, then push the puck outward along the collision
        # normal by exactly that amount so it's just touching (no longer inside).
        overlap = (PADDLE_R + PUCK_R) - dist
        puck.x += (dx / dist) * overlap
        puck.y += (dy / dist) * overlap

        # ── Step 2: Velocity response ─────────────────────────────────────────
        # Delegate the reflection maths to puck.apply_hit().
        # This keeps all puck velocity logic in one place (game_objects.py).
        # The paddle's own velocity (vx, vy) is passed so fast swings hit harder.
        puck.apply_hit(paddle.vx, paddle.vy, dx, dy, dist)

        return True   # collision happened — caller should play sound + burst particles

    return False   # no overlap this frame