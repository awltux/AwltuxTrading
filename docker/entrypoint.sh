#!/bin/sh
# Two processes in one container, and the reason there are two.
#
# The scheduler must be exactly one process -- two of them run every job twice against the same
# database -- while the web tier wants several, because one uvicorn worker is one interpreter and
# a page render is CPU-bound Python that threads cannot share. Measured 2026-10-20: one instrument
# page 69-87 ms warm, seven at once 6.3 s each. So the scheduler runs alone and the web tier runs
# `AWLTUX_WEB_WORKERS` workers, and the workers reach the scheduler over loopback instead of
# owning it (see `awltux/scheduler/control.py`).
#
# Migrate first, and only once: the `&&` is deliberate. Serving on a schema the code does not
# expect produces 500s that look like application bugs, which is how a missing migration once
# went unnoticed until the dashboard failed.
#
# Either process exiting stops the container. A running web tier without a scheduler looks
# healthy and runs nothing, which is the failure this supervisor exists to make impossible.
set -eu

python -m awltux.cli migrate

python -m awltux.cli schedule &
scheduler=$!

python -m awltux.cli serve --workers "${AWLTUX_WEB_WORKERS:-1}" &
web=$!

stop() {
    # The scheduler drains in its own SIGTERM handler, bounded by
    # `shutdown_drain_seconds`; the web tier just stops accepting. `awltux quiet` before a
    # rebuild is still the way to leave nothing to interrupt.
    kill -TERM "$scheduler" "$web" 2>/dev/null || true
}
trap stop TERM INT

# POSIX sh has no `wait -n`, so poll and then reap. One second is the resolution a container
# restart cares about.
while kill -0 "$scheduler" 2>/dev/null && kill -0 "$web" 2>/dev/null; do
    sleep 1
done

echo "one of the two processes exited; stopping the other" >&2
if ! kill -0 "$scheduler" 2>/dev/null; then
    echo "the scheduler process exited first -- the web tier serves pages but runs no jobs" >&2
fi
stop
wait "$web" 2>/dev/null || true
wait "$scheduler" 2>/dev/null || true
