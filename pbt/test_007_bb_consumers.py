"""007 bb-consumers: do the Babashka twins of the reference checker and mock
server give the Python originals' output on every input?  See
experiments/007-bb-consumers/README.org; the gate items are named below.

Both sides run on the same bytes, and each twin is compared with its
original live, never with a recorded copy (the corpus is compared both
ways).  Python side: checker.py imported as written and called through its
main(), with stdout a strict UTF-8 stream as a real one is, so a crash and
a failed print are outputs, as in 004.  bb side: pbt/consumers/bb/driver.clj
runs many argument vectors through checker.clj's run-cli, the function its
command line runs.  test_cli_matches_in_process checks that both shortcuts
agree with the real command lines.  The servers are always real processes.

Outputs are compared by value: exit status, the stdout object with floats
by bit pattern and numbers by JSON type (004's _same), and the exception
line on a crash.  Byte identity of stdout is counted, not required.

BB_CONSUMERS_DIR selects the twins (default pbt/consumers/bb); the
calibration scripts point it at a planted copy.
"""

from __future__ import annotations

import contextlib
import http.client
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

import pytest
from hypothesis import Phase, given, settings
from hypothesis import strategies as st

import gforth_run
from test_004_reference_consumers import _inject, _same, _strip_unknown, build, programs

PBT = Path(__file__).resolve().parent
REPO = PBT.parent
CONSUMERS = PBT / "consumers"
BB_DIR = Path(os.environ.get("BB_CONSUMERS_DIR", CONSUMERS / "bb")).resolve()
UNKNOWN = "x-unknown-004"

sys.path.insert(0, str(CONSUMERS))
import checker  # noqa: E402  (the original, imported as written; never edited)

# bb runs the reference consumers (docs/RELEASING.org): on CI a missing bb is a
# failure, never a skip; locally a skip, so the rest of the suite still runs.
if shutil.which("bb") is None and os.environ.get("CI"):
    raise RuntimeError("bb is not installed on CI; the reference consumers need it")
pytestmark = pytest.mark.skipif(shutil.which("bb") is None, reason="bb is not installed")

STATS: dict = {"records": 0, "logs": 0, "checker": 0, "server": 0, "bytes_identical": 0, "stdout_compared": 0,
               "disagreements": Counter(), "started": time.monotonic(), "lines": [],
               "time": Counter(), "differential_ran": False}


class _Summary:
    def pytest_terminal_summary(self, terminalreporter):
        write = terminalreporter.write_line
        write("== 007 bb-consumers summary")
        write(f"twins: {BB_DIR.relative_to(REPO) if BB_DIR.is_relative_to(REPO) else BB_DIR.name}  "
              f"producer: {gforth_run.inspect_source()[1]}")
        write(f"gforth snapshot records {STATS['records']}  logs {STATS['logs']}  "
              f"checker comparisons {STATS['checker']} (stdout byte-identical in "
              f"{STATS['bytes_identical']} of {STATS['stdout_compared']} past usage errors)  server comparisons {STATS['server']}  "
              f"wall {time.monotonic() - STATS['started']:.1f}s")
        if STATS["time"]:
            write("  time in the differential: " + ", ".join(f"{k} {v:.1f}s" for k, v in sorted(STATS["time"].items())))
        if not STATS["disagreements"]:
            write("disagreements: none")
        for kind, count in sorted(STATS["disagreements"].items()):
            write(f"  disagree {kind} n={count}")
        for example in STATS.get("not_identical", [])[:5]:
            write(f"  stdout equal by value, not by bytes: {example}")
        for line in STATS["lines"]:
            write(line)


@pytest.fixture(scope="module", autouse=True)
def _summary(request):
    if request.config.pluginmanager.get_plugin("007-summary") is None:
        request.config.pluginmanager.register(_Summary(), "007-summary")
    yield


# --- the two checkers ------------------------------------------------------

def _crash_line(error: BaseException) -> str:
    """The last line of the traceback Python would print."""
    cls = type(error)
    name = cls.__qualname__ if cls.__module__ == "builtins" else f"{cls.__module__}.{cls.__qualname__}"
    return f"{name}: {error}"


def py_checker(args: list[str]) -> dict:
    """checker.py's main(args), as its command line would behave."""
    raw = io.BytesIO()
    stdout = io.TextIOWrapper(raw, encoding="utf-8", errors="strict", write_through=True)
    crash = None
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
            status = checker.main(args)
    except SystemExit as error:  # argparse
        status = error.code
    except Exception as error:  # noqa: BLE001  (an uncaught exception is exit 1)
        status, crash = 1, _crash_line(error)
    return {"exit": status, "out": raw.getvalue().decode("utf-8"), "crash": crash}


