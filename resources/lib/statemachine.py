# -*- coding: utf-8 -*-
"""
Pure, Kodi-independent sleep timer state machine.

The machine is deliberately free of any xbmc import so that it can be unit
tested and reasoned about in isolation.  Everything it needs from the outside
world is supplied through two objects:

    cfg   -- a Config snapshot (plain values, read once per tick)
    io    -- an object implementing the Actuators protocol (see below)

Actuators protocol
------------------
    io.get_volume() -> int          current Kodi volume in percent (0..100)
    io.set_volume(pct: int)         set Kodi volume
    io.tv_off()                     fire the IR TV-off command (TOGGLE!)
    io.tv_on()                      fire the CEC TV-on command
    io.stop_playback()              stop the active player
    io.activate_screensaver()       force Kodi's screensaver on
    io.notify(msg, seconds)         OSD notification
    io.sleep(seconds) -> bool       interruptible sleep, False if aborting
    io.log(msg)                     debug log

States
------
    Idle            nothing playing / not watching
    Watching        playback running, TV on, single elapsed timer running
    WatchingTvOff   playback running, TV switched off, audio continues
    RampDown        volume being faded out additively
    TurnOff         terminal action sequence, always returns to Idle
"""

IDLE = "Idle"
WATCHING = "Watching"
WATCHING_TV_OFF = "WatchingTvOff"
RAMP_DOWN = "RampDown"
TURN_OFF = "TurnOff"


class Config(object):
    """Immutable snapshot of the addon settings, in base units (seconds)."""

    __slots__ = (
        "enabled",
        "movie_sleep_timer",
        "tv_off_timer",
        "volume_reduction_percent",
        "volume_reduction_interval",
        "notify_on_ramp",
        "tv_off_command",
        "tv_on_command",
        "stop_grace_period",
        "volume_restore_delay",
    )

    def __init__(self, **kw):
        for name in self.__slots__:
            setattr(self, name, kw[name])

    @property
    def tv_off_active(self):
        """
        The early TV-off stage is only meaningful when
          * a TV-off command is configured at all,
          * the timer is not 0 (0 == disabled by definition), and
          * it is strictly smaller than the total sleep time.

        tv_off_timer >= movie_sleep_timer is treated as 'disabled', which
        collapses to exactly the tv_off_timer == 0 behaviour: TV and movie go
        off together at movie_sleep_timer.
        """
        return (
            bool(self.tv_off_command)
            and self.tv_off_timer > 0
            and self.tv_off_timer < self.movie_sleep_timer
        )


