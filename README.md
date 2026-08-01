# FileShare

A tiny cross-platform desktop app that turns any folder into a web page other
people on your network can browse, download from, and upload to — the same idea
as **HFS (HTTP File Server)**, but written in pure Python so it runs on both
**Windows** and **macOS** (and Linux).

No dependencies to install: it uses only Python's standard library (Tkinter for
the window, `http.server` for the server).

---

## Files

| File                     | What it is                                                        |
|--------------------------|-------------------------------------------------------------------|
| `fileshare.py`           | The whole app — GUI + web server in one file.                     |
| `run-windows-python.bat` | Windows one-step launcher: installs Python if needed, then runs the app. |

---

## What it does

- Pick a folder with a **Browse…** button.
- Press **Start server** — the app shows a URL like `http://192.168.1.20:8000`.
- Anyone on the same Wi-Fi/LAN opens that URL in a browser and can:
  - browse the folder and any subfolders,
  - download individual files,
  - **Download all (.zip)** — grab the current folder (subfolders included) as
    one ZIP file, built on the fly,
  - **upload** files back into the folder (can be turned off).
- The web page works on phones, tablets, and other computers, with a clean
  light/dark interface.
- The app window shows a live activity log (who downloaded/uploaded what) and a
  **Copy** button for the share URL.
- Press **Stop server** or close the window to shut it down.

---

## Quick start — Windows (easiest)

1. Put `run-windows-python.bat` and `fileshare.py` in the same folder.
2. **Double-click `run-windows-python.bat`.**

That's it. The script:

1. Looks for Python 3 already on the PC (it ignores the fake Microsoft Store
   `python` stub).
2. If Python is missing, installs **Python 3.12** automatically via `winget`.
3. Launches the FileShare window.

If automatic install fails (e.g. `winget` not available on an old Windows 10),
the script tells you and points to https://www.python.org/downloads/ — during
manual install, tick **"Add python.exe to PATH"**, then double-click the `.bat`
again.

> **Firewall:** the first time you press *Start server*, Windows may ask to
> allow Python through the firewall. Choose **Allow** on *private* networks so
> other devices can connect.

---

## Quick start — macOS

1. Install Python from https://python.org if you don't have it (the python.org
   build includes Tkinter; the version bundled with older macOS may not).
2. In Terminal:

```bash
cd ~/Downloads/FileShare
python3 fileshare.py
```

3. Choose a folder, press **Start server**, and share the URL shown.

---

## Using the shared page (what visitors see)

- **Folders** — click to open; `↩ ..` goes back up.
- **Files** — click to view/download.
- **⬇️ Download all (.zip)** (top right) — downloads the folder currently shown,
  including everything inside it, as a single ZIP named after the folder.
- **Upload** — choose one or more files and press *Upload here*; they land in
  the folder currently shown. If a name already exists, the new file is saved
  as `name (1).ext` instead of overwriting.

---

## Command-line options

```bash
python fileshare.py --help
```

| Option          | What it does                                                        |
|-----------------|---------------------------------------------------------------------|
| `folder`        | Pre-fill the folder to share, e.g. `python fileshare.py D:\Stuff`   |
| `-p, --port N`  | Use port N instead of 8000                                          |
| `--no-upload`   | Disable uploads (browse/download only)                              |
| `--no-gui`      | Run headless in the terminal — no window, good for servers          |

Headless example:

```bash
python fileshare.py --no-gui -p 9000 /path/to/folder
```

---

## Notes & safety

- **Local network only, by design.** It listens on all interfaces so devices on
  *your* network can reach it. Don't expose it directly to the public internet.
- **No password.** Anyone who can reach the URL can browse and (if enabled)
  upload. Keep it to networks you trust.
- **Path safety.** The server refuses to serve anything outside the folder you
  chose — `../` tricks can't escape the shared directory.
- **Requirements:** Python 3.8+ with Tkinter (included in python.org and winget
  installs). The `.bat` handles all of this on Windows automatically.

---

*FileShare 1.1 — single file, no dependencies, MIT-style free to use and modify.*
