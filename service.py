# -*- coding: utf-8 -*-

""" Service Sleep Timer  (c)  2015 enen92, Solo0815

# This program is free software; you can redistribute it and/or modify it under the terms
# of the GNU General Public License as published by the Free Software Foundation;
# either version 2 of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
# without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program;
# if not, see <http://www.gnu.org/licenses/>.


"""

import datetime
import json
import os
import shutil

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ADDON_ID = 'service.sleeptimer'
SIGNAL_FILENAME = 'key_signal'
KEYMAP_FILENAME = 'sleeptimer_keymap.xml'

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def _log(message):
    """Write *message* to the Kodi log at DEBUG level."""
    xbmc.log(ADDON_ID + ": " + str(message), level=xbmc.LOGDEBUG)


def _debug(message, debug):
    """Write *message* to the Kodi log only when *debug* is ``'true'``."""
    if debug == 'true':
        _log("DEBUG: " + str(message))


def _print_playing_file(debug):
    """Log the currently playing file when debug mode is active."""
    if debug == 'true':
        try:
            _log(str(xbmc.Player().getPlayingFile()))
        except RuntimeError:
            pass


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def get_kodi_time():
    """Return the current Kodi system time as an integer ``HHMM``."""
    am_pm = xbmc.getInfoLabel('System.Time(xx)').lower()
    system_time = xbmc.getInfoLabel('System.Time(hh:mm)')
    hour = int(system_time.split(':')[0])
    minute = system_time.split(':')[1]
    if am_pm == 'pm':
        if hour != 12:
            hour += 12
    elif am_pm == 'am':
        if hour == 12:
            hour = 0
    # Zero-pad hour to always produce a 4-digit number (e.g. "0030", "1305")
    return int(str(hour).zfill(2) + str(minute))


def should_supervise(kodi_time, start_time, end_time, mode, debug):
    """Return ``True`` if the service should be active right now.

    *mode* ``'0'`` means "always supervise".  Any other value limits
    supervision to the window between *start_time* and *end_time*
    (both integers in ``HHMM`` format).  Debug mode forces ``True``.
    """
    if mode == '0' or debug == 'true':
        return True
    if start_time == 0 and end_time == 0:
        return True

    if kodi_time > start_time:
        effective_end = end_time if end_time > start_time else end_time + 2400
        return kodi_time < effective_end
    else:
        return kodi_time < end_time


def _wait_minutes(monitor, minutes, debug):
    """Sleep for *minutes* minutes, returning ``True`` if Kodi wants to abort."""
    _debug("next check in " + str(minutes) + " min", debug)
    return monitor.waitForAbort(int(minutes) * 60)


# ---------------------------------------------------------------------------
# Alternative Detection Mode
# ---------------------------------------------------------------------------

class AlternativeDetectionMode(xbmc.Player):
    """Track user interaction through playback events and external signals.

    Instead of relying on ``xbmc.getGlobalIdleTime()`` (which may not
    reflect actual user inactivity in recent Kodi versions), this class
    records the timestamp of the last meaningful user action and computes
    idle time from that.
    """

    def __init__(self, *args):
        _log("Init Alternative mode")
        self.reset_time()
        self.last_ended = None

    # -- helpers -----------------------------------------------------------

    def _seconds_since(self, dt):
        """Return seconds elapsed since *dt*."""
        return (datetime.datetime.now() - dt).total_seconds()

    def reset_time(self):
        """Record 'now' as the last user interaction."""
        self.last_user_interaction = datetime.datetime.now()

    # -- playback callbacks ------------------------------------------------

    def onPlayBackSeekChapter(self, chapter):
        _log("onPlayBackSeekChapter")
        self.reset_time()

    def onPlayBackSeek(self, time, seekOffset):
        _log("onPlayBackSeek")
        self.reset_time()

    def onPlayBackResumed(self):
        _log("onPlayBackResumed")
        self.reset_time()

    def onPlayBackPaused(self):
        _log("onPlayBackPaused")
        self.reset_time()

    def onPlayBackStopped(self):
        _log("onPlayBackStopped")
        self.reset_time()

    def onPlayBackStarted(self):
        """Distinguish auto-play (playlist advancement) from user-initiated play."""
        if self.last_ended is None:
            _log("onPlayBackStarted: No ended movie detected before => user interaction")
            self.reset_time()
            return

        delay = self._seconds_since(self.last_ended)
        _log("onPlayBackStarted: Last Ended was detected within " + str(delay) + " seconds")

        if delay < 60:
            _log("onPlayBackStarted: Last movie ended => No user interaction")
        else:
            _log("onPlayBackStarted: Last movie did not end during 60s => User interaction")
            self.reset_time()

    def onPlayBackEnded(self):
        _log("onPlayBackEnded")
        _log("Storing last Ended time")
        self.last_ended = datetime.datetime.now()

    # -- idle time ---------------------------------------------------------

    def get_idle_seconds(self, debug):
        """Return the number of seconds since the last user interaction."""
        result = int(self._seconds_since(self.last_user_interaction))
        _debug("XBMC        Idle Time " + repr(xbmc.getGlobalIdleTime()), debug)
        _debug("Alternative Idle Time " + repr(result), debug)
        return result


