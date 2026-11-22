"""Run the pinned consumers of experiment 009 on one log and classify what they did.

Consumers (pinned by blob, copied into the work dir before any run):
  jq        pbt/consumers/stacks.jq, as `jq -c -f`
  checker   pbt/consumers/checker.py  --expect E, with the consumer's own schema
  mock      pbt/consumers/mock_server.py, one GET /stacks
  bb-checker, bb-mock   the bb twins at PR #28's head, if bb and the files exist
  follower  the course's own follower (local only: counts, never content)

Verdicts:
  checker   accept | stop:minor | stop:major | reject:<reason> | crash:<exception>
  jq        follow | die:<first stderr line>
  mock      serve | serve-mismatch | 404 | crash
  follower  follow | follow+unparsable | crash:<jq error>
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
BB_REF = "0dd6d88"  # PR #28 head (exp/007-bb-consumers)


@dataclass
class Result:
    consumer: str
    verdict: str
    output: object = None            # parsed output: jq lines (decoded), checker dict, mock body
    raw: str = ""
    extra: dict = field(default_factory=dict)


def git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(REPO), *args], check=True, capture_output=True).stdout


def pin(work: Path) -> dict[str, str]:
    """Copy the consumers into WORK/consumers; return name -> blob (public ones only)."""
    out = work / "consumers"
    out.mkdir(parents=True, exist_ok=True)
    blobs = {}
    for name in ("stacks.jq", "checker.py", "mock_server.py"):
        content = git("show", f"HEAD:pbt/consumers/{name}")
        (out / name).write_bytes(content)
        blobs[name] = git("rev-parse", f"HEAD:pbt/consumers/{name}").decode().strip()[:12]
    if shutil.which("bb"):
        for name in ("checker.clj", "mock_server.clj"):
            try:
                content = git("show", f"{BB_REF}:pbt/consumers/bb/{name}")
            except subprocess.CalledProcessError:
                continue
            (out / f"bb-{name}").write_bytes(content)
            blobs[f"bb/{name}"] = git("rev-parse", f"{BB_REF}:pbt/consumers/bb/{name}").decode().strip()[:12]
    sys.path.insert(0, str(HERE))
    import ledger
    root = ledger.vc_root()
    if root is not None:
        shutil.copyfile(root / "scripts" / "stacks-tail.sh", out / "follower.sh")
    return blobs


def available(work: Path) -> list[str]:
    out = work / "consumers"
    names = ["jq", "checker", "mock"]
    if (out / "bb-checker.clj").exists():
        names.append("bb-checker")
    if (out / "bb-mock_server.clj").exists():
        names.append("bb-mock")
    if (out / "follower.sh").exists():
        names.append("follower")
    return names


# --- jq ------------------------------------------------------------------

def run_jq(work: Path, log: Path) -> Result:
    proc = subprocess.run(["jq", "-c", "-f", str(work / "consumers" / "stacks.jq"), str(log)],
                          capture_output=True)
    lines = proc.stdout.decode("utf-8", "replace").splitlines()
    decoded = [json.loads(line) for line in lines]
    if proc.returncode == 0:
        return Result("jq", "follow", decoded, raw="\n".join(lines))
    first = (proc.stderr.decode("utf-8", "replace").strip().splitlines() or ["?"])[0]
    reason = first.split(":")[1].strip() if first.startswith("jq: error") else first[:60]
    return Result("jq", f"die:{reason[:60]}", decoded, raw="\n".join(lines))


# --- checker --------------------------------------------------------------

def classify_checker(name: str, proc: subprocess.CompletedProcess) -> Result:
    stdout = proc.stdout.decode("utf-8", "replace").strip()
    stderr = proc.stderr.decode("utf-8", "replace").strip()
    try:
        output = json.loads(stdout)
    except ValueError:
        last = (stderr.splitlines() or ["(no stderr)"])[-1]
        return Result(name, f"crash:{last[:70]}", None, raw=stdout)
    if not isinstance(output, dict):
        return Result(name, "crash:non-object output", output, raw=stdout)
    if "stopped" in output:
        kind = "minor" if "(minor update)" in output["stopped"] else "major"
        return Result(name, f"stop:{kind}", output, raw=stdout)
    if "error" in output:
        return Result(name, f"reject:{output['error'][:60]}", output, raw=stdout)
    if proc.returncode == 0 and "event" in output:
        return Result(name, "accept", output, raw=stdout)
    return Result(name, f"crash:exit {proc.returncode}", output, raw=stdout)


def run_checker(work: Path, log: Path, schema: Path, expect: str = "1.1",
                twin: bool = False, no_stop: bool = False) -> Result:
    if twin:
        command = ["bb", str(work / "consumers" / "bb-checker.clj")]
    else:
        command = [sys.executable, str(work / "consumers" / "checker.py")]
    flags = ["--no-version-stop"] if no_stop else []
    proc = subprocess.run(command + [str(log), str(schema), "--expect", expect, *flags], capture_output=True)
    return classify_checker("bb-checker" if twin else "checker", proc)


# --- mock server ---------------------------------------------------------------

def run_mock(work: Path, log: Path, twin: bool = False) -> Result:
    name = "bb-mock" if twin else "mock"
    if twin:
        command = ["bb", str(work / "consumers" / "bb-mock_server.clj"), str(log)]
    else:
        command = [sys.executable, str(work / "consumers" / "mock_server.py"), str(log)]
    server = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        port_line = server.stdout.readline()
        if not port_line.startswith("PORT "):
            return Result(name, "crash:no PORT line", None)
        url = f"http://127.0.0.1:{port_line.split()[1]}/stacks"
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                status, body, ctype = response.status, response.read(), response.headers.get("Content-Type")
        except urllib.error.HTTPError as error:
            status, body, ctype = error.code, error.read(), error.headers.get("Content-Type")
    finally:
        server.terminate()
        server.wait(timeout=5)
    if status == 404:
        return Result(name, "404", None, extra={"status": 404})
    content = log.read_bytes() if log.exists() else b""
    lines = [line for line in content.split(b"\n") if line]
    verdict = "serve" if lines and body == lines[-1] else "serve-mismatch"
    return Result(name, verdict, body.decode("utf-8", "replace"),
                  extra={"status": status, "content-type": ctype})


# --- the course follower (local only) --------------------------------------------

def run_follower(work: Path, log: Path, settle: float = 1.2) -> Result:
    """stacks-tail.sh as written, pointed at the log's directory, killed after `settle` s."""
    env = {key: value for key, value in os.environ.items() if key != "XDG_STATE_HOME"}
    env["GFORTH_INSPECT_LOG_DIR"] = str(log.parent)
    env["TZ"] = "UTC"
    proc = subprocess.Popen(["bash", str(work / "consumers" / "follower.sh")], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    time.sleep(settle)
    os.killpg(proc.pid, signal.SIGTERM)
    stdout, stderr = proc.communicate(timeout=5)
    lines = stdout.decode("utf-8", "replace").splitlines()
    errors = [line for line in stderr.decode("utf-8", "replace").splitlines() if line.startswith("jq:")]
    if errors:
        reason = errors[0].split(":", 2)[-1].strip()
        return Result("follower", f"crash:{reason[:60]}", len(lines), extra={"lines": len(lines)})
    unparsable = sum(1 for line in lines if line.startswith("?? unparsable"))
    nulls = sum(1 for line in lines if "data=null" in line)
    verdict = "follow+unparsable" if unparsable else "follow"
    return Result("follower", verdict, len(lines),
                  extra={"lines": len(lines), "unparsable": unparsable, "data-null": nulls})


def run_all(work: Path, log: Path, consumer_schema: Path, expect: str = "1.1",
            names: list[str] | None = None) -> dict[str, Result]:
    names = names or available(work)
    results: dict[str, Result] = {}
    for name in names:
        if name == "jq":
            results[name] = run_jq(work, log)
        elif name == "checker":
            results[name] = run_checker(work, log, consumer_schema, expect)
        elif name == "bb-checker":
            results[name] = run_checker(work, log, consumer_schema, expect, twin=True)
        elif name == "mock":
            results[name] = run_mock(work, log)
        elif name == "bb-mock":
            results[name] = run_mock(work, log, twin=True)
        elif name == "follower":
            results[name] = run_follower(work, log)
    return results
