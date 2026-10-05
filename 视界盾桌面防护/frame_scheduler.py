"""Skip identical submissions, but periodically refresh current screen coverage."""
import numpy as np


class FrameScheduler:
    def __init__(self, refresh_interval=3.0, min_interval=.1, capture_timeout=1.5):
        self.refresh_interval = refresh_interval
        self.min_interval = min_interval
        self.capture_timeout = capture_timeout
        self.image = self.submitted_at = None

    def due(self, frame, now):
        if frame is None or not 0 <= now-frame.captured_at <= self.capture_timeout:
            return False
        if self.image is None:
            return True
        age = now-self.submitted_at
        if age < self.min_interval:
            return False
        return (age >= self.refresh_interval or self.image.shape != frame.image.shape
                or not np.array_equal(self.image, frame.image))

    def submitted(self, frame, now):
        self.image, self.submitted_at = frame.image, now
