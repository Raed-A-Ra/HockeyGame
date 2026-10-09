import cv2
import mediapipe as mp


class HandTracker:
    def __init__(self):
        self.hands = mp.solutions.hands.Hands(
            model_complexity=0,
            max_num_hands=1,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )

    def get_right_wrist(self, rgb_frame):
        results = self.hands.process(rgb_frame)

        if not results.multi_hand_landmarks:
            return None

        lm = results.multi_hand_landmarks[0].landmark[0]
        return (lm.x, lm.y)

    def close(self):
        self.hands.close()