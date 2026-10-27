"""HTTP admission and bounded NAS shutdown without doing work in signal handlers."""
from contextlib import contextmanager
import os
import signal
import threading


class Stopping(Exception):
    pass


class Requests:
    """Drain handlers doing application work, excluding idle browser sockets."""
    def __init__(self):
        self.condition = threading.Condition()
        self.closing = False
        self.count = 0

    @contextmanager
    def active(self):
        with self.condition:
            if self.closing:
                raise Stopping()
            self.count += 1
        try:
            yield
        finally:
            with self.condition:
                self.count -= 1
                self.condition.notify_all()

    def close(self):
        with self.condition:
            self.closing = True

    def drain(self):
        with self.condition:
            self.condition.wait_for(lambda: self.count == 0)


def serve(server, requests, executors, *, shutdown_timeout=20):
    """Handle TERM/INT on the main thread and drain work before normal exit.

    The NAS deadline fits inside Compose's 30-second grace period. Docker's
    init/namespace cleans up children if a stuck operation requires exit 1.
    Local mode passes None and allows active exports to finish, as before.
    """
    stop_signal = None

    def stop(signum, frame):
        # No locks, IO or server.shutdown() in the handler. The accept loop
        # notices this flag within its timeout, avoiding same-thread deadlocks.
        nonlocal stop_signal
        if stop_signal is None:
            stop_signal = signum

    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    server.timeout = .25
    finished = threading.Event()

    def deadline():
        if not finished.wait(shutdown_timeout):
            try:
                os.write(2, b"Shutdown deadline reached; unfinished work was interrupted. Exiting with status 1.\n")
            finally:
                os._exit(1)

    try:
        while stop_signal is None:
            server.handle_request()
    finally:
        reason = signal.Signals(stop_signal).name if stop_signal is not None else "server exit"
        print(f"Shutdown requested ({reason}). Draining active requests and background work.", flush=True)
        if shutdown_timeout is not None:
            threading.Thread(target=deadline, name="shutdown-deadline", daemon=True).start()
        requests.close()
        try:
            server.server_close()
            requests.drain()
        finally:
            # Cancel every pool's pending work before waiting for any one pool.
            for executor in executors:
                executor.shutdown(wait=False, cancel_futures=True)
            for executor in executors:
                executor.shutdown(wait=True)
        print("Shutdown complete. Active requests finished; queued background tasks cancelled.", flush=True)
        finished.set()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
