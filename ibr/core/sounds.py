import time

# Sweeping the pointer across a row of buttons should not rattle off a burst of ticks.
HOVER_GAP = 0.06


class SoundGate:
    def __init__(self, play, clock=time.monotonic):
        self.enabled = True
        self._play = play
        self._clock = clock
        self._target = None
        self._last_hover = float("-inf")

    def hover(self, target):
        if target is self._target:
            return
        self._target = target
        if target is None or not self.enabled:
            return
        now = self._clock()
        if now - self._last_hover >= HOVER_GAP:
            self._last_hover = now
            self._play("hover")

    def click(self):
        self.cue("click")

    def cue(self, name: str):
        if self.enabled:
            self._play(name)