def _bb_result(result: dict) -> dict:
    err_lines = [line for line in result["err"].splitlines() if line.strip()]
    crash = err_lines[-1] if result["exit"] == 1 and not result["out"] and err_lines else None
    return {"exit": result["exit"], "out": result["out"], "crash": crash, "err": result["err"]}


def bb_checker_many(jobs: list[list[str]], scratch: Path) -> list[dict]:
    jobs_path = scratch / "jobs.json"
    jobs_path.write_text(json.dumps(jobs))
    proc = subprocess.run(["bb", str(BB_DIR / "driver.clj"), str(jobs_path)], capture_output=True,
                          timeout=300)
    assert proc.returncode == 0, f"bb driver failed: {proc.stderr.decode('utf-8', 'replace')[-800:]}"
    return [_bb_result(result) for result in json.loads(proc.stdout.decode("utf-8"))]


def py_checker_cli(args: list[str]) -> dict:
    proc = subprocess.run([sys.executable, str(CONSUMERS / "checker.py"), *args], capture_output=True)
    err_lines = [line for line in proc.stderr.decode("utf-8", "replace").splitlines() if line.strip()]
    out = proc.stdout.decode("utf-8")
    crash = err_lines[-1] if proc.returncode == 1 and not out and err_lines else None
    return {"exit": proc.returncode, "out": out, "crash": crash}


def bb_checker_cli(args: list[str]) -> dict:
    proc = subprocess.run(["bb", str(BB_DIR / "checker.clj"), *args], capture_output=True)
    return _bb_result({"exit": proc.returncode, "out": proc.stdout.decode("utf-8"),
                       "err": proc.stderr.decode("utf-8", "replace")})


def _parsed(out: str):
    return json.loads(out) if out.strip() else None


def checker_disagreement(py: dict, bb: dict) -> str | None:
    """None if the twin's output equals the original's by value."""
    STATS["checker"] += 1
    if py["exit"] != bb["exit"]:
        return f"exit {py['exit']} != {bb['exit']} (py {py['out'][:120]!r} {py['crash']}; " \
               f"bb {bb['out'][:120]!r} {bb['crash'] or bb.get('err', '')[-200:]})"
    if py["exit"] == 2:  # usage: argparse's text is not compared
        return None
    if py["crash"] != bb["crash"]:
        return f"crash {py['crash']!r} != {bb['crash']!r}"
    try:
        bb_value = _parsed(bb["out"])
    except ValueError:
        return f"bb stdout is not JSON: {bb['out'][:200]!r}"
    if not _same(_parsed(py["out"]), bb_value):
        return f"stdout {py['out'][:200]} != {bb['out'][:200]}"
    STATS["stdout_compared"] += 1
    if py["out"] == bb["out"]:
        STATS["bytes_identical"] += 1
    else:
        STATS.setdefault("not_identical", []).append(f"{py['out'][:100]!r} vs {bb['out'][:100]!r}")
    return None


# --- the two servers -------------------------------------------------------

