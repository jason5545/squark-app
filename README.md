# Squark

Squark runs Microsoft Flight Simulator 2024 from the macOS Steam client on Apple Silicon.
It is a fork of [Hadron](https://github.com/nheisterkamp/Hadron) and the app half of
[squark](https://github.com/jason5545/squark), which holds the investigation notes, tools
and the list of patches. It carries Wine runtimes with Highball's arm64 engine (FEX),
D3D12 through vkd3d-proton and DXVK on KosmicKrisp, and its own Wine and FEX patches:
Wine 11.18 (`runtime/patches/wine-11.18-fex`, the series as Highball made it) and Wine 11.21
(`runtime/patches/wine-11.21-highball`, the same series moved over), with `runtime/fex/highball`.

Squark is not Hadron. Please report problems with Squark in squark, not to Hadron or
NotProton. Hadron is itself a fork of [NotProton](https://github.com/NotProtonNot/NotProton),
and nearly all of the Steam integration is NotProton's work. Squark keeps their licences,
see NOTICE.

Squark took over from a Hadron install on 2026-11-04. Its first start moves Hadron's data
(`~/Library/Application Support/hadron`, `~/Library/Caches/hadron`, the record of modified
Steam bundles and the app's settings) to Squark's names and leaves a link at the old
folder; Install then replaces the hadron.dylib in Steam with squark.dylib. Names nobody
sees stay as Hadron had them: the `HADRON_*` variables, the compatibility tool ids
(`hadron-proton-*`), the marker files in each prefix, the Steam signing identity and the
game launchers' bundle ids, so prefixes, Steam's per-game tool choice and macOS
permissions carry over.

Like Hadron, it follows the Steam client versions NotProton supports. Tuxera NTFS is not
supported, because of a corruption bug in Tuxera's driver.

## How it works

- **Steam Play in macOS Steam.** A dylib injected into the Steam client enables the
  Steam Play support that macOS Steam carries but keeps switched off, and registers
  Squark as a compatibility tool.
- **The Wine runtimes.** Squark downloads them from Hadron's releases, or
  `runtime/build-wine.sh` builds them, with lsteamclient, the steam.exe shim, wine-mono
  and wine-gecko built in. Each is a small definition in `runtime/runtimes`, and each
  shows up in Steam as its own compatibility tool:
  - **Wine 11.15**, the default.
  - **Wine Staging 11.15**, with the wine-staging patch set.
  - **Wine 11.19**, a development release.
  - **Wine 11.21**, the newest development release.
  - **Wine Staging 11.21**, the same with the wine-staging patch set.
  - **CrossOver Wine 26.3**, built from CodeWeavers' published source, the one runtime
    that runs D3DMetal.
  - **Wine 11.19 and 11.21 for Apple Silicon**, native arm64 Wine that runs x86 games
    with [FEX](https://github.com/FEX-Emu/FEX) instead of Rosetta. They need macOS 26.5.

  A game's prefix moves between the Rosetta and Apple Silicon runtimes in place. The
  patches in `runtime/patches` redirect Steam's steamclient to lsteamclient in Wine's
  loader, name the prefix profile `steamuser` like Proton does, let a DLL overlay stand
  in for Wine's own Direct3D, and hand games Steam Input's virtual controller in the
  layout XInput expects. `runtime/patches/wine-11.21-fex` ports arm64 Wine to macOS, and
  `runtime/fex` ports FEX's unix side.
- **Graphics.** Direct3D 10 and 11 go to Metal through
  [DXMT](https://github.com/3Shain/dxmt) by default. Each game's Properties in Steam has a
  Squark panel to pick DXVK 3.1 on KosmicKrisp, DXVK 1.10 on MoltenVK, D3DMetal (with
  CrossOver Wine, once added from Apple's Game Porting Toolkit or CrossOver), or Wine's
  own Direct3D. On Apple Silicon Wine, DXVK 1.10 and Wine's own Direct3D are available.
- **Starting games.** A small window follows each launch: its steps, the game's Windows
  processes and logs, and a warning when nothing happens. It can stop the game and save
  diagnostics.

## Status

Early, but games run. All runtimes boot, reach Steam through lsteamclient for 32 and 64
bit games, make HTTPS connections through schannel, and create Direct3D 11 devices with
every backend they ship. Hadron updates itself through Sparkle; Squark has that off. Not yet done:

- Direct3D 12 outside D3DMetal goes no further than Wine's own vkd3d manages on MoltenVK.
- The Apple Silicon runtime is new and starts heavy programs slowly: Ubisoft Connect takes
  about a minute, against seconds under Rosetta. It is there for when Apple drops
  Rosetta, in macOS 28.

**Valve Anti-Cheat is not supported.** VAC titles launch in Insecure Mode and cannot
matchmake.

## Adding D3DMetal

D3DMetal is Apple's translation of DirectX 11 and 12 to Metal, from the Game Porting
Toolkit. Apple's licence does not let Squark pass it on, so the CrossOver Wine runtime
Squark downloads comes without it. Squark adds it from a copy on your Mac:

1. Get a copy. Either one works:
   - **CrossOver:** install it in Applications. The free trial is enough: Squark copies
     D3DMetal into its runtime, so the copy stays after the trial ends.
   - **Game Porting Toolkit:** sign in at
     [developer.apple.com/download/all](https://developer.apple.com/download/all/) with a
     free Apple developer account, download the Game Porting Toolkit and open its disk
     image.
2. In Squark's Status page, the CrossOver Wine row says whether D3DMetal is added. Click
   **Add D3DMetal from CrossOver** (or from the Game Porting Toolkit). With neither
   installed, **Add D3DMetal…** lets you pick a folder that has it.
3. In Steam, open the game's Properties, go to Squark, and pick D3DMetal. A game set to
   D3DMetal without it added runs with DXMT instead.

## Building

```
brew install mingw-w64 bison flex autoconf cmake ninja
make runtime                  # every runtime in runtime/runtimes
make bridge dobby fonts app
```

`make fonts` also needs FontForge, GNU patch and afdko 4.0. Then open `out/Squark.app`,
add a folder from `out/runtime` with "Add Wine Runtime…" (or put it in
`~/Library/Application Support/squark/runtimes/`), set it up, and install into Steam.

Squark can also download the runtimes. `runtime/release.sh <tag> <runtime>...` packs
staged runtimes into `out/release/<tag>` and writes the manifest the app bundles, with
each archive's SHA-256; `--publish` uploads them as a GitHub release. The archives leave
out D3DMetal, which Apple's licence does not allow passing on: Squark's "Add D3DMetal…"
takes it from the Game Porting Toolkit or CrossOver on the user's Mac. An Apple Silicon
runtime is only packed when its loader is signed with a Developer ID profile, since a
development profile runs on its own devices only.

`app/release.sh` is Hadron's release script and Squark does not use it: Squark has no
releases and Sparkle is off (see `app/Info.plist`), so build it from source. The script it signs the app and all code in it with
Developer ID and the hardened runtime, has it notarized, signs the zip for Sparkle and
adds it to the appcast on the `updates` branch, which Hadron's update checks read.
`--publish` uploads it as GitHub release `app-<version>`. For every release, raise
`HADRON_VERSION` in `dylib/version.h` and write what changed in `CHANGELOG.md`, which
becomes the release notes and the text in Sparkle's update window.

## Source layout

The macOS app is in `app`, and the code injected into Steam is in `dylib`.
`dylib/feats/compat_run.sh` is the compatibility tool's launch script. `lsteamclient` is
a macOS port of Valve's lsteamclient, and `steam-shim` a port of the steam-helper from
Proton 9.0. `runtime` builds the Wine runtime, with its patches and tests.

Please read NOTICE for license information.

## Made with AI

Squark's changes to Hadron were written by Claude in Claude Code, directed and tested by
Jason Chien. What follows is Hadron's own note.

Much of what Hadron adds to NotProton was written by Claude, Anthropic's AI model,
working in Claude Code: the Wine runtime builds and their patches, the macOS port of FEX
for Apple Silicon, and most of the app's newer features, such as runtime downloads, the
launch window and the update channel. Niels Heisterkamp directed that work, reviewed it
and tested it. NotProton's code, which Hadron builds on, is its author's own.

The code has tests, and every runtime is checked before it is released, but it has run on
few machines and games so far. Please report what breaks as an issue.

## Thanks

NotProton's author, for the project this is built on. And, as NotProton's README puts it,
the people who worked on similar ideas before:

[Nat Brown](https://github.com/natbro) made [Kaon](https://github.com/natbro/kaon), which
is similar in goals.

mont127's [Neutron](https://github.com/mont127/Neutron) is also a similar idea, implemented
differently.

[Gio](https://github.com/giodotblue) was working on enabling Steam Play inside of Steam on
macOS before NotProton was released.
