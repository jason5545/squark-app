#!/usr/bin/env python3
"""fpcrscan.py: which native functions of our own ARM64EC builds may run with FEX's JIT FPCR.

Every call from x64 code to native ARM64EC code leaves the JIT through FEX's ExitFunctionEC, which writes FPCR to
drop the JIT's bits (AH, NEP and the trap enables armed from MXCSR) and writes it again when the call returns to the
JIT. On Apple cores a write to FPCR waits for everything in flight: about 8 ns in a tight loop, several times that
in real code. FEX patch 0043 skips both writes for the targets this tool lists.

A target qualifies when nothing it can execute is affected by those bits. The tool walks the code reachable from the
target (both ways of every conditional branch, jumps, tail calls, direct calls, calls through the import table into
our other images, following forwarders and api sets) and rejects it when any reachable instruction is:

- floating-point data processing: a mnemonic starting with 'f' other than fmov, scvtf/ucvtf, bf*. AH changes the
  results of some of them (NaN and signed-zero handling of fmin/fmax, estimates), NEP what scalar ones leave in the
  upper lanes, and the trap enables can make them trap. Loads, stores, moves, fmov and integer SIMD are unaffected;
- a write to FPCR (msr fpcr). Reading it is fine: RtlCaptureContext only stores it in a CONTEXT;
- an indirect branch or call whose target is not known here. Known ones: the import table; jump tables of a switch
  (the whole function is then walked); Wine's syscall and unix call dispatchers, which Wine patch 0070 makes drop
  the JIT bits before the unix side runs (and they put the caller's FPCR back on return); Wine's call checker
  arm64x_check_call (integer only) for calls to hybrid_patchable functions, whose native code is then walked; ntdll's
  pointers to FEX's notification exports (pNotify*, pBTCpu64*), which FEX patch 0043 fences: they drop the JIT bits
  on entry and put them back on return;
- svc, hvc, udf, brk other than #0x1 (__builtin_trap) and #0xf003 (__fastfail), which end the process.

A call to ntdll's debug output entry points (__wine_dbg_header, __wine_dbg_strdup, __wine_dbg_output) ends a path:
Wine patch 0070 makes them drop the JIT's bits for the rest of the call.

Raising an exception (RtlRaiseException, RtlRaiseStatus) ends a path: only error paths of listed functions reach it
(a unix call failing while a debug message is written, heap corruption, a critical section wait timing out), and the
dispatch then runs with the JIT's FPCR as it already does for every exception raised in JIT code (self-modifying-code
write faults, guest access violations): the unix side gives KiUserExceptionDispatcher the faulting context's FPCR.

Only for images built from source here (Wine, vkd3d-proton): it reads their code, never anything closed.

build-wine.sh runs it on the Wine build's unstripped DLLs (it needs their symbols; strip keeps TimeDateStamp and the
.text size the table is keyed by) before it compiles FEX.

usage: fpcrscan.py <dll> [--search dir:dir] [--rvas rva,...] [--why]      check exports (or RVAs) of one image
       fpcrscan.py --table <out.inc> <dll> [<dll>...]                      the include for FEX patch 0043
"""
import bisect, re, struct, subprocess, sys, os

# llvm-mingw's (build-wine.sh puts it on PATH); LLVM_OBJDUMP names another
OBJDUMP = os.environ.get('LLVM_OBJDUMP', 'llvm-objdump')


