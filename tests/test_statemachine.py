# -*- coding: utf-8 -*-
"""
Offline tests for the sleep timer state machine.  Run with:

    python3 -m unittest discover -s tests -v

No Kodi installation required: statemachine.py has no xbmc dependency.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from resources.lib import statemachine as sm


class FakeIO(object):
    def __init__(self, volume=100):
        self.volume = volume
        self.events = []
        self.tv_off_count = 0
        self.tv_on_count = 0
        self.stopped = 0
        self.screensaver = 0
        self.notifications = []

    def get_volume(self):
        return self.volume

    def set_volume(self, pct):
        self.volume = max(0, min(100, int(pct)))
        self.events.append(("volume", self.volume))

    def tv_off(self):
        self.tv_off_count += 1
        self.events.append(("tv_off", None))

    def tv_on(self):
        self.tv_on_count += 1
        self.events.append(("tv_on", None))

    def stop_playback(self):
        self.stopped += 1
        self.events.append(("stop", None))

    def activate_screensaver(self):
        self.screensaver += 1
        self.events.append(("screensaver", None))

    def notify(self, msg, seconds=8):
        self.notifications.append(msg)

    def notify_ramp(self, seconds):
        self.notifications.append("ramp:%d" % seconds)

    def sleep(self, seconds):
        return True

    def log(self, msg, force=False):
        self.events.append(("log", msg))


class Clock(object):
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def make(sleep_min=45, tvoff_min=0, reduction=7, interval=5,
         tv_off_command="ir-off", volume=100, notify=True):
    cfg = sm.Config(
        enabled=True,
        movie_sleep_timer=sleep_min * 60,
        tv_off_timer=tvoff_min * 60,
        volume_reduction_percent=reduction,
        volume_reduction_interval=interval,
        notify_on_ramp=notify,
        tv_off_command=tv_off_command,
        tv_on_command="cec-on",
        stop_grace_period=60,
        volume_restore_delay=5,
    )
    io = FakeIO(volume=volume)
    clock = Clock()
    machine = sm.SleepTimerMachine(io, lambda: cfg, clock)
    return machine, io, clock, cfg


def run_for(machine, clock, seconds, playing=True, activity_at=()):
    """Tick once per second for `seconds`, injecting activity at given offsets."""
    start = clock.now
    for _ in range(int(seconds)):
        offset = int(clock.now - start)
        machine.tick(playing, offset in activity_at)
        clock.advance(1)


class TestConfig(unittest.TestCase):
    def test_tv_off_disabled_when_zero(self):
        _, _, _, cfg = make(tvoff_min=0)
        self.assertFalse(cfg.tv_off_active)

    def test_tv_off_disabled_without_command(self):
        _, _, _, cfg = make(tvoff_min=10, tv_off_command="")
        self.assertFalse(cfg.tv_off_active)

    def test_tv_off_disabled_when_not_smaller_than_sleep(self):
        for tvoff in (45, 50):
            _, _, _, cfg = make(sleep_min=45, tvoff_min=tvoff)
            self.assertFalse(cfg.tv_off_active, tvoff)

    def test_tv_off_active(self):
        _, _, _, cfg = make(sleep_min=45, tvoff_min=10)
        self.assertTrue(cfg.tv_off_active)


class TestHappyPath(unittest.TestCase):
    def test_idle_to_watching(self):
        m, io, clock, _ = make()
        m.tick(False, False)
        self.assertEqual(m.state, sm.IDLE)
        m.tick(True, False)
        self.assertEqual(m.state, sm.WATCHING)

    def test_tv_off_then_ramp_then_turnoff(self):
        """45 min sleep, TV off at 10 min: the documented main scenario."""
        m, io, clock, cfg = make(sleep_min=45, tvoff_min=10)
        m.tick(True, False)
        self.assertEqual(m.state, sm.WATCHING)

        # advance to just before 10 min
        clock.advance(9 * 60)
        m.tick(True, False)
        self.assertEqual(m.state, sm.WATCHING)
        self.assertEqual(io.tv_off_count, 0)

        # cross 10 min -> TV off, audio continues
        clock.advance(70)
        m.tick(True, False)
        self.assertEqual(m.state, sm.WATCHING_TV_OFF)
        self.assertEqual(io.tv_off_count, 1)
        self.assertTrue(m.tv_is_off)

        # the IR toggle must never be re-sent while in this state
        for _ in range(30):
            clock.advance(10)
            m.tick(True, False)
        self.assertEqual(io.tv_off_count, 1)
        self.assertEqual(m.state, sm.WATCHING_TV_OFF)

        # cross 45 min -> ramp
        clock.advance(45 * 60)
        m.tick(True, False)
        self.assertEqual(m.state, sm.RAMP_DOWN)
        self.assertTrue(io.notifications)

        # ramp to zero
        for _ in range(200):
            if m.state != sm.RAMP_DOWN:
                break
            clock.advance(5)
            m.tick(True, False)
        self.assertEqual(io.volume, 100)          # restored in TurnOff
        self.assertEqual(m.state, sm.IDLE)
        self.assertEqual(io.stopped, 1)
        self.assertEqual(io.screensaver, 1)
        # crucially: TV off was sent exactly once in total
        self.assertEqual(io.tv_off_count, 1)

    def test_no_tv_off_stage_sends_ir_once_in_turnoff(self):
        m, io, clock, _ = make(sleep_min=45, tvoff_min=0)
        m.tick(True, False)
        clock.advance(45 * 60 + 1)
        m.tick(True, False)
        self.assertEqual(m.state, sm.RAMP_DOWN)
        self.assertEqual(io.tv_off_count, 0)
        for _ in range(200):
            if m.state != sm.RAMP_DOWN:
                break
            clock.advance(5)
            m.tick(True, False)
        self.assertEqual(io.tv_off_count, 1)
        self.assertEqual(m.state, sm.IDLE)


class TestRamp(unittest.TestCase):
    def test_additive_steps(self):
        m, io, clock, _ = make(sleep_min=1, reduction=7, interval=5, volume=20)
        m.tick(True, False)
        clock.advance(61)
        m.tick(True, False)
        self.assertEqual(m.state, sm.RAMP_DOWN)
        seen = []
        for _ in range(20):
            if m.state != sm.RAMP_DOWN:
                break
            clock.advance(5)
            m.tick(True, False)
            seen.append(io.volume)
        # 20 -> 13 -> 6 -> 0, then TurnOff restores the saved 20
        self.assertEqual(seen[:2], [13, 6])
        self.assertEqual(m.state, sm.IDLE)
        self.assertEqual(io.volume, 20)

    def test_interval_is_respected(self):
        m, io, clock, _ = make(sleep_min=1, interval=5)
        m.tick(True, False)
        clock.advance(61)
        m.tick(True, False)
        before = io.volume
        self.assertEqual(before, 100)           # no step on entry
        clock.advance(2)
        m.tick(True, False)
        self.assertEqual(io.volume, before)     # too early
        clock.advance(4)
        m.tick(True, False)
        self.assertLess(io.volume, before)

    def test_activity_restores_volume_and_wakes_tv(self):
        m, io, clock, _ = make(sleep_min=1, tvoff_min=0, volume=80)
        m.tick(True, False)
        clock.advance(61)
        m.tick(True, False)
        clock.advance(5)
        m.tick(True, False)
        self.assertLess(io.volume, 80)
        m.tick(True, True)                       # user presses a key
        self.assertEqual(m.state, sm.WATCHING)
        self.assertEqual(io.volume, 80)
        self.assertAlmostEqual(m.elapsed, 0.0, places=3)

    def test_activity_during_ramp_after_tv_off_sends_tv_on(self):
        m, io, clock, _ = make(sleep_min=10, tvoff_min=5)
        m.tick(True, False)
        clock.advance(5 * 60 + 1)
        m.tick(True, False)
        self.assertEqual(m.state, sm.WATCHING_TV_OFF)
        clock.advance(5 * 60)
        m.tick(True, False)
        self.assertEqual(m.state, sm.RAMP_DOWN)
        m.tick(True, True)
        self.assertEqual(io.tv_on_count, 1)
        self.assertFalse(m.tv_is_off)
        self.assertEqual(m.state, sm.WATCHING)

    def test_saved_volume_not_overwritten_during_ramp(self):
        """Regression: sampling during the ramp would restore a near-zero value."""
        m, io, clock, _ = make(sleep_min=1, volume=90)
        m.tick(True, False)
        clock.advance(61)
        m.tick(True, False)
        for _ in range(3):
            clock.advance(5)
            m.tick(True, False)
        self.assertEqual(m.saved_volume, 90)


class TestActivity(unittest.TestCase):
    def test_activity_resets_timer_in_watching(self):
        m, io, clock, _ = make(sleep_min=45)
        m.tick(True, False)
        clock.advance(44 * 60)
        m.tick(True, True)                       # e.g. a pause keypress
        self.assertEqual(m.state, sm.WATCHING)
        clock.advance(44 * 60)
        m.tick(True, False)
        self.assertEqual(m.state, sm.WATCHING)   # fresh 45 min

    def test_activity_in_tv_off_returns_to_watching_with_tv_on(self):
        m, io, clock, _ = make(sleep_min=45, tvoff_min=10)
        m.tick(True, False)
        clock.advance(10 * 60 + 1)
        m.tick(True, False)
        self.assertEqual(m.state, sm.WATCHING_TV_OFF)
        m.tick(True, True)
        self.assertEqual(m.state, sm.WATCHING)
        self.assertEqual(io.tv_on_count, 1)
        self.assertFalse(m.tv_is_off)

        # and the TV-off stage can fire again later, once
        clock.advance(10 * 60 + 1)
        m.tick(True, False)
        self.assertEqual(m.state, sm.WATCHING_TV_OFF)
        self.assertEqual(io.tv_off_count, 2)

    def test_volume_tracked_while_watching(self):
        m, io, clock, _ = make()
        m.tick(True, False)
        io.volume = 55                            # user turns it down
        clock.advance(10)
        m.tick(True, False)
        self.assertEqual(m.saved_volume, 55)


class TestPlaybackLoss(unittest.TestCase):
    def test_short_gap_does_not_end_session(self):
        m, io, clock, _ = make(sleep_min=45)
        m.tick(True, False)
        for _ in range(30):
            clock.advance(1)
            m.tick(False, False)
        self.assertEqual(m.state, sm.WATCHING)
        m.tick(True, False)
        self.assertEqual(m.state, sm.WATCHING)

    def test_long_gap_returns_to_idle(self):
        m, io, clock, _ = make(sleep_min=45)
        m.tick(True, False)
        for _ in range(70):
            clock.advance(1)
            m.tick(False, False)
        self.assertEqual(m.state, sm.IDLE)

    def test_idle_restores_volume_after_abnormal_exit(self):
        """Stopping the movie mid-ramp must not leave the volume reduced."""
        m, io, clock, _ = make(sleep_min=1, volume=75)
        m.tick(True, False)
        clock.advance(61)
        m.tick(True, False)
        for _ in range(3):
            clock.advance(5)
            m.tick(True, False)
        self.assertLess(io.volume, 75)
        for _ in range(70):
            clock.advance(1)
            m.tick(False, False)
        self.assertEqual(m.state, sm.IDLE)
        self.assertEqual(io.volume, 75)

    def test_tv_flag_cleared_on_idle(self):
        m, io, clock, _ = make(sleep_min=45, tvoff_min=10)
        m.tick(True, False)
        clock.advance(10 * 60 + 1)
        m.tick(True, False)
        self.assertTrue(m.tv_is_off)
        for _ in range(70):
            clock.advance(1)
            m.tick(False, False)
        self.assertFalse(m.tv_is_off)


class TestDisabled(unittest.TestCase):
    def test_disabled_forces_idle_and_restores_volume(self):
        cfg_holder = {}

        def provider():
            return cfg_holder["cfg"]

        cfg_holder["cfg"] = sm.Config(
            enabled=True, movie_sleep_timer=60, tv_off_timer=0,
            volume_reduction_percent=7, volume_reduction_interval=5,
            notify_on_ramp=False, tv_off_command="off", tv_on_command="on",
            stop_grace_period=60, volume_restore_delay=0,
        )
        io = FakeIO(volume=64)
        clock = Clock()
        m = sm.SleepTimerMachine(io, provider, clock)
        m.tick(True, False)
        clock.advance(61)
        m.tick(True, False)
        clock.advance(5)
        m.tick(True, False)
        self.assertEqual(m.state, sm.RAMP_DOWN)

        cfg_holder["cfg"] = sm.Config(
            enabled=False, movie_sleep_timer=60, tv_off_timer=0,
            volume_reduction_percent=7, volume_reduction_interval=5,
            notify_on_ramp=False, tv_off_command="off", tv_on_command="on",
            stop_grace_period=60, volume_restore_delay=0,
        )
        m.tick(True, False)
        self.assertEqual(m.state, sm.IDLE)
        self.assertEqual(io.volume, 64)


if __name__ == "__main__":
    unittest.main()
