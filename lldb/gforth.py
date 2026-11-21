"""lldb commands for inspecting a running gforth 0.7.3 VM.

    (lldb) command script import lldb/gforth.py

Commands
    fstacks          data, float, return stacks + current word / IP
    finput           current input line with a caret at >IN
    fbt              return-stack backtrace (Forth words, not C frames)
    fip [N]          threaded code of frame N (0 = current IP), IP marked
    fsee NAME        decompile a colon definition from memory
    fregs            where each VM register came from (exact / heuristic)
    fword NAME       look a word up in the dictionary (nt, xt, kind)
    fbrk             break on getpid (the `brk` word in env/brk.fs)
    fbreak-prim NAME break at the engine code of primitive NAME

How the VM state is found (gforth 0.7.3, see vendor/gforth-0.7.3/engine):
  * gforth_header (C global) -> ImageHeader: stack bases, sizes; the
    dictionary starts at the header itself (= Forth `forthstart`).
  * dsize/fsize/rsize/lsize (C statics): stack sizes -> sp0/fp0/rp0/lp0.
  * gforth_SP/FP/RP/LP: exact *only* right after CALL-C (and ffcall
    callbacks) stored them -- that is what `brk` exploits.
  * saved_ip, rp: C globals in the GFORTH_DEBUGGING engines (gforth,
    gforth-itc); saved_ip = IP at entry of the current primitive.
  * otherwise: the engine keeps sp/fp/ip in callee-saved registers
    chosen freely by clang (no fixed binding on arm64, no DWARF), so we
    unwind to the gforth_engine frame and classify register values by
    which stack region they point into.
"""

import bisect
import struct

import lldb

CELL = 8
LCOUNT_MASK = (1 << 61) - 1
ALIAS_BIT = 1 << 63      # set for ordinary words, clear for aliases
IMM_BIT = 1 << 62
RESTRICT_BIT = 1 << 61
MAX_NAME = 64

_cache = {}

# first entries of vm_prims[] (engine/prim_names.i), needed for gforth-itc,
# which is built without prim_names[]
_DOERS = ["(docol)", "(docon)", "(dovar)", "(douser)", "(dodefer)",
          "(dofield)", "(dovalue)", "(dodoes)", "(does-handler)"]


def _u64(data, off):
    return struct.unpack_from("<Q", data, off)[0]


def _s64(value):
    return value - (1 << 64) if value & (1 << 63) else value


