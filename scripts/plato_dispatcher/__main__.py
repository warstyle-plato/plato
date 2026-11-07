"""Private local CLI. stdout is fixed status/boolean/count JSON only."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import sys
import threading

from .runtime import Dispatcher, SDKAdapter, StopRequested
from .store import SafeError, Store, private_input


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's normal error can echo private arguments and paths.
        raise SafeError("invalid_arguments")


def parser():
    p = Parser(description="Private PLATO SDK queue host")
    p.add_argument("--store-dir", type=Path, required=True)
    p.add_argument("--workspace", type=Path, required=True)
    sub = p.add_subparsers(dest="command", required=True, parser_class=Parser)
    for name in ("submit", "resume"):
        q = sub.add_parser(name)
        q.add_argument("--task", required=True)
        q.add_argument("--request", required=True)
        q.add_argument("--input-file", type=Path, required=True)
    q = sub.add_parser("status")
    q.add_argument("--task")
    q.add_argument("--request")
    sub.add_parser("run-once")
    q = sub.add_parser("retry-auth")
    q.add_argument("--request", required=True)
    q = sub.add_parser("reconcile")
    q.add_argument("--request", required=True)
    q = sub.add_parser("serve")
    q.add_argument("--poll-seconds", type=float, default=5)
    return p


def emit(value):
    print(json.dumps(value, sort_keys=True), flush=True)


def main(argv=None):
    os.umask(0o077)
    stop = threading.Event()
    active = True

    def terminate(signum, frame):
        stop.set()
        if active:
            raise StopRequested()

    previous = {s: signal.signal(s, terminate) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        args = parser().parse_args(argv)
        store = Store(args.store_dir)
        dispatcher = Dispatcher(store, lambda: SDKAdapter(args.workspace, store.directory))
        if args.command in ("submit", "resume"):
            emit(store.submit(args.task, args.request, private_input(args.input_file), continuation=args.command == "resume"))
        elif args.command == "status":
            emit(store.status(args.task, args.request))
        elif args.command == "retry-auth":
            with store.worker():
                emit(store.retry_auth(args.request))
        elif args.command == "reconcile":
            active = True
            emit(dispatcher.reconcile(args.request))
        elif args.command == "run-once":
            active = True
            emit(dispatcher.run_once())
        else:
            if not 0.1 <= args.poll_seconds <= 300:
                raise SafeError("invalid_poll_interval")
            last = None
            while not stop.is_set():
                active = True
                try:
                    result = dispatcher.run_once()
                except SafeError as exc:
                    if exc.code != "busy":
                        raise
                    result = {"status": "busy", "claimed": False}
                finally:
                    active = False
                if result != last:
                    emit(result)
                    last = result
                if not result.get("claimed"):
                    stop.wait(args.poll_seconds)
        return 0
    except (StopRequested, KeyboardInterrupt):
        emit({"status": "stopping"})
        return 0
    except SafeError as exc:
        emit({"status": exc.code})
        return 2
    except Exception:
        emit({"status": "local_error"})
        return 2
    finally:
        for s, handler in previous.items():
            signal.signal(s, handler)


if __name__ == "__main__":
    sys.exit(main())