class Server:
    def __init__(self, command: list[str]):
        self.proc = subprocess.Popen(command, stdout=subprocess.PIPE, text=True)
        port_line = self.proc.stdout.readline()
        assert port_line.startswith("PORT "), f"{command[-2]}: {port_line!r}"
        self.port = int(port_line.split()[1])

    def get(self, path: str = "/stacks") -> tuple[int, str | None, bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            return response.status, response.getheader("Content-Type"), response.read()
        finally:
            connection.close()

    def stop(self) -> None:
        self.proc.terminate()
        self.proc.wait(timeout=5)


@pytest.fixture(scope="module")
def servers():
    """Both servers on one file: (served path, python server, bb server)."""
    with tempfile.TemporaryDirectory(prefix="gfi-007-srv-") as tmp:
        served = Path(tmp) / "stacks.jsonl"
        with contextlib.ExitStack() as stack:
            python_server = Server([sys.executable, str(CONSUMERS / "mock_server.py"), str(served)])
            stack.callback(python_server.stop)
            bb_server = Server(["bb", str(BB_DIR / "mock_server.clj"), str(served)])
            stack.callback(bb_server.stop)
            yield served, python_server, bb_server


def expected_last_line(content: bytes) -> bytes | None:
    lines = [line for line in content.split(b"\n") if line]
    return lines[-1] if lines else None


def server_disagreement(servers, content: bytes | None, path: str = "/stacks") -> str | None:
    """Serve `content` (None: no file) to both servers; None if they answer alike."""
    served, python_server, bb_server = servers
    if content is None:
        served.unlink(missing_ok=True)
    else:
        served.write_bytes(content)
    STATS["server"] += 1
    py_answer, bb_answer = python_server.get(path), bb_server.get(path)
    if py_answer != bb_answer:
        return f"server {path}: py {py_answer[0]} {py_answer[1]} {py_answer[2][:80]!r} != " \
               f"bb {bb_answer[0]} {bb_answer[1]} {bb_answer[2][:80]!r}"
    if path == "/stacks" and content is not None and expected_last_line(content) is not None \
            and py_answer[2] != expected_last_line(content):
        return "server: body is not the last line"  # the original's own contract
    return None


# --- logs ------------------------------------------------------------------

def _log(lines: list[bytes]) -> bytes:
    return b"".join(line + b"\n" for line in lines)


def _schema_text() -> str:
    return json.dumps(gforth_run.schema())


def _renamed_schema() -> str:
    """004-rename-data's schema plant, as text."""
    return re.sub('"data"', '"stack"', _schema_text())


def _dumps(record: dict) -> bytes:
    return json.dumps(record, separators=(",", ":")).encode("ascii")


def _with_raw(record: dict, key: str, raw: str, inside: str | None = None) -> bytes:
    """The record with record[key] (or record[inside][key]) as raw JSON text."""
    record = json.loads(json.dumps(record))
    (record[inside] if inside else record)[key] = "@@RAW@@"
    return _dumps(record).replace(b'"@@RAW@@"', raw.encode("utf-8"), 1)


def mutations(line: bytes) -> list[tuple[str, bytes, str]]:
    """(name, mutated line, schema) for one snapshot line: every keyword the
    checker implements gets records that violate it, and the reader's and
    printer's edge cases get records that reach them.  schema is "real" or
    "renamed" (004-rename-data's schema)."""
    record = json.loads(line.decode("utf-8"))

    def edit(**changes):
        mutated = json.loads(json.dumps(record))
        for key, value in changes.items():
            if key.startswith("input_"):
                mutated["input"][key[len("input_"):]] = value
            elif value is DELETE:
                mutated.pop(key)
            else:
                mutated[key] = value
        return _dumps(mutated)

    without_text = json.loads(json.dumps(record))
    without_text["input"].pop("text")
    renamed = json.loads(json.dumps(record))
    renamed["stack"] = renamed.pop("data")
    odd_keys = {"word": "w", "off": 1, "\U00010000": 1, "￿": 2, "é": 3, "it's": 4,
                'q"': 5, "b'\"": 6, "\x01": 7, " ": 8, "\ud800": 9, "\x7f": 10, "\xa0": 11}
    return [
        ("type-data-str", edit(data="x"), "real"),
        ("type-line-float", edit(input_line=1.5), "real"),
        ("type-line-bool", edit(input_line=True), "real"),
        ("type-where-int", edit(where=1), "real"),
        ("type-float-item-str", edit(float=["s"]), "real"),
        ("float-overflow", _with_raw(record, "float", "[1e400,-1e400,1E+2,5e-324,1e16,-0.0,0.1]"), "real"),
        ("data-4300-digits", _with_raw(record, "data", "[" + "9" * 4300 + ",-" + "9" * 4300 + "]"), "real"),
        ("data-4301-digits", _with_raw(record, "data", "[" + "9" * 4301 + "]"), "real"),
        ("data-float-one", _with_raw(record, "data", "[1.0]"), "real"),
        ("data-minus-zero", _with_raw(record, "data", "[-0]"), "real"),
        ("items-data-mixed", edit(data=[1, "2"]), "real"),
        ("const-v-2", edit(v=2), "real"),
        ("const-v-float", _with_raw(record, "v", "1.0"), "real"),
        ("const-v-true", edit(v=True), "real"),
        ("const-v-str", edit(v="1"), "real"),
        ("enum-event", edit(event="snap"), "real"),
        ("enum-event-true", edit(event=True), "real"),
        ("enum-event-list", edit(event=["snapshot"]), "real"),
        ("oneof-hello-no-gforth", edit(event="hello"), "real"),
        ("oneof-hello-with-gforth", edit(event="hello", gforth="x"), "real"),
        ("required-data", edit(data=DELETE), "real"),
        ("required-t", edit(t=DELETE), "real"),
        ("required-v", edit(v=DELETE), "real"),
        ("required-input-text", _dumps(without_text), "real"),
        ("additional-one", edit(rs=[{"word": "w", "off": 1, "x": 2}]), "real"),
        ("additional-sorted", edit(rs=[odd_keys]), "real"),
        ("oneof-rs-sp", edit(rs=["sp", 3, {"word": "w", "off": -1}]), "real"),
        ("oneof-rs-spx", edit(rs=["spx"]), "real"),
        ("oneof-rs-float", edit(rs=[1.5]), "real"),
        ("oneof-rs-bool", edit(rs=[True]), "real"),
        ("oneof-rs-no-off", edit(rs=[{"word": "w"}]), "real"),
        ("surrogate-lone", edit(input_text="ab\ud800cd"), "real"),
        ("surrogate-run", edit(input_text="a\ud800\udbffz"), "real"),
        ("surrogate-reversed", edit(input_text="\udc00\ud800"), "real"),
        ("surrogate-pair", edit(input_text="a😀"), "real"),
        ("surrogate-in-where", edit(where="\udfff"), "real"),
        ("escapes", _with_raw(record, "text", '"\\/\\b\\f\\n\\r\\t\\u0000\\u001f\\"\\\\\x7fé\U0001f600"',
                              inside="input"), "real"),
        ("in-float-exp", _with_raw(record, "in", "1E2", inside="input"), "real"),
        ("dup-key-type", line[:-1] + b',"data":"dup"}', "real"),
        ("dup-key-value", line[:-1] + b',"data":[7]}', "real"),
        ("dup-key-input", line.replace(b'"input":{', b'"input":{"file":"first",', 1), "real"),
        ("raw-control", line.replace(b'"text":"', b'"text":"\x01', 1), "real"),
        ("trailing-object", line + b'{"a":1}', "real"),
        ("trailing-space-cr", line + b" \r", "real"),
        ("leading-ws", b" \t" + line, "real"),
        ("bom", b"\xef\xbb\xbf" + line, "real"),
        ("nan-last", _with_raw(record, "float", "[NaN]"), "real"),
        ("infinity-last", _with_raw(record, "float", "[-Infinity]"), "real"),
        ("leading-zero", _with_raw(record, "in", "01", inside="input"), "real"),
        ("trailing-comma", _with_raw(record, "data", "[1,]"), "real"),
        ("not-utf8-ff", line.replace(b'"text":"', b'"text":"\xff', 1), "real"),
        ("not-utf8-overlong", line.replace(b'"text":"', b'"text":"\xc0\xaf', 1), "real"),
        ("not-utf8-surrogate", line.replace(b'"text":"', b'"text":"\xed\xa0\x80', 1), "real"),
        ("not-utf8-past-max", line.replace(b'"text":"', b'"text":"\xf4\x90\x80\x80', 1), "real"),
        ("top-array", b"[]", "real"),
        ("top-null", b"null", "real"),
        ("top-empty-object", b"{}", "real"),
        ("renamed-schema-plain", line, "renamed"),
        ("renamed-schema-keyerror", _dumps(renamed), "renamed"),
    ]


DELETE = object()


def hello_variants(hello: bytes) -> list[tuple[str, bytes]]:
    record = json.loads(hello.decode("utf-8"))

    def with_contract(value):
        mutated = dict(record)
        if value is DELETE:
            mutated.pop("contract", None)
        else:
            mutated["contract"] = value
        return _dumps(mutated)

    return [
        ("contract-1.2", with_contract("1.2")),
        ("contract-1", with_contract("1")),
        ("contract-empty", with_contract("")),
        ("contract-1.1.7", with_contract("1.1.7")),
        ("contract-2.1", with_contract("2.1")),
        ("contract-01.1", with_contract("01.1")),
        ("contract-number", with_contract(1.1)),
        ("contract-null", with_contract(None)),
        ("contract-missing", with_contract(DELETE)),
        ("hello-nan", hello[:-1] + b',"x":NaN}'),
        ("hello-raw-control", hello[:-1] + b',"x":"\x01"}'),
        ("hello-dup-contract", hello[:-1] + b',"contract":"1.2"}'),
        ("hello-event-dup", hello[:-1] + b',"event":"snapshot"}'),
    ]


EXPECTS = ["1.1", "1.2", "2.0", "2", "1.1.0", "", "1.1."]


# --- gate 1: corpus ----------------------------------------------------------

CORPUS_REF = "origin/main"  # PR #22 merged the corpus


def _git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(REPO), *args], check=True, capture_output=True).stdout