# ---------------------------------------------------------------------------
# Idle time accessor
# ---------------------------------------------------------------------------

def get_idle_seconds(alt_mode, use_alt, debug):
    """Return idle time in seconds using the appropriate source."""
    if use_alt == 'true':
        return alt_mode.get_idle_seconds(debug)
    return xbmc.getGlobalIdleTime()


# ---------------------------------------------------------------------------
# Settings loader
# ---------------------------------------------------------------------------

def load_settings():
    """Re-read all addon settings and return them as a dict.

    Called on every loop iteration so the user never needs to restart
    Kodi after changing settings.
    """
    addon = xbmcaddon.Addon(ADDON_ID)
    return {
        'debug':                addon.getSetting('debug_mode'),
        'check_time':           int(addon.getSetting('check_time')),
        'check_time_next':      int(addon.getSetting('check_time_next')),
        'time_to_wait':         int(addon.getSetting('waiting_time_dialog')),
        'audiochange':          addon.getSetting('audio_change'),
        'mute_vol':             int(addon.getSetting('mute_volume')),
        'audio_interval':       int(addon.getSetting('audio_interval_length')),
        'audio_enable':         addon.getSetting('audio_enable'),
        'video_enable':         addon.getSetting('video_enable'),
        'max_time_audio':       int(addon.getSetting('max_time_audio')),
        'max_time_video':       int(addon.getSetting('max_time_video')),
        'enable_screensaver':   addon.getSetting('enable_screensaver'),
        'custom_cmd':           addon.getSetting('custom_cmd'),
        'cmd':                  addon.getSetting('cmd'),
        'use_alt_mode':         addon.getSetting('alternativemode'),
        'supervision_mode':     addon.getSetting('supervision_mode'),
        'hour_start_sup':       addon.getSetting('hour_start_sup'),
        'hour_end_sup':         addon.getSetting('hour_end_sup'),
        # New settings
        'enable_keypress':      addon.getSetting('enable_keypress_trigger'),
        'custom_cmd_idle_delay': int(addon.getSetting('custom_cmd_idle_delay') or '0'),
    }


# ---------------------------------------------------------------------------
# Signal-file helpers  (key-press IPC)
# ---------------------------------------------------------------------------

def _get_signal_path():
    """Return the full path to the key-press signal file."""
    addon = xbmcaddon.Addon(ADDON_ID)
    data_path = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
    return os.path.join(data_path, SIGNAL_FILENAME)


def write_signal():
    """Create the signal file (called from ``trigger_key.py``)."""
    path = _get_signal_path()
    # Ensure the directory exists
    directory = os.path.dirname(path)
    if not os.path.exists(directory):
        os.makedirs(directory)
    with open(path, 'w') as fh:
        fh.write(str(datetime.datetime.now()))
    _log("Signal file written: " + path)


def _consume_signal():
    """If the signal file exists, delete it and return ``True``."""
    path = _get_signal_path()
    if os.path.exists(path):
        try:
            os.remove(path)
            _log("Signal file consumed: " + path)
            return True
        except OSError as exc:
            _log("Error removing signal file: " + str(exc))
    return False


# ---------------------------------------------------------------------------
# Keymap installer
# ---------------------------------------------------------------------------

def _install_keymap():
    """Copy the addon's keymap file into the Kodi keymaps directory."""
    addon = xbmcaddon.Addon(ADDON_ID)
    addon_dir = xbmcvfs.translatePath(addon.getAddonInfo('path'))
    source = os.path.join(addon_dir, KEYMAP_FILENAME)
    dest_dir = xbmcvfs.translatePath('special://profile/keymaps/')
    dest = os.path.join(dest_dir, KEYMAP_FILENAME)

    if not os.path.exists(source):
        _log("Keymap source file not found: " + source)
        return

    if os.path.exists(dest):
        _log("Keymap already installed: " + dest)
        return

    if not os.path.exists(dest_dir):
        os.makedirs(dest_dir)
    shutil.copy2(source, dest)
    _log("Keymap installed: " + dest)
    # Kodi picks up new keymaps on next input action or restart.


