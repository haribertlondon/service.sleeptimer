# -*- coding: utf-8 -*-
"""
Pure, Kodi-independent sleep timer state machine.

No xbmc import: everything the machine needs from the outside world arrives
through an injected `io` object, which makes the whole thing unit-testable.

Actuators protocol
------------------
    io.get_volume() -> int | None    current Kodi volume in percent (0..100)
    io.set_volume(pct)              set Kodi volume
    io.tv_off()                     start the cancellable TV-off worker
    io.tv_on()                      cancel any TV-off worker, switch TV on
    io.stop_playback()              stop the active player
    io.activate_screensaver()       force Kodi's screensaver on
    io.notify_ramp(seconds)         OSD notification at ramp start
    io.sleep(seconds) -> bool       interruptible sleep
    io.log(msg, force=False)        log

States
------
    Idle            not watching
    Watching        playback running, TV on, elapsed timer running
    WatchingTvOff   playback running, TV off, audio continues
    RampDown        volume fading out additively
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
        "session_max_timer",
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
        The early TV-off stage is only meaningful when a command is configured,
        the timer is non-zero, and it is strictly below the total sleep time.
        tv_off_timer >= movie_sleep_timer collapses to the disabled behaviour:
        TV and playback go off together at movie_sleep_timer.
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
        self._timer_base = clock()      # reset by user activity
        self._session_base = clock()    # NOT reset by user activity
        self._not_playing_since = None
        self._last_ramp_step = 0.0

        self.saved_volume = None        # sampled in Watching / WatchingTvOff
        self.tv_is_off = False          # IR toggle bookkeeping

    # ------------------------------------------------------------------ utils

    @property
    def elapsed(self):
        """Time since the last user interaction (or session start)."""
        return self._clock() - self._timer_base

    @property
    def session_elapsed(self):
        """Time since the session began, immune to user activity."""
        return self._clock() - self._session_base

    def _goto(self, state):
        if state == self.state:
            return
        self._io.log(
            "state %s -> %s (t=%.0fs, session=%.0fs)"
            % (self.state, state, self.elapsed, self.session_elapsed)
        )
        self.state = state
        self._on_enter(state)

    def _restore_volume(self):
        if self.saved_volume is None:
            return
        self._io.log("restoring volume to %d%%" % self.saved_volume)
        self._io.set_volume(self.saved_volume)

    def _sample_volume(self):
        vol = self._io.get_volume()
        if vol is not None:
            self.saved_volume = vol

    def _reset_timer(self, reason):
        self._io.log("user activity (%s) -> timer reset" % reason)
        self._timer_base = self._clock()
        self._sample_volume()

    # ----------------------------------------------------------- entry actions

    def _on_enter(self, state):
        if state == IDLE:
            # Safety net: every abnormal exit lands here and must leave the
            # volume the way the user had it.
            self._restore_volume()
            self.saved_volume = None
            self._io.tv_on_cancel_only()
            self.tv_is_off = False
            self._not_playing_since = None

        elif state == WATCHING:
            self._timer_base = self._clock()
            self._not_playing_since = None
            self._sample_volume()

        elif state == WATCHING_TV_OFF:
            if not self.tv_is_off:
                self._io.log("switching TV off (audio continues)", force=True)
                self._io.tv_off()
                self.tv_is_off = True

        elif state == RAMP_DOWN:
            # First reduction happens after one full interval so the OSD
            # notification is readable before anything gets quieter.
            self._last_ramp_step = self._clock()
            cfg = self._config_provider()
            if self.saved_volume is None:
                self._sample_volume()
            if cfg.notify_on_ramp:
                steps = max(
                    1,
                    int((self.saved_volume or 0)
                        / max(1, cfg.volume_reduction_percent)),
                )
                self._io.notify_ramp(int(steps * cfg.volume_reduction_interval))

        elif state == TURN_OFF:
            self._run_turn_off_sequence()

    # ---------------------------------------------------------- session start

    def _start_session(self):
        self._session_base = self._clock()
        self._goto(WATCHING)

    # -------------------------------------------------------------- transitions

    def tick(self, playing, user_activity, activity_reason=""):
        """
        Advance the machine by one step.

        playing          -- True while a relevant player is active, including
                            while paused
        user_activity    -- True only for *genuine* user interaction.  Playlist
                            advancement (onPlayBackStarted / onAVStarted /
                            Player.OnPlay) and this machine's own volume writes
                            are NOT user activity.
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
        handler(cfg, playing, user_activity, activity_reason)

    # --- Idle

    def _tick_idle(self, cfg, playing, user_activity, reason):
        if playing:
            self._start_session()

    # --- shared guards

    def _playback_lost(self, cfg, playing):
        """
        True once playback has been absent for stop_grace_period seconds.  A
        short gap (next playlist item, re-buffering stream, browsing the
        library) must not tear the session down.
        """
        if playing:
            self._not_playing_since = None
            return False
        if self._not_playing_since is None:
            self._not_playing_since = self._clock()
            return False
        return (self._clock() - self._not_playing_since) >= cfg.stop_grace_period

    def _deadline_reached(self, cfg):
        """
        The ramp starts when either the inactivity timer expires, or -- if a
        session cap is configured -- the session has run that long regardless
        of how often the timer was reset.  The cap is what guarantees the
        timer can never be starved by frequent interaction.
        """
        if self.elapsed >= cfg.movie_sleep_timer:
            return True
        return self._cap_reached(cfg)

    def _cap_reached(self, cfg):
        if cfg.session_max_timer <= 0:
            return False
        if self.session_elapsed < cfg.session_max_timer:
            return False
        self._io.log(
            "session cap reached (%.0fs) -> ramp" % self.session_elapsed,
            force=True,
        )
        return True

    # --- Watching

    def _tick_watching(self, cfg, playing, user_activity, reason):
        if self._playback_lost(cfg, playing):
            self._goto(IDLE)
            return

        if user_activity:
            self._reset_timer(reason)
            # The cap is still evaluated: it must not be starvable by
            # interaction, that is its entire purpose.
            if self._cap_reached(cfg):
                self._goto(RAMP_DOWN)
            return

        if playing:
            self._sample_volume()

        if self._deadline_reached(cfg):
            self._goto(RAMP_DOWN)
            return

        if cfg.tv_off_active and self.elapsed >= cfg.tv_off_timer:
            self._goto(WATCHING_TV_OFF)

    # --- WatchingTvOff

    def _tick_watching_tv_off(self, cfg, playing, user_activity, reason):
        if self._playback_lost(cfg, playing):
            self._goto(IDLE)
            return

        if user_activity:
            self._wake_tv()
            self._reset_timer(reason)
            self._goto(WATCHING)
            if self._cap_reached(cfg):
                self._goto(RAMP_DOWN)
            return

        if playing:
            self._sample_volume()

        if self._deadline_reached(cfg):
            self._goto(RAMP_DOWN)

    # --- RampDown

    def _tick_ramp_down(self, cfg, playing, user_activity, reason):
        if self._playback_lost(cfg, playing):
            self._goto(IDLE)
            return

        if user_activity:
            self._io.log("user activity (%s) during ramp -> abort" % reason,
                         force=True)
            self._restore_volume()
            self._wake_tv()
            self._session_base = self._clock()   # cap restarts too
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

    def _tick_turn_off(self, cfg, playing, user_activity, reason):
        # Only reached if the entry sequence was interrupted; retry it.
        self._run_turn_off_sequence()

    def _run_turn_off_sequence(self):
        """
        Sequential, runs once, then unconditionally returns to Idle.  Waking up
        afterwards is Kodi's normal screensaver deactivation (CEC).
        """
        cfg = self._config_provider()
        if not self.tv_is_off:
            self._io.log("switching TV off", force=True)
            self._io.tv_off()
            self.tv_is_off = True

        self._io.log("stopping playback", force=True)
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
            self._io.log("switching TV on", force=True)
            self._io.tv_on()
            self.tv_is_off = False
