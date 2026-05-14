import datetime
from rich import print


class Logger:
    def __init__(self):
        self._last_timestamp = None

    def format_duration(self, ms: float) -> str:
        """
        Human readable duration.

        Examples:
            12ms
            532ms
            1.24s
            2m 15s
            1h 03m 22s
        """

        ms = int(ms)

        #
        # < 1 second
        #
        if ms < 1000:
            return f"{ms}ms"

        seconds = ms / 1000

        #
        # < 1 minute
        #
        if seconds < 60:
            return f"{seconds:.2f}s"

        minutes = int(seconds // 60)
        seconds = int(seconds % 60)

        #
        # < 1 hour
        #
        if minutes < 60:
            return f"{minutes}m{seconds:02d}s"

        hours = minutes // 60
        minutes = minutes % 60

        return f"{hours}h{minutes:02d}m{seconds:02d}s"

    def log(self, msg, display_last_log_interval=True):
        now = datetime.datetime.now()
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        if self._last_timestamp:
            delta_ms = (now - self._last_timestamp).total_seconds() * 1000
        interval_str = ""
        if (
            display_last_log_interval
            and (self._last_timestamp is not None)
            and (delta_ms >= 10)
        ):
            interval_str = f"  <[purple]{self.format_duration(delta_ms)}[/]>"

        self._last_timestamp = now
        print(f"[{timestamp_str}] {msg}{interval_str}")


logger = Logger()
