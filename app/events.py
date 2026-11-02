"""Bounded, coalesced notifications: clients always recover from HTTP snapshots."""
import threading


class Events:
    def __init__(self):
        self.condition = threading.Condition()
        self.revision = 0

    def publish(self):
        with self.condition:
            self.revision += 1
            self.condition.notify_all()

    def wait(self, after, timeout=15):
        with self.condition:
            self.condition.wait_for(lambda: self.revision != after, timeout)
            return self.revision
