"""
renderer.py — CV Air Hockey
============================
All rendering code lives here and ONLY here.

Functions
---------
draw_field(frame, obstacles, show_obstacles)
    Paints the ice rink, centre markings, goal bars, and bumper obstacles.

draw_hud(frame, player_score, ai_score, time_left, combo, muted, difficulty, paused)
    Draws the score pill, timer, hit-streak badge, controls hint, and pause overlay.

draw_game_over(frame, player_score, ai_score)
    Full-screen darkened overlay shown when the timer reaches zero.

draw_no_hand_warning(frame)
    Orange warning banner at the bottom when no hand is detected.

draw_fps(frame, fps)
    Small FPS counter in the bottom-right corner.

Rules this module must never break
-----------------------------------
  ✗ No game logic (scoring, physics, state changes)
  ✗ No hand tracking
  ✗ No importing from game_objects or physics
  ✓ Only imports from config and uses cv2 / numpy
"""

import cv2
import numpy as np

from config import (
    WIN_W, WIN_H, WALL_MARGIN,
    GOAL_W, GOAL_H,
    C_FIELD_ICE, C_FIELD_DARK, C_ICE_LINE, C_ICE_TINT_AI, C_ICE_TINT_P,
    C_ORANGE, C_ORANGE_DIM, C_ORANGE_BRIGHT,
    C_GOAL_P, C_GOAL_AI,
    C_WHITE, C_SHADOW, C_TEXT_DIM,
)


# ══════════════════════════════════════════════════════════════════════════════
#  FIELD
# ══════════════════════════════════════════════════════════════════════════════

