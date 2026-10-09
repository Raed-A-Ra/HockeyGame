"""
config.py — CV Air Hockey
=========================
Single source of truth for every constant in the game.

If you want to tune anything — puck speed, AI difficulty, colours, window
size, match duration — this is the ONLY file you need to edit.  Nothing
else in the project should contain raw magic numbers.
"""

# ── Window / display ──────────────────────────────────────────────────────────
WIN_W, WIN_H = 1280, 720   # game window resolution (also the webcam target size)
FPS_TARGET   = 60          # target frame rate; actual FPS shown in the corner

# ── Colour Palette (all values are BGR — OpenCV uses Blue-Green-Red, not RGB) ─
#
# Design language:
#   Dark charcoal (#1A1A1A) everywhere outside the rink.
#   Bright bluish-white ice so game objects pop visually.
#   Orange (#F59E0B → BGR: 11,158,245) is the ONLY accent colour:
#     your paddle, the puck, your score, hit flashes, warnings, goal bars.
#   Dark crimson for the AI paddle so it reads as "enemy" at a glance.

# Field / background
C_BG           = ( 26,  26,  26)   # near-black background (#1A1A1A)
C_FIELD_ICE    = (230, 235, 245)   # bluish-white ice rink surface
C_FIELD_DARK   = ( 22,  22,  22)   # dark charcoal border surrounding the rink
C_ICE_LINE     = (180, 190, 210)   # slightly darker ice for rink markings
C_ICE_TINT_AI  = (220, 230, 245)   # very subtle cool tint on the AI's half
C_ICE_TINT_P   = (225, 235, 248)   # very subtle warm tint on the player's half

# Orange accent (#F59E0B converted to BGR)
C_ORANGE        = ( 11, 158, 245)  # primary orange — used on almost everything player-side
C_ORANGE_DIM    = (  6,  90, 140)  # dimmer orange for glow halos and shadow blends
C_ORANGE_BRIGHT = ( 30, 200, 255)  # extra-bright orange for hit-flash and speed-flare moments

# Puck — three layers give it a glowing sphere appearance
C_PUCK          = ( 11, 158, 245)  # main puck body (same orange as the accent colour)
C_PUCK_GLOW     = (  6,  90, 140)  # glow halo (darker, bleeds softly into the ice)
C_PUCK_CORE     = ( 30, 200, 255)  # bright inner core — lit-from-inside effect

# Paddles
C_PADDLE_P          = ( 11, 158, 245)  # player paddle = orange (matches puck = "yours")
C_PADDLE_AI         = ( 60,  60, 200)  # AI paddle = dark crimson = "enemy"
C_PADDLE_AI_BRIGHT  = ( 80,  80, 240)  # slightly brighter crimson for the AI's outer ring

# Goal bars at the top (AI) and bottom (player) of the rink
C_GOAL_P        = ( 11, 158, 245)  # your goal bar (bottom) = orange
C_GOAL_AI       = ( 50,  50, 180)  # AI goal bar  (top)    = crimson

# UI / overlay colours
C_HIT_FLASH     = ( 30, 200, 255)  # bright flash when puck is struck
C_WHITE         = (255, 255, 255)  # pure white for specular highlights and text
C_GOLD          = ( 11, 158, 245)  # alias for orange used in score/combo text
C_SHADOW        = (  0,   0,   0)  # black for text drop-shadows
C_TEXT_DIM      = (140, 150, 160)  # muted grey for hints and secondary labels

# ── Game geometry ─────────────────────────────────────────────────────────────
PADDLE_R    = 32   # radius of both paddles in pixels
PUCK_R      = 20   # radius of the puck in pixels
GOAL_W      = 280  # width of each goal opening, centred horizontally
GOAL_H      = 18   # visual height of the goal bar at the wall
WALL_MARGIN = 5    # pixels from the window edge that count as "the wall"

# ── Puck physics ──────────────────────────────────────────────────────────────
# The puck starts slow and ramps up over the 60-second match.
# PUCK_FRICTION is multiplied every frame: 0.998 keeps 99.8% of speed —
# nearly frictionless, like real ice, but not perfectly so.
PUCK_SPEED_INIT = 7.0    # starting speed in pixels per frame
PUCK_SPEED_MAX  = 22.0   # hard cap — prevents the puck becoming untrackable
PUCK_FRICTION   = 0.998  # per-frame speed multiplier (1.0 = no friction at all)
PUCK_SPEED_RAMP = 0.003  # extra pixels/frame of speed added per second of play

# ── AI difficulty settings ────────────────────────────────────────────────────
# Three knobs make the AI beatable on all levels without being robotic:
#   SPEED    — max pixels the paddle can move per frame (no teleporting)
#   REACTION — probability the AI acts at all on a given frame (0.0–1.0)
#   WOBBLE   — ±pixel random offset added to the AI's target position (bad aim)

AI_SPEED_EASY    = 5.5   # slow — easy to get past with a straight shot
AI_SPEED_MED     = 8.5   # noticeably faster — harder to outrun
AI_SPEED_HARD    = 13.5  # very fast — needs angled shots to beat

AI_REACTION_EASY = 0.55  # acts on 55% of frames — zones out a lot
AI_REACTION_MED  = 0.78  # 78% — occasional lapses, still beatable
AI_REACTION_HARD = 0.95  # 95% — almost never misses a frame

AI_WOBBLE_EASY   = 10    # ±10px aim error — misses wide frequently
AI_WOBBLE_MED    = 5     # ±5px — more precise, shootable corners still exist
AI_WOBBLE_HARD   = 1     # ±1px — nearly perfect aim

# ── Match settings ────────────────────────────────────────────────────────────
GAME_DURATION = 60   # match length in seconds

# ── Hit streak / combo system ─────────────────────────────────────────────────
# Hitting the puck multiple times within COMBO_WINDOW seconds builds a streak
# badge on screen.  COMBO_BONUS is intentionally all zeros — no bonus points.
# Every goal from either side is strictly 1 point.  This was a deliberate
# balance fix to stop players exploiting the rally system for free points.
COMBO_WINDOW = 3.0                      # seconds before the streak resets
COMBO_BONUS  = [0, 0, 0, 0, 0, 0, 0]   # all zeros — cosmetic streaks only

# ── Bumper obstacles (Medium and Hard only) ───────────────────────────────────
# Two circular bumpers on the centre line deflect the puck unpredictably.
# Stored as normalised fractions (0.0–1.0) so they scale with WIN_W / WIN_H.
OBSTACLES = [
    {"cx": 0.30, "cy": 0.50, "r": 28},   # left bumper, on the centre line
    {"cx": 0.70, "cy": 0.50, "r": 28},   # right bumper, symmetrical
]