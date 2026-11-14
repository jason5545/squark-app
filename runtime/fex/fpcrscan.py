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
  upper lanes, and the trap enables can make them trap. Loads, stores, moves, fmov and integer SIMD are unaffected.
  Scalar arithmetic is the exception, see "scalar functions" below;
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

Scalar functions (FEX patch 0044). A second class, listed with bit 0 of the RVA set: the C runtime's math functions
named in SCALAR_ALLOW, when their reachable code does floating-point arithmetic only with scalar instructions
(SCALAR_OK below: add, subtract, multiply, divide, fused multiply-add, square root, compares, selects, conversions, the
frint family, fmaxnm/fminnm, fabs, fneg). Those give the same value in the low lane with or without the JIT's bits:
- NEP only changes what a scalar instruction leaves above the low lane of its destination (the first source's lanes
  instead of zero). So nothing may look above the low lane of a register a scalar instruction wrote: no 128-bit
  store of it, no element access, no vector instruction on it. Scan.taint follows this through each function that
  has both kinds of instruction: every vector register counts as scalar-written at the function's entry and after
  each call, a scalar instruction marks its destination, a load or a vector instruction that writes the whole
  register clears it, bit operations on whole registers (and, orr, eor, bic, orn, bit, bif, bsl, not) pass the
  mark from their sources on, and a vector instruction that reads a marked register rejects the
  function. A function without scalar arithmetic may use vectors freely, as before (its vector code initialises
  what it reads). Arguments and results travel in the low lane; an x64 caller of a double-returning function gets
  unspecified upper lanes in xmm0, as from any x64 function.
- AH changes fmax/fmin on NaNs and zeros and the estimate instructions (never allowed), makes a generated default NaN
  negative as x86 does, and detects tininess after rounding as x86 does. It also makes fabs and fneg leave a NaN
  as it is, sign included. That one matters: the compiler builds the mask 0x7fff... as fneg of all-ones (a NaN
  pattern), which stays all-ones with AH set, so log, cbrt and _copysign returned other values; vector fneg/fabs are
  never allowed. A scalar fabs/fneg of a negative NaN keeps the sign, and code that then reads the exponent from the
  bits can miss its NaN check (hypot went on to sqrt and set errno). No rule here can tell such code apart, so the
  class is limited to SCALAR_ALLOW: the functions whose values, NaN counts and errno squark-private's
  tools/msfs-harness/mods/x64shape/mathsweep.c found identical with and without the JIT's bits (special values, NaNs
  of both signs, every exponent; only the sign and payload of NaN results differ). Compare again with that program
  after any change to Wine's math code or the compiler before trusting a new table.
- the trap enables are only armed when the guest unmasked an exception in MXCSR. FEX checks them on such a call and
  switches FPCR as before when any is set.
msvcrt's math_error ends a path: Wine patch 0073 makes it drop the JIT's bits before it calls the program's matherr
handler (any code) and sets errno.

Only for images built from source here (Wine, vkd3d-proton): it reads their code, never anything closed.

build-wine.sh runs it on the Wine build's unstripped DLLs (it needs their symbols; strip keeps TimeDateStamp and the
.text size the table is keyed by) before it compiles FEX.

usage: fpcrscan.py <dll> [--search dir:dir] [--rvas rva,...] [--why]      check exports (or RVAs) of one image
       fpcrscan.py --table <out.inc> <dll> [<dll>...]                      the include for FEX patch 0043
