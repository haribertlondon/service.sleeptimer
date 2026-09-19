# Sleep Timer — Kodi Service Addon

[![License: GPL-2.0](https://img.shields.io/badge/License-GPL%202.0-blue.svg)](LICENSE)

> Did you fall asleep? Get better control over media playback.

This service addon makes Kodi stop any playback if it exceeds a given idle time. If you have that awful habit of leaving Kodi playing live content after you fell asleep, this addon is for you! It gives extended control over the playback time — step-mute the audio, enable the screensaver, or run a custom command after the playback is stopped.

---

## Features

- **Automatic Playback Stop** — Stops audio and/or video playback when idle time exceeds a configurable threshold.
- **Separate Audio & Video Timers** — Set independent max idle times for audio and video content.
- **Gradual Volume Fade-Out** — Smoothly reduces volume before stopping playback (configurable target volume and fade duration).
- **User Awareness Dialog** — Shows a cancellable progress dialog before stopping, giving you a chance to cancel if you're still watching.
- **Screensaver Activation** — Optionally activates the Kodi screensaver after playback is stopped.
- **Custom Command Execution** — Run any shell command after stopping playback (e.g., suspend, shutdown, turn off displays).
- **Idle-Based Custom Command** — Run the custom command after a configurable idle delay, independent of playback state (e.g., turn off TV after being idle for 5 minutes).
- **PageUp Key Trigger** — Press PageUp on your keyboard/remote to immediately run the custom command and reset the idle timer. Useful for triggering actions like turning off a projector on demand.
- **Supervision Time Window** — Restrict the sleep timer to only operate during specific hours (e.g., 22:00–06:00).
- **Alternative Idle Detection** — An advanced mode that detects user interaction through playback events (seek, pause, resume) and key-press signals instead of relying solely on Kodi's global idle timer. Useful for users who control playback via remote apps.
- **Live Settings Reload** — Settings changes take effect immediately without restarting Kodi.

---

## Installation

### From Kodi Repository

1. Open **Kodi** → **Add-ons** → **Install from repository**
2. Navigate to **Services** → **Sleep Timer**
3. Click **Install**

### Manual Installation

1. Download or clone this repository.
2. Copy the `service.sleeptimer` folder into your Kodi addons directory:
   - **Linux**: `~/.kodi/addons/`
   - **Windows**: `%APPDATA%\Kodi\addons\`
   - **macOS**: `~/Library/Application Support/Kodi/addons/`
   - **LibreELEC / OSMC**: `/storage/.kodi/addons/`
3. Restart Kodi. The addon will start automatically on login.

---

## Configuration

Open the addon settings via **Add-ons** → **My Add-ons** → **Services** → **Sleep Timer** → **Configure**.

### General Settings

| Setting | Description | Default |
|---------|-------------|---------|
| **Check interval** | How often (in minutes) the service checks idle time | `1 min` |
| **Dialog wait time** | How many seconds the "Are you still there?" dialog stays open | `60 s` |
| **Audio fade-out** | Enable gradual volume reduction before stopping | `true` |
| **Fade duration** | Length of the audio fade-out in minutes | `1 min` |
| **Mute volume** | Target volume at the end of the fade-out | `10` |
| **Next check after cancel** | Delay (in minutes) before the next check if the user cancels the dialog | `30 min` |
| **Activate screensaver** | Activate the Kodi screensaver after stopping playback | `false` |
| **Custom command** | Enable running a shell command after stopping | `false` |
| **Command** | The shell command to run (visible when custom command is enabled) | *(empty)* |
| **Custom cmd idle delay** | Run the custom command after this many seconds of idle time, independent of playback (0 = disabled) | `0` |

### Playback Monitoring

| Setting | Description | Default |
|---------|-------------|---------|
| **Enable video monitoring** | Monitor and stop idle video playback | `true` |
| **Enable audio monitoring** | Monitor and stop idle audio playback | `true` |
| **Max idle time (video)** | Stop video after this many minutes of idle | `45 min` |
| **Max idle time (audio)** | Stop audio after this many minutes of idle | `45 min` |
| **Supervision mode** | `Always` or `Time window` — restrict monitoring to specific hours | `Always` |
| **Start hour** | Start of the supervision window (when mode is `Time window`) | `00:00` |
| **End hour** | End of the supervision window (when mode is `Time window`) | `00:00` |

### Advanced

| Setting | Description | Default |
|---------|-------------|---------|
| **Alternative idle detection** | Use playback event-based idle detection instead of Kodi's global idle timer | `false` |
| **Enable PageUp key trigger** | Map PageUp to run the custom command and reset the idle timer (auto-installs keymap) | `false` |
| **Debug mode** | Enable verbose debug logging to `kodi.log` | `false` |

---

## How It Works

1. The service runs as a background service, starting automatically when Kodi launches.
2. At each check interval, it reads the current idle time (time since last user interaction).
3. If media is playing and idle time exceeds the configured threshold:
   - A progress dialog is shown, giving you time to cancel.
   - If not cancelled: the volume is gradually faded out (if enabled), then playback is stopped.
   - Volume is restored **after** playback stops (so you won't hear a brief volume spike).
   - Optionally, the screensaver is activated and/or a custom command is executed.
4. If the dialog is cancelled, the service waits for the "next check" interval before re-checking.
5. **Idle-based custom command**: If configured, the custom command also runs independently when idle time exceeds the specified delay (regardless of playback state).
6. **PageUp key trigger**: When enabled, pressing PageUp immediately runs the custom command and resets the idle timer.

### Alternative Idle Detection

The standard Kodi idle timer (`xbmc.getGlobalIdleTime()`) resets on any system-level input event. The **Alternative Detection Mode** instead tracks user interactions at the playback level (seek, pause, resume, stop) and through key-press signals (PageUp). This is particularly useful for setups where:

- Kodi receives periodic system-level input that resets the standard idle timer (e.g., CEC polling, IR noise).
- You use a remote app that sends keep-alive signals.
- `getGlobalIdleTime()` does not behave as expected in recent Kodi versions.

### PageUp Key Trigger

When "Enable PageUp key trigger" is turned on, the addon automatically installs a keymap file (`sleeptimer_keymap.xml`) into your Kodi keymaps directory. This maps the PageUp key globally to a trigger script that:

1. Writes a signal file to the addon's data directory.
2. The service picks this up on the next check cycle.
3. The idle timer is reset (in Alternative mode).
4. The configured custom command is executed immediately.

When the setting is turned off, the keymap file is automatically removed.

**Manual keymap setup**: If you prefer to map a different key, copy `sleeptimer_keymap.xml` from the addon directory to your `userdata/keymaps/` folder and edit the key name.

---

## Troubleshooting

### The sleep timer doesn't trigger

- Check that **audio or video monitoring is enabled** in settings.
- Verify the **max idle time** is set to a reasonable value.
- If using **supervision time window**, make sure the current time falls within the configured window.
- Enable **debug mode** and check `kodi.log` for messages prefixed with `service.sleeptimer`.

### The dialog appears too often

- Increase the **max idle time** for audio/video.
- Increase the **next check after cancel** time to delay re-checks after dismissing the dialog.

### Volume doesn't restore after cancelling

- This may occur if Kodi is interrupted during the fade-out. The addon attempts to restore the original volume, but if it fails, manually adjust the volume or restart Kodi.

### Settings changes don't take effect

- Settings are reloaded on every check cycle. Wait for the next check interval (default: 1 minute) for changes to apply.

### PageUp key doesn't work

- Make sure **Enable PageUp key trigger** is enabled in the addon settings.
- Check that the keymap file `sleeptimer_keymap.xml` exists in your Kodi keymaps directory (`userdata/keymaps/`).
- If using a remote control, verify that the remote button is mapped to `pageup` in Kodi's input settings.
- Check `kodi.log` for `trigger_key.py invoked` messages to confirm the keymap is working.

---

## Development

### Project Structure

```
service.sleeptimer/
├── addon.xml                # Kodi addon manifest
├── service.py               # Main service logic
├── trigger_key.py           # Key-press trigger script (invoked by keymap)
├── sleeptimer_keymap.xml    # Reference keymap (auto-installed when enabled)
├── changelog.txt            # Version history
├── icon.png                 # Addon icon
├── LICENSE                  # GPL-2.0 license
├── README.md                # This file
└── resources/
    ├── settings.xml         # Addon settings definition
    └── language/
        ├── English/         # English translations
        └── Portuguese/      # Portuguese translations
```

### Debug Mode

Enable debug mode in the addon settings to get detailed logging output in `kodi.log`. Look for lines starting with `service.sleeptimer: DEBUG:`.

---

## License

This project is licensed under the **GNU General Public License v2.0** — see the [LICENSE](LICENSE) file for details.

## Credits

- **enen92** — Original author
- **Solo0815** — Co-author and maintainer
