"""FMCSA hours-of-service clock (property-carrying driver, simplified).

Converts *driving* time into *elapsed* (wall-clock) time by inserting the
mandatory stops a solo driver must take:

* a 30-minute break once 8 hours have been driven since the last break, and
* a 10-hour off-duty rest after 11 hours of driving.

Driving continuously, 11 h of driving plus one 30-minute break fits inside the
14-hour on-duty window, so that window never binds and is not modelled.
"""

from __future__ import annotations

import math

HOUR = 3600.0
MAX_DRIVE_S = 11 * HOUR
BREAK_AFTER_S = 8 * HOUR
BREAK_S = 0.5 * HOUR
REST_S = 10 * HOUR
SHIFT_S = MAX_DRIVE_S + BREAK_S + REST_S  # one full drive/break/rest cycle


def elapsed_for_drive(drive_s: float, enabled: bool = True) -> float:
    """Wall-clock seconds needed to accumulate ``drive_s`` seconds of driving.

    A stop is only inserted once driving continues past it, so arriving exactly
    at the 11-hour mark does not add a rest at the destination.
    """
    if not enabled or drive_s <= 0:
        return max(0.0, drive_s)
    completed_shifts = math.ceil(drive_s / MAX_DRIVE_S) - 1
    in_shift = drive_s - completed_shifts * MAX_DRIVE_S
    breaks = completed_shifts + (1 if in_shift > BREAK_AFTER_S else 0)
    return drive_s + breaks * BREAK_S + completed_shifts * REST_S


def drive_for_elapsed(elapsed_s: float, enabled: bool = True) -> float:
    """Inverse of :func:`elapsed_for_drive`: driving done after ``elapsed_s``.

    While the driver is stopped, the returned driving time stays flat.
    """
    if not enabled or elapsed_s <= 0:
        return max(0.0, elapsed_s)
    shifts, t = divmod(elapsed_s, SHIFT_S)
    done = shifts * MAX_DRIVE_S
    if t <= BREAK_AFTER_S:
        return done + t
    if t <= BREAK_AFTER_S + BREAK_S:
        return done + BREAK_AFTER_S
    return done + min(MAX_DRIVE_S, t - BREAK_S)