"""
import bisect, re, struct, subprocess, sys, os

# llvm-mingw's (build-wine.sh puts it on PATH); LLVM_OBJDUMP names another
OBJDUMP = os.environ.get('LLVM_OBJDUMP', 'llvm-objdump')
READOBJ = os.environ.get('LLVM_READOBJ', 'llvm-readobj')


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


def hybrid_exports(pe):
    """Export name -> RVA of the ARM64EC code x64 callers of an ARM64X image's export end up in: the export table of
    its ARM64EC view (llvm-readobj prints it under HybridObject; the one in the file's own header is the ARM64 view)
    through the image's redirection table (x64 entry -> ARM64EC function). Empty for an image without that view."""
    out = subprocess.run([READOBJ, '--coff-exports', pe.path], capture_output=True, text=True).stdout
    meta = pe.chpe()
    red = {}
    if meta and meta[4]:
        o = pe.off(meta[4])
        red = dict(struct.iter_unpack('<II', pe.d[o:o + 8 * meta[13]]))
    res, hybrid, name = {}, False, None
    for line in out.splitlines():
        t = line.strip()
        if t.startswith('HybridObject'):
            hybrid = True
        elif hybrid and t.startswith('Name:'):
            name = t[5:].strip()
        elif hybrid and t.startswith('RVA:') and name:
            rva = int(t[4:].strip(), 16)
            if rva in red:
                res[name] = red[rva]
            name = None
    return res


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
# _amsg_exit is the CRT's fatal runtime error (message, then _exit(255)): msvcrt_get_thread_data calls it when a
# thread's data cannot be allocated, which kept _errno, the ctype functions, _stricmp, calloc and rand off the list.
ASSERTS = ('_assert', '#_assert', '_wassert', '#_wassert', '_amsg_exit', '#_amsg_exit')
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
# Wine patch 0073: msvcrt's math_error (every math function's error path: the program's matherr handler, errno) drops
# them first thing
FENCES += ('math_error', '#math_error')
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


SCALAR_OK = frozenset(
    'fadd fsub fmul fdiv fnmul fmadd fmsub fnmadd fnmsub fabs fneg fsqrt fcmp fcmpe fccmp fccmpe fcsel fcvt fcvtzs '
    'fcvtzu fcvtas fcvtau fcvtms fcvtmu fcvtns fcvtnu fcvtps fcvtpu frinta frinti frintm frintn frintp frintx frintz '
    'fmaxnm fminnm fabd scvtf ucvtf'.split())
LANEWISE = frozenset('and orr eor bic orn bit bif bsl mvn not movi mvni mov'.split())
# The scalar class: only these exports of these images (see "scalar functions" at the top). log, cbrt, _copysign,
# hypot and _hypot compared unequal; atanf, atan2f, sinh, cosh, tanh, _nextafter store 128-bit registers; fabs and
# fabsf compared equal but would return a negative NaN with its sign (x86 code clears it, and never calls them).
SCALAR_IMAGES = ('ucrtbase.dll', 'msvcrt.dll')
SCALAR_ALLOW = frozenset(
    'cos sin tan acos asin atan exp log10 sqrt floor ceil round trunc exp2 log2 rint _logb atan2 fmod pow fmax fmin '
    'remainder fdim modf ldexp frexp cosf sinf tanf acosf asinf expf logf sqrtf floorf ceilf roundf truncf tanhf log10f '
    'powf fmodf'.split())
VECTOR_REG = re.compile(r'\bv\d+\.|\bq\d+\b|\bz\d+\b')
ELEMENT = re.compile(r'\[\d+\]|\bq\d+\b')


FP_REG = re.compile(r'\b(?:v(\d+)(\.\w+)?(\[\d+\])?|([qdshb])(\d+))\b')
STORES = frozenset('str stur stp stnp st1 st2 st3 st4'.split())
LOADS = frozenset('ldr ldur ldp ldnp ld1 ld2 ld3 ld4 ld1r ld2r ld3r ld4r'.split())
COMPARES = frozenset('fcmp fcmpe fccmp fccmpe'.split())
# the destination is also a source
ACCUMULATE = frozenset('bit bif bsl mla mls fmla fmls saba uaba sli sri tbx ins sdot udot usdot'.split())


def fp_regs(ops):
    """The vector registers an instruction names, in order: (number, element access)."""
    return [(int(m.group(1) if m.group(1) is not None else m.group(5)), m.group(3) is not None)
            for m in FP_REG.finditer(re.sub(r'<[^>]*>', '', ops))]


def fp_class(mn, ops):
    """None: the JIT's FPCR bits change nothing here. 'bad': they can. 'scalar': scalar arithmetic, the same low lane
    either way, the destination's upper lanes differ (NEP). 'vector': looks above the low lane of a vector register,
    fine unless a scalar instruction wrote that register (Scan.taint)."""
    vec = bool(VECTOR_REG.search(ops))
    if mn.startswith(('bfcvt', 'bfm', 'bfdot')):
        return 'bad'
    if (mn.startswith('f') and mn != 'fmov') or mn.startswith(('scvtf', 'ucvtf')):
        if vec:
            return 'bad'  # also fneg and fabs: with AH set they leave NaN patterns alone, and masks are built that way
        return 'scalar' if mn in SCALAR_OK else 'bad'
    if vec:
        return None if mn in LANEWISE and not ELEMENT.search(ops) else 'vector'
    return None


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
        scalar = vector = None  # the first instruction of each kind
        flow = {}  # address -> the addresses the walk went on to from it
        while work:
            a = work.pop()
            prev = None
            while True:
                if prev is not None:
                    flow.setdefault(prev, []).append(a)
                if a in seen:
                    break
                seen.add(a)
                if a in self.sinks or a in self.fences:  # also when a tail call jumps there
                    break
                prev = a
                ins = self.code.get(a)
                if ins is None:
                    return 'no code at %#x' % a, edges
                mn, ops = ins
                reg = ops.split(',')[0].strip()
                kind = fp_class(mn, ops)
                if kind == 'bad' or (mn == 'msr' and 'fpcr' in ops.lower()):
                    return '%#x %s %s' % (a, mn, ops), edges
                if kind == 'scalar' and scalar is None:
                    scalar = '%#x %s %s' % (a, mn, ops)
                elif kind == 'vector' and vector is None:
                    vector = '%#x %s %s' % (a, mn, ops)
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
                        flow.setdefault(a, []).extend(range(fb, fe, 4))
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
                            flow.setdefault(a, []).append(tr)
                a += 4
        if scalar and vector:
            why = self.taint(rva, flow)
            if why:
                return why, edges
        if scalar:
            SCALAR.add((self.pe.path, rva))
        return None, edges

    def taint(self, entry, flow):
        """The NEP rule for a function with scalar arithmetic and vector instructions (see the top of the file): why
        it fails, or None. A bit per vector register: something above its low lane may differ with NEP set."""
        every = (1 << 32) - 1
        state, work = {entry: every}, [entry]
        while work:
            a = work.pop()
            if a in self.sinks or a in self.fences or a not in self.code:
                continue
            mn, ops = self.code[a]
            t = state[a]
            regs = fp_regs(ops)
            if mn == 'bl' or (mn in INDIRECT and mn.startswith('bl')):
                t = every  # the callee's scalar instructions
            elif regs:
                kind = fp_class(mn, ops)
                first = FP_REG.match(ops.lstrip('{ ')) is not None
                if mn in STORES or mn in COMPARES or not first:
                    writes, reads = [], regs
                elif mn in LOADS:
                    writes, reads = regs, []
                else:
                    writes, reads = regs[:1], regs[1:]
                    if mn in ACCUMULATE or regs[0][1]:  # an element of the destination: the rest of it stays
                        reads = regs
                marked = any(t >> n & 1 for n, e in reads)
                if kind == 'vector':
                    if marked:
                        return 'vector use of a register a scalar instruction wrote: %#x %s %s' % (a, mn, ops)
                    for n, e in writes:
                        t &= ~(1 << n)
                elif kind is None and (VECTOR_REG.search(ops) or mn in LOADS):
                    # whole-register bit operations pass the mark on, movi/mvni and loads write clean registers
                    for n, e in writes:
                        t = t | 1 << n if marked else t & ~(1 << n)
                elif mn == 'fmov' and writes and not reads and '#' not in ops:
                    t &= ~(1 << writes[0][0])  # from a general register: the rest is zero
                else:
                    for n, e in writes:  # scalar arithmetic, scalar moves, scalar integer SIMD
                        t |= 1 << n
            for nxt in flow.get(a, ()):
                new = state.get(nxt, 0) | t
                if nxt not in state or new != state[nxt]:
                    state[nxt] = new
                    work.append(nxt)
        return None

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
SCALAR = set()  # (image path, rva) of walked functions that do scalar floating-point arithmetic
USES_SCALAR = {}  # (image path, rva) of a good node -> whether anything it reaches does


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
    # scalar arithmetic anywhere below a good node puts it in the second class
    uses = {k: k in SCALAR for k in nodes if k not in bad}
    changed = True
    while changed:
        changed = False
        for k in uses:
            if not uses[k] and any(uses.get(ek) or USES_SCALAR.get(ek) for ek, label in nodes[k][1]):
                uses[k] = changed = True
    USES_SCALAR.update(uses)
    return RESULT[key]


def uses_scalar(scan, rva):
    return USES_SCALAR.get((scan.pe.path, rva), False)


def scalar_targets(scan):
    """The functions of the scalar class in an image: the ARM64EC code of each SCALAR_ALLOW export, when it passes."""
    out = set()
    for name, rva in hybrid_exports(scan.pe).items():
        if name in SCALAR_ALLOW and rva not in scan.asserts and scan.check(rva) is None and uses_scalar(scan, rva):
            out.add(rva)
    return out


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
                 '// strip, unlike SizeOfImage): another build of the image gets no entries.',
                 '// An RVA with bit 0 set: a function that does scalar floating-point arithmetic (FEX patch 0044).', '']
        total, images = 0, []
        for d in dlls:
            name = os.path.basename(d).lower()
            sc = image(name)
            cands = candidates(sc)
            good = sorted({r for n, r in cands.items() if r not in sc.asserts and sc.check(r) is None})
            # the scalar class: what the allowed exports really lead to (an export and a function of the same name can
            # be two things: ucrtbase's exp is MSVCRT_exp, its sqrt a wrapper of the math library's)
            scalar_ok = scalar_targets(sc) if name in SCALAR_IMAGES else set()
            good = sorted({r for r in good if not uses_scalar(sc, r)} | scalar_ok)
            nscalar = len(scalar_ok)
            rvas = [r | 1 if r in scalar_ok else r for r in good]
            total += len(rvas)
            ident = 'FPCRNeutral_' + re.sub(r'\W', '_', name)
            lines.append('static const uint32_t %s[] = {' % ident)
            for i in range(0, len(rvas), 10):
                lines.append('  ' + ', '.join('0x%x' % r for r in rvas[i:i + 10]) + ',')
            lines.append('};')
            text = [vs for n, va, vs, ra, rs, ch in sc.pe.secs if n == '.text'][0]
            images.append('  {"%s", 0x%08x, 0x%x, std::size(%s), %s},' % (name, sc.pe.timestamp, text, ident, ident))
            print('# %s: %d neutral of %d candidates, %d of them scalar floating point' % (name, len(rvas), len(cands), nscalar),
                  file=sys.stderr)
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
    allowed = os.path.basename(path).lower() in SCALAR_IMAGES
    hybrid = hybrid_exports(sc.pe)
    if '--rvas' not in args:
        targets = {n: hybrid.get(n, r) for n, r in targets.items()}  # where x64 callers of the export really go
    for name, rva in sorted(targets.items()):
        why = sc.check(rva)
        if why is None and uses_scalar(sc, rva):
            why = 'SCALAR' if allowed and name in SCALAR_ALLOW else 'scalar arithmetic, not in SCALAR_ALLOW'
            ok += why == 'SCALAR'
        elif why is None:
            why = 'NEUTRAL'
            ok += 1
        if '--why' in args or '--rvas' in args:
            print('%-40s %#8x %s' % (name, rva, why))
    print('# %s: %d of %d neutral' % (os.path.basename(path), ok, len(targets)), file=sys.stderr)


if __name__ == '__main__':
    main()
