"""
CUSUM Detector — Cumulative Sum Control Chart
Classic statistical method for detecting slow drift / camouflage attacks.
Each instance tracks one metric time series.
"""


class CUSUMDetector:
    """
    CUSUM algorithm for detecting slow monotonic drift.
    Catches camouflage attacks that Isolation Forest misses because
    each individual reading looks normal — only the accumulated
    drift is anomalous.

    From master design:
        def cusum(values, threshold=5, drift=0.5): ...
    """

    def __init__(self, threshold: float = 5.0, drift: float = 0.5):
        self.threshold = threshold
        self.drift = drift
        self.s_pos = 0.0   # upper cumulative sum
        self.s_neg = 0.0   # lower cumulative sum
        self.fired = False

    def update(self, value: float) -> bool:
        """
        Push new observation. Returns True only on the first detection
        per episode (resets after firing to avoid repeated alerts).
        """
        self.s_pos = max(0.0, self.s_pos + value - self.drift)
        self.s_neg = max(0.0, self.s_neg - value - self.drift)

        if self.s_pos > self.threshold or self.s_neg > self.threshold:
            if not self.fired:
                self.fired = True
                return True
        else:
            self.fired = False  # reset after episode clears

        return False

    def reset(self):
        """Hard reset — call this after recovery completes."""
        self.s_pos = 0.0
        self.s_neg = 0.0
        self.fired = False

    @staticmethod
    def run_batch(values: list[float], threshold: float = 5.0, drift: float = 0.5) -> bool:
        """One-shot check over a list of values (for retrospective analysis)."""
        s_pos, s_neg = 0.0, 0.0
        for v in values:
            s_pos = max(0.0, s_pos + v - drift)
            s_neg = max(0.0, s_neg - v - drift)
            if s_pos > threshold or s_neg > threshold:
                return True
        return False
