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
- `0064-ntdll-server-msync.patch`: msync, the in-process synchronization of CrossOver on macOS (by
  Marc-Aurel Zent, [marzent/winecx](https://github.com/marzent/winecx) `ff-wine-11.17`, `94044df0` "Add msync.",
  LGPL-2.1-or-later): events, semaphores and mutexes live in memory shared with the wineserver and
  waiting threads sleep on Mach semaphores, so `NtSetEvent`, `NtReleaseSemaphore`, `NtResetEvent` and
  the waits on them no longer go through a wineserver request. It plugs into the in-process sync
  framework Wine 11 has for ntsync (`inproc_sync.c`, the `linux_*_obj` operations in `sync.c`), which
  macOS otherwise lacks. MSFS 2024's main thread wakes its 17 fiber workers through one semaphore, about
  143 times a frame at 39 µs a round trip (squark records 25.71, 25.72). Rebased onto 11.21: 11.21 calls
  `dbg_init()` after `server_init_process()`, so `msync_init()` goes right after `server_init_process( data )`
  (where it was relative to the server in 11.17); the generated `server_protocol.h`, `request_handlers.h`
  and `request_trace.h` come from `tools/make_requests` on 11.21, with `SERVER_PROTOCOL_VERSION` raised
  from 971 to 972 as the original raised it. The rest applies as it is (`sync.c` next to `0061`, `server/thread.c`
  next to `0029`).
- `0065-msync-unregister-early-return.patch`: Highball's `patches/0014` (highball-engine `34bd3b0`, for their
  x64 engine on CrossOver 26.3), unchanged: a multi-object wait that finds an object available while it
  spins takes its registration with the wineserver's msync thread back, and the server unregisters
  objects 0..i-1 whenever i > 0. Without it every lost race left a node on an object's waiter list, the
  node pool ran out and the wineserver grew until the Mac ran out of memory (highball#224). marzent's
  11.17 tree still has the bug.
- Highball's `patches/0005` (yield once after an auto-reset event goes 0 to 1, for a CS:GO map load under
  Rosetta that relied on Windows' boost of the woken thread) is left out: MSFS 2024 has not shown that
  hang, the yield costs every auto-reset `SetEvent`, and its second half changes the wineserver path too,
  so `WINEMSYNC=0` would no longer be the synchronization we had before. Carry it if a program hangs on
  a job hand-off with msync and not without.
- `0066-msync-on-by-default.patch`: msync is on unless `WINEMSYNC=0` (0064 turned it on only with
  `WINEMSYNC=1`). The wineserver and every process of a prefix have to agree; a client that disagrees with
  the running server stops with msync's error ("Server is running with WINEMSYNC but this process is
  not"). `compat_run.sh` passes `WINEMSYNC` to the game by name, so a launch option `WINEMSYNC=0 %command%`
  reaches the game and the Wine the script runs itself (prefix updates, helpers) alike.
- `0067-ntdll-wait-recorder-records-msync.patch`: the wait recorder (`0061`) starts its record before the
  in-process attempt, so with msync the waits, releases and sets are recorded too, flagged
  `WAITLOG_F_INPROC` (0x2000) and without a waker (msync wakes a waiter through a Mach semaphore, not
  through a wineserver request that names the thread). squark's `tools/waitlog/waitlog.py` shows them as
  path `msync`, "waker not recorded". With `WINEMSYNC=0` nothing changes.
- `0068-msync-mutex-release-count-and-abandoned-after-close.patch`: two mutex fixes to msync that Wine's own
  tests found (they failed with msync only). `NtReleaseMutant` reported the recursion count as the previous
  state (2, 1 for a mutex taken twice) where Windows, the wineserver path and ntsync report 1 - count (-1, 0;
  `ntdll_test sync`, sync.c:428 and 433). And a mutex whose handles were all closed while a thread waited on it
  was not abandoned when its owner died, so the waiter timed out instead of getting `WAIT_ABANDONED`
  (`kernel32_test sync`, sync.c:416 and 420): the wineserver only went through the mutexes that still had a
  server object; `msync_abandon_mutexes()` now goes through every mutex in use in the shared memory (thread
  deaths are rare; only allocated pages are read). squark's `tools/msync-test/termwait.exe 5 close`
  reproduces the second (3 of 3 bad before, 0 of 5 after, `WINEMSYNC=0` 0 of 5 both times).
- `0069-msync-wake-one-for-a-release-of-one.patch`: msync wakes one thread, not every thread sleeping on the
  object, for `ReleaseSemaphore(1)`, `SetEvent` on an auto-reset event and `ReleaseMutex`. Every one of them
  used to wake (`ULF_WAKE_ALL`); one took the object and the others went back to sleep, with 17 workers on one
  semaphore 16 wasted wake-ups a job. A release of more than one still wakes all: a wake call costs the
  releasing thread the same for one thread or all, and waking 7 one by one made the main thread's
  `ReleaseSemaphore(7)` in squark's harness `fiber` module 3.7 µs instead of 0.7 µs. Manual-reset events,
  `PulseEvent` and the wineserver's own wakes still wake all. A wake without `ULF_WAKE_ALL` goes to a thread
  still queued; one that timed out or was interrupted (suspend, system APC) is already off the queue, so it
  can't swallow it. The ones that can are wait-all threads, which wait for each object in turn without taking
  it: they now hand the wake on before they sleep on the next object, time out or leave for an APC (without
  that, squark's `tools/msync-test/wakepass.exe` loses about half the releases of its `absorb` part). What a
  wait-all puts back after missing an object (`tooslow`) now wakes one too; it woke nobody before, even with
  `ULF_WAKE_ALL`. `SQUARK_MSYNC_WAKE_ALL=1` wakes all again. Harness, three rounds against 0068: `sync` (one
  release a job) frame 19.75 → 19.1 ms, process CPU 112.4 → 105.4 ms a frame, main thread 12.9 → 11.7 ms;
  `fiber` main thread's releases unchanged (0.29 ms a frame), workers' releases and sets 0.43 → 0.38 ms;
  `sync jobs=1` CPU 34.9 → 32.1 ms a frame. msync's 344–410 µs `dispatch_us` / `job_wake_us` (145 / 14 µs
  through the wineserver) are queueing, not wake-ups: msync lets the main thread release a batch's jobs before
  the workers can start them; with jobs=1 (no queue) a job's wake is 7.7 µs (6.9 with 0068, 8.9 through the
  wineserver). Records 25.73.
- `0070-ntdll-drop-FEX-JIT-FPCR-bits-for-the-unix-side-and-debug-output.patch`: with FEX patch 0043, x64 code
  calls checked native functions without FPCR leaving the JIT's mode (AH, NEP and the trap enables armed from
  MXCSR stay set). What those functions reach that the check does not follow is fenced here:
  `__wine_syscall_dispatcher` drops the bits for the unix side (it already saved FPCR and writes it back on
  return; the mask goes in x13, as x11 holds the user stack for the arguments past the eighth);
  `__wine_unix_call_dispatcher` now saves FPCR in the frame, drops the bits and puts them back after the call;
  `__wine_dbg_header`, `__wine_dbg_strdup`, `__wine_dbg_output` and `enter_syscall_callback` (the ARM64EC
  wrappers that notify the emulator) drop them for the rest of the call. Native code is always fine with the
  native FPCR; FEX writes the JIT's back when the call returns to x64 code. One `mrs` and a branch more
  otherwise. Goes with FEX patch 0043 (squark records 25.77).
