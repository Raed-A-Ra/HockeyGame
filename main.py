"""
main.py — CV Air Hockey
========================
Entry point and game loop.  This file is intentionally thin — it coordinates
the other modules but contains no heavy logic itself.

Responsibilities
----------------
  • Open the webcam and the game window
  • Run the main loop at ~60 fps
  • Call hand_tracker  → get wrist position
  • Call game_objects  → update physics and AI
  • Call physics       → resolve collisions
  • Call renderer      → draw everything
  • Handle keyboard input (Q/R/P/M/1/2/3)

What does NOT belong here
--------------------------
  ✗ Colour constants  (→ config.py)
  ✗ Drawing code      (→ renderer.py)
  ✗ Collision maths   (→ physics.py)
  ✗ Hand detection    (→ hand_tracker.py)
  ✗ Object classes    (→ game_objects.py)

Run
---
    python main.py
"""

import cv2
import numpy as np
import time

# ── Project modules ───────────────────────────────────────────────────────────
from config import (
    WIN_W, WIN_H,
    WALL_MARGIN,
    GAME_DURATION, COMBO_WINDOW, COMBO_BONUS, OBSTACLES,
    C_FIELD_DARK, C_ORANGE, C_PADDLE_AI,
)
from hand_tracker  import HandTracker
from game_objects  import Puck, PlayerPaddle, AIPaddle, ParticleSystem, FloatingText, SoundEngine
from physics       import check_paddle_puck
from renderer      import (
    draw_field, draw_hud, draw_game_over,
    draw_no_hand_warning, draw_fps,
)


# ══════════════════════════════════════════════════════════════════════════════
#  GAME CONTROLLER
# ══════════════════════════════════════════════════════════════════════════════

