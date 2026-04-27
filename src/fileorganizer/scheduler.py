import threading
from datetime import datetime
from typing import Callable, Optional, Set


class Scheduler:
    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._cb: Optional[Callable] = None
        self.hour: int = 22
        self.minute: int = 0
        self.days: Set[int] = set(range(7))
        self.enabled: bool = False

    def configure(self, hour: int, minute: int, days: Set[int], cb: Callable):
        self.hour = hour
        self.minute = minute
        self.days = days
        self._cb = cb

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.enabled = True

    def stop(self):
        self._stop.set()
        self.enabled = False

    def _loop(self):
        last_run_date = None
        while not self._stop.wait(20):
            now = datetime.now()
            if (
                now.weekday() in self.days
                and now.hour == self.hour
                and now.minute == self.minute
                and last_run_date != now.date()
            ):
                last_run_date = now.date()
                if self._cb:
                    try:
                        self._cb()
                    except Exception:
                        pass
