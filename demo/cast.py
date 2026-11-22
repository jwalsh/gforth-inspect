"""cast.py OUT.cast COLS ROWS -- command...: record a command on a pty as asciicast v2.

asciinema 2.4 crashes on exit when the recorded program's stdin is a pipe
(it restores terminal modes on a descriptor that isn't a terminal). This
records output only, which is all a self-driving demo needs, and exits with
the recorded command's status so a failed demo is never kept. Standard
library only.
"""

import codecs
import fcntl
import json
import os
import pty
import select
import struct
import sys
import termios
import time

out_path, cols, rows = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
command = sys.argv[sys.argv.index("--") + 1:]

pid, master_fd = pty.fork()
if pid == 0:
    os.environ.update({"COLUMNS": str(cols), "LINES": str(rows), "TERM": "xterm-256color"})
    os.execvp(command[0], command)

# give the pty the size the header claims, so TIOCGWINSZ agrees with the player
fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
start = None  # the clock starts at the first output, so frame 0 is not blank
exit_status = None


def emit(cast, text):
    global start
    if not text:
        return
    if start is None:
        start = time.monotonic()
    cast.write(json.dumps([round(time.monotonic() - start, 6), "o", text]) + "\n")


with open(out_path, "w", encoding="utf-8") as cast:
    header = {"version": 2, "width": cols, "height": rows, "env": {"TERM": "xterm-256color"}}
    cast.write(json.dumps(header) + "\n")
    while True:
        ready, _, _ = select.select([master_fd], [], [], 0.5)
        if not ready:
            waited_pid, status = os.waitpid(pid, os.WNOHANG)
            if waited_pid:
                exit_status = status
                break
            continue
        try:
            chunk = os.read(master_fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        emit(cast, decoder.decode(chunk))
    emit(cast, decoder.decode(b"", final=True))

if exit_status is None:
    _, exit_status = os.waitpid(pid, 0)
code = os.waitstatus_to_exitcode(exit_status)
if code != 0:
    print(f"cast.py: recorded command exited {code}; recording is not kept", file=sys.stderr)
sys.exit(1 if code else 0)
