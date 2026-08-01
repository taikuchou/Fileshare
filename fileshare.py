#!/usr/bin/env python3
"""
FileShare - a simple cross-platform (Windows / macOS / Linux) HTTP file server
with a desktop GUI, similar in spirit to HFS (HTTP File Server).

Pick a folder, hit Start, and anyone on your network can browse and download
its files from a web browser -- and upload files back into it.

Runs on Python 3.8+ using only the standard library (Tkinter + http.server),
so there are no dependencies to install.

    python fileshare.py            # launch the GUI
    python fileshare.py -h         # command-line options

Author: built for Ken
"""

import argparse
import html
import io
import os
import re
import socket
import sys
import threading
import time
import urllib.parse
from datetime import datetime
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP_NAME = "FileShare"
APP_VERSION = "1.0"

# ------------------------------------------------------------------------------------
# Networking helpers
# ------------------------------------------------------------------------------------

def get_lan_ip():
    """Best-effort discovery of this machine's LAN IP address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # No packets are actually sent; this just picks the outbound interface.
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def human_size(num):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0:
            if unit == "B":
                return f"{num} B"
            return f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"


# ------------------------------------------------------------------------------------
# Multipart/form-data parser (upload support, stdlib-only, works on Python 3.13+)
# ------------------------------------------------------------------------------------

def parse_multipart(body, boundary):
    """
    Minimal multipart/form-data parser.
    Returns a list of (field_name, filename, content_bytes) tuples.
    filename is None for plain form fields.
    """
    results = []
    delim = b"--" + boundary
    # Split on the boundary; ignore preamble and closing "--boundary--".
    parts = body.split(delim)
    for part in parts:
        if part in (b"", b"--", b"--\r\n", b"\r\n"):
            continue
        part = part.strip(b"\r\n")
        if not part:
            continue
        header_blob, _, content = part.partition(b"\r\n\r\n")
        if not _:
            continue
        headers = {}
        for line in header_blob.split(b"\r\n"):
            if b":" in line:
                k, v = line.split(b":", 1)
                headers[k.strip().lower().decode("latin-1")] = v.strip().decode("latin-1")
        disp = headers.get("content-disposition", "")
        name_match = re.search(r'name="([^"]*)"', disp)
        file_match = re.search(r'filename="([^"]*)"', disp)
        field_name = name_match.group(1) if name_match else None
        filename = file_match.group(1) if file_match else None
        results.append((field_name, filename, content))
    return results


# ------------------------------------------------------------------------------------
# HTTP request handler
# ------------------------------------------------------------------------------------

class FileShareHandler(BaseHTTPRequestHandler):
    server_version = f"{APP_NAME}/{APP_VERSION}"

    # These are injected by the server factory.
    root_dir = "."
    allow_upload = True
    log_callback = None

    # ----- logging -----
    def log_message(self, fmt, *args):
        msg = "%s - %s" % (self.address_string(), fmt % args)
        if callable(type(self).log_callback):
            type(self).log_callback(msg)
        else:
            sys.stderr.write(msg + "\n")

    # ----- path helpers -----
    def translate(self, url_path):
        """Map a URL path to a safe absolute path inside root_dir."""
        url_path = urllib.parse.unquote(url_path.split("?", 1)[0].split("#", 1)[0])
        url_path = url_path.lstrip("/")
        root = os.path.abspath(type(self).root_dir)
        target = os.path.abspath(os.path.join(root, url_path))
        # Prevent directory traversal outside the shared root.
        if target != root and not target.startswith(root + os.sep):
            return None
        return target

    # ----- GET -----
    def do_GET(self):
        target = self.translate(self.path)
        if target is None:
            self.send_error(403, "Forbidden")
            return
        if os.path.isdir(target):
            self.render_directory(target)
        elif os.path.isfile(target):
            self.serve_file(target)
        else:
            self.send_error(404, "Not found")

    def do_HEAD(self):
        target = self.translate(self.path)
        if target is None or not os.path.exists(target):
            self.send_error(404, "Not found")
            return
        if os.path.isfile(target):
            self.send_response(200)
            self.send_header("Content-Type", self.guess_type(target))
            self.send_header("Content-Length", str(os.path.getsize(target)))
            self.end_headers()
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()

    def guess_type(self, path):
        import mimetypes
        ctype, _ = mimetypes.guess_type(path)
        return ctype or "application/octet-stream"

    def serve_file(self, target):
        try:
            fs = os.stat(target)
            size = fs.st_size
            self.send_response(200)
            self.send_header("Content-Type", self.guess_type(target))
            self.send_header("Content-Length", str(size))
            # Suggest a download filename while still allowing inline preview.
            fname = os.path.basename(target)
            self.send_header(
                "Content-Disposition",
                'inline; filename="%s"' % fname.replace('"', ""),
            )
            self.send_header("Last-Modified", self.date_time_string(fs.st_mtime))
            self.end_headers()
            with open(target, "rb") as f:
                self.copy_stream(f, self.wfile)
        except BrokenPipeError:
            pass
        except Exception as e:
            self.log_message("error serving file: %s", e)

    @staticmethod
    def copy_stream(src, dst, length=64 * 1024):
        while True:
            chunk = src.read(length)
            if not chunk:
                break
            dst.write(chunk)

    def render_directory(self, target):
        root = os.path.abspath(type(self).root_dir)
        try:
            entries = os.listdir(target)
        except OSError:
            self.send_error(403, "Permission denied")
            return
        entries.sort(key=lambda n: (not os.path.isdir(os.path.join(target, n)), n.lower()))

        rel = os.path.relpath(target, root)
        display_path = "/" if rel == "." else "/" + rel.replace(os.sep, "/")
        url_base = "" if rel == "." else "/" + urllib.parse.quote(rel.replace(os.sep, "/"))

        rows = []
        if os.path.abspath(target) != root:
            parent = os.path.dirname(display_path.rstrip("/"))
            parent_url = urllib.parse.quote(parent) if parent != "/" else "/"
            rows.append(
                f'<tr><td class="name"><a href="{parent_url or "/"}">'
                f'&#8617; ..</a></td><td></td><td></td></tr>'
            )

        for name in entries:
            full = os.path.join(target, name)
            is_dir = os.path.isdir(full)
            link = url_base + "/" + urllib.parse.quote(name)
            if is_dir:
                link += "/"
            try:
                st = os.stat(full)
                size = "" if is_dir else human_size(st.st_size)
                mtime = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
            except OSError:
                size, mtime = "", ""
            icon = "&#128193;" if is_dir else "&#128196;"
            label = html.escape(name) + ("/" if is_dir else "")
            rows.append(
                f'<tr><td class="name"><a href="{link}">{icon} {label}</a></td>'
                f'<td class="size">{size}</td><td class="date">{mtime}</td></tr>'
            )

        upload_html = ""
        if type(self).allow_upload:
            action = url_base + "/" if url_base else "/"
            upload_html = f"""
            <div class="upload">
              <form method="POST" action="{action}" enctype="multipart/form-data">
                <label class="filebtn">
                  Choose files
                  <input type="file" name="file" multiple onchange="document.getElementById('fn').textContent = this.files.length + ' file(s) selected';">
                </label>
                <span id="fn" class="fn">No files selected</span>
                <button type="submit" class="upbtn">Upload here</button>
              </form>
            </div>"""

        page = PAGE_TEMPLATE.format(
            app=APP_NAME,
            path=html.escape(display_path),
            rows="\n".join(rows),
            upload=upload_html,
            count=len(entries),
        )
        body = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ----- POST (upload) -----
    def do_POST(self):
        if not type(self).allow_upload:
            self.send_error(403, "Uploads are disabled")
            return
        target_dir = self.translate(self.path)
        if target_dir is None:
            self.send_error(403, "Forbidden")
            return
        if not os.path.isdir(target_dir):
            target_dir = os.path.dirname(target_dir)

        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            self.send_error(400, "Expected multipart/form-data")
            return
        m = re.search(r'boundary=(?:"([^"]+)"|([^;]+))', ctype)
        if not m:
            self.send_error(400, "Missing multipart boundary")
            return
        boundary = (m.group(1) or m.group(2)).encode("latin-1")

        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        if length <= 0:
            self.send_error(411, "Length required")
            return

        body = self.rfile.read(length)
        saved = []
        for field_name, filename, content in parse_multipart(body, boundary):
            if not filename:
                continue
            safe = os.path.basename(filename).replace("\\", "_")
            if not safe:
                continue
            dest = os.path.join(target_dir, safe)
            # Avoid clobbering existing files.
            base, ext = os.path.splitext(safe)
            counter = 1
            while os.path.exists(dest):
                dest = os.path.join(target_dir, f"{base} ({counter}){ext}")
                counter += 1
            try:
                with open(dest, "wb") as f:
                    f.write(content)
                saved.append(os.path.basename(dest))
                self.log_message("uploaded %s (%s)", os.path.basename(dest), human_size(len(content)))
            except OSError as e:
                self.log_message("upload failed: %s", e)

        # Redirect back to the directory the user was viewing.
        back = self.path if self.path.endswith("/") else self.path + "/"
        self.send_response(303)
        self.send_header("Location", back)
        self.end_headers()


# ------------------------------------------------------------------------------------
# HTML template
# ------------------------------------------------------------------------------------

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{app} - {path}</title>
<style>
  :root {{ color-scheme: light dark; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
         margin: 0; background: #f5f6f8; color: #1c1e21; }}
  header {{ background: #2b6cb0; color: #fff; padding: 16px 20px; }}
  header h1 {{ margin: 0; font-size: 18px; font-weight: 600; }}
  header .path {{ margin-top: 4px; font-size: 13px; opacity: .9; word-break: break-all; }}
  .wrap {{ max-width: 960px; margin: 0 auto; padding: 16px 20px 60px; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 10px;
          overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
  th, td {{ text-align: left; padding: 10px 14px; font-size: 14px; border-bottom: 1px solid #eceef1; }}
  th {{ background: #fafbfc; font-weight: 600; font-size: 12px; text-transform: uppercase;
       letter-spacing: .4px; color: #65676b; }}
  tr:last-child td {{ border-bottom: none; }}
  td.name a {{ color: #2b6cb0; text-decoration: none; }}
  td.name a:hover {{ text-decoration: underline; }}
  td.size, td.date {{ color: #65676b; white-space: nowrap; }}
  .upload {{ margin: 16px 0; background: #fff; padding: 14px 16px; border-radius: 10px;
            box-shadow: 0 1px 3px rgba(0,0,0,.08); display: flex; align-items: center;
            gap: 12px; flex-wrap: wrap; }}
  .filebtn {{ background: #edf2f7; padding: 8px 14px; border-radius: 8px; cursor: pointer;
             font-size: 14px; }}
  .filebtn input {{ display: none; }}
  .fn {{ font-size: 13px; color: #65676b; flex: 1; min-width: 120px; }}
  .upbtn {{ background: #2b6cb0; color: #fff; border: none; padding: 9px 18px;
           border-radius: 8px; font-size: 14px; cursor: pointer; }}
  .upbtn:hover {{ background: #245a94; }}
  footer {{ text-align: center; color: #90949c; font-size: 12px; margin-top: 24px; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #18191a; color: #e4e6eb; }}
    table, .upload {{ background: #242526; box-shadow: none; }}
    th {{ background: #2b2c2d; color: #b0b3b8; }}
    th, td {{ border-color: #3a3b3c; }}
    td.name a {{ color: #6ca8e8; }}
    .filebtn {{ background: #3a3b3c; }}
  }}
</style>
</head>
<body>
<header>
  <h1>&#128225; {app}</h1>
  <div class="path">{path}</div>
</header>
<div class="wrap">
  {upload}
  <table>
    <thead><tr><th>Name</th><th>Size</th><th>Modified</th></tr></thead>
    <tbody>
      {rows}
    </tbody>
  </table>
  <footer>{count} item(s) &middot; {app} file server</footer>
</div>
</body>
</html>"""