def corpus_files() -> tuple[str, dict[str, bytes]]:
    """(where the corpus came from, {name: content}) for corpus/*."""
    tree = REPO / "corpus"
    if tree.is_dir() and list(tree.glob("*.expect.json")):
        return "tree", {path.name: path.read_bytes() for path in tree.iterdir() if path.is_file()}
    try:
        names = _git("ls-tree", "--name-only", f"{CORPUS_REF}:corpus").decode().split()
    except subprocess.CalledProcessError:
        return "", {}
    return CORPUS_REF, {name: _git("show", f"{CORPUS_REF}:corpus/{name}") for name in names}


def test_corpus(servers, tmp_path):
    source, files = corpus_files()
    if not files:
        pytest.skip(f"no corpus: neither corpus/ nor {CORPUS_REF}")
    schema_blob = re.search(rb"stacks-log.schema.json blob ([0-9a-f]{40})", files["PROVENANCE"]).group(1)
    schema_path = tmp_path / "schema.json"
    schema_path.write_bytes(_git("cat-file", "blob", schema_blob.decode()))
    scenarios = sorted(name[:-len(".expect.json")] for name in files if name.endswith(".expect.json"))
    assert len(scenarios) >= 16, scenarios
    failures = []
    for scenario in scenarios:
        log_path = tmp_path / f"{scenario}.jsonl"
        log_path.write_bytes(files[f"{scenario}.jsonl"])
        expect = json.loads(files[f"{scenario}.expect.json"])
        args = [str(log_path), str(schema_path)]
        py, bb = py_checker_cli(args), bb_checker_cli(args)
        for problem in [checker_disagreement(py, bb),
                        None if bb["exit"] == expect["checker"]["exit"] else f"exit vs expect.json",
                        None if _same(_parsed(bb["out"]), expect["checker"]["output"]) else "output vs expect.json",
                        server_disagreement(servers, files[f"{scenario}.jsonl"])]:
            if problem:
                failures.append(f"{scenario}: {problem}")
        status, _, body = servers[2].get()
        if (status, body.decode("utf-8")) != (expect["mock_get_stacks"]["status"], expect["mock_get_stacks"]["body"]):
            failures.append(f"{scenario}: bb server vs expect.json: {status} {body[:80]!r}")
    STATS["lines"].append(f"gate 1 corpus ({source}): {len(scenarios)} scenarios, "
                          f"{len(failures)} disagreements")
    assert not failures, "\n".join(failures)


