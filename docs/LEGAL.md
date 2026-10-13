# Legal and distribution

Pinyon Shift distributes independently authored source, build configuration,
patches, and its launcher. Releases do not distribute the original game,
extracted assets, executable modules, generated translations, or a linked game
binary.

Users must supply a lawfully acquired, personally dumped copy of the exact
supported disc. The build workflow verifies and reads that image locally. It
does not upload, share, modify, bypass verification for, or help locate game
content.

Do not commit or redistribute:

- disc images, executable modules, title updates, keys, or extracted assets;
- generated translation source or object files derived from game executable
  modules; or
- locally linked preview executables or support files containing game data.

## Native replacements of game and library code

Pinyon Shift replaces some of the title's translated code with native code:
`src/guest_native`, hooks, and replacements of the libraries linked into
the game (XDK libraries and middleware such as FMOD Ex). The repository may
hold a replacement only when it is independently authored:

- It implements a contract documented from our own analysis: what the
  function takes, returns and changes in guest state, recorded in
  `site/findings`, and checked by comparing its results with the translated
  original within a stated tolerance.
- Its algorithm is our own or comes from a published source under a
  compatible licence: standard signal-processing filters, codecs, maths, or an
  open-source library listed in `THIRD_PARTY_NOTICES.md`.

The repository must not hold:

- a game or library function rewritten statement by statement from its
  instructions, its disassembly or a decompiler's output. Such a hand
  translation is derived from the executable like the generated source above;
- constant tables, coefficients or other data copied from the executable. A
  replacement that needs them reads them from the player's own files at
  build or run time;
- a middleware product's own algorithms reproduced beyond what its public
  documentation and the published literature define. Middleware is
  replaced at its documented API boundary.

When a replacement must keep the original's exact arithmetic, it is produced
at build time from the player's own executable, for example by a
code-generator option or a specialised translation of that function. It
then stays in the generated tree, which is never committed.

The BSD 3-Clause License applies only to the independently authored material in
this repository. It grants no rights to *Forza Horizon*, Xbox software, ReXGlue,
or any user-supplied content. This document describes the project's distribution
policy and is not legal advice.
