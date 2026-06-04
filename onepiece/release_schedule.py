"""Best-effort release-schedule heuristic for One Piece.

There is no official API for chapter release dates. The observed pattern is:
roughly three weekly chapters released on Sundays, then a ~1-week break (about
once a month), plus occasional unscheduled hiatuses. So we can't *know* the next
date — we estimate it and adapt how hard we poll.

Strategy (purely time-based, robust to schedule drift):
  - For the first ~6 days after the last chapter we fetched, a new one isn't due
    yet, so poll slowly (default: once a day).
  - Once we cross that threshold, a chapter is "due": poll fast (default: hourly)
    until it appears, which resets the clock.
  - If nothing shows up for ~2 weeks, assume a real break/hiatus and back off to a
    politer cadence (default: every 6h) so we're not hammering hourly for nothing.

All thresholds are env-configurable. ``expected_next_release`` is provided for
display (e.g. the webapp) and is explicitly a guess, not a guarantee.
"""

import os
from dataclasses import dataclass
from datetime import timedelta

SUNDAY = 6  # Python weekday(): Monday=0 ... Sunday=6


@dataclass
class ScheduleConfig:
    idle: int = 86400          # cadence when a new chapter isn't due yet (1 day)
    window: int = 3600         # cadence once a chapter is due (1 hour)
    long_break: int = 21600    # cadence during a confirmed long break (6 hours)
    window_start_days: float = 6.0   # a chapter becomes "due" this long after the last
    long_break_days: float = 14.0    # past this with nothing new, assume a hiatus

    @classmethod
    def from_env(cls):
        g = os.environ.get
        return cls(
            idle=int(g("CHECK_INTERVAL_IDLE", cls.idle)),
            window=int(g("CHECK_INTERVAL_WINDOW", cls.window)),
            long_break=int(g("CHECK_INTERVAL_LONGBREAK", cls.long_break)),
            window_start_days=float(g("WINDOW_START_DAYS", cls.window_start_days)),
            long_break_days=float(g("LONG_BREAK_DAYS", cls.long_break_days)),
        )


def next_check_delay(now, last_release, cfg=None, expected_release=None):
    """Seconds to sleep before the next check. ``now``, ``last_release`` and
    ``expected_release`` are timezone-aware datetimes.

    If ``expected_release`` is set (a manual override, e.g. via opctl), it wins:
    idle until ~a day before it, then poll at the window cadence until a chapter
    lands, backing off only if it's long overdue. Otherwise fall back to the
    last-release heuristic. ``last_release`` None -> window cadence to orient."""
    cfg = cfg or ScheduleConfig()

    if expected_release is not None:
        until_open = (expected_release - now).total_seconds() - 86400  # window opens ~1 day before
        if until_open > 0:
            return int(min(cfg.idle, max(60.0, until_open)))
        overdue = (now - expected_release).total_seconds()
        if overdue >= cfg.long_break_days * 86400:
            return cfg.long_break
        return cfg.window

    if last_release is None:
        return cfg.window

    age_days = (now - last_release).total_seconds() / 86400.0

    if age_days < cfg.window_start_days:
        # Not due yet: wake when the window opens, but no longer than the idle cap.
        until_window = (cfg.window_start_days - age_days) * 86400.0
        return int(min(cfg.idle, max(60.0, until_window)))

    if age_days >= cfg.long_break_days:
        return cfg.long_break

    return cfg.window


def expected_next_release(last_release, release_weekday=SUNDAY):
    """Heuristic guess at the next release date: the first ``release_weekday``
    (default Sunday) on or after last_release + 6 days. Returns None if unknown.
    This is a guess — breaks and hiatuses routinely push it later."""
    if last_release is None:
        return None
    earliest = last_release + timedelta(days=6)
    days_ahead = (release_weekday - earliest.weekday()) % 7
    return earliest + timedelta(days=days_ahead)
