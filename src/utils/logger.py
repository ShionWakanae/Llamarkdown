import datetime
from rich import print


class Logger:
    def __init__(self):
        self._last_timestamp = None

    def log(self, msg, display_last_log_interval=True):
        now = datetime.datetime.now()
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        if self._last_timestamp:
            delta_ms = (now - self._last_timestamp).total_seconds() * 1000
        interval_str = ""
        if (
            display_last_log_interval
            and (self._last_timestamp is not None)
            and (delta_ms >= 1)
        ):
            interval_str = f"  <{int(delta_ms)}ms>"

        self._last_timestamp = now
        print(f"[{timestamp_str}] {msg}{interval_str}")


logger = Logger()
