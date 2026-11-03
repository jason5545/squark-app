# wine-11.18-fex

Applied after `patches/0001` to `0003` and `0005` (Hadron's Steam integration), in name order, on
WineHQ Wine 11.18.

- `0004-arm64-macos-loader.patch`: the two parts of Hadron's `wine-11.21-fex/0004` that Highball's
  series does not cover: the loader's link flags on aarch64 (PAGEZERO of 0x170000000 that it may map
  over with `-x86_64_layout_emulation`, image base 0x170000000 as in Highball's signed loader, built
  for macOS 11 so the kernel keeps x18), and finding `ntdll.so` when the loader is the main executable
  of `Wine.app` in the unix dir. The rest of Hadron's 0004 (reserving the low area, 4K pages, the ID
  registers, writable and executable pages) is in Highball's 0018, 0019, 0023, 0024 and 0025.
- `0018` to `0052`: Highball's arm64 series, unchanged, from
  [highball-engine](https://github.com/gauthierpiarrette/highball-engine) `patches-arm64/` at
  `2eedc50`. Its README there explains each one. LGPL-2.1-or-later, like Wine. Highball's `0003`
  (`WINEDLLPATH_PREPEND`) is left out: Hadron's `0003` (`HADRON_DLL_OVERLAY`) does the same.
- `0053-unixlib-host-libraries-from-cplusplus.patch`: casts `malloc`'s result in Highball 0030's
  `dlopen_host_lib`, so `include/wine/unixlib.h` also compiles as C++ (lsteamclient's unix side).
- `0054-ntdll-user-name-from-hadron-wine-user.patch`: `HADRON_WINE_USER` names the Windows user in
  place of `steamuser`. Wine's DPAPI mixes the user name into its keys, so a prefix NotProton set
  up under CrossOver, which ran as `crossover`, has to keep that name for what its programs
  protected there (Xbox sign-in tokens) to open; `compat_run.sh` sets it for such a prefix.
- `0055-win32u-vulkan-host-sharing-hides-external-memory-win32.patch`: `HADRON_VK_HOST_SHARING=1` hides
  `VK_KHR_external_memory_win32` (which Highball's 0036 exposes through Metal objects) from the
  program, so the steamac DXVK and vkd3d-proton share textures through host memory on KosmicKrisp,
  the path they were validated on. `compat_run.sh` sets it for those graphics layers.
- `0056-winemac-background-mode.patch`: `HADRON_MAC_BACKGROUND=1` keeps the program off the screen
  for automated runs on a Mac someone else is using: it never activates itself or unhides, its
  windows sit under the desktop picture (still on screen, so they draw and `screencapture -l` works)
  and ignore the mouse, and it leaves the host cursor and display modes alone. Input comes from inside
  Wine (SendHardwareInput), without the macOS input method (it would swallow keys of a program that is
  never the active app). `compat_run.sh` sets it for one launch when asked to (see there).
