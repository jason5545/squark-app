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
