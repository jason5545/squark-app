# gstreamer

GStreamer for a runtime with `GSTREAMER=yes`, so Wine's winegstreamer plays the videos games open
through Media Foundation and DirectShow (without it Microsoft Flight Simulator 2024's start screen
stays black). `build-wine.sh` takes the official macOS packages, installs nothing, and stages the
framework as `lib/GStreamer.framework`, where winegstreamer's rpath looks.

`unpkg.py` and `prune.py` come from [highball-engine](https://github.com/gauthierpiarrette/highball-engine)
`gstreamer/` at `2eedc50`, unchanged (LGPL-2.1-or-later). `unpkg.py` unpacks one component of a package
expanded with `pkgutil --expand`; `prune.py` keeps the plugins winegstreamer can use for games and the
libraries they link, thinned to arm64.