class CVAirHockey:
    """
    Top-level game controller.  Owns all game objects and runs the main loop.
    Instantiate once, call .run().
    """

    def __init__(self):
        # ── Webcam ────────────────────────────────────────────────────────────
        # VideoCapture(0) = first/default camera.  Try index 1 or 2 if it fails.
        self.cap = cv2.VideoCapture(0)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT,  720)
        self.cap.set(cv2.CAP_PROP_FPS,            60)

        # ── Hand tracker ──────────────────────────────────────────────────────
        # Auto-detects legacy vs Tasks MediaPipe API.
        self.tracker = HandTracker()

        # ── Game objects ──────────────────────────────────────────────────────
        self.puck       = Puck()
        self.player     = PlayerPaddle()
        self.ai         = AIPaddle("medium")
        self.particles  = ParticleSystem()
        self.floats     = []          # active FloatingText objects
        self.sound      = SoundEngine()

        # ── Game state ────────────────────────────────────────────────────────
        self.difficulty     = "medium"
        self.player_score   = 0
        self.ai_score       = 0
        self.game_over      = False
        self.paused         = False
        self.start_time     = time.time()
        self.time_left      = float(GAME_DURATION)
        self.show_obstacles = False   # True on medium and hard

        # ── Hit-streak (combo) tracking ───────────────────────────────────────
        self.combo    = 0     # current consecutive-hit streak
        self.last_hit = 0.0   # wall-clock time of the most recent paddle hit

        # ── FPS measurement (exponential moving average) ───────────────────────
        self._last_t = time.time()
        self._fps    = 60.0

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _add_float(self, text, x, y, color, scale=1.5, life=1.2):
        """Spawn a new FloatingText at (x, y)."""
        self.floats.append(FloatingText(text, x, y, color, scale, life))

    def _set_difficulty(self, d):
        """Switch difficulty and update AI + obstacle state immediately."""
        self.difficulty     = d
        self.ai.set_difficulty(d)
        self.show_obstacles = (d in ("medium", "hard"))
        print(f"[CV Air Hockey] Difficulty → {d.upper()}")

    def _reset_game(self):
        """Reset all game state to a clean start. Does not close the window."""
        self.puck.reset()
        self.player_score   = 0
        self.ai_score       = 0
        self.game_over      = False
        self.paused         = False
        self.start_time     = time.time()
        self.time_left      = float(GAME_DURATION)
        self.combo          = 0
        self.floats.clear()
        self.particles.particles.clear()

    def _score_goal(self, scorer):
        """
        Handle a goal event: update score, spawn effects, reset puck.
        Both sides always earn exactly 1 point — no bonuses or multipliers.
        """
        if scorer == "player":
            self.player_score += 1
            self._add_float("GOAL!", WIN_W // 2, WIN_H // 3, C_ORANGE, 2.5, 2.0)
            self.particles.burst(self.puck.x, self.puck.y, C_ORANGE, 50)
            self.sound.play(self.sound.goal)
        else:
            self.ai_score += 1
            self._add_float("AI GOAL!", WIN_W // 2, WIN_H // 2, C_PADDLE_AI, 2.5, 2.0)
            self.particles.burst(self.puck.x, self.puck.y, C_PADDLE_AI, 40)
            self.sound.play(self.sound.goal)

        self.combo = 0          # goal resets the hit streak
        time.sleep(0.4)         # brief pause so the player sees the celebration
        self.puck.reset()

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self):
        """Run the game until the player quits. Each loop iteration = one frame."""
        print("=" * 60)
        print("   CV AIR HOCKEY  —  starting webcam …")
        print("   Controls:  Q=Quit  R=Restart  P=Pause  M=Mute")
        print("              1=Easy  2=Medium  3=Hard")
        print("   Move your RIGHT HAND in front of the camera!")
        print("=" * 60)

        while True:

            # ── STEP 1: Timing ────────────────────────────────────────────────
            # dt (delta-time) makes all physics frame-rate independent.
            # Capped at 50ms to prevent a physics jump after a long freeze
            # (e.g. the 400ms time.sleep() inside _score_goal).
            now          = time.time()
            dt           = min(now - self._last_t, 0.05)
            self._last_t = now
            self._fps    = 0.9 * self._fps + 0.1 * (1.0 / max(dt, 1e-6))
            elapsed      = now - self.start_time

            # ── STEP 2: Webcam input ──────────────────────────────────────────
            ret, cam_frame = self.cap.read()
            if not ret:
                print("[ERROR] Cannot read from webcam.")
                break

            # Flip horizontally (selfie/mirror mode) so hand movement feels natural
            cam_frame = cv2.flip(cam_frame, 1)
            cam_frame = cv2.resize(cam_frame, (WIN_W, WIN_H))

            # ── STEP 3: Hand tracking ─────────────────────────────────────────
            rgb        = cv2.cvtColor(cam_frame, cv2.COLOR_BGR2RGB)
            lm         = self.tracker.get_right_wrist(rgb)   # (x,y) or None
            hand_found = lm is not None

            if hand_found and not self.game_over and not self.paused:
                self.player.update_from_landmark(lm[0], lm[1], WIN_W, WIN_H)
            else:
                self.player.visible = hand_found   # hide paddle when no hand

            # ── STEP 4: Build base frame ──────────────────────────────────────
            # Dark background → field (ice, markings, goals) → dim camera blend
            frame = np.full((WIN_H, WIN_W, 3), C_FIELD_DARK, dtype=np.uint8)
            draw_field(frame, OBSTACLES, self.show_obstacles)

            # Blend 10% camera feed into the player's half for spatial awareness
            INSET     = WALL_MARGIN + 2
            cam_lower = cam_frame[WIN_H // 2 : WIN_H - INSET, INSET : WIN_W - INSET]
            ice_lower = frame    [WIN_H // 2 : WIN_H - INSET, INSET : WIN_W - INSET].copy()
            frame[WIN_H // 2 : WIN_H - INSET, INSET : WIN_W - INSET] = \
                cv2.addWeighted(cam_lower, 0.10, ice_lower, 0.90, 0)

            # ── STEP 5: Game logic (only when active) ─────────────────────────
            if not self.game_over and not self.paused:

                # Timer countdown
                self.time_left = max(0.0, GAME_DURATION - elapsed)
                if self.time_left <= 0:
                    self.game_over = True
                    self.sound.play(self.sound.end)

                # Puck physics — returns an event string or None
                event = self.puck.update(dt, OBSTACLES, elapsed)

                if event == "goal_ai":
                    self._score_goal("player")
                elif event == "goal_player":
                    self._score_goal("ai")
                elif event == "wall":
                    self.sound.play(self.sound.wall)

                # AI movement
                self.ai.update(self.puck, dt)

                # Player paddle ↔ puck collision
                if check_paddle_puck(self.player, self.puck):
                    now_t = time.time()
                    gap   = now_t - self.last_hit

                    self.combo    = min(self.combo + 1, len(COMBO_BONUS) - 1) \
                                    if gap < COMBO_WINDOW else 1
                    self.last_hit = now_t

                    # Combo badge at x3+ — purely cosmetic, no bonus points
                    if self.combo >= 3:
                        self._add_float(f"x{self.combo} COMBO",
                                        self.puck.x, self.puck.y - 40,
                                        C_ORANGE, 1.1, 0.9)
                        self.sound.play(self.sound.combo)
                    else:
                        self.sound.play(self.sound.hit)

                    self.particles.burst(int(self.puck.x), int(self.puck.y), C_ORANGE, 22)

                # AI paddle ↔ puck collision
                if check_paddle_puck(self.ai, self.puck):
                    self.sound.play(self.sound.wall)
                    self.particles.burst(int(self.puck.x), int(self.puck.y), C_PADDLE_AI, 12)

            # ── STEP 6: Render game objects ───────────────────────────────────
            # Order: particles (behind) → puck → AI paddle → player paddle (front)
            self.particles.update_draw(frame, dt)
            self.puck.draw(frame)
            self.ai.draw(frame)
            self.player.draw(frame)

            # Floating texts (update + draw + prune expired)
            alive_f = []
            for ft in self.floats:
                ft.update(dt)
                ft.draw(frame)
                if ft.life > 0:
                    alive_f.append(ft)
            self.floats = alive_f

            # ── STEP 7: HUD overlay ───────────────────────────────────────────
            draw_hud(frame, self.player_score, self.ai_score,
                     self.time_left, self.combo,
                     self.sound.muted, self.difficulty, self.paused)

            if not hand_found:
                draw_no_hand_warning(frame)

            if self.game_over:
                draw_game_over(frame, self.player_score, self.ai_score)

            draw_fps(frame, self._fps)

            # ── STEP 8: Display ───────────────────────────────────────────────
            cv2.imshow("CV Air Hockey", frame)

            # ── STEP 9: Keyboard input ────────────────────────────────────────
            # waitKey(1) processes window events and returns the pressed key code.
            # & 0xFF strips high bits for cross-platform compatibility.
            key = cv2.waitKey(1) & 0xFF

            if key == ord('q') or key == 27:       # Q or ESC → quit
                break
            elif key == ord('r'):                   # R → restart
                self._reset_game()
            elif key == ord('p') and not self.game_over:   # P → pause/unpause
                self.paused = not self.paused
                if self.paused:
                    self.start_time -= elapsed              # freeze the timer
                else:
                    self.start_time = time.time() - (GAME_DURATION - self.time_left)
            elif key == ord('m'):                   # M → mute toggle
                self.sound.toggle_mute()
            elif key == ord('1'):
                self._set_difficulty("easy")
            elif key == ord('2'):
                self._set_difficulty("medium")
            elif key == ord('3'):
                self._set_difficulty("hard")

        # ── Cleanup ───────────────────────────────────────────────────────────
        self.cap.release()
        self.tracker.close()
        cv2.destroyAllWindows()
        print("[CV Air Hockey] Bye! 🏒")


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    game = CVAirHockey()
    game.run()