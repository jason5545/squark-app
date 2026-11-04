# fex/highball

FEX for a runtime with `FEX_SERIES=highball`, from
[highball-engine](https://github.com/gauthierpiarrette/highball-engine) `fex/` at `2eedc50`, unchanged:

- `0001` to `0033`, Highball's series for FEX 2610 (`fex/patches/` there, whose README explains each
  one). They pair with Wine's `patches/wine-11.18-fex` 0022 to 0052. MIT, like FEX.
- `fexunixlib_darwin.cpp`, the unix helper FEX's Windows DLLs load from the ntdll.so directory, with
  BSD calls and hardware TSO through `thread_set_x86_64_compat`. It replaces FEX's own
  `Source/Windows/UnixLib` (and `fex/0001-macos-hardware-tso.patch`): `0019` and `0023` add calls
  (`AliasWrite`, `ZeroPages`) that only this helper has. MIT.

With `0018` hardware TSO is on in every thread. Hadron turned it off by default because Ubisoft
Connect deadlocked with it (6bb8d87); Highball runs Microsoft Flight Simulator 2024 with it on.
The switches for programs that rewrite their own code (`HB_FEX_*`) are off unless a game sets them.

## Ours (squark), on top of Highball's series

Measured on squark's `tools/wasm-bench` FBW A380X systems benchmark (Rust to WebAssembly, wasm2c, x64),
the stand-in for the WebAssembly gauges of Microsoft Flight Simulator's add-on aircraft. Highball's
upstream has a `0034` of its own (MAP_JIT backfill), not taken here; ours start at `0035`.

- `0035`: the entry of a block a call returns to stores the block header but skips the suspend check;
  the callee's entry made one. -1% host instructions.
- `0036`: `ExitFunctionEC` keeps the JIT's FPCR for memcpy, memmove and memset of Wine's builtin
  ucrtbase, msvcrt and ntdll (no floating-point arithmetic in their ARM64EC code), saving the two FPCR
  writes of each such call. -5% cycles on the benchmark.
- `0037`: `SQUARK_FEX_ABI_FLAGS=<path piece>;...` treats flags as dead across calls and returns in the
  listed modules (compiler output only, never a protected executable). Off without the variable.
  -3.6% instructions with the benchmark listed.
- `0038`: LEA with a 32-bit destination uses 32-bit adds. -2% instructions.
- `0039`: entry points no longer store the block header (`CPUState::InlineJITBlockHeader`); each code buffer keeps
  its block starts and the fault, suspend and self-modifying-code paths find the block from the host PC. On the TFDi
  MD-11 WebAssembly replay (squark `md11-bench`, x64 build without wasm2c's per-call depth count) -6% cycles per
  frame (9.96M -> 9.37M), A380X -1.7%. `SQUARK_FEX_ENTRY_HEADER=1` brings the store back. squark's
  `tools/fault-test` checks the RIP of faults in entry, return and loop blocks.

Measured on Apple M5 Max: the call/return path of call-dense code is bound by its stores and the memory-ordering
flushes around them, not by instruction count, so 0035-0038 cut instructions without cutting cycles there.

Wine loads FEX from the prefix's `C:\windows\system32\xtajit64.dll`, not from the runtime's
`lib/wine/aarch64-windows`: a prefix made with an older runtime keeps its old FEX until that copy is
replaced.