# ------------------------------------------------------------------------------------
# Server controller
# ------------------------------------------------------------------------------------

class ServerController:
    def __init__(self, log_callback=None):
        self.httpd = None
        self.thread = None
        self.log_callback = log_callback

    @property
    def running(self):
        return self.httpd is not None

    def start(self, directory, port, allow_upload=True):
        if self.running:
            raise RuntimeError("Server already running")

        handler = type("BoundHandler", (FileShareHandler,), {
            "root_dir": os.path.abspath(directory),
            "allow_upload": allow_upload,
            "log_callback": staticmethod(self.log_callback) if self.log_callback else None,
        })

        self.httpd = ThreadingHTTPServer(("0.0.0.0", port), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
            self.thread = None


# ------------------------------------------------------------------------------------
# GUI
# ------------------------------------------------------------------------------------

def launch_gui(initial_dir=None, initial_port=8000):
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title(f"{APP_NAME} {APP_VERSION}")
    root.geometry("640x480")
    root.minsize(560, 420)

    state = {"dir": initial_dir or os.path.expanduser("~"), "controller": None}

    # --- styling ---
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    pad = {"padx": 12, "pady": 6}
    main = ttk.Frame(root, padding=14)
    main.pack(fill="both", expand=True)

    ttk.Label(main, text=f"\U0001F4E1 {APP_NAME}", font=("Helvetica", 16, "bold")).pack(anchor="w")
    ttk.Label(main, text="Share a folder over your local network.", foreground="#666").pack(anchor="w", pady=(0, 10))

    # --- folder row ---
    folder_frame = ttk.Frame(main)
    folder_frame.pack(fill="x")
    ttk.Label(folder_frame, text="Folder:").pack(side="left")
    folder_var = tk.StringVar(value=state["dir"])
    folder_entry = ttk.Entry(folder_frame, textvariable=folder_var)
    folder_entry.pack(side="left", fill="x", expand=True, padx=6)

    def choose_folder():
        d = filedialog.askdirectory(initialdir=folder_var.get() or os.path.expanduser("~"))
        if d:
            folder_var.set(d)

    ttk.Button(folder_frame, text="Browse…", command=choose_folder).pack(side="left")

    # --- options row ---
    opts = ttk.Frame(main)
    opts.pack(fill="x", pady=(10, 4))
    ttk.Label(opts, text="Port:").pack(side="left")
    port_var = tk.StringVar(value=str(initial_port))
    port_entry = ttk.Entry(opts, textvariable=port_var, width=8)
    port_entry.pack(side="left", padx=(6, 16))
    upload_var = tk.BooleanVar(value=True)
    ttk.Checkbutton(opts, text="Allow uploads", variable=upload_var).pack(side="left")

    # --- URL display ---
    url_var = tk.StringVar(value="Server stopped.")
    url_frame = ttk.Frame(main)
    url_frame.pack(fill="x", pady=(10, 4))
    url_label = ttk.Label(url_frame, textvariable=url_var, font=("Helvetica", 11, "bold"),
                          foreground="#2b6cb0")
    url_label.pack(side="left")

    def copy_url():
        url = url_var.get()
        if url.startswith("http"):
            root.clipboard_clear()
            root.clipboard_append(url.split()[0])
            log("Copied URL to clipboard.")

    copy_btn = ttk.Button(url_frame, text="Copy", command=copy_url, state="disabled")
    copy_btn.pack(side="right")

    # --- log box ---
    ttk.Label(main, text="Activity:").pack(anchor="w", pady=(8, 2))
    log_box = tk.Text(main, height=10, wrap="word", state="disabled",
                      background="#1e1e1e", foreground="#d4d4d4", font=("Menlo", 10),
                      relief="flat")
    log_box.pack(fill="both", expand=True)

    log_lock = threading.Lock()

    def log(msg):
        stamp = time.strftime("%H:%M:%S")
        line = f"[{stamp}] {msg}\n"
        def append():
            log_box.configure(state="normal")
            log_box.insert("end", line)
            log_box.see("end")
            log_box.configure(state="disabled")
        try:
            root.after(0, append)
        except RuntimeError:
            pass

    controller = ServerController(log_callback=log)
    state["controller"] = controller

    # --- start/stop ---
    def toggle_server():
        if controller.running:
            controller.stop()
            url_var.set("Server stopped.")
            start_btn.configure(text="Start server")
            copy_btn.configure(state="disabled")
            folder_entry.configure(state="normal")
            port_entry.configure(state="normal")
            log("Server stopped.")
            return

        directory = folder_var.get().strip()
        if not directory or not os.path.isdir(directory):
            messagebox.showerror(APP_NAME, "Please choose a valid folder to share.")
            return
        try:
            port = int(port_var.get())
            if not (1 <= port <= 65535):
                raise ValueError
        except ValueError:
            messagebox.showerror(APP_NAME, "Port must be a number between 1 and 65535.")
            return

        try:
            controller.start(directory, port, allow_upload=upload_var.get())
        except OSError as e:
            messagebox.showerror(APP_NAME, f"Could not start server on port {port}.\n\n{e}")
            return

        ip = get_lan_ip()
        url = f"http://{ip}:{port}"
        url_var.set(f"{url}  (also http://localhost:{port})")
        start_btn.configure(text="Stop server")
        copy_btn.configure(state="normal")
        folder_entry.configure(state="disabled")
        port_entry.configure(state="disabled")
        log(f"Serving '{directory}' at {url}")
        log(f"Uploads {'enabled' if upload_var.get() else 'disabled'}. Open the URL on any device on your network.")

    start_btn = ttk.Button(main, text="Start server", command=toggle_server)
    start_btn.pack(pady=(10, 0), ipadx=10, ipady=2)

    def on_close():
        if controller.running:
            controller.stop()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    log(f"{APP_NAME} {APP_VERSION} ready. Choose a folder and press Start.")
    root.mainloop()


# ------------------------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=f"{APP_NAME} - share a folder over HTTP with a desktop GUI."
    )
    parser.add_argument("folder", nargs="?", help="Folder to share (skips GUI folder picker if given with --no-gui).")
    parser.add_argument("-p", "--port", type=int, default=8000, help="Port to listen on (default 8000).")
    parser.add_argument("--no-upload", action="store_true", help="Disable file uploads.")
    parser.add_argument("--no-gui", action="store_true", help="Run headless in the terminal (no window).")
    args = parser.parse_args()

    if args.no_gui:
        directory = args.folder or os.getcwd()
        if not os.path.isdir(directory):
            print(f"Error: '{directory}' is not a folder.", file=sys.stderr)
            sys.exit(1)
        controller = ServerController(log_callback=lambda m: print(m))
        controller.start(directory, args.port, allow_upload=not args.no_upload)
        ip = get_lan_ip()
        print(f"{APP_NAME} {APP_VERSION} serving '{os.path.abspath(directory)}'")
        print(f"  -> http://{ip}:{args.port}   (http://localhost:{args.port})")
        print(f"  Uploads: {'disabled' if args.no_upload else 'enabled'}")
        print("Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping...")
            controller.stop()
        return

    try:
        launch_gui(initial_dir=args.folder, initial_port=args.port)
    except Exception as e:
        # Tkinter may be unavailable in some minimal Python installs.
        print(f"Could not start the GUI ({e}).", file=sys.stderr)
        print("Try running headless:  python fileshare.py --no-gui <folder>", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