# --- gate 2: the 004 plants and the contract-1.2 version stop ---------------

PLANT_PROGRAM = (": w 7 >r ~~~ r> drop ;\n"
                 "log-on 255 -3 1 1e -0e 0e 0e f/ .stacks fclearstack clearstack w log-off")
PLANTS = ["004-rename-data", "004-split-record", "004-hex-integer", "004-nan-zero",
          "004-default-path-empty", "004-contract-minor"]


def _plant(name: str, tmp: Path) -> tuple[Path, Path]:
    """Apply the 004 plant's own sed to harden's inspect.fs (and schema)."""
    script = (PBT / "calibrate" / f"{name}.sh").read_text()
    inspect_fs, _ = gforth_run.inspect_source()
    planted_fs, planted_schema = tmp / "inspect.fs", tmp / "schema.json"
    planted_schema.write_text(_schema_text())
    for function, target, original in [("plant_fs", planted_fs, inspect_fs.read_bytes()),
                                       ("plant_schema", planted_schema, planted_schema.read_bytes())]:
        match = re.search(rf"^{function} '(.*)'$", script, re.M)
        if match:
            planted = subprocess.run(["sed", match.group(1)], input=original, capture_output=True,
                                     check=True).stdout
            assert planted != original, f"{name}: {function} did not apply"
            target.write_bytes(planted)
        elif function == "plant_fs":
            target.write_bytes(original)
    return planted_fs, planted_schema


@contextlib.contextmanager
def _env(**values):
    saved = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _planted_log(name: str, tmp: Path) -> tuple[Path, Path]:
    """(the log a consumer reads, the schema) for one plant."""
    planted_fs, planted_schema = _plant(name, tmp)
    log_path = tmp / "stacks.jsonl"
    if name == "004-default-path-empty":
        # the consumer reads the documented default; the plant left it empty
        program = tmp / "prog.fs"
        program.write_text(PLANT_PROGRAM + "\nbye\n")
        home = tmp / "home"
        home.mkdir()
        env = {key: value for key, value in os.environ.items() if key != "GFORTH_INSPECT_LOG_DIR"}
        env.update(XDG_STATE_HOME=str(tmp / "state"), HOME=str(home))
        subprocess.run(["gforth", "inspect.fs", "prog.fs"], cwd=tmp, env=env, capture_output=True,
                       stdin=subprocess.DEVNULL, timeout=30, check=False)
        return tmp / "state" / "gforth-inspect" / "stacks.jsonl", planted_schema
    with _env(INSPECT_FS=str(planted_fs)):
        result = gforth_run.run(PLANT_PROGRAM, timeout=30)
    log_path.write_bytes(_log([line.encode("utf-8", "surrogateescape") for line in result.log_lines]))
    return log_path, planted_schema