def _uninstall_keymap():
    """Remove the addon's keymap file from the Kodi keymaps directory."""
    dest_dir = xbmcvfs.translatePath('special://profile/keymaps/')
    dest = os.path.join(dest_dir, KEYMAP_FILENAME)
    if os.path.exists(dest):
        try:
            os.remove(dest)
            _log("Keymap uninstalled: " + dest)
        except OSError as exc:
            _log("Error removing keymap: " + str(exc))


# ---------------------------------------------------------------------------
# Main service class
# ---------------------------------------------------------------------------

class SleepTimerService:
    """Encapsulates the entire sleep-timer service lifecycle."""

    def __init__(self):
        addon = xbmcaddon.Addon(ADDON_ID)
        _log("started ... (" + addon.getAddonInfo('version') + ")")

        self.monitor = xbmc.Monitor()
        self.alt_mode = AlternativeDetectionMode()

        # Tracks whether this is the very first iteration
        self._first_cycle = True
        # Tracks whether the user cancelled the dialog (next re-check logic)
        self._next_check = False
        self._idle_carryover = 0.0
        # Tracks whether the custom-cmd-idle-delay already fired (resets on
        # interaction)
        self._idle_cmd_fired = False

    # -- main loop ---------------------------------------------------------

    def run(self):
        """Run the service until Kodi signals abort."""
        while not self.monitor.abortRequested():
            s = load_settings()
            debug = s['debug']

            if self._first_cycle:
                self._log_startup(s)
                # Wait 15 s to let Kodi finish its startup / intro movie
                if self.monitor.waitForAbort(15):
                    break
                self._max_time = -1
                self._first_cycle = False

            # -- manage keymap installation --------------------------------
            if s['enable_keypress'] == 'true':
                _install_keymap()
            else:
                _uninstall_keymap()

            # -- check for key-press signal --------------------------------
            if _consume_signal():
                _log("Key-press signal detected — resetting idle timer")
                self.alt_mode.reset_time()
                self._idle_cmd_fired = False
                # Run custom command immediately on key-press if enabled
                if s['custom_cmd'] == 'true' and s['cmd']:
                    _debug("Running custom script (key-press trigger)", debug)
                    os.system(s['cmd'])

            # -- supervision window ----------------------------------------
            kodi_time = get_kodi_time()
            start_t = self._parse_time(s['hour_start_sup'])
            end_t = self._parse_time(s['hour_end_sup'])
            proceed = should_supervise(
                kodi_time, start_t, end_t, s['supervision_mode'], debug
            )

            check_interval = s['check_time']

            if proceed:
                idle_secs = get_idle_seconds(
                    self.alt_mode, s['use_alt_mode'], debug
                )
                idle_mins = idle_secs / 60.0

                # -- post-idle custom command delay ------------------------
                self._check_idle_cmd(s, idle_secs, debug)

                if xbmc.Player().isPlaying():
                    check_interval = self._handle_playback(
                        s, idle_mins, check_interval, debug
                    )
                else:
                    _debug("Not playing any media file", debug)
                    self._max_time = -1
                    self._next_check = False
                    self._idle_carryover = 0.0

                # Remember the difference for the "next check" carry-over
                self._idle_carryover = idle_mins - check_interval

                if debug == 'true' and self._next_check:
                    _log("DEBUG: idle_carryover: " + str(self._idle_carryover))

            if _wait_minutes(self.monitor, check_interval, debug):
                break

    # -- startup logging ---------------------------------------------------

    def _log_startup(self, s):
        """Print initial settings to the log in debug mode."""
        debug = s['debug']
        if debug != 'true':
            return
        _log("DEBUG: " + "#" * 64)
        _log("DEBUG: Settings in Kodi:")
        _log("DEBUG: enable_audio: " + s['audio_enable'])
        _log("DEBUG: maxaudio_time_in_minutes: " + str(s['max_time_audio']))
        _log("DEBUG: enable_video: " + str(s['video_enable']))
        _log("DEBUG: maxvideo_time_in_minutes: " + str(s['max_time_video']))
        _log("DEBUG: check_time: " + str(s['check_time']))
        _log("DEBUG: use_alt_mode: " + s['use_alt_mode'])
        _log("DEBUG: enable_keypress: " + s['enable_keypress'])
        _log("DEBUG: custom_cmd_idle_delay: " + str(s['custom_cmd_idle_delay']))
        _log("DEBUG: Supervision mode: Always")
        _log("DEBUG: " + "#" * 64)

    # -- idle-based custom command -----------------------------------------

    def _check_idle_cmd(self, s, idle_secs, debug):
        """Run the custom command if idle time exceeds the configured delay.

        This fires independently of playback state — useful for turning off
        a TV/projector/receiver after the user has been idle for a while.
        Resets when the user interacts (idle time drops).
        """
        delay = s['custom_cmd_idle_delay']
        if delay <= 0:
            return
        if s['custom_cmd'] != 'true' or not s['cmd']:
            return

        if idle_secs >= delay and not self._idle_cmd_fired:
            _log("Idle time (" + str(idle_secs) + "s) exceeds custom_cmd_idle_delay ("
                 + str(delay) + "s) — running custom command")
            _debug("Running custom script (idle delay trigger)", debug)
            os.system(s['cmd'])
            self._idle_cmd_fired = True
        elif idle_secs < delay:
            # User interacted — reset so it can fire again next time
            self._idle_cmd_fired = False

    # -- playback handling -------------------------------------------------

    def _handle_playback(self, s, idle_mins, check_interval, debug):
        """Check the currently playing media and apply idle-time logic.

        Returns the check interval to use for the next wait.
        """
        if debug == 'true' and self._max_time == -1:
            _log("DEBUG: max_time_in_minutes before calculation: "
                 + str(self._max_time))

        # Carry over idle time from previous cancelled-dialog cycle
        if self._next_check:
            idle_mins += self._idle_carryover

        if debug == 'true' and self._max_time == -1:
            _log("DEBUG: max_time_in_minutes after calculation: "
                 + str(self._max_time))

        # Determine what is playing and the corresponding limit
        media_type, max_time = self._detect_media(s, debug)

        if media_type is None:
            # Playing something we don't monitor — just wait
            return check_interval

        self._max_time = max_time

        _debug("what_is_playing: " + media_type, debug)
        _debug("idle_time_in_minutes: '" + str(idle_mins) + "'", debug)
        _debug("max_time_in_minutes: " + str(max_time), debug)

        if idle_mins >= max_time:
            _debug("idle_time exceeds max allowed. Display Progressdialog", debug)
            cancelled = self._show_countdown_dialog(s, debug)

            if cancelled:
                check_interval = s['check_time_next']
                _log("Progressdialog cancelled, next check in "
                     + str(check_interval) + " min")
                self._next_check = True
            else:
                aborted = self._stop_playback(s, max_time, debug)
                if aborted:
                    # User woke up during fade-out — treat like cancel
                    check_interval = s['check_time_next']
                    self._next_check = True
                else:
                    self._next_check = False
                    self._idle_carryover = 0.0
        else:
            _debug("Playing the stream, time does not exceed max limit", debug)

        return check_interval

    def _detect_media(self, s, debug):
        """Return ``(media_type, max_minutes)`` or ``(None, None)``."""
        player = xbmc.Player()

        if player.isPlayingAudio():
            if s['audio_enable'] == 'true':
                _debug("enable_audio is true", debug)
                _print_playing_file(debug)
                return ("audio", s['max_time_audio'])
            else:
                _debug("Player is playing Audio, but check is disabled", debug)
                return (None, None)

        elif player.isPlayingVideo():
            if s['video_enable'] == 'true':
                _debug("enable_video is true", debug)
                _print_playing_file(debug)
                return ("video", s['max_time_video'])
            else:
                _debug("Player is playing Video, but check is disabled", debug)
                return (None, None)

        else:
            # Could be RetroPlayer / other — not yet supported
            _debug("Player is playing, but no Audio or Video", debug)
            _print_playing_file(debug)
            return (None, None)

    # -- countdown dialog --------------------------------------------------

    def _show_countdown_dialog(self, s, debug):
        """Show the "Are you still there?" countdown dialog.

        Returns ``True`` if the user cancelled the dialog.
        """
        time_to_wait = s['time_to_wait']
        addon = xbmcaddon.Addon(ADDON_ID)

        dialog = xbmcgui.DialogProgress()
        dialog.create(addon.getLocalizedString(30000),
                      addon.getLocalizedString(30001))
        cancelled = False
        # Use multiplier 100 for better percentage calculation
        increment = 100 * 100 / time_to_wait

        for secs in range(1, time_to_wait + 1):
            percent = int(increment * secs / 100)
            remaining = str(time_to_wait - secs) + " seconds left."
            dialog.update(percent, remaining)
            xbmc.sleep(1000)

            if dialog.iscanceled():
                cancelled = True
                self.alt_mode.reset_time()
                _debug("Progressdialog cancelled", debug)
                break

        dialog.close()
        return cancelled

    # -- stop playback -----------------------------------------------------

    def _stop_playback(self, s, max_time, debug):
        """Fade out volume (if enabled), stop the player, then clean up.

        Returns ``True`` if the user interrupted the fade-out (i.e. they
        pressed something and the process was aborted).
        """
        _log("Progressdialog not cancelled: stopping Player")
        original_vol = None

        # -- gradual volume fade-out ---------------------------------------
        if s['audiochange'] == 'true':
            original_vol = self._get_current_volume(debug)

            if original_vol is not None:
                aborted = self._fade_out_volume(
                    s, original_vol, max_time, debug
                )
                if aborted:
                    return True

        # -- wait a moment before stopping ---------------------------------
        if original_vol is not None:
            _debug("Waiting before stop, volume=" + str(original_vol), debug)
        else:
            _debug("Waiting before stop (no volume change)", debug)
        self.monitor.waitForAbort(5)

        # -- stop player FIRST (while volume is still muted) ---------------
        _debug("Stopping player...", debug)
        xbmc.executebuiltin('PlayerControl(Stop)')

        # -- THEN restore volume (nothing playing → silent) ----------------
        if s['audiochange'] == 'true' and original_vol is not None:
            _debug("Reset volume to original value " + str(original_vol), debug)
            xbmc.executebuiltin('SetVolume(%d,showVolumeBar)' % original_vol)

        # -- screensaver ---------------------------------------------------
        if s['enable_screensaver'] == 'true':
            _debug("Activating screensaver", debug)
            xbmc.executebuiltin('ActivateScreensaver')

        # -- custom command ------------------------------------------------
        if s['custom_cmd'] == 'true' and s['cmd']:
            _debug("Running custom script", debug)
            os.system(s['cmd'])

        return False

    # -- volume helpers ----------------------------------------------------

    @staticmethod
    def _get_current_volume(debug):
        """Query Kodi for the current volume level via JSON-RPC."""
        resp = xbmc.executeJSONRPC(
            '{"jsonrpc": "2.0", "method": "Application.GetProperties",'
            ' "params": { "properties": ["volume"] }, "id": 1}'
        )
        dct = json.loads(resp)
        if "result" in dct and "volume" in dct["result"]:
            vol = dct["result"]["volume"]
            _debug("Original volume value is " + str(vol), debug)
            return vol
        _debug("Could not read volume from JSON-RPC response", debug)
        return None

    def _fade_out_volume(self, s, original_vol, max_time, debug):
        """Gradually reduce volume from *original_vol* to *mute_vol*.

        Returns ``True`` if the user interrupted (idle time dropped below
        *max_time* during the fade), in which case volume is restored and
        the caller should abort the stop sequence.
        """
        mute_vol = s['mute_vol']
        interval = s['audio_interval']
        steps = original_vol - mute_vol

        if steps <= 0:
            return False

        step_sleep_ms = round(interval / steps * 60000)

        for vol in range(original_vol - 1, mute_vol - 1, -1):
            _debug("Reducing volume to " + str(vol), debug)
            xbmc.executebuiltin('SetVolume(%d,showVolumeBar)' % vol)
            xbmc.sleep(step_sleep_ms)

            # Check if user woke up during fade-out
            idle_mins = get_idle_seconds(
                self.alt_mode, s['use_alt_mode'], debug
            ) / 60.0
            if idle_mins < max_time:
                _debug("User pressed a key while volume is going down. "
                       "Aborting sleep process", debug)
                _debug("Setting back original volume " + str(original_vol),
                       debug)
                xbmc.executebuiltin(
                    'SetVolume(%d,showVolumeBar)' % original_vol
                )
                _log("Fade-out aborted by user interaction, next check in "
                     + str(s['check_time_next']) + " min")
                return True

        return False

    # -- utilities ---------------------------------------------------------

    @staticmethod
    def _parse_time(time_str):
        """Parse a ``"HH:MM"`` string into an ``HHMM`` integer."""
        try:
            parts = time_str.split(':')
            return int(parts[0] + parts[1])
        except (ValueError, IndexError):
            return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    SleepTimerService().run()
