# Upgrade to 3.0.3

## 1. Install

```sh
cd ~/.kodi/addons
rm -rf service.sleeptimer
unzip /path/to/service.sleeptimer-3.0.3.zip
```

On LibreELEC/CoreELEC the addon directory is `/storage/.kodi/addons`.
Restart Kodi afterwards. Installing from the zip inside Kodi also works.

## 2. Fix the TV-off command (REQUIRED)

The old value contained a retry loop that toggles the TV on and off forever and
cannot be cancelled. Replace it:

| Setting | Old | New |
|---|---|---|
| TV off command | `while ! cec-ctl -S \| grep -q "Standby"; do ir-ctl -S nec:0x408 -d /dev/lirc0; sleep 30; done` | `ir-ctl -S nec:0x408 -d /dev/lirc0` |
| Verify command | *(did not exist)* | `cec-ctl -S \| grep -q Standby` |

Keep **Command type = Shell command**. Leave *Maximum retries* at 3 and
*Retry interval* at 30 s.

If you would rather send the code exactly once and never retry, leave the verify
command empty. That is the safest option for a toggle-only button.

## 3. Recommended settings for your setup

```
Sleep after            45 min
Switch TV off after    0        (or 10 if you want audio to continue)
Maximum session length 120 min  (hard safety cap)
Verbose logging        on       (until you trust it)
```

The session cap is the belt-and-braces guarantee: even if some future event is
misclassified as user activity, playback stops after that many minutes.

## 4. Optional: count every key press as activity

Kodi does not emit a player event for plain navigation keys during playback.
If you want any remote key press to restart the timer:

```sh
cp resources/sleeptimer_keymap.xml ~/.kodi/userdata/keymaps/
```

Restart Kodi. Delete the file to undo.

Your log shows a `sleeptimer_keymap.xml` already being loaded from
`special://profile/keymaps/`, so you may already have one — check that it uses
`NotifyAll(service.sleeptimer,sleeptimer_activity)`, which is the message
3.0.3 listens for.

## 5. Verify it works tonight

With verbose logging on:

```sh
tail -f ~/.kodi/temp/kodi.log | grep sleeptimer
```

You should see, every 5 minutes:

```
heartbeat: state=Watching t=780s remaining=1920s session=780s
```

and when a new playlist item starts:

```
ignored (not user activity): onPlayBackStarted (playlist advance)
```

`t` must keep climbing across file boundaries. If it resets to 0 without you
touching anything, capture the preceding `activity:` line — that names the
event responsible.

## 6. Quick functional test

Set *Sleep after* to 2 min, play something, and leave it alone. Expect the OSD
notification, the fade, playback stopping, the screensaver, and the volume
restored. Then set it back to 45.
