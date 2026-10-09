"""
game_objects.py — CV Air Hockey
================================
All core game objects: Puck, PlayerPaddle, AIPaddle, Particle system,
FloatingText, and SoundEngine.

Each class is self-contained: it owns its state, updates its own physics,
and can draw itself.  The main loop in main.py calls update() then draw()
on each object every frame.

Sound is also here because SoundEngine is tightly coupled to game events
(hits, goals, combos) that happen inside these objects or just after them.

No hand-tracking code lives here.  No field/HUD rendering lives here.
"""

import cv2
import numpy as np
import math
import random
import time

from config import (
    WIN_W, WIN_H,
    PADDLE_R, PUCK_R, WALL_MARGIN, GOAL_W,
    PUCK_SPEED_INIT, PUCK_SPEED_MAX, PUCK_FRICTION, PUCK_SPEED_RAMP,
    AI_SPEED_EASY, AI_SPEED_MED, AI_SPEED_HARD,
    AI_REACTION_EASY, AI_REACTION_MED, AI_REACTION_HARD,
    AI_WOBBLE_EASY, AI_WOBBLE_MED, AI_WOBBLE_HARD,
    C_PUCK, C_PUCK_GLOW, C_PUCK_CORE,
    C_ORANGE, C_ORANGE_BRIGHT,
    C_PADDLE_P, C_PADDLE_AI, C_PADDLE_AI_BRIGHT,
    C_HIT_FLASH, C_WHITE, C_SHADOW,
    C_TEXT_DIM,
)

# ── Optional sound support ─────────────────────────────────────────────────────
# pygame is optional — the game runs silently without it.
# Windows forces stereo even when you request mono, so we always query the real
# channel count and build audio arrays of the correct shape for make_sound().
try:
    import pygame
    pygame.mixer.init(frequency=44100, size=-16, channels=1, buffer=512)
    _MIXER_CHANNELS = pygame.mixer.get_init()[2]   # 1=mono or 2=stereo
    SOUND_AVAILABLE = True
except Exception:
    _MIXER_CHANNELS = 1
    SOUND_AVAILABLE = False


# ══════════════════════════════════════════════════════════════════════════════
#  SOUND ENGINE
# ══════════════════════════════════════════════════════════════════════════════

def _make_beep(freq=440, duration=0.08, volume=0.4, wave="sine"):
    """
    Procedurally synthesise a short beep and return it as a pygame.Sound.

    freq     — pitch in Hz
    duration — length in seconds
    volume   — amplitude 0.0–1.0
    wave     — "sine" (smooth) or "square" (buzzy retro)

    All sounds are generated once at startup so there is zero synthesis cost
    during the 60fps game loop.  Returns None if pygame is unavailable.
    """
    if not SOUND_AVAILABLE:
        return None

    sr = 44100
    t  = np.linspace(0, duration, int(sr * duration), endpoint=False)

    mono = np.sign(np.sin(2 * np.pi * freq * t)) if wave == "square" \
           else np.sin(2 * np.pi * freq * t)

    # Fade-out envelope: prevents the hard-cutoff "pop" artefact
    env  = np.ones_like(t)
    fade = int(sr * 0.03)   # 30 ms fade-out
    if fade > 0:
        env[-fade:] = np.linspace(1, 0, fade)

    mono = (mono * env * volume * 32767).astype(np.int16)

    # pygame needs a 2D (N,2) array for stereo, 1D (N,) for mono
    channels = pygame.mixer.get_init()[2]
    if channels == 2:
        audio = np.ascontiguousarray(np.column_stack((mono, mono)))
    else:
        audio = np.ascontiguousarray(mono)

    return pygame.sndarray.make_sound(audio)


class SoundEngine:
    """
    Holds all game sound effects and a safe play() wrapper.
    When pygame is unavailable every attribute is None and play() is a no-op.
    """
    def __init__(self):
        self.muted = False

        if SOUND_AVAILABLE:
            self.hit   = _make_beep(freq=520,  duration=0.07, volume=0.5)
            self.goal  = _make_beep(freq=880,  duration=0.25, volume=0.6, wave="square")
            self.wall  = _make_beep(freq=300,  duration=0.05, volume=0.3)
            self.combo = _make_beep(freq=1200, duration=0.12, volume=0.5)
            self.end   = _make_beep(freq=200,  duration=0.5,  volume=0.5, wave="square")
        else:
            self.hit = self.goal = self.wall = self.combo = self.end = None

    def play(self, sound):
        """Play `sound` if not muted and the object exists."""
        if not self.muted and sound is not None:
            try:
                sound.play()
            except Exception:
                pass   # audio hardware error — never crash over a missing sound

    def toggle_mute(self):
        """Flip mute state. Called when the player presses M."""
        self.muted = not self.muted