def test_planted_breaks(servers, tmp_path):
    failures, seen = [], []
    for name in PLANTS:
        tmp = tmp_path / name
        tmp.mkdir()
        log_path, schema_path = _planted_log(name, tmp)
        content = log_path.read_bytes() if log_path.exists() else None
        # every prefix, as 004 reads them: the checker sees only the last line
        lines = [line for line in content.split(b"\n") if line] if content else []
        prefixes = [(f"[:{end}]", _log(lines[:end])) for end in range(1, len(lines) + 1)]
        if content is not None and not content.endswith(b"\n"):
            prefixes.append(("whole", content))
        for label, prefix in prefixes or [("missing", None)]:
            prefix_path = log_path if prefix is None else tmp / f"prefix{len(seen)}.jsonl"
            if prefix is not None:
                prefix_path.write_bytes(prefix)
            for extra in ([], ["--no-version-stop"]):
                args = [str(prefix_path), str(schema_path), *extra]
                py, bb = py_checker_cli(args), bb_checker_cli(args)
                seen.append(f"{name} {label}{' ' + extra[0] if extra else ''}: "
                            f"{(py['out'].strip() or py['crash'] or '')[:110]}")
                problem = checker_disagreement(py, bb)
                if problem:
                    failures.append(f"{name} {label} {extra}: {problem}")
            problem = server_disagreement(servers, prefix)
            if problem:
                failures.append(f"{name} {label}: {problem}")
    STATS["lines"] += ["gate 2 plants, the Python checker's output:"] + [f"  {line}" for line in seen]
    assert not failures, "\n".join(failures)


def test_contract_minor_version_stop(tmp_path):
    """A producer announcing 1.2, read four ways.  The originals' answers
    are pinned too, so a twin that ignores MINOR cannot agree by accident."""
    log_path, schema_path = _planted_log("004-contract-minor", tmp_path)
    cases = [([], "stopped", "(minor update)"), (["--expect", "1.2"], "event", None),
             (["--expect", "2.0"], "stopped", "(major update)"), (["--no-version-stop"], "event", None)]
    failures = []
    for extra, key, phrase in cases:
        args = [str(log_path), str(schema_path), *extra]
        py, bb = py_checker_cli(args), bb_checker_cli(args)
        py_out = _parsed(py["out"])
        assert key in py_out and (phrase is None or phrase in py_out[key]), f"original: {extra} {py_out}"
        problem = checker_disagreement(py, bb)
        if problem:
            failures.append(f"version stop {extra}: {problem}")
    assert not failures, "\n".join(failures)


# --- gates 3 and 4: the generated differential ------------------------------

_no_shrink = os.environ.get("PBT_007_NO_SHRINK")
_phases = settings(phases=[Phase.explicit, Phase.reuse, Phase.generate]) if _no_shrink else (lambda f: f)


def _record_disagreement(kind: str, failures: list[str], problem: str | None) -> None:
    if problem:
        STATS["disagreements"][kind] += 1
        failures.append(f"disagree {kind}: {problem}")


@_phases
@given(batch=st.lists(programs, min_size=6, max_size=10),  # >= 600 records at 100 examples
       cuts=st.lists(st.integers(0, 2**20), min_size=3, max_size=6))
