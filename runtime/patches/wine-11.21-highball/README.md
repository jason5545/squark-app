# wine-11.21-highball

Applied after `patches/0001` to `0003` and `0005` (Hadron's Steam integration), in name order, on
WineHQ Wine 11.21. The same series as `wine-11.18-fex`, moved to 11.21 on 2026-11-07; Highball's own arm64
line is still on 11.18. Wine 11.21 brings upstream's bf225d43 (XInput rescans its controllers only when
the WINEXINPUT device interfaces changed in the registry): on 11.18, with one pad connected, every
`XInputGetState` on an empty slot enumerated the devices again, 0.57-0.75 ms a call with 0059's virtual
pad.

What the move changed (each patch below keeps its header; the diff of a rebased one is the patch's
commit on 11.21):

- 37 of the 45 apply to 11.21 as they are and are byte for byte the 11.18 files.
- `0004`, `0038`, `0059`, `0061`: the context around them moved; the lines they add and remove are the
  same.
- `0056`: upstream moved `macdrv_ImeToAsciiEx` from `keyboard.c` to a new `ime.c` (dd51711d), so the
  background-mode check that skips the macOS input method is there now, at the same place in the function.
- `0031` (Highball): upstream renamed `id_WineMetalSwapChain` to `WineMetalSwapChain_id` (2b782cf4), made
  winemac's internal functions return C99 `bool` (fdc2d5eb) and put autorelease pools in the
  WineMetalSwapChain C wrappers (1300ec99); the patch follows all three. Its logic is unchanged.
- `0036` (Highball): upstream made the import of a D3DKMT resource's memory a switch on the host memory
  type with only the fd case (8dd867c0, "Don't assume every D3DKMT resource has an unix fd"). The Metal
  import is now an `if (metal)` branch in front of that switch; it does what it did on 11.18.
- `0045` (Highball): applied as it was, but did not build: upstream ended `map_view_ex`'s search with an
  if/else chain that falls through to `create_view`, without the `done:` label the patch jumped to. The
  search above 4 GB for top-down requests is now the first branch of that chain, in place of the
  `goto done`.

- `0004-arm64-macos-loader.patch`: the two parts of Hadron's `wine-11.21-fex/0004` that Highball's
  series does not cover: the loader's link flags on aarch64 (PAGEZERO of 0x170000000 that it may map
  over with `-x86_64_layout_emulation`, image base 0x170000000 as in Highball's signed loader, built
  for macOS 11 so the kernel keeps x18), and finding `ntdll.so` when the loader is the main executable
  of `Wine.app` in the unix dir. The rest of Hadron's 0004 (reserving the low area, 4K pages, the ID
  registers, writable and executable pages) is in Highball's 0018, 0019, 0023, 0024 and 0025.
