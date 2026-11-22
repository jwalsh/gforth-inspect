"""cast.py OUT.cast COLS ROWS -- command...: record a command on a pty as asciicast v2.

asciinema 2.4 crashes on exit when the recorded program's stdin is a pipe
(it restores terminal modes on a descriptor that isn't a terminal). This
records output only, which is all a self-driving demo needs. Standard
library only.
"""

import json
import os
import pty
import select
import sys
import time

out_path, cols, rows = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
command = sys.argv[sys.argv.index("--") + 1:]

pid, master_fd = pty.fork()
if pid == 0:
    os.environ.update({"COLUMNS": str(cols), "LINES": str(rows), "TERM": "xterm-256color"})
    os.execvp(command[0], command)

start = None  # the clock starts at the first output, so frame 0 is not blank
decoder_buffer = b""
with open(out_path, "w", encoding="utf-8") as cast:
    header = {"version": 2, "width": cols, "height": rows, "env": {"TERM": "xterm-256color"}}
    cast.write(json.dumps(header) + "\n")
    while True:
        ready, _, _ = select.select([master_fd], [], [], 0.5)
        if not ready:
            if os.waitpid(pid, os.WNOHANG) != (0, 0):
                break
            continue
        try:
            chunk = os.read(master_fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        decoder_buffer += chunk
        try:
            text = decoder_buffer.decode("utf-8")
            decoder_buffer = b""
        except UnicodeDecodeError:
            continue  # wait for the rest of a multi-byte character
        if start is None:
            start = time.monotonic()
        cast.write(json.dumps([round(time.monotonic() - start, 6), "o", text]) + "\n")
