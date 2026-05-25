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
- **Supervision Time Window** — Restrict the sleep timer to only operate during specific hours (e.g., 22:00–06:00).
- **Alternative Idle Detection** — An advanced mode that detects user interaction through playback events (seek, pause, resume) instead of relying solely on Kodi's global idle timer. Useful for users who control playback via remote apps.
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
| **Debug mode** | Enable verbose debug logging to `kodi.log` | `false` |

---

## How It Works

1. The service runs as a background service, starting automatically when Kodi launches.
2. At each check interval, it reads the current idle time (time since last user interaction).
3. If media is playing and idle time exceeds the configured threshold:
   - A progress dialog is shown, giving you time to cancel.
   - If not cancelled: the volume is gradually faded out (if enabled), then playback is stopped.
   - Optionally, the screensaver is activated and/or a custom command is executed.
4. If the dialog is cancelled, the service waits for the "next check" interval before re-checking.

### Alternative Idle Detection

The standard Kodi idle timer (`xbmc.getGlobalIdleTime()`) resets on any system-level input event. The **Alternative Detection Mode** instead tracks user interactions at the playback level (seek, pause, resume, stop). This is particularly useful for setups where:

- Kodi receives periodic system-level input that resets the standard idle timer (e.g., CEC polling, IR noise).
- You use a remote app that sends keep-alive signals.

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

---

## Development

### Project Structure

```
service.sleeptimer/
├── addon.xml            # Kodi addon manifest
├── service.py           # Main service logic
├── changelog.txt        # Version history
├── icon.png             # Addon icon
├── LICENSE              # GPL-2.0 license
├── README.md            # This file
└── resources/
    ├── settings.xml     # Addon settings definition
    └── language/
        ├── English/     # English translations
        └── Portuguese/  # Portuguese translations
```

### Debug Mode

Enable debug mode in the addon settings to get detailed logging output in `kodi.log`. Look for lines starting with `service.sleeptimer: DEBUG:`.

---

## License

This project is licensed under the **GNU General Public License v2.0** — see the [LICENSE](LICENSE) file for details.

## Credits

- **enen92** — Original author
- **Solo0815** — Co-author and maintainer