- `0018` to `0052`: Highball's arm64 series from
  [highball-engine](https://github.com/gauthierpiarrette/highball-engine) `patches-arm64/` at
  `2eedc50` (made for Wine 11.18), unchanged but for `0031`, `0036` and `0045` above. Its README there
  explains each one. LGPL-2.1-or-later, like Wine. Highball's `0003`
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
- `0057-crypt32-pfx-key-only-to-matching-certificate.patch`: `PFXImportCertStore` gives the private key
  only to the certificate whose public key matches it, as Windows does. Wine gave it to every
  certificate in the PFX, so .NET, which deletes the key container of the certificates of a PFX it does
  not keep, deleted the one container they shared and the kept server certificate lost its key
  (schannel: SEC_E_UNKNOWN_CREDENTIALS). Found with MSFS Map Enhancement's local HTTPS server;
  `tools/tls-server-test` in squark reproduces it.
- `0058-secur32-machine-keyset-server-key.patch`: schannel also looks under HKEY_LOCAL_MACHINE for the
  rsaenh container of a server certificate's CAPI private key, where rsaenh keeps machine key sets
  (.NET's `X509KeyStorageFlags.MachineKeySet`); it looked only under HKEY_CURRENT_USER and refused the
  certificate (SEC_E_INTERNAL_ERROR). Also found with MSFS Map Enhancement; `tools/tls-server-test`
  (`serve <port> filem=<pfx>|<password>`) reproduces it.
- `0059-winebus-sdl-fakepad.patch`: `SQUARK_FAKEPAD=<path>` adds a virtual SDL gamepad, 045e:02fd like a
  Bluetooth Xbox Wireless Controller, driven by text lines written to the FIFO at `<path>` (`ly -32768`,
  `a 1`, `reset`; raw SDL values). It goes through SDL's game controller API and the rest of winebus like
  a real pad, for testing input without a controller and for driving a program with a pad in the
  background. Without the variable, an existing FIFO `$WINEPREFIX/squark-fakepad` turns it on (Steam runs a
  game's install script first, without launch options, and the game reuses that winedevice). squark's
  `tools/padprobe/fakepad.py` sends physical moves; `fakepad-test.py` checks XInput. Needs "Enable SDL",
  which `compat_run.sh` turns on for a runtime that carries SDL.
- `0060-winemac-onmainthread-on-main-thread.patch`: `OnMainThread` runs the block directly when called on
  the main thread. `-[WineContentView viewWillDraw]` updates pending GL contexts on the main thread, and
  `macdrv_update_opengl_context` then called `OnMainThread`, which queued the block and waited for the main
  thread itself: the process hung. Found with the TFDi MD-11 Install Manager (WPF, d3d9 through wined3d's
  OpenGL), which froze when a tooltip popup closed. Wine master still has the same code.
- `0061-ntdll-wait-recorder.patch`: a wait recorder that is switched on while the program runs. Off unless
  the folder `$WINEPREFIX/squark-waitlog` (or `$SQUARK_WAITLOG_DIR`) exists when a process starts; then
  `dlls/ntdll/unix/waitlog.c` starts a thread that sleeps in kqueue on that folder. Writing a file `ctl` there
  (atomically: write `ctl.tmp`, rename) starts one window in each process whose image name matches:

  ```
  id=<new name each time>   exe=FlightSimulator2024.exe (or *)   seconds=10   warmup=0.5
  events=2000000            yieldgap_us=100                      out=<unix folder, default the control folder>
  ```

  The events go to a buffer allocated before the window (40 bytes each) and are written after it by that
  thread: `<out>/waitlog-<id>-<exe>-<pid>.events` and `.json` (written last: Windows thread ids with Mach port
  names, Mach thread ids and CPU times at both ends of the window, thread names, object types). Recorded:
  server waits (NtWaitForSingleObject, NtWaitForMultipleObjects including win32u's message waits,
  NtSignalAndWaitForSingleObject, keyed events, I/O completion, alertable sleeps) with the thread whose
  wineserver request woke them, which the wineserver now puts in the unused `__pad` of `wake_up_reply`
  (bit 31 set; bits 21-30 request code + 1, 0 for a timeout, timer or fd; bits 0-20 thread id / 4);
  NtSetEvent, NtPulseEvent, NtReleaseSemaphore, NtReleaseMutant; NtWaitForAlertByThreadId (critical
  sections, SRW locks, condition variables, barriers, WaitOnAddress) with the thread that alerted it —
  RtlWaitOnAddress passes the address with what it waits for in the top byte (1 WaitOnAddress, 2 critical
  section, 3/4 SRW exclusive/shared, 5 condition variable, 6 barrier); Sleep; runs of yields. While off, each
  of these costs one load and a branch, no system call. Not recorded: waits begun before the window's
  recording started (the warmup keeps them out of the window), waits outside ntdll (Vulkan driver, Cocoa).
  squark's `tools/waitlog/waitlog.py` turns a recording into tables; `tools/waitlog-test/` has the test
  program with known answers.
- `0062-ntdll-threadpool-timer-queue-waits-forever-without-relative-timers.patch`: the thread pool's timer
  queue thread (`wine_threadpool_timerqueue`) waits forever on its relative NT timer when no relative timer
  is pending. `update_timers` armed it with `rel_now - MAXLONGLONG`; the wineserver's `timeout - monotonic_time`
  (`timeout_to_abstime`) overflows on that, and our clang/arm64 wineserver then files the wrapped, positive
  value in its relative list, where `get_next_timeout` finds it expired at once. The thread spun as long as
  the process had a thread pool timer object but no relative timer pending (an unset timer, a one-shot that
  ran, only absolute due times): MSFS 2024 227,384 waits in 10 s, a third of a core plus the wineserver's
  share. squark's `tools/tptimer-test/` reproduces it (idle timer: 144,000-164,000 waits in 4 s and 44-46%
  of a core in the wineserver before, none after); periodic timers fire the same, and Wine's
  `ntdll_test threadpool` no longer fails "expected that timers are merged" (threadpool.c:1625: absolute
  timers with a window length now merge as designed). Wine master still has the same code (since f6c53a24).
- `0063-ntdll-tptimer-debug-channel.patch`: `WINEDEBUG=+tptimer` (off by default) logs thread pool timers as
  the program sets them: TpAllocTimer with the module its callback is in, tp_set_timer with the due time
  (relative ms, absolute as ms from now, 0, NULL to cancel), period and window, TpReleaseTimer; and once a
  second the timer queue thread's rounds (which NT timer woke it, rounds with no relative timer pending,
  callbacks submitted, timer objects, pending timers). No summary line means the thread did not wake.
