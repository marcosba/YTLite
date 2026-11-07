# YTLite

**English** | [Español](README.es.md)

A single-window YouTube player for old hardware (designed with a ThinkPad T60p running antiX Linux in mind). No browser, no heavy frameworks: **Python + Tkinter** for the UI, **mpv** for playback and **yt-dlp** for extraction.

Video starts playing a few seconds after pasting the URL, and the buffer lives in **RAM**, not on disk, so a slow mechanical hard drive doesn't get hammered.

> **Status:** the player, IPC control, crash recovery, screenshots and queue/history persistence were tested with a real mpv on a local video in a virtual X server. Real YouTube extraction (playback, playlists, search, automatic quality detection, downloads) and performance on ~2006 hardware have **not been verified yet**. If something fails, open an issue with the contents of *Herramientas → Ver log* (Tools → View log).

> **Note:** the app's interface is currently in Spanish.

## Features

**Playback**
- Paste a video or playlist URL and play it in the same window (embedded mpv).
- Play/pause, seekable progress bar, 0.5x–2x speed, volume, mute and fullscreen.
- Quality selector (360p / 480p / 720p / 1080p) that reloads the video at the same position, without restarting the app.
- **Auto**: measures your connection before playing and picks a quality.
- **Audio only**, switchable on and off during playback.
- Live streams: the progress bar adapts ("EN VIVO").
- Subtitles and chapter skipping when the video has them.

**Queue and playlists**
- Queue with automatic advance, reordering, removing, clearing and text filtering.
- Full playlists: each video shows which playlist it came from (column and its own color).
- Save/load the queue to a `.json` file, plus autosave on exit.

**Memory and navigation**
- History with automatic resume from where you left off.
- Built-in YouTube search (no browser).
- Favorites.

**Extras**
- Screenshots, and downloading the current video (low CPU and disk priority).
- Sleep timer (15/30/60 min or end of video) with a cancelable countdown.
- Notification when the queue ends, status bar, and in-app manual and diagnostic log.

**Robustness**
- If mpv crashes, it is relaunched automatically and resumes near where it was (up to 3 attempts).
- Invalid URL, a playlist when you wanted one video, failed extraction: reported in the status bar without freezing the window.
- Button to update yt-dlp.

## Requirements

- Linux with **X11** (video is embedded with `--wid`; it does not work on pure Wayland).
- Python 3.8 or newer.
- `mpv` and `python3-tk`.
- Optional: `ffmpeg` (to merge video+audio when downloading) and `libnotify-bin` (notifications).
- `yt-dlp`: the app can download and install it by itself into `~/.local/bin` (see below).

## Installation

```sh
sudo apt install mpv python3-tk ffmpeg libnotify-bin
git clone <REPO-URL> ytlite
cd ytlite
sh install.sh
```

`install.sh` copies the app to `~/.local/share/ytlite/`, creates the `ytlite` command in `~/.local/bin/` and registers the menu entry (`ytlite.desktop`).

Then open YTLite and use **Herramientas → Actualizar yt-dlp** (Tools → Update yt-dlp). It downloads the latest release to `~/.local/bin/yt-dlp`, which the app prefers over the system one (the apt version is usually outdated, and YouTube changes often).

If it doesn't show up in the antiX menu, try `desktop-menu --write-out-global` or restart the window manager.

You can also run it directly:

```sh
python3 ytlite.py [URL ...]
```

## Quick start

1. Paste a URL and press **Enter** (or the **Pegar** button, which takes the clipboard contents and plays them).
2. **Encolar** adds to the end of the queue. **Playlist** adds every video in the list.
3. A video URL containing `&list=...` plays only that video; use **Playlist** for the whole list.
4. If the video is black at first, a click on it starts playback.

The full manual is under **Ayuda → Manual de uso** (Help → User manual).

### Shortcuts

| Key | Action |
|---|---|
| Space / click | Pause / resume |
| ← / → | −5 s / +5 s |
| Shift + ← / → | −30 s / +30 s |
| ↑ / ↓, `+` / `-`, wheel | Volume |
| M | Mute |
| `[` / `]` | Speed down / up |
| N / P | Next / previous |
| F / Esc | Fullscreen / exit |
| S | Screenshot |
| A | Audio only |
| C | Subtitles |
| B | Favorite |
| PgUp / PgDn | Previous / next chapter |

Letter keys do nothing while you are typing in a text field.

## Configuration

Everything is stored in `~/.config/ytlite/`:

| File | Contents |
|---|---|
| `config.json` | Preferences |
| `queue.json` | Queue (restored on startup) |
| `history.json` | History and playback positions |
| `favorites.json` | Favorites |
| `ytlite.log` | Rotating log (~200 KB) |

Preferences are edited under **Herramientas → Preferencias** (Tools → Preferences): conservative mode, loudnorm, subtitles, RAM buffer size, video output, screenshot and download folders, download rate limit, timer action, and more.

Extra yt-dlp options (cookies, JavaScript runtime, etc.) go in `~/.config/yt-dlp/config`; they also apply to what mpv plays.

## If performance isn't enough

1. Use **audio only** or **360p**: it saves the most CPU.
2. Keep **conservative mode** on (480p cap, H.264, fast decoding). H.264 is what a 2006 CPU can decode with the least effort; VP9/AV1 is not.
3. Tune the **RAM buffer** (default 64 MiB ahead, 8 MiB behind): raise it if you have spare memory, lower it if you are short.
4. Turn off **loudnorm** and **subtitles**.
5. Don't download while watching something else: downloads write to disk (they run under `nice`/`ionice`, but a slow mechanical drive will still feel it).
6. Video output `auto` tries `xv`, then `x11`, then `gpu`. If you get a black picture with sound, set `x11` in Preferences.

## Troubleshooting

- **"Extraction error" / no YouTube video loads:** *Herramientas → Actualizar yt-dlp*. If it persists, check yt-dlp's documentation to see whether YouTube now requires a JavaScript runtime (deno or node). Deno doesn't run on 32-bit systems; there you would need node.
- **The player crashes:** it relaunches itself up to 3 times, then reports it. *Herramientas → Ver log* shows mpv's output.
- **Black video with audio:** change the video output to `x11` or `gpu`.
- **No notifications:** install `libnotify-bin`; without it the app only beeps.

## How it works

```
Tkinter (window, queue, history, search)
   │  JSON IPC over a Unix socket
   ▼
mpv  --wid=<Tk frame>   ← embedded in the window, RAM-only cache
   │  ytdl hook
   ▼
yt-dlp  → YouTube streams
```

- mpv runs as a separate process: if it dies, the UI stays up and can relaunch it.
- The UI only reads cached player properties, so it stays responsive even on a slow network.
- Shortcuts pressed while the video window has focus go through mpv (`script-message`) and back to the app, so they work whether focus is on the video or elsewhere.

## License

Choose a license before publishing (for example MIT or GPLv3) and add a `LICENSE` file.