class VM(object):
    """Snapshot of the gforth VM of the selected process."""

    def __init__(self, debugger):
        self.target = debugger.GetSelectedTarget()
        self.process = self.target.GetProcess()
        if not self.process.IsValid():
            raise RuntimeError("no process")
        self.thread = self.process.GetSelectedThread()
        self.exe = self.target.GetExecutable().GetFilename() or ""
        self.err = lldb.SBError()
        self.notes = []
        self._symbols()
        self._header()
        self.docol = None
        self._dictionary()
        self._prims()
        self._registers()

    # ---- memory -------------------------------------------------------
    def read(self, addr, size):
        data = self.process.ReadMemory(addr, size, self.err)
        if not self.err.Success():
            raise RuntimeError("cannot read %d bytes at 0x%x: %s"
                               % (size, addr, self.err.GetCString()))
        return data

    def cell(self, addr):
        return _u64(self.read(addr, CELL), 0)

    def fcell(self, addr):
        return struct.unpack("<d", self.read(addr, 8))[0]

    def cstr(self, addr, limit=128):
        out = self.process.ReadCStringFromMemory(addr, limit, self.err)
        return out if self.err.Success() else None

    def sym(self, name, required=True):
        for ctx in self.target.FindSymbols(name):
            symbol = ctx.GetSymbol()
            if symbol.IsValid():
                load = symbol.GetStartAddress().GetLoadAddress(self.target)
                if load != lldb.LLDB_INVALID_ADDRESS:
                    return load
        if required:
            raise RuntimeError("symbol %s not found" % name)
        return None

    # ---- static layout ------------------------------------------------
    def _symbols(self):
        self.a_header = self.sym("gforth_header")
        self.a_SP = self.sym("gforth_SP")
        self.a_FP = self.sym("gforth_FP")
        self.a_RP = self.sym("gforth_RP")
        self.a_LP = self.sym("gforth_LP")
        self.a_UP = self.sym("gforth_UP")
        self.a_saved_ip = self.sym("saved_ip", required=False)
        self.a_rp = self.sym("rp", required=False)
        self.debugging = self.a_saved_ip is not None
        self.itc = "itc" in self.exe
        if self.debugging and not self.itc:
            self.engine = "gforth (direct threaded, GFORTH_DEBUGGING)"
        elif self.itc:
            self.engine = "gforth-itc (indirect threaded, GFORTH_DEBUGGING)"
        else:
            self.engine = "gforth-fast (direct threaded, stack caching)"
        sizes = {}
        for name in ("dsize", "fsize", "rsize", "lsize"):
            sizes[name] = self.cell(self.sym(name))
        self.sizes = sizes

    def _header(self):
        self.base = self.cell(self.a_header)
        if self.base == 0:
            raise RuntimeError("gforth_header is NULL: image not loaded yet")
        h = self.read(self.base, 20 * CELL)
        self.image_size = _u64(h, 2 * CELL)
        self.dict_size = _u64(h, 3 * CELL)
        self.ds_base = _u64(h, 12 * CELL)
        self.fs_base = _u64(h, 13 * CELL)
        self.rs_base = _u64(h, 14 * CELL)
        self.ls_base = _u64(h, 15 * CELL)
        self.ds_top = self.ds_base + self.sizes["dsize"]
        self.fs_top = self.fs_base + self.sizes["fsize"]
        self.rs_top = self.rs_base + self.sizes["rsize"]
        self.ls_top = self.ls_base + self.sizes["lsize"]

    def _prims(self):
        """Map engine code labels and C-side xts to primitive names.

        vm_prims[] (0-terminated) holds the code label of every primitive.
        prim_names[] is parallel to it but only exists in gforth and
        gforth-fast; gforth-itc is built without it.  Independently, the
        image has a header for each named primitive whose code field holds
        the primitive's C-side xt (an address in the engine's xts[]), and
        *xt is the label.  We use both; headers win for naming.
        """
        vm_prims = self.cell(self.sym("vm_prims"))
        names = self.sym("prim_names", required=False)
        self.label2prim = {}
        self.prim2label = {}
        self.xt2prim = {}
        i = 0
        while i < 4000:
            label = self.cell(vm_prims + i * CELL)
            if label == 0:
                break
            if names is None and i < len(_DOERS):
                self.label2prim.setdefault(label, _DOERS[i])
            if names is not None:
                name = self.cstr(self.cell(names + i * CELL))
                if name:
                    self.label2prim.setdefault(label, name)
                    self.prim2label.setdefault(name, label)
            i += 1
        self.nprims = i
        self.docol = self.cell(vm_prims) if i else None
        self.prim_names_source = ("prim_names[] + headers" if names
                                  is not None else "headers only")
        labels = set(self.read_cells(vm_prims, i))
        for xt, nt, name, cnt in self.words:
            if cnt & ALIAS_BIT:
                continue
            cxt = self.cell(xt)
            if self.base <= cxt < self.base + self.dict_size:
                continue
            try:
                label = self.cell(cxt)
            except RuntimeError:
                continue
            if label in labels:
                self.xt2prim[cxt] = name
                self.label2prim[label] = name
                self.prim2label.setdefault(name, label)

    def read_cells(self, addr, count):
        data = self.read(addr, count * CELL)
        return [_u64(data, k * CELL) for k in range(count)]

    # ---- dictionary ---------------------------------------------------
    def _dictionary(self):
        """Scan [forthstart, forthstart+dict_size) for headers.

        0.7.3 header (64-bit, not f83headerstring):
            nt+0   link   (previous nt in the same wordlist, or 0)
            nt+8   count  (length | alias $80.. | immediate $40.. | restrict $20..)
            nt+16  name chars, padded to a cell
            xt     code field, then body at xt+2 cells
        A candidate is kept if its link is 0 or points to another candidate.
        """
        upid = (self.process.GetProcessID(), self.process.GetStopID(),
                self.base)
        hit = _cache.get("dict")
        if hit and hit[0] == upid:
            (_, self.words, self.xts, self.nts, self.dict_data) = hit
            return
        data = self.read(self.base, self.dict_size)
        cand = {}
        n = len(data) - 3 * CELL
        for off in range(0, n, CELL):
            cnt = _u64(data, off + CELL)
            length = cnt & LCOUNT_MASK
            if length == 0 or length > MAX_NAME:
                continue
            raw = data[off + 2 * CELL: off + 2 * CELL + length]
            if any(b <= 32 or b >= 127 for b in raw):
                continue
            link = _u64(data, off)
            nt = self.base + off
            if link and (link & 7 or link < self.base or link >= nt):
                continue
            xt = (nt + 2 * CELL + length + 7) & ~7
            cand[nt] = (link, raw.decode("latin-1"), cnt, xt)
        words = []
        for nt, (link, name, cnt, xt) in cand.items():
            if link and link not in cand:
                continue
            words.append((xt, nt, name, cnt))
        words.sort()
        self.words = words
        self.xts = [w[0] for w in words]
        self.nts = sorted(w[1] for w in words)
        self.dict_data = data
        _cache["dict"] = (upid, self.words, self.xts, self.nts, data)

    def word_at(self, xt):
        i = bisect.bisect_left(self.xts, xt)
        if i < len(self.xts) and self.xts[i] == xt:
            return self.words[i][2]
        return None

    def lookup(self, name):
        found = [w for w in self.words if w[2] == name]
        return found[-1] if found else None

    def containing(self, addr):
        """(name, offset) of the word whose body contains addr, or None."""
        if not (self.base <= addr < self.base + self.dict_size):
            return None
        i = bisect.bisect_right(self.xts, addr) - 1
        if i < 0:
            return None
        xt, nt, name, cnt = self.words[i]
        j = bisect.bisect_right(self.nts, nt)
        end = self.nts[j] if j < len(self.nts) else self.base + self.dict_size
        if addr >= end:
            return None
        # a headerless colon definition (:noname, or the code built by
        # handler-intro,) between the header and addr starts with a code
        # field holding the docol label; report it instead of the header
        if self.docol is not None:
            pos = (addr & ~7) - CELL
            while pos > xt:
                if _u64(self.dict_data, pos - self.base) == self.docol:
                    return "(noname@0x%x)" % pos, addr - pos
                pos -= CELL
        return name, addr - xt

    def xt_name(self, xt):
        """Name of an execution token (dictionary or primitive)."""
        name = self.word_at(xt)
        if name:
            return name
        if xt in self.xt2prim:
            return self.xt2prim[xt]
        try:
            label = self.cell(xt)
        except RuntimeError:
            return None
        return self.label2prim.get(label)

    def decode(self, value):
        """Name of a threaded-code cell: a code label (direct) or xt (itc)."""
        if not self.itc and value in self.label2prim:
            return self.label2prim[value]
        return self.xt_name(value)

    def body_name(self, addr):
        """Name of the colon definition whose body starts at addr (CALL arg)."""
        return self.word_at(addr - 2 * CELL)

    # ---- VM registers -------------------------------------------------
    def _engine_frame(self):
        for frame in self.thread:
            if frame.GetFunctionName() in ("gforth_engine", "gforth_engine2"):
                return frame
        return None

    def _registers(self):
        self.frame0 = self.thread.GetFrameAtIndex(0).GetFunctionName()
        eframe = self._engine_frame()
        self.eframe = eframe
        self.exact = ("getpid" in (self.frame0 or "")
                      and eframe is not None
                      and self.thread.GetFrameAtIndex(1).GetFunctionName()
                      in ("gforth_engine", "gforth_engine2"))
        self.pc_prim = self._pc_prim()
        self.sp_cands, self.fp_cands, self.ip_cands = [], [], []
        self.ftos = None
        if eframe is not None:
            for reg in eframe.GetRegisters().GetFirstValueByName(
                    "General Purpose Registers"):
                value = reg.GetValueAsUnsigned(0)
                rname = reg.GetName()
                if self.ds_base <= value <= self.ds_top:
                    self.sp_cands.append((rname, value))
                elif self.fs_base <= value <= self.fs_top:
                    self.fp_cands.append((rname, value))
                elif (self.base <= value < self.base + self.dict_size
                      and value % CELL == 0 and self.containing(value)):
                    self.ip_cands.append((rname, value))
        dwarf = self._dwarf_regs(eframe)
        if dwarf and not self.exact:
            self.sp, self.fp, ip, rp = (dwarf.get("sp"), dwarf.get("fp"),
                                        dwarf.get("ip"), dwarf.get("rp"))
            self.lp = dwarf.get("lp")
            self.how = dict((k, "DWARF local %s of gforth_engine" % k)
                            for k in dwarf)
            if rp is None and self.a_rp is not None:
                rp = self.cell(self.a_rp)
                self.how["rp"] = "C global rp (GFORTH_DEBUGGING)"
            self.rp = rp
            self.sp0 = self._user("sp0") or self.ds_top
            self.fp0 = self._user("fp0") or self.fs_top
            self.rp0 = self._user("rp0") or self.rs_top
            if ip is not None:
                self.ip = ip
                return
            # partial debug info: fall through to the heuristics below and
            # overlay what DWARF did provide at the end
        if self.exact:
            self.sp = self.cell(self.a_SP)
            self.fp = self.cell(self.a_FP)
            self.rp = self.cell(self.a_RP)
            self.lp = self.cell(self.a_LP)
            self.how = {"sp": "gforth_SP (set by CALL-C)",
                        "fp": "gforth_FP (set by CALL-C)",
                        "rp": "gforth_RP (set by CALL-C)"}
        else:
            self.how = {}
            self.sp = self._pick(self.sp_cands, "sp")
            self.fp = self._pick(self.fp_cands, "fp")
            if self.a_rp is not None:
                self.rp = self.cell(self.a_rp)
                self.how["rp"] = "C global rp (GFORTH_DEBUGGING)"
            else:
                rcands = []
                if eframe is not None:
                    for reg in eframe.GetRegisters().GetFirstValueByName(
                            "General Purpose Registers"):
                        v = reg.GetValueAsUnsigned(0)
                        if self.rs_base <= v <= self.rs_top:
                            rcands.append((reg.GetName(), v))
                self.rp = self._pick(rcands, "rp")
            self.lp = None
            if not self.debugging and eframe is not None:
                # gforth-fast caches the float TOS in a callee-saved FP
                # register; in this build it is d8 (see README)
                d8 = eframe.FindRegister("d8")
                if d8.IsValid():
                    self.ftos = d8.GetValue()
        if self.a_saved_ip is not None:
            self.ip = self.cell(self.a_saved_ip)
            self.how["ip"] = "C global saved_ip (set by NAME() on entry)"
            prim, at_label = self.pc_prim
            if (at_label and not self.exact
                    and self.decode(self.cell(self.ip)) == prim):
                # stopped on the first instruction of prim: NAME() has not
                # run yet, saved_ip still belongs to the previous primitive
                self.ip += CELL
                self.how["ip"] += "; +1 cell, stopped before NAME() of %s" \
                    % prim
        elif self.ip_cands:
            self.ip, how = self._pick_ip()
            self.how["ip"] = how
        else:
            self.ip = None
            self.how["ip"] = "unknown (gforth-fast keeps IP in a register)"
        # Forth-level stack bottoms (user variables), fall back to C ones
        self.sp0 = self._user("sp0") or self.ds_top
        self.fp0 = self._user("fp0") or self.fs_top
        self.rp0 = self._user("rp0") or self.rs_top
        if not self.exact:
            for key, value in dwarf.items():
                if key in ("sp", "fp", "rp"):
                    setattr(self, key, value)
                    self.how[key] = "DWARF local %s of gforth_engine" % key

    def mode(self):
        if self.exact:
            return "exact: stopped in brk (CALL-C)"
        if any("DWARF" in v for v in self.how.values()):
            return "debug info (DWARF)"
        return "heuristic: see fregs"

    def _dwarf_regs(self, eframe):
        """VM registers from debug info, when the engine was built with -g
        and they are available at this pc (always at -O0; mostly
        <variable not available> at -O2, see README)."""
        out = {}
        if eframe is None or not eframe.GetLineEntry().IsValid():
            return out
        for name in ("sp", "fp", "rp", "ip", "lp"):
            var = eframe.FindVariable(name)
            if var.IsValid() and var.GetError().Success():
                value = var.GetValueAsUnsigned(0)
                if value:
                    out[name] = value
        return out

    def _pc_prim(self):
        """Primitive whose engine code contains the engine frame's pc."""
        if self.eframe is None:
            return None, False
        pc = self.eframe.GetPC()
        if pc in self.label2prim:
            return self.label2prim[pc], True
        labels = sorted(self.label2prim)
        i = bisect.bisect_right(labels, pc) - 1
        return (self.label2prim[labels[i]] if i >= 0 else None), False

    def _spill_cands(self):
        """Dictionary pointers in the engine frame's C stack (spill slots)."""
        out = []
        if self.eframe is None:
            return out
        lo = self.eframe.GetSP()
        hi = self.eframe.GetFP()
        if not lo < hi <= lo + 4096:
            return out
        data = self.read(lo, hi - lo)
        for k in range(0, hi - lo, CELL):
            v = _u64(data, k)
            if (self.base <= v < self.base + self.dict_size
                    and v % CELL == 0 and self.containing(v)):
                out.append(("[sp+0x%x]" % k, v))
        return out

    def _pick_ip(self):
        """Choose the IP candidate consistent with the primitive at pc.

        Convention used throughout: cell[ip-1] is the primitive being
        executed.  Candidates come from registers and from the engine
        frame's C stack (clang spills VM registers there and reloads them
        at primitive entry, so a register can hold a stale IP)."""
        cands = self.ip_cands + self._spill_cands()
        prim = self.pc_prim[0]
        if prim:
            for reg, value in cands:
                if self.decode(self.cell(value - CELL)) == prim:
                    return value, ("heuristic: %s, cell[ip-1]=%s matches pc"
                                   % (reg, prim))
            for reg, value in cands:
                if self.decode(self.cell(value)) == prim:
                    return value + CELL, (
                        "heuristic: %s+1 cell, cell[ip-1]=%s matches pc"
                        % (reg, prim))
        reg, value = cands[0]
        return value, "heuristic (unverified): %s of %s" % (
            reg, ",".join(r for r, _ in cands))

    def _pick(self, cands, what):
        if not cands:
            self.how[what] = "unknown (no register points into the stack)"
            return None
        values = sorted(set(v for _, v in cands))
        best = values[-1]
        regs = ",".join("%s=0x%x" % c for c in cands)
        self.how[what] = ("heuristic: highest of %s" % regs
                          if len(values) > 1 else
                          "heuristic: register %s" % cands[0][0])
        return best

    def _user(self, name):
        """Value of a Forth user variable: [gforth_UP + offset-in-body]."""
        w = self.lookup(name)
        if not w:
            return None
        try:
            up = self.cell(self.a_UP)
            off = self.cell(w[0] + 2 * CELL)
            return self.cell(up + off)
        except RuntimeError:
            return None

    def user_addr(self, name):
        w = self.lookup(name)
        if not w:
            return None
        return self.cell(self.a_UP) + self.cell(w[0] + 2 * CELL)

    # ---- formatting ---------------------------------------------------
    def describe(self, value):
        """Best-effort label for a cell that may be a return address."""
        hit = self.containing(value)
        if hit and value % CELL == 0:
            return "%s+%d" % hit
        for lo, hi, what in ((self.ds_base, self.ds_top, "data"),
                             (self.fs_base, self.fs_top, "float"),
                             (self.rs_base, self.rs_top, "return"),
                             (self.ls_base, self.ls_top, "locals")):
            if lo <= value <= hi:
                return "(-> %s stack, %d cells below top)" % (
                    what, (hi - value) // CELL)
        name = self.decode(value)
        if name:
            return "<%s>" % name
        return None


def _vm(debugger, result, command=""):
    """Build a VM snapshot; `command` may override pointers, e.g.
    `sp=x27 fp=0x1348113f0` (a register of the gforth_engine frame or an
    address) for when the heuristic picks the wrong candidate."""
    try:
        vm = VM(debugger)
        for word in command.split():
            if "=" not in word:
                continue
            key, val = word.split("=", 1)
            if key not in ("sp", "fp", "rp", "ip"):
                raise RuntimeError("unknown override %s" % key)
            if val.startswith("0x"):
                value = int(val, 16)
            else:
                reg = vm.eframe.FindRegister(val) if vm.eframe else None
                if reg is None or not reg.IsValid():
                    raise RuntimeError("no register %s" % val)
                value = reg.GetValueAsUnsigned()
            setattr(vm, key, value)
            vm.how[key] = "override %s" % val
        return vm
    except RuntimeError as exc:
        result.SetError(str(exc))
        return None


def _stack(vm, ptr, top, kind, out, limit=32):
    if ptr is None:
        out.append("  (%s pointer unknown)" % kind)
        return
    depth = (top - ptr) // 8
    if depth < 0 or depth > 4096:
        out.append("  <%d> ptr=0x%x bottom=0x%x: out of range"
                   % (depth, ptr, top))
        return
    items = []
    for i in range(min(depth, limit)):
        addr = top - 8 * (i + 1)
        if kind == "f":
            items.append("%g" % vm.fcell(addr))
        else:
            items.append(str(_s64(vm.cell(addr))))
    more = " ..." if depth > limit else ""
    out.append("  <%d> %s%s   (ptr=0x%x)" % (depth, " ".join(items), more, ptr))


def _rstack(vm, out, limit=24):
    if vm.rp is None:
        out.append("  (rp unknown)")
        return
    depth = (vm.rp0 - vm.rp) // 8
    if depth < 0 or depth > 2048:
        out.append("  rp=0x%x rp0=0x%x: out of range" % (vm.rp, vm.rp0))
        return
    out.append("  <%d> top first   (rp=0x%x rp0=0x%x)" % (depth, vm.rp, vm.rp0))
    for i in range(min(depth, limit)):
        value = vm.cell(vm.rp + 8 * i)
        label = vm.describe(value)
        out.append("    [%2d] 0x%016x %-6s %s"
                   % (i, value, str(_s64(value)) if abs(_s64(value)) < 1 << 20
                      else "", label or ""))


def _current(vm):
    prim, at_label = vm.pc_prim
    pcs = "pc %s %s" % ("at start of" if at_label else "inside", prim)
    if vm.ip is None:
        return "ip unknown; %s" % pcs
    where = vm.containing(vm.ip - CELL)
    loc = "%s+%d" % where if where else "0x%x" % vm.ip
    return "%s executing [ip-1]=%s, next [ip]=%s   (ip=0x%x; %s)" % (
        loc, vm.decode(vm.cell(vm.ip - CELL)), vm.decode(vm.cell(vm.ip)),
        vm.ip, pcs)


def fstacks(debugger, command, result, internal_dict):
    """fstacks [sp=REG|0xADDR] [fp=..] [rp=..] [ip=..]: all VM stacks"""
    vm = _vm(debugger, result, command)
    if not vm:
        return
    out = ["engine: %s  [%s]" % (vm.engine, vm.mode())]
    if vm.exact and vm.rp is not None:
        caller = vm.describe(vm.cell(vm.rp))
        out.append("brk called from: %s" % caller)
    out.append("current: %s" % _current(vm))
    out.append("data stack (bottom first):")
    _stack(vm, vm.sp, vm.sp0, "d", out)
    if "heuristic" in vm.how.get("sp", ""):
        alts = sorted(set(v for _, v in vm.sp_cands) - set([vm.sp]))
        if alts:
            out.append("  other sp candidates: " + ", ".join(
                "%s=0x%x (depth %d)" % (r, v, (vm.sp0 - v) // CELL)
                for r, v in vm.sp_cands if v in alts)
                + "  -- rerun as fstacks sp=REG")
    if not vm.debugging and not vm.exact:
        out.append("  gforth-fast: TOS is cached in a register; the top"
                   " memory slot may be stale (use brk for exact stacks)")
    out.append("float stack (bottom first):")
    _stack(vm, vm.fp, vm.fp0, "f", out)
    if vm.ftos is not None:
        out.append("  gforth-fast: top float is cached in d8 = %s; the memory"
                   " slot above is stale" % vm.ftos)
    out.append("return stack:")
    _rstack(vm, out)
    result.PutCString("\n".join(out))


def fregs(debugger, command, result, internal_dict):
    """show VM registers and how each was obtained"""
    vm = _vm(debugger, result)
    if not vm:
        return
    out = ["engine: %s  exe=%s  frame0=%s" % (vm.engine, vm.exe, vm.frame0),
           "forthstart=0x%x image=0x%x dict=0x%x prims=%d words=%d"
           % (vm.base, vm.image_size, vm.dict_size, vm.nprims, len(vm.words)),
           "C stacks: d=[0x%x,0x%x) f=[0x%x,0x%x) r=[0x%x,0x%x) l=[0x%x,0x%x)"
           % (vm.ds_base, vm.ds_top, vm.fs_base, vm.fs_top,
              vm.rs_base, vm.rs_top, vm.ls_base, vm.ls_top),
           "Forth sp0=0x%x fp0=0x%x rp0=0x%x" % (vm.sp0, vm.fp0, vm.rp0)]
    for reg in ("sp", "fp", "rp", "ip"):
        value = getattr(vm, reg)
        out.append("  %-2s = %-18s %s" % (reg, "0x%x" % value if value
                                          is not None else "?",
                                          vm.how.get(reg, "")))
    out.append("register candidates in gforth_engine frame: sp%s fp%s ip%s"
               % (vm.sp_cands, vm.fp_cands, vm.ip_cands))
    result.PutCString("\n".join(out))


def fbt(debugger, command, result, internal_dict):
    """fbt [overrides]: Forth backtrace (IP, then return addresses)"""
    vm = _vm(debugger, result, command)
    if not vm:
        return
    out = []
    for n, ip in enumerate(_frames(vm)):
        if n == 0 and vm.ip is not None:
            name, off = vm.containing(ip - CELL)
            out.append("#0  %s+%d  executing %s" % (
                name, off, vm.decode(vm.cell(ip - CELL))))
            continue
        name, off = vm.containing(ip)
        out.append("#%-2d %s+%d  returns to %s" % (
            n, name, off, vm.decode(vm.cell(ip)) or "?"))
    result.PutCString("\n".join(out))


# inline operands of 0.7.3 primitives (from the `#' items in prim)
_TARGET = {"branch", "?branch", "(next)", "(loop)", "(+loop)", "(-loop)",
           "(s+loop)", "?dup-?branch", "?dup-0=-?branch", "(?do)", "(+do)",
           "(u+do)", "(-do)", "(u-do)"}
_LITERAL = {"lit", "lit+", "useraddr", "lit@", "@local#", "f@local#",
            "laddr#", "lp+!#", "set-next-code", "lit-perform", "does-exec"}


def _operands(name):
    if name == "call":
        return ["callee"]
    if name == "call2":
        return ["callee", "target"]
    if name.endswith("-lp+!#"):
        return ["target", "literal"]
    if name in _TARGET:
        return ["target"]
    if name in _LITERAL:
        return ["literal"]
    return []


def see_lines(vm, xt, marks=None, limit=96):
    """Decompile the threaded code of the colon definition at xt."""
    marks = marks or {}
    name = vm.word_at(xt) or "0x%x" % xt
    code = vm.label2prim.get(vm.cell(xt)) or vm.xt_name(vm.cell(xt)) or "?"
    out = [": %s   (xt=0x%x, code field %s)" % (name, xt, code)]
    addr = xt + 2 * CELL
    j = bisect.bisect_right(vm.nts, xt)
    end = vm.nts[j] if j < len(vm.nts) else addr + limit * CELL
    end = min(end, addr + limit * CELL)
    todo = []
    while addr < end:
        value = vm.cell(addr)
        mark = marks.get(addr, "  ")
        if todo:
            kind = todo.pop(0)
            if kind == "callee":
                label = "  (%s)" % (vm.body_name(value) or "0x%x" % value)
            elif kind == "target":
                hit = vm.containing(value)
                label = "  -> %s+%d" % hit if hit else "  -> 0x%x" % value
            else:
                label = "  %d" % _s64(value)
        else:
            label = vm.decode(value) or "?0x%x" % value
            todo = _operands(label)
        out.append("%2s 0x%x  +%-4d %s" % (mark, addr, addr - xt, label))
        addr += CELL
        if label == ";s" and addr < end and vm.cell(addr) == 0:
            break     # end of the last definition: rest is unused space
    return out


def _frames(vm):
    """[(label, ip)] innermost first: current IP, then return addresses."""
    frames = []
    if vm.ip is not None:
        frames.append(vm.ip)
    if vm.rp is not None:
        depth = (vm.rp0 - vm.rp) // CELL
        for i in range(max(0, min(depth, 512))):
            value = vm.cell(vm.rp + CELL * i)
            if value % CELL == 0 and vm.containing(value):
                frames.append(value)
    return frames


def fip(debugger, command, result, internal_dict):
    """fip [N]: threaded code around frame N of fbt (0 = current IP)"""
    vm = _vm(debugger, result)
    if not vm:
        return
    frames = _frames(vm)
    n = int(command.strip() or "0")
    if n >= len(frames):
        result.SetError("only %d frames" % len(frames))
        return
    ip = frames[n]
    name, off = vm.containing(ip)
    marks = {ip: "->"}
    if n == 0 and vm.ip is not None:
        marks = {ip - CELL: "=>", ip: "->"}  # executing, next
    result.PutCString("\n".join(see_lines(vm, ip - off, marks)))


def fsee(debugger, command, result, internal_dict):
    """fsee NAME: decompile a colon definition from memory"""
    vm = _vm(debugger, result)
    if not vm:
        return
    w = vm.lookup(command.strip())
    if not w:
        result.SetError("no word %s" % command.strip())
        return
    result.PutCString("\n".join(see_lines(vm, w[0])))


def finput(debugger, command, result, internal_dict):
    """current input line with >IN caret"""
    vm = _vm(debugger, result)
    if not vm:
        return
    ci = vm._user("current-input")
    if not ci:
        result.SetError("current-input not found")
        return
    to_in = vm.cell(ci + 1 * CELL)
    ntib = vm.cell(ci + 4 * CELL)
    loadline = vm.cell(ci + 7 * CELL)
    loadfile = vm.cell(ci + 8 * CELL)
    # loadfilename was stored with 2! ( c-addr u ): u first, then c-addr
    fname_len = vm.cell(ci + 11 * CELL)
    fname_addr = vm.cell(ci + 12 * CELL)
    inline = ci + 13 * CELL
    # evaluate-input keeps a pointer in the tib slot instead of the text;
    # its method table differs from the file/terminal ones.
    methods = vm.cell(ci)
    kind = vm.describe(methods) or "0x%x" % methods
    buf = inline
    if "evaluate" in kind:
        buf = vm.cell(inline)
    text = b""
    if 0 < ntib < 4096:
        text = vm.read(buf, ntib)
    fname = b""
    if 0 < fname_len < 1024:
        fname = vm.read(fname_addr, fname_len)
    line = text.decode("latin-1").rstrip("\n")
    out = ["input: %s  file=%s line=%d  >in=%d #tib=%d  (current-input=0x%x)"
           % (kind, fname.decode("latin-1") or ("<loadfile 0x%x>" % loadfile
                                                if loadfile else "-"),
              loadline, to_in, ntib, ci),
           "  " + line,
           "  " + " " * min(to_in, len(line)) + "^"]
    result.PutCString("\n".join(out))


def fword(debugger, command, result, internal_dict):
    """fword NAME: dictionary entry for NAME"""
    vm = _vm(debugger, result)
    if not vm:
        return
    name = command.strip()
    hits = [w for w in vm.words if w[2] == name]
    if not hits:
        result.SetError("%s not found among %d headers" % (name, len(vm.words)))
        return
    out = []
    for xt, nt, nm, cnt in hits:
        cf = vm.cell(xt)
        flags = []
        if not cnt & ALIAS_BIT:
            flags.append("alias")
        if cnt & IMM_BIT:
            flags.append("immediate")
        if cnt & RESTRICT_BIT:
            flags.append("compile-only")
        kind = vm.label2prim.get(cf) or vm.xt_name(cf) or "?"
        out.append("%s nt=0x%x xt=0x%x code=0x%x (%s) %s"
                   % (nm, nt, xt, cf, kind, " ".join(flags)))
    result.PutCString("\n".join(out))


def _brk_callback(frame, bp_loc, internal_dict):
    parent = frame.GetThread().GetFrameAtIndex(1)
    if parent.GetFunctionName() not in ("gforth_engine", "gforth_engine2"):
        return False      # someone else's getpid(): keep going
    return True


def fbrk(debugger, command, result, internal_dict):
    """break whenever the Forth word `brk` (env/brk.fs) runs"""
    target = debugger.GetSelectedTarget()
    bp = target.BreakpointCreateByName("getpid")
    bp.SetScriptCallbackFunction("gforth._brk_callback")
    result.PutCString("breakpoint %d on getpid (Forth `brk`)" % bp.GetID())


def fbreak_prim(debugger, command, result, internal_dict):
    """fbreak-prim NAME: break at the engine code of primitive NAME"""
    vm = _vm(debugger, result)
    if not vm:
        return
    name = command.strip()
    label = vm.prim2label.get(name)
    if label is None:
        result.SetError("no primitive %s" % name)
        return
    bp = vm.target.BreakpointCreateByAddress(label)
    result.PutCString("breakpoint %d at 0x%x (primitive %s)"
                      % (bp.GetID(), label, name))


def __lldb_init_module(debugger, internal_dict):
    for cmd, fn in (("fstacks", "fstacks"), ("fregs", "fregs"),
                    ("fbt", "fbt"), ("fip", "fip"), ("finput", "finput"),
                    ("fword", "fword"), ("fbrk", "fbrk"), ("fsee", "fsee"),
                    ("fbreak-prim", "fbreak_prim")):
        debugger.HandleCommand("command script add -o -f gforth.%s %s"
                               % (fn, cmd))