def test_generated_differential(batch, cuts, servers):
    STATS["differential_ran"] = True
    source, _, _ = build(batch)
    result = gforth_run.run(source, timeout=30)
    assert result.returncode == 0, f"gforth exit {result.returncode}: {result.stderr[-400:]}"
    lines = [line.encode("utf-8", "surrogateescape") for line in result.log_lines]
    snapshots = [line for line in lines if b'"event":"snapshot"' in line]
    assert len(snapshots) == len(batch), f"{len(snapshots)} snapshots for {len(batch)} programs"
    STATS["records"] += len(snapshots)
    injected = [_inject(line.decode("utf-8", "surrogateescape")).encode("utf-8", "surrogateescape")
                for line in lines]

    with tempfile.TemporaryDirectory(prefix="gfi-007-") as tmp:
        scratch = Path(tmp)
        schemas = {"real": scratch / "schema.json", "renamed": scratch / "renamed.json"}
        schemas["real"].write_text(_schema_text())
        schemas["renamed"].write_text(_renamed_schema())
        logs: list[tuple[str, bytes]] = []  # (label, content), for both checkers and servers
        jobs: list[tuple[str, list[str]]] = []  # (label, args)

        def add(label: str, content: bytes, schema: str = "real", modes=("stop", "no-stop"),
                expects=(None,)):
            path = scratch / f"log{len(logs)}.jsonl"
            path.write_bytes(content)
            logs.append((label, content))
            for mode in modes:
                for expect in expects:
                    args = [str(path), str(schemas[schema])]
                    args += ["--no-version-stop"] if mode == "no-stop" else []
                    args += ["--expect", expect] if expect is not None else []
                    jobs.append((f"{label} {mode}{' --expect ' + repr(expect) if expect is not None else ''}",
                                 args))

        for end in range(1, len(lines) + 1):
            add(f"plain[:{end}]", _log(lines[:end]))
            add(f"injected[:{end}]", _log(injected[:end]))
        for name, mutated, schema in mutations(snapshots[-1]):
            add(f"mutation {name}", _log(lines[:-1] + [mutated]), schema, modes=("no-stop",))
        for name, hello in hello_variants(lines[0]):
            add(f"hello {name}", _log([hello] + lines[1:]), expects=EXPECTS if name == "contract-1.2" else (None,),
                modes=("stop",))
        whole = _log(lines)
        multibyte = [index + 1 for index, byte in enumerate(whole) if byte >= 0xC0]
        for cut in sorted({cut % (len(whole) + 1) for cut in cuts} | set(multibyte[:2])):
            add(f"cut[:{cut}]", whole[:cut], modes=("stop",))
        STATS["logs"] += len(logs)

        clock = time.monotonic()
        py_results = [py_checker(args) for _, args in jobs]
        STATS["time"]["py checker"] += time.monotonic() - clock
        clock = time.monotonic()
        bb_results = bb_checker_many([args for _, args in jobs], scratch)
        STATS["time"]["bb checker"] += time.monotonic() - clock
        clock = time.monotonic()
        failures: list[str] = []
        for (label, _), py, bb in zip(jobs, py_results, bb_results):
            _record_disagreement("checker", failures, (lambda p: p and f"{label}: {p}")(checker_disagreement(py, bb)))

        # gate 3: the injected key changes neither side's output
        by_label = {label: (py, bb) for (label, _), py, bb in zip(jobs, py_results, bb_results)}
        for end in range(1, len(lines) + 1):
            for mode in ("stop", "no-stop"):
                plain, with_key = by_label[f"plain[:{end}] {mode}"], by_label[f"injected[:{end}] {mode}"]
                for side, index in (("py", 0), ("bb", 1)):
                    if not _same(_parsed(plain[index]["out"]), _parsed(with_key[index]["out"])) \
                            or plain[index]["exit"] != with_key[index]["exit"]:
                        _record_disagreement("unknown-key", failures,
                                             f"{side} [:{end}] {mode}: {plain[index]['out'][:100]} != "
                                             f"{with_key[index]['out'][:100]}")

        for label, content in logs:
            _record_disagreement("server", failures, (lambda p: p and f"{label}: {p}")(
                server_disagreement(servers, content)))
            if label.startswith("injected"):  # the file still holds this log
                end = int(label[len("injected[:"):-1])
                _, _, bb_body = servers[2].get()
                if not _same(_strip_unknown([json.loads(bb_body)]), [json.loads(lines[end - 1])]):
                    _record_disagreement("unknown-key", failures, f"bb server {label}")
        STATS["time"]["servers"] += time.monotonic() - clock
    assert not failures, "\n".join(failures[:15])


def test_zz_volume():
    """Gate 4 asks for at least 500 gforth records (runs after the differential)."""
    if not STATS["differential_ran"]:
        pytest.skip("test_generated_differential did not run in this session")
    assert STATS["records"] >= 500, f"only {STATS['records']} gforth snapshot records"


# --- gate 6: server bytes ----------------------------------------------------

def test_server_bytes(servers):
    hello = b'{"v":1,"event":"hello","t":0,"gforth":"0.7.3","contract":"1.1"}'
    snapshot = b'{"v":1,"event":"snapshot","t":0,"input":{"text":"caf\xc3\xa9 \xff \xed\xa0\x80"}}'
    cases = [
        ("0xFF in the last line", hello + b"\n" + snapshot + b"\n", "/stacks"),
        ("0xFF alone", b"\xff\n", "/stacks"),
        ("no final newline", hello + b"\n" + snapshot[:-9], "/stacks"),
        ("trailing blank lines", hello + b"\n\n\n", "/stacks"),
        ("CR kept", hello + b"\r\n", "/stacks"),
        ("only newlines", b"\n\n", "/stacks"),
        ("empty file", b"", "/stacks"),
        ("missing file", None, "/stacks"),
        ("other path", hello + b"\n", "/other"),
        ("trailing slash", hello + b"\n", "/stacks/"),
        ("query", hello + b"\n", "/stacks?x=1"),
        ("empty query", hello + b"\n", "/stacks?"),
        ("encoded path", hello + b"\n", "/%73tacks"),
        ("double slash", hello + b"\n", "//stacks"),
        ("triple slash", hello + b"\n", "///stacks"),
        ("double slash, other", hello + b"\n", "//other/stacks"),
    ]
    failures = []
    for name, content, path in cases:
        problem = server_disagreement(servers, content, path)
        if problem:
            failures.append(f"{name}: {problem}")
    servers[0].write_bytes(hello + b"\n" + snapshot + b"\n")
    status, ctype, body = servers[2].get()
    assert (status, ctype, body) == (200, "application/json", snapshot), (status, ctype, body)
    assert not failures, "\n".join(failures)


# --- the shortcuts agree with the command lines --------------------------------