def draw_field(frame, obstacles, show_obstacles):
    """
    Paint the ice rink and all static field elements onto `frame` (in-place).

    Drawing order (back to front):
      1. Dark charcoal outer fill  — the arena "wall" outside the rink
      2. Bluish-white ice surface  — the playable area
      3. Subtle half-tints         — cool AI side / warm player side
      4. Rink border rectangle
      5. Centre line and circle    — with orange accent dot at the very centre
      6. Goal bars                 — orange (player/bottom) and crimson (AI/top)
      7. Bumper obstacles          — only when show_obstacles is True
    """
    INSET = WALL_MARGIN + 2   # pixels of dark border visible around the ice edge

    # 1. Dark outer border
    frame[:] = C_FIELD_DARK

    # 2. Ice surface
    frame[INSET : WIN_H - INSET, INSET : WIN_W - INSET] = C_FIELD_ICE

    # 3. Subtle half-tints (barely perceptible — subconsciously zones the halves)
    MID = WIN_H // 2
    frame[INSET : MID,           INSET : WIN_W - INSET] = C_ICE_TINT_AI   # top = AI
    frame[MID   : WIN_H - INSET, INSET : WIN_W - INSET] = C_ICE_TINT_P    # bottom = player

    # 4. Rink border rectangle
    cv2.rectangle(frame, (INSET, INSET), (WIN_W - INSET, WIN_H - INSET), C_ICE_LINE, 3)

    # 5. Centre line and circle
    cv2.line(frame, (INSET + 10, MID), (WIN_W - INSET - 10, MID), C_ICE_LINE, 2)
    cv2.circle(frame, (WIN_W // 2, MID), 92, C_ICE_LINE, 1)   # outer thin ring
    cv2.circle(frame, (WIN_W // 2, MID), 90, C_ICE_LINE, 2)   # inner thicker ring
    cv2.circle(frame, (WIN_W // 2, MID),  6, C_ICE_LINE, -1)  # filled centre dot
    cv2.circle(frame, (WIN_W // 2, MID),  4, C_ORANGE,   -1)  # orange accent on top

    # 6. Goal bars
    gx1 = WIN_W // 2 - GOAL_W // 2
    gx2 = WIN_W // 2 + GOAL_W // 2

    # AI goal — top, crimson
    cv2.rectangle(frame, (gx1, INSET), (gx2, INSET + GOAL_H + 6), C_GOAL_AI, -1)
    cv2.rectangle(frame, (gx1, INSET), (gx2, INSET + GOAL_H + 6), (100, 100, 220), 2)
    cv2.putText(frame, "AI GOAL", (gx1 + 10, INSET + GOAL_H + 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.52, C_GOAL_AI, 1)

    # Player goal — bottom, orange
    cv2.rectangle(frame,
                  (gx1, WIN_H - INSET - GOAL_H - 6),
                  (gx2, WIN_H - INSET),
                  C_GOAL_P, -1)
    cv2.rectangle(frame,
                  (gx1, WIN_H - INSET - GOAL_H - 6),
                  (gx2, WIN_H - INSET),
                  C_ORANGE_BRIGHT, 2)
    cv2.putText(frame, "YOUR GOAL",
                (gx1 + 6, WIN_H - INSET - GOAL_H - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.52, C_GOAL_P, 1)

    # 7. Bumper obstacles
    if show_obstacles:
        for obs in obstacles:
            ox  = int(obs["cx"] * WIN_W)
            oy  = int(obs["cy"] * WIN_H)
            orr = obs["r"]
            cv2.circle(frame, (ox, oy), orr + 5, (50, 50, 50), -1)     # shadow
            cv2.circle(frame, (ox, oy), orr,     (80, 80, 90), -1)     # body
            cv2.circle(frame, (ox, oy), orr,     C_ORANGE_DIM, 2)      # orange ring accent
            cv2.circle(frame,                                            # specular dot
                       (ox - orr // 3, oy - orr // 3),
                       orr // 4,
                       (200, 205, 215), -1)


# ══════════════════════════════════════════════════════════════════════════════
#  HUD
# ══════════════════════════════════════════════════════════════════════════════

def draw_hud(frame, player_score, ai_score, time_left, combo, muted, difficulty, paused):
    """
    Draw all heads-up display elements.  Called LAST so HUD sits on top of everything.

    Uses addWeighted() to fake semi-transparent dark pill backgrounds so text
    is readable against both the bright ice and any coloured game object.

    Colour language:
      Orange  → your score, timer warning (≤10s), streak badge
      Crimson → AI score
      White   → timer when time is comfortable, result text
      Grey    → hints, labels, secondary info
    """
    font  = cv2.FONT_HERSHEY_DUPLEX    # slightly fancier — scores and timer
    font2 = cv2.FONT_HERSHEY_SIMPLEX   # plain — labels and hints

    # ── Score pill (top centre) ───────────────────────────────────────────────
    pill = frame.copy()
    cv2.rectangle(pill, (WIN_W // 2 - 170, 6), (WIN_W // 2 + 170, 58), (18, 18, 18), -1)
    cv2.addWeighted(pill, 0.82, frame, 0.18, 0, frame)
    cv2.rectangle(frame, (WIN_W // 2 - 170, 6), (WIN_W // 2 + 170, 58), C_ORANGE, 2)
    cv2.line(frame, (WIN_W // 2, 10), (WIN_W // 2, 54), C_ORANGE_DIM, 1)  # divider

    # Player score — right side, orange
    cv2.putText(frame, "YOU",         (WIN_W // 2 + 14, 30),  font2, 0.52, C_TEXT_DIM, 1)
    cv2.putText(frame, f"{player_score}", (WIN_W // 2 + 14, 52),  font,  1.0,  C_ORANGE, 2)

    # AI score — left side, cool blue-crimson
    cv2.putText(frame, "AI",          (WIN_W // 2 - 50, 30),  font2, 0.52, C_TEXT_DIM, 1)
    cv2.putText(frame, f"{ai_score}", (WIN_W // 2 - 155, 52), font,  1.0,  (120, 120, 210), 2)

    # ── Timer pill ─────────────────────────────────────────────────────────────
    tpill = frame.copy()
    cv2.rectangle(tpill, (WIN_W // 2 - 52, 62), (WIN_W // 2 + 52, 98), (18, 18, 18), -1)
    cv2.addWeighted(tpill, 0.80, frame, 0.20, 0, frame)
    tborder = C_ORANGE if time_left <= 10 else (60, 60, 60)  # orange border when urgent
    cv2.rectangle(frame, (WIN_W // 2 - 52, 62), (WIN_W // 2 + 52, 98), tborder, 1)
    tim_col = C_ORANGE if time_left <= 10 else C_WHITE
    cv2.putText(frame, f"{int(time_left):02d}s", (WIN_W // 2 - 38, 93), font, 1.0, tim_col, 2)

    # ── Hit streak / combo badge (top right) ──────────────────────────────────
    if combo >= 2:
        ctext = f"HIT STREAK  x{combo}"
        col   = C_ORANGE if combo < 5 else C_ORANGE_BRIGHT
        cbg   = frame.copy()
        tw    = cv2.getTextSize(ctext, font2, 0.78, 2)[0][0]
        cv2.rectangle(cbg, (WIN_W - tw - 28, 8), (WIN_W - 8, 42), (18, 18, 18), -1)
        cv2.addWeighted(cbg, 0.80, frame, 0.20, 0, frame)
        cv2.rectangle(frame, (WIN_W - tw - 28, 8), (WIN_W - 8, 42), C_ORANGE, 1)
        cv2.putText(frame, ctext, (WIN_W - tw - 18, 33), font2, 0.78, col, 2)

    # ── Bottom-left: difficulty + mute status ─────────────────────────────────
    cv2.putText(frame,
                difficulty.upper() + ("  MUTED" if muted else ""),
                (10, WIN_H - 10), font2, 0.48, C_TEXT_DIM, 1)

    # ── Top-left: controls hint ────────────────────────────────────────────────
    cv2.putText(frame,
                "Q:Quit  R:Restart  P:Pause  M:Mute  1/2/3:Difficulty",
                (10, 16), font2, 0.40, C_TEXT_DIM, 1)

    # ── Pause overlay ──────────────────────────────────────────────────────────
    if paused:
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (WIN_W, WIN_H), (10, 10, 10), -1)
        cv2.addWeighted(overlay, 0.60, frame, 0.40, 0, frame)
        cv2.putText(frame, "PAUSED",
                    (WIN_W // 2 - 135, WIN_H // 2 - 10), font, 3.0, C_ORANGE, 5)
        cv2.putText(frame, "Press P to resume",
                    (WIN_W // 2 - 145, WIN_H // 2 + 55), font2, 0.9, C_WHITE, 2)


# ══════════════════════════════════════════════════════════════════════════════
#  GAME OVER SCREEN
# ══════════════════════════════════════════════════════════════════════════════

def draw_game_over(frame, player_score, ai_score):
    """
    Full-screen darkened overlay shown when the timer expires.
    The rink state is dimly visible underneath at 28% brightness.
    """
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (WIN_W, WIN_H), (10, 10, 10), -1)
    cv2.addWeighted(overlay, 0.72, frame, 0.28, 0, frame)

    font  = cv2.FONT_HERSHEY_DUPLEX
    font2 = cv2.FONT_HERSHEY_SIMPLEX

    # "GAME OVER" — black shadow then orange text on top
    cv2.putText(frame, "GAME OVER", (WIN_W // 2 - 205, WIN_H // 2 - 78), font, 2.8, (0, 0, 0), 8)
    cv2.putText(frame, "GAME OVER", (WIN_W // 2 - 205, WIN_H // 2 - 78), font, 2.8, C_ORANGE,   5)

    # Result text
    if player_score > ai_score:
        result_text, result_col = "YOU WIN!", C_ORANGE
    elif player_score < ai_score:
        result_text, result_col = "AI WINS!", (100, 100, 220)
    else:
        result_text, result_col = "DRAW!",    C_WHITE

    cv2.putText(frame, result_text,
                (WIN_W // 2 - 130, WIN_H // 2 + 5), font, 2.2, result_col, 4)

    # Final score
    cv2.putText(frame, f"You  {player_score}   :   {ai_score}  AI",
                (WIN_W // 2 - 170, WIN_H // 2 + 68), font2, 1.4, C_WHITE, 3)

    # Decorative divider
    cv2.line(frame,
             (WIN_W // 2 - 300, WIN_H // 2 + 90),
             (WIN_W // 2 + 300, WIN_H // 2 + 90),
             C_ORANGE_DIM, 1)

    # Prompt
    cv2.putText(frame, "R  — Play Again          Q  — Quit",
                (WIN_W // 2 - 200, WIN_H // 2 + 128), font2, 0.82, C_TEXT_DIM, 1)


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def draw_no_hand_warning(frame):
    """
    Orange pill-shaped banner at the bottom of the screen when hand tracking
    cannot find the player's right hand in the current camera frame.
    The game keeps running — the puck still moves — but the player paddle
    is hidden until a hand is detected again.
    """
    msg   = "Show your RIGHT HAND to the camera"
    font2 = cv2.FONT_HERSHEY_SIMPLEX
    tw    = cv2.getTextSize(msg, font2, 0.72, 2)[0][0]
    x0    = WIN_W // 2 - tw // 2 - 14
    y0    = WIN_H - 55
    bg    = frame.copy()
    cv2.rectangle(bg, (x0, y0), (x0 + tw + 28, y0 + 34), (18, 18, 18), -1)
    cv2.addWeighted(bg, 0.82, frame, 0.18, 0, frame)
    cv2.rectangle(frame, (x0, y0), (x0 + tw + 28, y0 + 34), C_ORANGE, 2)
    cv2.putText(frame, msg, (x0 + 14, y0 + 24), font2, 0.72, C_ORANGE, 2)


def draw_fps(frame, fps):
    """Small FPS counter in the bottom-right corner — useful for performance checks."""
    cv2.putText(frame, f"FPS:{fps:.0f}",
                (WIN_W - 88, WIN_H - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, C_TEXT_DIM, 1)