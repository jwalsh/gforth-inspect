"""Simulate Forth package-manager rules against real gforth 0.7.3.

Packages are toy directories, each with a manifest (forth-package.json) and
Forth source. A resolver applies the proposed rules, writes a load file,
and gforth loads it in an isolated temp dir. Every scenario states the
expected outcome and the observed one. Standard library only.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()          # gforth-inspect checkout (for env/inspect.fs)
WORK = Path(tempfile.mkdtemp(prefix="pkgsim-"))
INSPECT = (ROOT / "env/inspect.fs").read_bytes()


# ---- versions and ranges -------------------------------------------------
def parse(v):
    return tuple(int(x) for x in v.split("."))


def satisfies(version, rng):
    """rng: space-separated clauses, each OP X.Y.Z with OP in >= > <= < =."""
    for clause in rng.split():
        m = re.fullmatch(r"(>=|<=|>|<|=)(\d+\.\d+\.\d+)", clause)
        if not m:
            raise ValueError(f"bad range clause {clause!r}")
        op, bound = m.group(1), parse(m.group(2))
        v = parse(version)
        ok = {">=": v >= bound, ">": v > bound, "<=": v <= bound, "<": v < bound, "=": v == bound}[op]
        if not ok:
            return False
    return True


# ---- a registry of toy packages -----------------------------------------
def make_pkg(registry, name, version, main_src, depends=None, requires_gforth=">=0.7.3 <1.0.0",
             provides=None, tamper=False):
    d = registry / name / version
    d.mkdir(parents=True)
    main = f"{name}.fs"
    (d / main).write_bytes(main_src if isinstance(main_src, bytes) else main_src.encode())
    digest = hashlib.sha256((d / main).read_bytes()).hexdigest()
    if tamper:
        (d / main).write_bytes((d / main).read_bytes() + b"\n\\ tampered\n")
    manifest = {
        "name": name, "version": version, "main": main,
        "requires": {"gforth": requires_gforth},
        "depends": depends or {},
        "provides": provides or [],
        "assets": {main: {"sha256": digest, "required": True}},
    }
    (d / "forth-package.json").write_text(json.dumps(manifest, indent=1))


def build_registry():
    reg = WORK / "registry"
    for v in ("0.2.0", "0.3.0", "0.3.1"):
        src = INSPECT
        if v != "0.2.0":   # pretend newer versions; only the header changes
            src = INSPECT.replace(b"gforth-inspect v0.2.0", f"gforth-inspect v{v}".encode(), 1) \
                         .replace(b's" 0.2.0" ;', f's" {v}" ;'.encode(), 1)
        make_pkg(reg, "gforth-inspect", v, src,
                 provides=[".stacks", ".rs", ".input", ".cs", "~~~", "all-~~", "dbg-fix", "dbg+",
                           "log-on", "log-off", "log-where", "log-id", "fclearstack",
                           "inspect-version", "contract-version", "rs-full"])
    # a consumer package that needs the inspector's log-id (0.3 line)
    make_pkg(reg, "stackcheck", "0.1.0",
             "require gforth-inspect.fs\n: checked ( n -- n ) s\" stackcheck\" log-id dup ;\n",
             depends={"gforth-inspect": ">=0.3.0 <0.4.0"}, provides=["checked"])
    # needs a newer patch of the inspector
    make_pkg(reg, "tracer", "0.1.0",
             "require gforth-inspect.fs\n: traced ( -- ) .stacks ;\n",
             depends={"gforth-inspect": ">=0.3.1 <0.4.0"}, provides=["traced"])
    # clashes: defines .stacks itself
    make_pkg(reg, "rival", "0.1.0", ": .stacks ( -- ) .\" rival stacks\" cr ;\n",
             provides=[".stacks"])
    # needs gforth 1.0 (a system dependency nobody here can meet)
    make_pkg(reg, "modern", "0.1.0", ": m ;\n", requires_gforth=">=1.0.0 <2.0.0", provides=["m"])
    # tampered asset
    make_pkg(reg, "evil", "0.1.0", ": e ;\n", provides=["e"], tamper=True)
    # a cycle
    make_pkg(reg, "cyc-a", "0.1.0", "require cyc-b.fs\n: ca ;\n", depends={"cyc-b": ">=0.1.0 <0.2.0"}, provides=["ca"])
    make_pkg(reg, "cyc-b", "0.1.0", "require cyc-a.fs\n: cb ;\n", depends={"cyc-a": ">=0.1.0 <0.2.0"}, provides=["cb"])
    return reg


# ---- the rules under test -------------------------------------------------
class Refuse(Exception):
    pass


def versions(reg, name):
    d = reg / name
    if not d.exists():
        raise Refuse(f"unknown package {name}")
    return sorted((p.name for p in d.iterdir()), key=parse, reverse=True)


def manifest(reg, name, version):
    return json.loads((reg / name / version / "forth-package.json").read_text())


def resolve(reg, wants, gforth_version):
    """R1 one version per package per project (one dictionary);
    R2 highest version satisfying every constraint on it;
    R3 system requirement (gforth) checked for every chosen package;
    R4 cycles refused; R5 checksums verified; R6 no two packages provide one word."""
    constraints = {}            # name -> list of (range, by)
    chosen = {}

    def add(name, rng, by):
        constraints.setdefault(name, []).append((rng, by))

    for name, rng in wants.items():
        add(name, rng, "project")
    changed = True
    while changed:
        changed = False
        for name, cons in list(constraints.items()):
            ok = [v for v in versions(reg, name) if all(satisfies(v, r) for r, _ in cons)]
            if not ok:
                detail = "; ".join(f"{by} wants {r}" for r, by in cons)
                raise Refuse(f"R1/R2 conflict on {name}: {detail}")
            pick = ok[0]
            if chosen.get(name) != pick:
                chosen[name] = pick
                changed = True
                for dep, drng in manifest(reg, name, pick)["depends"].items():
                    if (drng, f"{name} {pick}") not in constraints.get(dep, []):
                        add(dep, drng, f"{name} {pick}")
    # R3 system dependency
    for name, v in chosen.items():
        req = manifest(reg, name, v)["requires"]["gforth"]
        if not satisfies(gforth_version, req):
            raise Refuse(f"R3 {name} {v} requires gforth {req}; this is gforth {gforth_version}")
    # R4 load order, refusing cycles
    order, state = [], {}

    def visit(n, path):
        if state.get(n) == "done":
            return
        if state.get(n) == "busy":
            raise Refuse("R4 dependency cycle: " + " -> ".join(path + [n]))
        state[n] = "busy"
        for dep in manifest(reg, n, chosen[n])["depends"]:
            visit(dep, path + [n])
        state[n] = "done"
        order.append(n)

    for n in sorted(chosen):
        visit(n, [])
    # R5 checksums
    for n in order:
        m = manifest(reg, n, chosen[n])
        for asset, meta in m["assets"].items():
            got = hashlib.sha256((reg / n / chosen[n] / asset).read_bytes()).hexdigest()
            if got != meta["sha256"]:
                raise Refuse(f"R5 {n} {chosen[n]}: {asset} sha256 mismatch")
    # R6 word clashes
    owner = {}
    for n in order:
        for w in manifest(reg, n, chosen[n])["provides"]:
            if w in owner:
                raise Refuse(f"R6 word {w} provided by both {owner[w]} and {n}")
            owner[w] = n
    return chosen, order


def install_and_load(reg, chosen, order, probe):
    proj = Path(tempfile.mkdtemp(prefix="proj-", dir=WORK))
    env_dir = proj / "forth-packages"
    env_dir.mkdir()
    for n in order:
        shutil.copy(reg / n / chosen[n] / f"{n}.fs", env_dir / f"{n}.fs")
    load = proj / "load.fs"
    load.write_text("".join(f"require {n}.fs\n" for n in order) + probe + "\nbye\n")
    env = {"PATH": os.environ["PATH"], "HOME": str(proj), "XDG_STATE_HOME": str(proj / "state"),
           "GFORTH_INSPECT_LOG_DIR": str(proj / "logs"), "PWD": str(proj)}
    r = subprocess.run(["gforth", "-e", f"fpath+ {env_dir}", str(load)], cwd=proj, env=env,
                       capture_output=True, text=True, timeout=30)
    return r


SCENARIOS = [
    ("S1 one package and its dependency", {"stackcheck": ">=0.1.0 <0.2.0"}, "0.7.3",
     "ok", "3 checked . . inspect-version type"),
    ("S2 diamond: two packages, overlapping ranges", {"stackcheck": ">=0.1.0 <0.2.0", "tracer": ">=0.1.0 <0.2.0"}, "0.7.3",
     "ok", "inspect-version type"),
    ("S3 project pins an older inspector than a package needs", {"gforth-inspect": "=0.2.0", "stackcheck": ">=0.1.0 <0.2.0"}, "0.7.3",
     "refuse", ""),
    ("S4 system gforth is 1.0.1", {"stackcheck": ">=0.1.0 <0.2.0"}, "1.0.1",
     "refuse", ""),
    ("S5 a package that needs gforth 1.0", {"modern": ">=0.1.0 <0.2.0"}, "0.7.3",
     "refuse", ""),
    ("S6 two packages define .stacks", {"gforth-inspect": ">=0.3.0 <0.4.0", "rival": ">=0.1.0 <0.2.0"}, "0.7.3",
     "refuse", ""),
    ("S7 tampered asset", {"evil": ">=0.1.0 <0.2.0"}, "0.7.3",
     "refuse", ""),
    ("S8 dependency cycle", {"cyc-a": ">=0.1.0 <0.2.0"}, "0.7.3",
     "refuse", ""),
    ("S9 require twice loads once", {"stackcheck": ">=0.1.0 <0.2.0", "tracer": ">=0.1.0 <0.2.0"}, "0.7.3",
     "ok", "s\" gforth-inspect.fs\" required inspect-version type"),
]


def main():
    reg = build_registry()
    rows = []
    for title, wants, gver, expect, probe in SCENARIOS:
        try:
            chosen, order = resolve(reg, wants, gver)
        except Refuse as e:
            rows.append((title, expect, "refuse", str(e), ""))
            continue
        r = install_and_load(reg, chosen, order, probe)
        out = (r.stdout + r.stderr).strip().replace("\n", " | ")
        redefined = [l for l in r.stderr.splitlines() if l.startswith("redefined ")]
        status = "ok" if r.returncode == 0 and not redefined else f"gforth exit {r.returncode}"
        rows.append((title, expect, status, " ".join(f"{n} {chosen[n]}" for n in order), out[-160:]))
    # a control: skip the rules and just load rival after the inspector, to show R6 is needed
    proj_rows = []
    chosen = {"gforth-inspect": "0.3.0", "rival": "0.1.0"}
    r = install_and_load(reg, chosen, ["gforth-inspect", "rival"], "1 .stacks")
    proj_rows.append(("C6 control: S6 loaded without R6", "silent shadowing", f"exit {r.returncode}",
                      "gforth-inspect 0.3.0, rival 0.1.0", (r.stdout + r.stderr).strip().replace("\n", " | ")[-200:]))
    print(json.dumps({"rows": rows, "controls": proj_rows}, indent=1))
    shutil.rmtree(WORK)


main()