# ══════════════════════════════════════════════════════════════════════════════
#  PARTICLE SYSTEM
# ══════════════════════════════════════════════════════════════════════════════

class Particle:
    """
    One particle dot: flies outward from a spawn point, falls with fake gravity,
    shrinks and fades over its lifetime (0.3–0.7 seconds).

    __slots__ avoids per-instance __dict__ — meaningfully faster when hundreds
    of particles are alive simultaneously during a goal burst.
    """
    __slots__ = ("x", "y", "vx", "vy", "life", "max_life", "color", "size")

    def __init__(self, x, y, color):
        angle = random.uniform(0, 2 * math.pi)   # random direction, full circle
        speed = random.uniform(2, 8)

        self.x  = float(x)
        self.y  = float(y)
        self.vx = math.cos(angle) * speed
        self.vy = math.sin(angle) * speed
        self.life = self.max_life = random.uniform(0.3, 0.7)
        self.color = color          # BGR tuple
        self.size  = random.randint(3, 7)

    def update(self, dt):
        """Move, apply gravity, decelerate horizontally, and age."""
        self.x    += self.vx
        self.y    += self.vy
        self.vy   += 0.15    # fake gravity
        self.life -= dt
        self.vx   *= 0.97    # horizontal drag

    def draw(self, frame):
        """Draw as a shrinking, fading filled circle."""
        if self.life <= 0:
            return
        alpha = self.life / self.max_life
        r = int(self.size * alpha)
        if r < 1:
            return
        col = tuple(int(c * alpha) for c in self.color)
        cv2.circle(frame, (int(self.x), int(self.y)), r, col, -1)


class ParticleSystem:
    """Manages all active particles — spawning and the per-frame update/draw loop."""
    def __init__(self):
        self.particles = []

    def burst(self, x, y, color, count=20):
        """Spawn `count` particles at (x, y)."""
        for _ in range(count):
            self.particles.append(Particle(x, y, color))

    def update_draw(self, frame, dt):
        """Advance all particles, draw survivors, discard dead ones."""
        alive = []
        for p in self.particles:
            p.update(dt)
            if p.life > 0:
                p.draw(frame)
                alive.append(p)
        self.particles = alive


# ══════════════════════════════════════════════════════════════════════════════
#  FLOATING TEXT  ("GOAL!", "x3 COMBO", etc.)
# ══════════════════════════════════════════════════════════════════════════════

class FloatingText:
    """
    Animated text that rises upward and fades over 1–2 seconds.
    Multiple instances coexist — e.g. "GOAL!" and "x3 COMBO" together.
    """
    __slots__ = ("text", "x", "y", "life", "max_life", "color", "scale", "vy")

    def __init__(self, text, x, y, color, scale=1.5, life=1.2):
        self.text     = text
        self.x        = float(x)   # horizontal centre — text drawn centred on x
        self.y        = float(y)   # vertical position, moves upward each frame
        self.color    = color
        self.scale    = scale
        self.life     = life
        self.max_life = life
        self.vy       = -2.0       # initial upward velocity (negative = up in OpenCV)

    def update(self, dt):
        """Rise upward and age. Velocity decelerates so text doesn't fly off screen."""
        self.y    += self.vy
        self.vy   *= 0.96   # decelerate each frame
        self.life -= dt

    def draw(self, frame):
        """Render with drop shadow, scaled and faded by remaining lifetime."""
        if self.life <= 0:
            return
        alpha = min(1.0, self.life / self.max_life * 2)  # reaches 1.0 at 50% life
        col   = tuple(int(c * alpha) for c in self.color)
        font  = cv2.FONT_HERSHEY_DUPLEX
        sz    = self.scale * (0.8 + 0.4 * (self.life / self.max_life))
        thick = max(1, int(sz * 2))
        tw, _ = cv2.getTextSize(self.text, font, sz, thick)[0]
        x = int(self.x - tw / 2)
        y = int(self.y)
        cv2.putText(frame, self.text, (x + 2, y + 2), font, sz, C_SHADOW, thick + 1)  # shadow
        cv2.putText(frame, self.text, (x,     y    ), font, sz, col,      thick)       # text