class PE:
    def __init__(self, path):
        self.path = path
        d = self.d = open(path, 'rb').read()
        o = struct.unpack_from('<I', d, 0x3c)[0]
        opt = o + 24
        self.timestamp = struct.unpack_from('<I', d, o + 8)[0]
        self.base = struct.unpack_from('<Q', d, opt + 24)[0]
        self.size = struct.unpack_from('<I', d, opt + 56)[0]
        nsec = struct.unpack_from('<H', d, o + 6)[0]
        soh = struct.unpack_from('<H', d, o + 20)[0]
        self.secs = []
        for i in range(nsec):
            name, vs, va, rs, ra = struct.unpack_from('<8sIIII', d, opt + soh + i * 40)
            ch = struct.unpack_from('<I', d, opt + soh + i * 40 + 36)[0]
            self.secs.append((name.rstrip(b'\0').decode(), va, vs, ra, rs, ch))
        self.dirs = [struct.unpack_from('<II', d, opt + 112 + 8 * i) for i in range(16)]

    def off(self, rva):
        for n, va, vs, ra, rs, ch in self.secs:
            if va <= rva < va + max(vs, rs):
                return rva - va + ra
        return None

    def u32(self, rva):
        return struct.unpack_from('<I', self.d, self.off(rva))[0]

    def cstr(self, rva):
        o = self.off(rva)
        return self.d[o:self.d.index(b'\0', o)].decode()

    def text(self):
        return [(va, vs) for n, va, vs, ra, rs, ch in self.secs if ch & 0x20000000]  # IMAGE_SCN_MEM_EXECUTE

    def functions(self):
        """(begin, end) RVAs from .pdata (ARM64 RUNTIME_FUNCTION). An ARM64X image (Wine's) has them in its exception
        directory; a pure ARM64EC one (vkd3d-proton's, the header says AMD64) has an empty one and keeps them in the
        CHPE metadata's ExtraRFETable."""
        rva, size = self.dirs[3]
        if not size:
            rva, size = self.extra_rfe()
        out = []
        for i in range(size // 8):
            begin, unwind = struct.unpack_from('<II', self.d, self.off(rva) + 8 * i)
            length = ((unwind >> 2) & 0x7ff) * 4 if unwind & 3 else (self.u32(unwind) & 0x3ffff) * 4
            out.append((begin, begin + length))
        return sorted(out)

    def chpe(self):
        """IMAGE_ARM64EC_METADATA as 14 ULONGs: Version, CodeMap, CodeMapCount, CodeRangesToEntryPoints,
        RedirectionMetadata, 5 dispatch fields, AlternateEntryPoint, AuxiliaryIAT, CodeRangesToEntryPointsCount,
        RedirectionMetadataCount."""
        rva, size = self.dirs[10]
        if not rva:
            return None
        lc = self.off(rva)
        if struct.unpack_from('<I', self.d, lc)[0] < 0xd0:
            return None
        va = struct.unpack_from('<Q', self.d, lc + 0xc8)[0]
        return struct.unpack_from('<14I', self.d, self.off(va - self.base)) if va else None

    def extra_rfe(self):
        """IMAGE_ARM64EC_METADATA's ExtraRFETable and ExtraRFETableSize (ULONGs 16 and 17), or (0, 0)."""
        if not self.chpe():
            return (0, 0)
        lc = self.off(self.dirs[10][0])
        va = struct.unpack_from('<Q', self.d, lc + 0xc8)[0]
        return struct.unpack_from('<2I', self.d, self.off(va - self.base) + 64)

    def exports(self):
        """name -> RVA, or the forwarder string ('NTDLL.RtlFreeHeap')."""
        rva, size = self.dirs[0]
        if not rva:
            return {}
        nf, nn, af, an, ao = struct.unpack_from('<IIIII', self.d, self.off(rva) + 20)
        out = {}
        for i in range(nn):
            name = self.cstr(self.u32(an + 4 * i))
            f = self.u32(af + 4 * struct.unpack_from('<H', self.d, self.off(ao) + 2 * i)[0])
            out[name] = self.cstr(f) if rva <= f < rva + size else f
        return out

    def imports(self):
        """IAT slot RVA -> (dll in lower case, function name), for the IAT and the ARM64EC auxiliary IAT that
        parallels it (native code calls imports through the latter)."""
        rva, size = self.dirs[1]
        out = {}
        i = 0
        while rva:
            oft, ts, fc, name, ft = struct.unpack_from('<IIIII', self.d, self.off(rva) + 20 * i)
            if not name and not ft:
                break
            dll = self.cstr(name).lower()
            j = 0
            while True:
                ent = struct.unpack_from('<Q', self.d, self.off(oft or ft) + 8 * j)[0]
                if not ent:
                    break
                if not ent >> 63:
                    out[ft + 8 * j] = (dll, self.cstr((ent & 0x7fffffff) + 2))
                j += 1
            i += 1
        meta = self.chpe()
        if meta and meta[11]:
            iat = self.dirs[12][0]
            for slot, imp in list(out.items()):
                out[slot - iat + meta[11]] = imp
        return out


INS = re.compile(r'^\s*([0-9a-f]+):\s+(\S+)\s*(.*)$')
HEX = re.compile(r'0x([0-9a-f]+)')


def disassemble(pe):
    code = {}
    for va, vs in pe.text():
        a, b = pe.base + va, pe.base + va + vs
        out = subprocess.run([OBJDUMP, '-d', '--no-show-raw-insn', '--start-address=%#x' % a,
                              '--stop-address=%#x' % b, pe.path], capture_output=True, text=True).stdout
        for line in out.splitlines():
            m = INS.match(line)
            if m:
                ops = re.sub(r'<[^>]*>', '', m.group(3).split('//')[0]).strip()  # drop <symbol+0x..>
                code[int(m.group(1), 16) - pe.base] = (m.group(2), ops)
    return code


def symbols(pe):
    """[(name, RVA, is function)] from the COFF symbol table of our own builds."""
    out = subprocess.run([OBJDUMP, '-t', pe.path], capture_output=True, text=True).stdout
    syms = []
    for line in out.splitlines():
        m = re.search(r'\(sec\s+(\d+)\).*\(ty\s+(\d+)\).*0x([0-9a-f]+) (\S+)$', line)
        if m and 0 < int(m.group(1)) <= len(pe.secs):
            syms.append((m.group(4), pe.secs[int(m.group(1)) - 1][1] + int(m.group(3), 16), m.group(2) == '20'))
    return syms


DISPATCHERS = ('__wine_syscall_dispatcher', '__wine_unix_call_dispatcher', '__wine_unix_call_dispatcher_arm64ec')
CHECKERS = ('__os_arm64x_dispatch_call',)
ICHECKERS = ('__os_arm64x_dispatch_icall', '__os_arm64x_dispatch_icall_cfg')
# ntdll's pointers to FEX's exports that FEX patch 0043 fences (not ProcessInit/Term, ThreadInit/Term,
# ResetToConsistentState, BeginSimulation: no listed function reaches them but through an exception)
FENCED = ('pNotifyMapViewOfSection', 'pNotifyMemoryAlloc', 'pNotifyMemoryFree', 'pNotifyMemoryProtect',
          'pNotifyUnmapViewOfSection', 'pBTCpu64FlushInstructionCache', 'pBTCpu64NotifyMemoryDirty',
          'pBTCpu64NotifyReadFile', 'pBTCpu64IsProcessorFeaturePresent', 'pFlushInstructionCacheHeavy',
          'pUpdateProcessorInformation', 'pGetX87State', 'pKeepX64DebugRegisters', 'pGetX64Mxcsr', 'pSetX64Mxcsr',
          'pGuestProtection', 'pGuestProtectionRange')
SINKS = ('RtlRaiseException', 'RtlRaiseStatus', '#RtlRaiseException', '#RtlRaiseStatus')
# The CRT's assertion failure ends the process (message, then abort): vkd3d-proton's release build keeps its asserts,
# whose failure ends a path. Not listed themselves (the check can't follow them: an x64 caller keeps the switch).
# ntdll's own _assert is checked as before (it raises an exception).
ASSERTS = ('_assert', '#_assert', '_wassert', '#_wassert')
ASSERT_IMAGES = ('ucrtbase.dll', 'msvcrt.dll')
# Wine patch 0070: ntdll's debug output entry points drop the JIT's FPCR bits for the rest of the call, so a path that
# calls one ends there (everything after it runs with the native FPCR, which native code is always fine with)
FENCES = ('__wine_dbg_header', '__wine_dbg_strdup', '__wine_dbg_output',
          '#__wine_dbg_header', '#__wine_dbg_strdup', '#__wine_dbg_output')
# Wine patch 0070 also drops them in enter_syscall_callback, first thing in the ARM64EC wrappers of these syscalls
# (they notify FEX, capture a context or notify another process before the syscall)
FENCES += tuple('#%s$hp_target' % n for n in (
    'NtAllocateVirtualMemory', 'NtAllocateVirtualMemoryEx', 'NtFlushInstructionCache', 'NtFreeVirtualMemory',
    'NtMapViewOfSection', 'NtMapViewOfSectionEx', 'NtProtectVirtualMemory', 'NtQueryVirtualMemory', 'NtReadFile',
    'NtTerminateProcess', 'NtTerminateThread', 'NtUnmapViewOfSection', 'NtUnmapViewOfSectionEx'))
# vkd3d-proton (our fork): vkd3d_squark_native_fpcr drops the JIT's bits for the rest of the call; VK_CALL and the
# debug output (vkd3d_dbg_printf, vkd3d_dbg_vsprintf) call it first, so a path ends there like at Wine's debug output
FENCES += ('vkd3d_squark_native_fpcr', '#vkd3d_squark_native_fpcr')
# Checked indirect calls (ARM64EC's icall checker, then blr x11) with a fixed set of targets, by the function they are
# in: (targets, how many checked calls the function has, its only indirect calls). vkd3d-proton's descriptor copy
# calls the heap's copy template, one of vkd3d_descriptor_copy_desc_<n>_single (vkd3d_bindless_find_copy_template_single),
# twice; its third is vkUpdateDescriptorSets, behind VK_CALL's fence, so no path reaches it. Another count (the source
# changed) and the function's indirect calls are unknown again.
TARGET_SETS = {
    'd3d12_desc_copy_single': (tuple('vkd3d_descriptor_copy_desc_%d_single' % n for n in (4, 8, 16, 32, 48, 64, 128)), 3),
    # the range copy: the heap's host_copy_template (vkd3d_bindless_find_copy_template) once, vkUpdateDescriptorSets
    'd3d12_desc_copy_range': (tuple('vkd3d_descriptor_copy_desc_%d' % n for n in (4, 8, 16, 32, 48, 64, 128)), 2),
}
# Images whose entry points for x64 code are their exports and the functions their data points at (COM vtables),
# not every EC function: d3d12core has thousands no x64 code calls
VTABLE_IMAGES = ('d3d12core.dll', 'd3d12.dll')
INDIRECT = ('blr', 'br', 'braa', 'brab', 'blraa', 'blrab', 'braaz', 'brabz', 'blraaz', 'blrabz')
CONDITIONAL = ('cbz', 'cbnz', 'tbz', 'tbnz')
READS_ONLY = ('cbz', 'cbnz', 'tbz', 'tbnz', 'cmp', 'cmn', 'tst', 'ccmp', 'ccmn', 'str', 'strb', 'strh', 'stur',
              'sturb', 'sturh', 'stp', 'stlr', 'stlrb', 'stlrh', 'prfm', 'blr', 'br')


def writes(mn, op, reg):
    return mn not in READS_ONLY and op.split(',')[0].strip() == reg


def fp_affected(mn):
    if mn.startswith('f') and mn != 'fmov':
        return True
    return mn.startswith(('scvtf', 'ucvtf', 'bfcvt', 'bfm', 'bfdot'))


REGISTRY = {}  # dll name (lower case) -> Scan
SEARCH = []    # folders holding our images


def image(dll):
    if dll not in REGISTRY:
        REGISTRY[dll] = None
        for d in SEARCH:
            p = os.path.join(d, dll)
            if os.path.exists(p):
                REGISTRY[dll] = Scan(PE(p))
                break
    return REGISTRY[dll]


class Scan:
    def __init__(self, pe):
        self.pe = pe
        self.code = disassemble(pe)
        self.funcs = pe.functions()
        self.begins = [b for b, e in self.funcs]
        self.imps = pe.imports()
        self.exps = None
        self.syms = symbols(pe)
        self.byname = {}
        for n, r, f in self.syms:
            self.byname.setdefault(n, r)
        vars_of = lambda names: {r for n, r, f in self.syms if n in names}
        self.dispatchers = vars_of(DISPATCHERS)
        self.checkers = vars_of(CHECKERS)
        self.icheckers = vars_of(ICHECKERS)
        self.fenced = vars_of(FENCED)
        self.sinks = vars_of(SINKS)
        self.asserts = vars_of(ASSERTS) if os.path.basename(pe.path).lower() in ASSERT_IMAGES else set()
        self.sinks |= self.asserts
        self.fences = vars_of(FENCES)
        self.target_sets = {}  # function begin -> [target RVAs]
        for fn, (targets, count) in TARGET_SETS.items():
            begin = self.byname.get('#' + fn, self.byname.get(fn))
            tgts = [self.byname.get('#' + t, self.byname.get(t)) for t in targets]
            if begin is None or None in tgts:
                continue
            fb, fe = self.extent(begin)
            checked = [a for a in range(fb, fe, 4) if self.code.get(a, ('',))[0] == 'blr'
                       and self.loaded_from(a, self.code[a][1].split(',')[0].strip()) in self.icheckers]
            others = [a for a in range(fb, fe, 4) if self.code.get(a, ('',))[0] in INDIRECT]
            # every indirect call is a checked one: the checker's blr, then blr x11
            if len(checked) == count and len(others) == 2 * count:
                self.target_sets[fb] = tgts

    def extent(self, rva):
        i = bisect.bisect_right(self.begins, rva) - 1
        if i >= 0 and self.funcs[i][0] <= rva < self.funcs[i][1]:
            return self.funcs[i]
        return (rva, rva)

    def ec_entry(self, name, rva):
        """Native callers in an ARM64EC process reach the EC copy ('#name') of an ARM64X export."""
        for n in ('#' + name + '$hp_target', '#' + name):
            if n in self.byname:
                return self.byname[n]
        return rva

    # where a register's value came from, looking back a few instructions
    def _def(self, at, reg, limit):
        """The last instruction before at (straight back) that writes reg. Past a bl only a callee-saved register
        (x19-x28) keeps its value."""
        saved = reg in ['x%d' % i for i in range(19, 29)]
        for k in range(1, limit):
            ins = self.code.get(at - 4 * k)
            if not ins or (ins[0] == 'bl' and not saved) or ins[0] in ('ret', 'b', 'br'):
                return None, None
            if writes(ins[0], ins[1], reg):
                return at - 4 * k, ins
        return None, None

    def page_of(self, at, reg):
        a, ins = self._def(at, reg, 64)
        if ins and ins[0] == 'adrp':
            return HEX.findall(ins[1]) and int(HEX.findall(ins[1])[-1], 16) - self.pe.base
        return None

    def loaded_from(self, at, reg):
        """The address reg was loaded from: ldr reg, [xM, #imm] after adrp xM, ldr reg, [xB] after a literal load of xB,
        or ldr reg, [xB] after mingw's .refptr load of xB."""
        a, ins = self._def(at, reg, 16)
        if not ins or ins[0] != 'ldr':
            return None
        parts = [x.strip() for x in ins[1].replace('[', ',').replace(']', ',').split(',') if x.strip()]
        if len(parts) == 2:  # ldr reg, [xB]
            base = parts[1]
            a2, i2 = self._def(a, base, 8)
            if i2 and i2[0] == 'ldr' and '[' not in i2[1]:  # xB loaded from a literal
                lit = int(HEX.findall(i2[1])[-1], 16) - self.pe.base
                return struct.unpack_from('<Q', self.pe.d, self.pe.off(lit))[0] - self.pe.base
            if i2 and i2[0] == 'ldr':  # mingw: adrp xB, page; ldr xB, [xB, #.refptr.x]; ldr reg, [xB]
                p2 = [x.strip() for x in i2[1].replace('[', ',').replace(']', ',').split(',') if x.strip()]
                if len(p2) >= 3 and p2[2].startswith('#'):
                    page = self.page_of(a2, p2[1])
                    ref = page + int(p2[2][1:], 0) if page is not None else None
                    if ref is not None and self.pe.off(ref) is not None:
                        return struct.unpack_from('<Q', self.pe.d, self.pe.off(ref))[0] - self.pe.base
                return None
            return None if base == reg else self.page_of(a, base)
        if len(parts) >= 3 and parts[2].startswith('#'):
            page = self.page_of(a, parts[1])
            return page + int(parts[2][1:], 0) if page is not None else None
        return None

    def constant(self, at, reg):
        """adrp reg, page ; add reg, reg, #off -> the address."""
        a, ins = self._def(at, reg, 12)
        if ins and ins[0] == 'add':
            parts = [x.strip() for x in ins[1].split(',')]
            if len(parts) == 3 and parts[1] == reg and parts[2].startswith('#'):
                page = self.page_of(a, reg)
                return page + int(parts[2][1:], 0) if page is not None else None
        if ins and ins[0] == 'adrp':
            return int(HEX.findall(ins[1])[-1], 16) - self.pe.base
        return None

    def is_jump_table(self, at, reg):
        a, ins = self._def(at, reg, 5)
        return bool(ins and ins[0] == 'add' and re.search(r'\b[wx]\d+, (sxt[bhw]|uxt[bhw]|lsl)', ins[1]))

    def local(self, rva):
        """Walk the code reachable from rva without entering calls. Returns (first bad instruction or None, edges):
        the callees of bl, of calls through the import table and of checked calls."""
        edges = []
        if rva in self.sinks or rva in self.fences:
            return None, edges
        work, seen, checked_x11 = [rva], set(), False
        while work:
            a = work.pop()
            while a not in seen:
                seen.add(a)
                if a in self.sinks:
                    break
                ins = self.code.get(a)
                if ins is None:
                    return 'no code at %#x' % a, edges
                mn, ops = ins
                reg = ops.split(',')[0].strip()
                if fp_affected(mn) or (mn == 'msr' and 'fpcr' in ops.lower()):
                    return '%#x %s %s' % (a, mn, ops), edges
                if mn == 'brk' and ops in ('#0x1', '#0xf003'):
                    break
                if mn in ('svc', 'hvc', 'brk', 'udf', 'smc', 'eret'):
                    return '%#x %s %s' % (a, mn, ops), edges
                if mn in ('ret', 'retaa', 'retab'):
                    break
                if mn in INDIRECT:
                    if reg == 'x11' and checked_x11:  # the checker's answer for a call already walked
                        checked_x11 = False
                        if mn == 'br':
                            break
                        a += 4
                        continue
                    slot = self.loaded_from(a, reg) if mn in ('blr', 'br') else None
                    if slot is not None and slot in self.dispatchers:
                        if mn == 'br':
                            break
                        a += 4
                        continue
                    if mn == 'blr' and slot is not None and slot in self.checkers:
                        tgt = self.constant(a, 'x9')
                        if tgt is None:
                            return '%#x checked call, unknown target' % a, edges
                        edges.append((self, tgt, '%#x' % tgt))
                        checked_x11 = True
                        a += 4
                        continue
                    if mn == 'blr' and slot is not None and slot in self.icheckers and \
                            self.extent(a)[0] in self.target_sets:
                        edges.extend((self, t, '%#x' % t) for t in self.target_sets[self.extent(a)[0]])
                        checked_x11 = True
                        a += 4
                        continue
                    if mn == 'blr' and slot is not None and slot in self.icheckers:
                        src = self.loaded_from(a, 'x11')
                        if src is None or src not in self.fenced:
                            return '%#x checked indirect call' % a, edges
                        checked_x11 = True
                        a += 4
                        continue
                    if slot is not None and slot in self.imps:
                        dll, name = self.imps[slot]
                        node = resolve_import(dll, name)
                        if isinstance(node, str):
                            return node, edges
                        if node[1] in node[0].fences:
                            break
                        edges.append(node + ('%s!%s' % (dll, name),))
                        if mn == 'br':
                            break
                        a += 4
                        continue
                    if mn == 'br' and self.is_jump_table(a, reg):
                        fb, fe = self.extent(a)
                        if fe == fb or fe - fb > 0x10000:
                            return '%#x jump table outside a known function' % a, edges
                        work.extend(range(fb, fe, 4))
                        break
                    return '%#x %s %s' % (a, mn, ops), edges
                if mn in ('bl', 'b') or mn.startswith('b.') or mn in CONDITIONAL:
                    t = HEX.findall(ops)
                    if t:
                        tr = int(t[-1], 16) - self.pe.base
                        if mn == 'bl' and tr in self.fences:
                            break
                        if mn == 'bl':
                            edges.append((self, tr, '%#x' % tr))
                        elif mn == 'b':
                            a = tr
                            continue
                        else:
                            work.append(tr)
                a += 4
        return None, edges

    def check(self, rva):
        return check_node(self, rva)


def resolve_import(dll, name, hops=0):
    """(scan, rva) of an import, following api sets and forwarders, or why it can't be followed."""
    if dll.startswith('api-ms-win-crt-'):
        dll = 'ucrtbase.dll'
    elif dll.startswith('api-ms-win-'):
        dll = 'kernelbase.dll'
    img = image(dll)
    if img is None:
        return 'import %s!%s: not one of our images' % (dll, name)
    if img.exps is None:
        img.exps = img.pe.exports()
    target = img.exps.get(name)
    if target is None:
        return 'import %s!%s: not exported' % (dll, name)
    if isinstance(target, str):
        if hops > 8:
            return 'forwarder loop at %s!%s' % (dll, name)
        fdll, fname = target.split('.', 1)
        return resolve_import(fdll.lower() + '.dll', fname, hops + 1)
    return (img, img.ec_entry(name, target))


RESULT = {}  # (image path, rva) -> None or reason


def check_node(scan, rva):
    """Build the graph reachable from (scan, rva), then mark bad every node with a bad instruction or a path to one."""
    key = (scan.pe.path, rva)
    if key in RESULT:
        return RESULT[key]
    nodes, stack = {}, [(scan, rva)]
    while stack:
        sc, r = stack.pop()
        k = (sc.pe.path, r)
        if k in nodes or k in RESULT:
            continue
        reason, edges = sc.local(r)
        nodes[k] = (reason, [((e[0].pe.path, e[1]), e[2]) for e in edges])
        if not reason:
            stack.extend((e[0], e[1]) for e in edges)
    bad = {k: v[0] for k, v in nodes.items() if v[0]}
    changed = True
    while changed:
        changed = False
        for k, (reason, edges) in nodes.items():
            if k in bad:
                continue
            for ek, label in edges:
                why = bad.get(ek) or RESULT.get(ek)
                if why:
                    bad[k] = 'via %s: %s' % (label, why)
                    changed = True
                    break
    for k in nodes:
        RESULT[k] = bad.get(k)
    return RESULT[key]


def data_pointers(scan):
    """Functions the image's data points at (absolute 8-byte pointers into a function's first instruction)."""
    begins = set(scan.begins)
    out = set()
    for n, va, vs, ra, rs, ch in scan.pe.secs:
        if ch & 0x20000000 or n in ('.pdata', '.reloc'):
            continue
        for off in range(0, min(vs, rs) - 7, 8):
            v = struct.unpack_from('<Q', scan.pe.d, ra + off)[0] - scan.pe.base
            if v in begins:
                out.add(v)
    return out


def candidates(scan):
    """What x64 code can reach: the EC entry of every export and every EC function symbol ('#name'); for
    VTABLE_IMAGES the exports and the functions their data points at."""
    out = {}
    for name, target in scan.pe.exports().items():
        if not isinstance(target, str):
            out[name] = scan.ec_entry(name, target)
    if os.path.basename(scan.pe.path).lower() in VTABLE_IMAGES:
        names = {r: n for n, r, f in scan.syms if f}
        for r in data_pointers(scan):
            out.setdefault(names.get(r, '%#x' % r), r)
        return out
    for n, r, f in scan.syms:
        if f and n.startswith('#') and r in scan.code:
            out.setdefault(n, r)
    return out


def main():
    args = sys.argv[1:]
    if '--search' in args:
        SEARCH.extend(args[args.index('--search') + 1].split(':'))
    if '--table' in args:
        out = args[args.index('--table') + 1]
        dlls = [a for a in args if a.endswith('.dll')]
        for d in dlls:
            SEARCH.append(os.path.dirname(os.path.abspath(d)))
        lines = ['// Generated by squark-app runtime/fex/fpcrscan.py --table: native functions that run with',
                 '// the JIT\'s FPCR (FEX patch 0043). Keyed by image name, TimeDateStamp and .text size (both kept by',
                 '// strip, unlike SizeOfImage): another build of the image gets no entries.', '']
        total, images = 0, []
        for d in dlls:
            name = os.path.basename(d).lower()
            sc = image(name)
            cands = candidates(sc)
            rvas = sorted({r for n, r in cands.items() if r not in sc.asserts and sc.check(r) is None})
            total += len(rvas)
            ident = 'FPCRNeutral_' + re.sub(r'\W', '_', name)
            lines.append('static const uint32_t %s[] = {' % ident)
            for i in range(0, len(rvas), 10):
                lines.append('  ' + ', '.join('0x%x' % r for r in rvas[i:i + 10]) + ',')
            lines.append('};')
            text = [vs for n, va, vs, ra, rs, ch in sc.pe.secs if n == '.text'][0]
            images.append('  {"%s", 0x%08x, 0x%x, std::size(%s), %s},' % (name, sc.pe.timestamp, text, ident, ident))
            print('# %s: %d neutral of %d candidates' % (name, len(rvas), len(cands)), file=sys.stderr)
        lines += ['', 'static const FPCRNeutralImage FPCRNeutralImages[] = {'] + images + ['};']
        open(out, 'w').write('\n'.join(lines) + '\n')
        print('# %d entries -> %s' % (total, out), file=sys.stderr)
        return
    path = args[0]
    SEARCH.insert(0, os.path.dirname(os.path.abspath(path)))
    sc = image(os.path.basename(path).lower())
    if '--rvas' in args:
        targets = {'%#x' % int(x, 16): int(x, 16) for x in args[args.index('--rvas') + 1].split(',')}
    else:
        targets = {n: sc.ec_entry(n, r) for n, r in sc.pe.exports().items() if not isinstance(r, str)}
    ok = 0
    for name, rva in sorted(targets.items()):
        why = sc.check(rva)
        ok += why is None
        if '--why' in args or '--rvas' in args:
            print('%-40s %#8x %s' % (name, rva, 'NEUTRAL' if why is None else why))
    print('# %s: %d of %d neutral' % (os.path.basename(path), ok, len(targets)), file=sys.stderr)


if __name__ == '__main__':
    main()
