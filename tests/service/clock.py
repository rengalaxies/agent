"""Controllable clock: the one time boundary the service tests replace."""

import threading


class Clock:
    def __init__(self, start=1_800_000_000.0):
        self.now = start
        self.lock = threading.Lock()

    def __call__(self):
        with self.lock:
            return self.now

    def advance(self, seconds):
        with self.lock:
            self.now += seconds