def test_cli_matches_in_process(tmp_path):
    """py_checker and the bb driver stand in for the command lines in the
    differential; here both are compared with the real command lines on the
    cases where they could differ: crashes, a failed print, usage, files."""
    schema = tmp_path / "schema.json"
    schema.write_text(_schema_text())
    renamed = tmp_path / "renamed.json"
    renamed.write_text(_renamed_schema())
    hello = b'{"v":1,"event":"hello","t":0,"gforth":"0.7.3","contract":"1.1"}'
    good = (b'{"v":1,"event":"snapshot","t":0,"where":null,"src":null,"data":[1],"float":[5e-324],'
            b'"rs":[],"input":{"file":"f","line":1,"in":2,"text":"t"}}')
    logs = {
        "good": hello + b"\n" + good + b"\n",
        "surrogate": hello + b"\n" + good.replace(b'"text":"t"', b'"text":"\\ud800"') + b"\n",
        "keyerror": hello + b"\n" + good.replace(b'"data"', b'"stack"') + b"\n",
        "not-utf8": b"\xff\n",
        "surrogate-low": hello + b"\n" + good.replace(b'"text":"t"', b'"text":"\\udc80"') + b"\n",
    }
    (tmp_path / "plain.txt").write_text("x\n")
    (tmp_path / "loop1").symlink_to("loop2")
    (tmp_path / "loop2").symlink_to("loop1")
    long_name = str(tmp_path / ("n" * 300))
    for name, content in logs.items():
        (tmp_path / f"{name}.jsonl").write_bytes(content)
    arg_lists = [
        [str(tmp_path / "good.jsonl"), str(schema)],
        [str(tmp_path / "surrogate.jsonl"), str(schema)],
        [str(tmp_path / "keyerror.jsonl"), str(renamed)],
        [str(tmp_path / "not-utf8.jsonl"), str(schema)],
        [str(tmp_path / "missing.jsonl"), str(schema)],
        [str(tmp_path), str(schema)],
        [str(tmp_path / "good.jsonl"), str(schema), "--expect", "2"],
        [str(tmp_path / "good.jsonl"), str(schema), "--expect=1.2"],
        [str(tmp_path / "good.jsonl"), str(schema), "--exp", "1.1", "--no"],
        [str(tmp_path / "good.jsonl")],
        [str(tmp_path / "good.jsonl"), str(schema), "--bogus"],
        [str(tmp_path / "surrogate-low.jsonl"), str(schema)],
        [str(tmp_path / "plain.txt" / "x"), str(schema)],
        [str(tmp_path / "loop1"), str(schema)],
        [long_name, str(schema)],
        [str(tmp_path / "good.jsonl"), str(tmp_path)],
        [str(tmp_path / "good.jsonl"), str(tmp_path / "plain.txt" / "x")],
        [str(tmp_path / "good.jsonl"), str(tmp_path / "loop1")],
        [str(tmp_path / "good.jsonl"), str(tmp_path / "missing.json")],
        [str(tmp_path / "good.jsonl"), str(schema), "--expect", "-"],
        [str(tmp_path / "good.jsonl"), str(schema), "--expect", "-1.1"],
        [str(tmp_path / "good.jsonl"), str(schema), "--expect", "-x"],
        ["-v", str(tmp_path / "good.jsonl"), str(schema)],
        ["-", str(schema)],
        [str(tmp_path / "good.jsonl"), str(schema), "--", "--expect"],
    ]
    bb_in_process = bb_checker_many(arg_lists, tmp_path)
    failures = []
    for args, bb_driver in zip(arg_lists, bb_in_process):
        py_cli, py_in = py_checker_cli(args), py_checker(args)
        bb_cli = bb_checker_cli(args)
        for label, left, right in [("py cli/in-process", py_cli, py_in), ("bb cli/driver", bb_cli, bb_driver),
                                   ("py/bb", py_cli, bb_cli)]:
            problem = checker_disagreement(left, right)
            if problem:
                failures.append(f"{label} {[Path(a).name for a in args]}: {problem}")
    assert not failures, "\n".join(failures)


def test_unknown_schema_keyword_refused(tmp_path):
    """The one declared difference: a keyword checker.py neither implements
    nor is known to ignore.  checker.py ignores it; the twin refuses (exit 2)."""
    schema = json.loads(_schema_text())
    schema["minProperties"] = 1
    schema_path = tmp_path / "schema.json"
    schema_path.write_text(json.dumps(schema))
    log_path = tmp_path / "log.jsonl"
    log_path.write_bytes(b'{"v":1,"event":"hello","t":0,"gforth":"0.7.3","contract":"1.1"}\n')
    py, bb = py_checker_cli([str(log_path), str(schema_path)]), bb_checker_cli([str(log_path), str(schema_path)])
    assert py["exit"] == 0, py
    assert bb["exit"] == 2 and "minProperties" in bb["err"], bb