# ══════════════════════════════════════════════════════════════════════════════
#  PUCK
# ══════════════════════════════════════════════════════════════════════════════

class Puck:
    """
    The orange puck that bounces around the rink.

    Physics overview:
      - Each frame: position += velocity  (simple Euler integration)
      - Wall bounce: flip the relevant velocity component + tiny random nudge
      - Goal detection: checked when the puck hits the top/bottom wall
      - Obstacle bounce: reflect velocity around the bumper's surface normal
      - Paddle hit: see apply_hit() — reflects velocity + adds paddle momentum
      - Speed ramp: base speed floor rises slowly over the 60-second match
      - Trail: last 16 positions stored for the motion-blur smear in draw()
    """

    def __init__(self):
        self.reset()
        self.trail = []   # stores (x, y) tuples for the motion-blur trail

    def reset(self):
        """Place puck at centre and launch upward in a random direction."""
        self.x = float(WIN_W / 2)
        self.y = float(WIN_H / 2)

        # Angle in the upper semicircle (45°–135°) so puck heads toward AI first
        angle = random.uniform(math.pi / 4, 3 * math.pi / 4)
        if random.random() < 0.5:
            angle = math.pi - angle   # mirror left/right for variety

        self.vx = math.cos(angle) * PUCK_SPEED_INIT
        self.vy = -abs(math.sin(angle) * PUCK_SPEED_INIT)   # negative = upward

        self.speed_base = PUCK_SPEED_INIT   # floor speed; ramps over match duration
        self.trail      = []               # clear trail — no ghost after a goal
        self.hit_flash  = 0.0             # countdown for the white hit-flash effect

    def update(self, dt, obstacles, elapsed):
        """
        Advance puck physics by one frame.

        Parameters
        ----------
        dt        — seconds since last frame
        obstacles — list of bumper dicts (empty on Easy, populated on Medium/Hard)
        elapsed   — seconds since match start (to ramp puck speed over time)

        Returns
        -------
        "wall"        — bounced off wall or bumper
        "goal_ai"     — entered the AI's goal → player scores
        "goal_player" — entered the player's goal → AI scores
        None          — nothing notable happened
        """
        # Speed ramp: base speed floor rises slightly each second
        self.speed_base = min(
            PUCK_SPEED_MAX,
            PUCK_SPEED_INIT + elapsed * PUCK_SPEED_RAMP
        )

        # Store position for the motion trail (max 16 entries)
        self.trail.append((int(self.x), int(self.y)))
        if len(self.trail) > 16:
            self.trail.pop(0)

        # Move
        self.x += self.vx
        self.y += self.vy

        # ── Left / right walls ─────────────────────────────────────────────────
        if self.x - PUCK_R < WALL_MARGIN:
            self.x  = WALL_MARGIN + PUCK_R
            self.vx = abs(self.vx) + random.uniform(-0.3, 0.3)
            return "wall"
        if self.x + PUCK_R > WIN_W - WALL_MARGIN:
            self.x  = WIN_W - WALL_MARGIN - PUCK_R
            self.vx = -abs(self.vx) + random.uniform(-0.3, 0.3)
            return "wall"

        # ── Top / bottom walls + goal detection ───────────────────────────────
        goal_x1 = WIN_W // 2 - GOAL_W // 2
        goal_x2 = WIN_W // 2 + GOAL_W // 2

        if self.y - PUCK_R < WALL_MARGIN:
            if goal_x1 < self.x < goal_x2:
                return "goal_ai"   # player scored!
            self.y  = WALL_MARGIN + PUCK_R
            self.vy = abs(self.vy) + random.uniform(-0.3, 0.3)
            return "wall"

        if self.y + PUCK_R > WIN_H - WALL_MARGIN:
            if goal_x1 < self.x < goal_x2:
                return "goal_player"   # AI scored!
            self.y  = WIN_H - WALL_MARGIN - PUCK_R
            self.vy = -abs(self.vy) + random.uniform(-0.3, 0.3)
            return "wall"

        # ── Circular bumper collisions ─────────────────────────────────────────
        for obs in obstacles:
            ox   = obs["cx"] * WIN_W
            oy   = obs["cy"] * WIN_H
            orr  = obs["r"]
            dx   = self.x - ox
            dy   = self.y - oy
            dist = math.hypot(dx, dy)
            if dist < PUCK_R + orr and dist > 0:
                nx, ny  = dx / dist, dy / dist
                overlap = PUCK_R + orr - dist
                self.x += nx * overlap
                self.y += ny * overlap
                dot      = self.vx * nx + self.vy * ny
                self.vx -= 2 * dot * nx
                self.vy -= 2 * dot * ny
                self.vx += random.uniform(-0.5, 0.5)
                self.vy += random.uniform(-0.5, 0.5)
                return "wall"

        # ── Friction ───────────────────────────────────────────────────────────
        self.vx *= PUCK_FRICTION
        self.vy *= PUCK_FRICTION

        # ── Speed clamping ─────────────────────────────────────────────────────
        spd = math.hypot(self.vx, self.vy)
        if spd > PUCK_SPEED_MAX:
            s = PUCK_SPEED_MAX / spd
            self.vx *= s; self.vy *= s
        elif 0 < spd < 3.0:
            s = 3.0 / spd
            self.vx *= s; self.vy *= s

        self.hit_flash = max(0.0, self.hit_flash - dt)
        return None

    def apply_hit(self, paddle_vx, paddle_vy, dx, dy, dist):
        """
        Transfer paddle force to the puck on collision.

        Reflects puck velocity around the collision normal, then adds 60% of
        the paddle's own velocity.  Fast swing → harder hit → more momentum.
        Called by physics.check_paddle_puck() after positional correction.
        """
        if dist == 0:
            dist = 1   # guard against zero-distance edge case

        nx, ny = dx / dist, dy / dist

        dot      = self.vx * nx + self.vy * ny
        self.vx  = self.vx - 2 * dot * nx + paddle_vx * 0.6
        self.vy  = self.vy - 2 * dot * ny + paddle_vy * 0.6

        self.vx += random.uniform(-0.5, 0.5)
        self.vy += random.uniform(-0.5, 0.5)

        spd     = math.hypot(self.vx, self.vy)
        min_spd = max(self.speed_base, 8.0)
        if spd < min_spd:
            s = min_spd / max(spd, 0.1)
            self.vx *= s; self.vy *= s

        self.hit_flash = 0.12   # trigger white flash for ~7 frames

    def draw(self, frame):
        """
        Draw the puck with (back to front):
          1. Motion trail — fading smear of past positions
          2. Speed glow   — soft orange aura when moving fast (>12 px/frame)
          3. Outer ring   — flashes white on hit, orange normally
          4. Main body    — solid orange disc
          5. Inner core   — brighter centre for the "lit from inside" look
          6. Specular dot — small white offset highlight for 3D sphere shading
        """
        spd  = math.hypot(self.vx, self.vy)
        fast = spd > 12.0
        cx   = int(self.x)
        cy   = int(self.y)

        # Motion trail
        n = len(self.trail)
        for i, (tx, ty) in enumerate(self.trail):
            t      = (i + 1) / n if n else 1
            r      = max(2, int(PUCK_R * (0.25 + 0.55 * t)))
            bright = int(245 * t * (1.4 if fast else 1.0))
            green  = int(158 * t * (1.2 if fast else 1.0))
            blue   = int(11  * t)
            col    = (min(blue, 255), min(green, 255), min(bright, 255))
            cv2.circle(frame, (tx, ty), r, col, -1)

        # Speed glow aura
        if fast:
            overlay = frame.copy()
            cv2.circle(overlay, (cx, cy), PUCK_R + 18, C_PUCK_GLOW, -1)
            alpha   = min(0.45, spd / 60.0)
            cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)

        # Outer ring (flashes on hit)
        ring_col = C_HIT_FLASH if self.hit_flash > 0 else C_ORANGE_BRIGHT
        cv2.circle(frame, (cx, cy), PUCK_R + 7, ring_col, 2)

        # Main body
        body_col = C_HIT_FLASH if self.hit_flash > 0 else C_PUCK
        cv2.circle(frame, (cx, cy), PUCK_R, body_col, -1)

        # Inner core
        cv2.circle(frame, (cx, cy), PUCK_R // 2, C_PUCK_CORE, -1)

        # Specular highlight
        hx = int(self.x - PUCK_R * 0.28)
        hy = int(self.y - PUCK_R * 0.28)
        cv2.circle(frame, (hx, hy), max(3, PUCK_R // 4), C_WHITE, -1)


# ══════════════════════════════════════════════════════════════════════════════
#  AI PADDLE
# ══════════════════════════════════════════════════════════════════════════════

class AIPaddle:
    """
    Computer-controlled opponent paddle — lives in the top half of the rink.

    The AI is deliberately imperfect on all levels.  Three parameters control
    how beatable it is:
      speed    — max pixels the paddle can move per frame
      reaction — probability (0–1) the AI acts on any given frame
      wobble   — ± pixel offset randomly added to the target position (bad aim)
    """

    def __init__(self, difficulty="medium"):
        self.x  = float(WIN_W / 2)
        self.y  = float(WIN_H * 0.15)   # starts at 15% down from top
        self.vx = 0.0
        self.vy = 0.0
        self.set_difficulty(difficulty)

    def set_difficulty(self, difficulty):
        """Apply speed, reaction, and wobble for the chosen level. Safe to call mid-game."""
        self.difficulty = difficulty
        if difficulty == "easy":
            self.speed    = AI_SPEED_EASY
            self.reaction = AI_REACTION_EASY
            self.wobble   = AI_WOBBLE_EASY
        elif difficulty == "hard":
            self.speed    = AI_SPEED_HARD
            self.reaction = AI_REACTION_HARD
            self.wobble   = AI_WOBBLE_HARD
        else:
            self.speed    = AI_SPEED_MED
            self.reaction = AI_REACTION_MED
            self.wobble   = AI_WOBBLE_MED

    def update(self, puck, dt):
        """Decide where to move and step toward that position."""
        # If puck is deep in player's half and moving away, drift to centre defensively
        if puck.y > WIN_H * 0.55 and puck.vy >= 0:
            tx, ty = WIN_W / 2, WIN_H * 0.15
        else:
            tx = puck.x + random.uniform(-self.wobble, self.wobble)
            ty = max(PADDLE_R + 5,
                     min(WIN_H * 0.45,
                         puck.y - 60 + random.uniform(-self.wobble, self.wobble)))

        # Reaction gate: the AI doesn't act every frame
        if random.random() < self.reaction:
            dx, dy = tx - self.x, ty - self.y
            dist   = math.hypot(dx, dy)
            if dist > 1:
                step    = min(self.speed, dist)
                self.vx = dx / dist * step
                self.vy = dy / dist * step

        # Apply movement, clamped to screen and top-half boundary
        self.x = max(PADDLE_R + WALL_MARGIN,
                     min(WIN_W - PADDLE_R - WALL_MARGIN, self.x + self.vx))
        self.y = max(PADDLE_R + WALL_MARGIN,
                     min(WIN_H * 0.48, self.y + self.vy))

        self.vx *= 0.8   # velocity damping for smooth deceleration
        self.vy *= 0.8

    def draw(self, frame):
        """Draw AI paddle: dark disc with crimson rings and a subtle glow aura."""
        cx, cy = int(self.x), int(self.y)

        # Subtle crimson glow aura
        ov = frame.copy()
        cv2.circle(ov, (cx, cy), PADDLE_R + 12, C_PADDLE_AI, -1)
        cv2.addWeighted(ov, 0.15, frame, 0.85, 0, frame)

        cv2.circle(frame, (cx, cy), PADDLE_R + 5,  C_PADDLE_AI_BRIGHT, 2)  # outer ring
        cv2.circle(frame, (cx, cy), PADDLE_R,       (30, 30, 30), -1)      # dark body
        cv2.circle(frame, (cx, cy), PADDLE_R,       C_PADDLE_AI, 3)        # crimson border
        cv2.circle(frame, (cx, cy), PADDLE_R - 8,   C_PADDLE_AI, 1)        # inner ring
        cv2.circle(frame, (cx, cy), PADDLE_R // 4,  C_PADDLE_AI, -1)       # centre dot
        cv2.circle(frame, (cx - PADDLE_R // 3, cy - PADDLE_R // 3),
                   PADDLE_R // 5, (200, 200, 220), -1)                       # specular dot


# ══════════════════════════════════════════════════════════════════════════════
#  PLAYER PADDLE  (hand-tracked)
# ══════════════════════════════════════════════════════════════════════════════

class PlayerPaddle:
    """
    The player's paddle, driven by wrist landmark coordinates from HandTracker.

    Coordinate remapping
    --------------------
    MediaPipe gives normalised [0.0, 1.0] coordinates across the full camera frame.
    update_from_landmark() remaps the vertical axis so the player's full hand range
    maps ONLY to the bottom half of the screen (their territory):
        lm_y = 0.0 → paddle just below centre line (52% of WIN_H)
        lm_y = 1.0 → paddle near the player's goal (96% of WIN_H)

    Smoothing
    ---------
    Raw landmarks are noisy (jitter by several pixels per frame).  A lerp filter
    (ALPHA = 0.45) moves the smoothed position 45% of the way toward the raw
    position each frame.  This eliminates jitter without adding perceptible lag.

    Velocity
    --------
    paddle.vx/vy = change in smoothed position this frame.
    Passed to puck.apply_hit() so fast hand swings transfer more momentum.
    """

    def __init__(self):
        self.x        = float(WIN_W / 2)
        self.y        = float(WIN_H * 0.80)
        self.vx       = 0.0
        self.vy       = 0.0
        self.visible  = False   # only draw the paddle when a hand is detected
        self.smooth_x = self.x
        self.smooth_y = self.y

    def update_from_landmark(self, lm_x, lm_y, frame_w, frame_h):
        """
        Move the paddle to the wrist position returned by HandTracker.

        Parameters
        ----------
        lm_x, lm_y  — normalised [0.0, 1.0] wrist coordinates (already flipped)
        frame_w/h   — not used here; kept for potential future scaling
        """
        raw_x = lm_x * WIN_W
        raw_y = WIN_H * 0.52 + lm_y * WIN_H * 0.44   # remap to bottom half

        ALPHA         = 0.45
        self.smooth_x = self.smooth_x * (1 - ALPHA) + raw_x * ALPHA
        self.smooth_y = self.smooth_y * (1 - ALPHA) + raw_y * ALPHA

        self.vx = self.smooth_x - self.x   # velocity = delta position
        self.vy = self.smooth_y - self.y

        self.x = np.clip(self.smooth_x,
                         PADDLE_R + WALL_MARGIN,
                         WIN_W - PADDLE_R - WALL_MARGIN)
        self.y = np.clip(self.smooth_y,
                         WIN_H * 0.50,
                         WIN_H - PADDLE_R - WALL_MARGIN)
        self.visible = True

    def draw(self, frame):
        """
        Draw player paddle: dark disc with orange rings and a speed-reactive glow.
        Glow intensity and flare ring scale with hand movement speed.
        """
        if not self.visible:
            return   # no hand detected — don't draw a phantom paddle

        cx, cy = int(self.x), int(self.y)
        spd    = math.hypot(self.vx, self.vy)

        # Orange glow aura — scales from 10% to 35% opacity with speed
        glow_alpha = min(0.35, 0.10 + spd / 80.0)
        overlay    = frame.copy()
        cv2.circle(overlay, (cx, cy), PADDLE_R + 14, C_PADDLE_P, -1)
        cv2.addWeighted(overlay, glow_alpha, frame, 1 - glow_alpha, 0, frame)

        cv2.circle(frame, (cx, cy), PADDLE_R + 5,  C_ORANGE_BRIGHT, 2)  # outer ring
        cv2.circle(frame, (cx, cy), PADDLE_R,       (40, 40, 40), -1)   # dark body
        cv2.circle(frame, (cx, cy), PADDLE_R,       C_PADDLE_P, 3)      # orange border
        cv2.circle(frame, (cx, cy), PADDLE_R - 8,   C_PADDLE_P, 1)      # inner ring
        cv2.circle(frame, (cx, cy), PADDLE_R // 4,  C_PADDLE_P, -1)     # centre dot
        cv2.circle(frame, (cx - PADDLE_R // 3, cy - PADDLE_R // 3),
                   PADDLE_R // 5, C_WHITE, -1)                            # specular dot

        # Speed flare ring — only when swinging fast (spd > 4 px/frame)
        if spd > 4:
            intensity = min(1.0, spd / 25)
            r_extra   = int(PADDLE_R + 12 + intensity * 8)
            alpha_e   = intensity * 0.5
            ov2 = frame.copy()
            cv2.circle(ov2, (cx, cy), r_extra, C_ORANGE_BRIGHT, 2)
            cv2.addWeighted(ov2, alpha_e, frame, 1 - alpha_e, 0, frame)