class SleepTimerMachine(object):
    def __init__(self, io, config_provider, clock):
        self._io = io
        self._config_provider = config_provider
        self._clock = clock

        self.state = IDLE
        self._entered_at = clock()
        self._timer_base = clock()          # reset on every Watching entry
        self._not_playing_since = None
        self._last_ramp_step = 0.0

        self.saved_volume = None            # sampled in Watching/WatchingTvOff
        self.tv_is_off = False              # IR toggle bookkeeping

    # ------------------------------------------------------------------ utils

    @property
    def elapsed(self):
        return self._clock() - self._timer_base

    def _goto(self, state):
        if state == self.state:
            return
        self._io.log("state %s -> %s (t=%.0fs)" % (self.state, state, self.elapsed))
        self.state = state
        self._entered_at = self._clock()
        self._on_enter(state)

    def _restore_volume(self):
        if self.saved_volume is None:
            return
        self._io.log("restoring volume to %d%%" % self.saved_volume)
        self._io.set_volume(self.saved_volume)

    def _sample_volume(self):
        """Track the user's volume while they are still in control of it."""
        vol = self._io.get_volume()
        if vol is not None:
            self.saved_volume = vol

    # ----------------------------------------------------------- entry actions

    def _on_enter(self, state):
        if state == IDLE:
            # Idempotent safety net: every abnormal exit path lands here and
            # must leave the volume the way the user had it.
            self._restore_volume()
            self.saved_volume = None
            self.tv_is_off = False
            self._not_playing_since = None

        elif state == WATCHING:
            self._timer_base = self._clock()
            self._not_playing_since = None
            self._sample_volume()

        elif state == WATCHING_TV_OFF:
            if not self.tv_is_off:
                self._io.log("switching TV off (audio continues)")
                self._io.tv_off()
                self.tv_is_off = True

        elif state == TURN_OFF:
            self._run_turn_off_sequence()

        elif state == RAMP_DOWN:
            # First reduction happens after one full interval, so the OSD
            # notification is visible before anything becomes quieter.
            self._last_ramp_step = self._clock()
            cfg = self._config_provider()
            if self.saved_volume is None:
                self._sample_volume()
            if cfg.notify_on_ramp:
                steps = max(
                    1,
                    int(
                        (self.saved_volume or 0) / max(1, cfg.volume_reduction_percent)
                    ),
                )
                self._io.notify_ramp(int(steps * cfg.volume_reduction_interval))

    # -------------------------------------------------------------- transitions

    def tick(self, playing, user_activity):
        """
        Advance the machine by one step.

        playing        -- True while a relevant (video) player is active,
                          including while paused
        user_activity  -- True if a player callback or the idle timer reported
                          interaction since the previous tick.  Volume writes
                          performed by this machine are NEVER reported here.
        """
        cfg = self._config_provider()

        if not cfg.enabled:
            if self.state != IDLE:
                self._goto(IDLE)
            return

        handler = {
            IDLE: self._tick_idle,
            WATCHING: self._tick_watching,
            WATCHING_TV_OFF: self._tick_watching_tv_off,
            RAMP_DOWN: self._tick_ramp_down,
            TURN_OFF: self._tick_turn_off,
        }[self.state]
        handler(cfg, playing, user_activity)

    # --- Idle

    def _tick_idle(self, cfg, playing, user_activity):
        if playing:
            self._goto(WATCHING)

    # --- shared guards

    def _playback_lost(self, cfg, playing):
        """
        True once playback has been absent for stop_grace_period seconds.
        A short gap (next episode, stream re-buffer, user browsing the library
        between two files) must not tear the session down.
        """
        if playing:
            self._not_playing_since = None
            return False
        if self._not_playing_since is None:
            self._not_playing_since = self._clock()
            return False
        return (self._clock() - self._not_playing_since) >= cfg.stop_grace_period

    # --- Watching

    def _tick_watching(self, cfg, playing, user_activity):
        if self._playback_lost(cfg, playing):
            self._goto(IDLE)
            return

        if user_activity:
            # Re-enter Watching: resets the elapsed timer and re-samples volume.
            self._io.log("user activity -> timer reset")
            self._timer_base = self._clock()
            self._sample_volume()
            return

        if playing:
            self._sample_volume()

        if self.elapsed >= cfg.movie_sleep_timer:
            self._goto(RAMP_DOWN)
            return

        if cfg.tv_off_active and self.elapsed >= cfg.tv_off_timer:
            self._goto(WATCHING_TV_OFF)

    # --- WatchingTvOff

    def _tick_watching_tv_off(self, cfg, playing, user_activity):
        if self._playback_lost(cfg, playing):
            self._goto(IDLE)
            return

        if user_activity:
            self._wake_tv()
            self._goto(WATCHING)
            return

        if playing:
            self._sample_volume()

        if self.elapsed >= cfg.movie_sleep_timer:
            self._goto(RAMP_DOWN)

    # --- RampDown

    def _tick_ramp_down(self, cfg, playing, user_activity):
        if self._playback_lost(cfg, playing):
            self._goto(IDLE)
            return

        if user_activity:
            self._io.log("user activity during ramp -> aborting sleep")
            self._restore_volume()
            self._wake_tv()
            self._goto(WATCHING)
            return

        now = self._clock()
        if (now - self._last_ramp_step) < cfg.volume_reduction_interval:
            return
        self._last_ramp_step = now

        current = self._io.get_volume()
        if current is None:
            current = 0
        target = max(0, current - cfg.volume_reduction_percent)
        self._io.log("ramp %d%% -> %d%%" % (current, target))
        self._io.set_volume(target)

        if target <= 0:
            self._goto(TURN_OFF)

    # --- TurnOff

    def _tick_turn_off(self, cfg, playing, user_activity):
        # Reached only if the entry sequence was interrupted; retry it.
        self._run_turn_off_sequence()

    def _run_turn_off_sequence(self):
        """
        Purely sequential, runs once, then unconditionally returns to Idle.
        Waking the TV up afterwards is Kodi's normal screensaver-deactivation
        behaviour (CEC) and needs no handling here.
        """
        cfg = self._config_provider()
        if not self.tv_is_off:
            self._io.log("switching TV off")
            self._io.tv_off()
            self.tv_is_off = True

        self._io.log("stopping playback")
        self._io.stop_playback()
        self._io.activate_screensaver()

        # Wait until playback has really ended, otherwise restoring the volume
        # produces an audible burst of the last frames.
        self._io.sleep(cfg.volume_restore_delay)

        self._restore_volume()
        self._goto(IDLE)

    # --------------------------------------------------------------- actuators

    def _wake_tv(self):
        if self.tv_is_off:
            self._io.log("switching TV on")
            self._io.tv_on()
            self.tv_is_off = False
