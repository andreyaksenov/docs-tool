# docs_tool.py

A single Python utility for checking that the `en/` and `ru/` documentation trees stay in sync, and for syncing a RU page's structure after an EN edit.
Run it from the root of the Antora docs repo you want to check.

Works on both single-module Antora sites (just `en/modules/ROOT`) and multi-module ones (`en/modules/ROOT`, `en/modules/how-to`, ...).
Every module under `en/modules/` and `ru/modules/` is auto-discovered, and every check scans all of them automatically.
Run `./docs_tool.py list modules` to see what was found.

## Prerequisites

- Python 3.7+ — no third-party dependencies, nothing else to install.
- `git` on `PATH` — only needed for `sync`, which shells out to it to detect reworded lines.
- `argcomplete` (optional) — only for [tab completion](#tab-completion-optional); the tool works exactly the same without it.

## Get it

It's a single self-contained file.
Copy it into any Antora docs repo without cloning this repo:

```bash
curl -O https://raw.githubusercontent.com/andreyaksenov/docs-tool/main/docs_tool.py && chmod +x docs_tool.py
```

Run it with an explicit path from the repo root:

```bash
./docs_tool.py check <family>
# or
python3 docs_tool.py check <family>
```

### Windows

Windows doesn't have an executable bit, so skip the `chmod` step and run the file with `python` (the Windows installer doesn't provide a `python3` command) or the `py` launcher instead of `./docs_tool.py`:

```powershell
Invoke-WebRequest -Uri https://raw.githubusercontent.com/andreyaksenov/docs-tool/main/docs_tool.py -OutFile docs_tool.py
python docs_tool.py check <family>
```

## Tab completion (optional)

`docs_tool.py` supports shell tab completion for every flag.
This is optional; the tool works exactly the same without it.

- macOS (zsh) and most Linux distros with `pip` available:

  ```bash
  pip install --user argcomplete   # one-time, not required to run the tool itself
  ```

  Add this to `~/.zshrc` (or `~/.bashrc`), then open a new shell (or `source` it):

  ```bash
  eval "$(python3 -m argcomplete.scripts.register_python_argcomplete docs_tool.py)"
  ```

- Ubuntu/Debian (including WSL) ship a system package instead, since `pip install` is blocked outside a virtualenv by default:

  ```bash
  sudo apt install python3-argcomplete   # one-time, not required to run the tool itself
  ```

  Add this to `~/.bashrc`, then open a new shell (or `source` it):

  ```bash
  eval "$(register-python-argcomplete docs_tool.py)"
  ```

Either way, `./docs_tool.py <TAB>` completes the subcommands and, within `check`, the families and their flags (the legacy `--check-<TAB>` form still completes too).
`--page` and `sync`'s file argument also complete with real filenames and directories from the current site, e.g. `--page reference/gp_toolkit/gp_ao<TAB>`.

## Usage

Run `./docs_tool.py` from the repo root, followed by one of:

```
check <family|all> [--<subcheck> ...] [--in <target>] [--lang en|ru] [-v]
                   [--page NAME ...] [--glossary PATH ...]
                   [--external-root NAME=PATH ...]

check --profile <name> [--page NAME ...]

sync <path/to/en/file.adoc> [-n] [--since REF]

list [families|checks|modules]

explain <subcheck|rule-id>
```

`./docs_tool.py` with no arguments (or `--help`) prints this whole surface.

Checks are grouped into six **families**, ordered by where a rule's authority comes from (see [`docs/proposals/cli-redesign.md`](docs/proposals/cli-redesign.md)):

| Family | Level | What it covers |
|--------|-------|----------------|
| `chars`  | encoding    | invisible chars, unicode dashes, RU/Latin homoglyphs, Cyrillic in EN files |
| `markup` | AsciiDoc    | stray backticks, unbalanced block delimiters |
| `refs`   | Antora      | broken `xref:`/`include:`/`image:` targets, orphaned pages/partials/examples/images/tag regions |
| `style`  | house style | `ё`/`Ё`, un-italicized file paths, table-cell periods |
| `terms`  | glossary    | EN term translated to a non-house-style RU word |
| `l10n`   | EN↔RU       | line-count / structure / nav parity, untranslated lines, `examples/` byte parity |

```bash
./docs_tool.py check style                  # every style check
./docs_tool.py check style --no-yo          # just one
./docs_tool.py check markup --lang ru       # both-tree checks, RU only
./docs_tool.py check refs                   # broken-refs + every orphan check
./docs_tool.py check all

./docs_tool.py check chars --no-cyrillic --in examples
./docs_tool.py check l10n --structure -v --page resource_groups.adoc

./docs_tool.py list families                # the map: subchecks, IDs, legacy keys
./docs_tool.py explain table-cell-periods   # a check's rationale and exceptions
```

Selection rules: `check <family>` runs the whole family across every scan target; adding `--<subcheck>` narrows to one check (target `pages` by default); `--in <target>` picks a different target (`pages`, `partials`, `examples`, `images`, `tags`, `nav`, or `all`). `refs` always scans the whole site regardless of `--page`.

`--lang en|ru` restricts the checks that scan both trees (`chars`, `markup`) to one language; inherently single- or bi-lingual checks ignore it.

Every check has a stable **rule ID** (`CH01`, `MK02`, `RF03`, `ST01`, `TM01`, `LN02`, …) shown by `list` and accepted by `explain`.

### Config file — `.docs_tool.ini`

The nearest `.docs_tool.ini` from the current directory up to the git root is read automatically (INI, via stdlib `configparser`). CLI flags always win over it.

```ini
[docs_tool]
glossary = greengagedb-glossary.psv
external_root =
    ADB=../docs-adb
    ADH=../docs-adh

[profile:pre-commit]
block = chars, markup
warn  = style, terms, l10n, refs
scope = uncommitted
```

- `[docs_tool] glossary` / `external_root` — defaults for `--glossary` / `--external-root` (comma- or newline-separated).
- `[profile:NAME]` — adds or overrides a `check --profile NAME` set. `block`/`warn` are family lists; `scope = uncommitted` makes the profile imply `--page UNCOMMITTED` when no `--page` is given. The built-in `pre-commit` profile blocks `chars` + `markup` and warns on the rest (scan everything unless you pass `--page`).

<details>
<summary><b>Legacy <code>--check-*</code> flags</b> (still supported)</summary>

The pre-subcommand form is unchanged — `main()` routes `check`/`sync`/`list`/`explain` to the new surface and everything else to the legacy parser:

```
--check-<name> [--check-<name> ...] [-v]
               [--page NAME ...] [--glossary PATH ...]
               [--external-root NAME=PATH ...]

--all-checks [-v]
--sync <path/to/en/file.adoc> [-n] [--since REF]
--list-checks
--list-modules
```

The full set of `--check-*` flags (the [migration map](docs/proposals/cli-redesign.md#4-full-migration-map) gives the `check <family>` equivalent of each):

```
--check-examples-no-cyrillic
--check-examples-orphaned
--check-examples-parity
--check-images-orphaned
--check-nav-structure-parity
--check-pages-broken-refs
--check-pages-file-path-italics (beta)
--check-pages-line-parity
--check-pages-no-cyrillic
--check-pages-no-invisible-chars
--check-pages-no-unicode-dashes
--check-pages-no-yo
--check-pages-orphaned
--check-pages-ru-latin-homoglyphs (beta)
--check-pages-stray-backticks
--check-pages-structure-parity (beta)
--check-pages-table-cell-periods (beta)
--check-pages-terminology (beta)
--check-pages-translation (beta)
--check-pages-unbalanced-delimiters
--check-partials-orphaned
--check-tags-orphaned
```

`(beta)` checks are heuristic rather than a real AsciiDoc parser and can misfire on legitimate content — see their entries under [Checks](#checks) and treat their output as a review list, not a hard gate.

Multiple `--check-*` flags can be combined in one run.
Exits `0` if every selected check passed, `1` if any check found something.

</details>

### Scoping to specific pages with `--page`

By default, every check scans the whole site.
Pass `--page NAME` (repeatable) to limit the per-file checks in the `chars`, `markup`, `style`, `terms`, and `l10n` families to just the page(s)/partial(s) whose filename matches `NAME`, e.g.:

```bash
./docs_tool.py check l10n --untranslated -v --page resource_groups.adoc
```

`NAME` must end with `.adoc` — AsciiDoc/Antora has no separate topic-id distinct from the filename, so unlike some other doc systems there's no shorter identifier to accept; matching is by the path relative to `pages`/`partials` (never the module itself), so the same name in two different modules is scoped together.
If a bare filename matches more than one file (e.g. the same name under two different directories), qualify it with as much of the trailing directory path as needed to disambiguate, e.g. `--page reference/gp_toolkit/gp_ao.adoc` or just `--page gp_toolkit/gp_ao.adoc`.

A `NAME` that *doesn't* end with `.adoc` scopes a whole directory instead, recursively, e.g. `--page reference/sql_commands` matches every page/partial under any module's `pages/reference/sql_commands/` or `partials/reference/sql_commands/` (and any subdirectory below it) — matched by the path relative to `pages`/`partials`, so again the same directory in different modules is scoped together.
File and directory forms can be mixed across repeated `--page` flags:

```bash
./docs_tool.py check l10n --untranslated -v --page reference/sql_commands
```

`check refs --orphaned --in tags` and `check refs --orphaned --in partials` also honor `--page`, but only to narrow *which files get reported on* — the usage scan (which file includes what) still covers the whole site regardless, since a tag or whole-file partial defined in the filtered-in file can be pulled in from any other page:

```bash
./docs_tool.py check refs --orphaned --in tags --page external_data_formats.adoc
```

The rest of the `refs` family (`--broken`, and orphan checks for pages / examples / images) builds a site-wide corpus (nav links, partial includers) before reporting, so `--page` doesn't narrow it at all — it always scans and reports on everything regardless.

Pass the special value `--page UNCOMMITTED` instead of a name to scope to whatever `.adoc` files currently have uncommitted changes — staged, unstaged, or untracked — per `git status`.
If nothing's uncommitted, the check prints `OK: no uncommitted .adoc changes to check.` and exits `0` immediately.
This is what the [pre-commit hook](#pre-commit-hook) below uses, so a commit only gets checked against what it's actually touching instead of the whole site.

## Checks

Checks are grouped into six **families** — `chars`, `markup`, `refs`, `style`, `terms`, `l10n` — ordered by where a rule's authority comes from (see [`docs/proposals/cli-redesign.md`](docs/proposals/cli-redesign.md)).
Run a whole family (`./docs_tool.py check chars`) or one check (`./docs_tool.py check chars --dashes`).
`--in <target>` (default `pages`, which covers `pages/` + `partials/`; also `partials`, `examples`, `images`, `tags`, `nav`, or `all`) picks the scan target for a check that has more than one.

Every check runs across all discovered modules automatically (`./docs_tool.py list modules`), even though the descriptions below say "EN"/"RU" for brevity.
Every check has a stable rule ID (shown below and by `./docs_tool.py list families`); `./docs_tool.py explain <subcheck>` prints one check's full rationale, exceptions, and the false positives it was tuned against — the same text lives in that `check_*` function's docstring in `docs_tool.py`.

### `chars` — Unicode / encoding

- **`check chars --no-cyrillic`** · `CH01` (`--in examples` → `CH02`)  
  No `.adoc` file under `en/modules/` may contain Cyrillic characters (catches RU text left in an EN file).
  `--in examples` runs the same check over each module's `examples/` (all file types).

  ```bash
  ./docs_tool.py check chars --no-cyrillic
  ./docs_tool.py check chars --no-cyrillic --in examples
  ./docs_tool.py check chars --no-cyrillic --page resource_groups.adoc
  ```

- **`check chars --no-invisible`** · `CH03`  
  No `pages/`/`partials/` `.adoc` file may contain zero-width or other invisible/formatting Unicode characters.
  `-v` also prints each hit line with the invisible character swapped for a visible `⟦U+XXXX⟧` marker.

  ```bash
  ./docs_tool.py check chars --no-invisible -v
  ```

- **`check chars --dashes`** · `CH04`  
  No `pages/`/`partials/` `.adoc` file may contain a literal en dash (`–`) or em dash (`—`); house style uses `--` instead.

  ```bash
  ./docs_tool.py check chars --dashes
  ./docs_tool.py check chars --dashes --lang ru        # RU tree only
  ```

- **`check chars --homoglyphs`** · `CH05` · beta  
  Flags Latin letters in `ru/` prose that look like they were meant to be Cyrillic: a word mixing both scripts, or a standalone Latin letter matching one of four Cyrillic/Latin homoglyph pairs that double as real one-letter Russian words (`а`/`о`/`с`/`у`).
  Found dozens of real typos across every repo tested during development. `-v` prints the full line for each hit.

  ```bash
  ./docs_tool.py check chars --homoglyphs -v
  ./docs_tool.py check chars --homoglyphs -v --page resource_groups.adoc
  ```

`--lang en|ru` restricts `--no-invisible` and `--dashes` (the checks that scan both trees) to one language; `--no-cyrillic` (EN-only) and `--homoglyphs` (RU-only) ignore it.

### `markup` — AsciiDoc spec

Both `--lang`-aware.

- **`check markup --backticks`** · `MK01`  
  No `pages/`/`partials/` `.adoc` line may have an odd number of backticks (almost always a missing or stray `` ` `` around an inline monospace span).

  ```bash
  ./docs_tool.py check markup --backticks
  ./docs_tool.py check markup --backticks --page resource_groups.adoc
  ```

- **`check markup --delimiters`** · `MK02`  
  Every AsciiDoc block delimiter (open `--`, listing `----`, literal `....`, example `====`, sidebar `****`, quote `____`, passthrough `++++`, table `|===`, comment `////`) must be properly closed once a page's full include chain is flattened into the single document Asciidoctor actually renders.
  An unclosed one is almost always a forgotten closing delimiter, which silently swallows everything after it once rendered.

  ```bash
  ./docs_tool.py check markup --delimiters
  ./docs_tool.py check markup --delimiters --page resource_groups.adoc
  ```

### `refs` — Antora reference resolution

Always scans the whole site: `--page` narrows only *which files are reported* for the `--in tags` / `--in partials` orphan checks, never the usage scan; `--broken` and the pages/examples/images orphan checks ignore `--page` entirely.
`check refs` with no subcheck runs `--broken` plus every orphan target.

- **`check refs --broken`** · `RF01`  
  Every `xref:`, `include::`, `image:`/`image::`, `injectSvg:`/`injectSvg::`, `inlineSVG:`/`inlineSVG::`, and `link:`/`link::` reference in `pages/`/`partials/` must resolve to a real file or anchor.
  Cross-module references resolve against sibling modules automatically.
  A reference into a component outside this repo (e.g. a separate ADCM docs repo) is left unchecked unless you pass `--external-root NAME=PATH` (repeatable, or `[docs_tool] external_root` in `.docs_tool.ini`) to resolve against a local checkout of it:

  ```bash
  ./docs_tool.py check refs --broken
  ./docs_tool.py check refs --broken --external-root ADCM=../docs-adcm
  ```

  Run from docs-adb, the second form is what actually resolves `xref:ADCM:ROOT:some-page.adoc[]`/`include::ADCM:ROOT:partial$...[]`-style references written in docs-adb's own content that point at ADCM's repo — without it they're silently left unchecked, not reported broken, since the tool can't tell a genuine typo apart from a real cross-repo reference it just hasn't been shown the target for.

- **`check refs --orphaned`** · `RF02`–`RF06`  
  Nothing under `pages/`, `partials/`, `examples/`, `images/`, or any `tag::`/`end::` region is defined but never used. `check refs --orphaned` runs all five; `--in <target>` picks one:

  | `--in` | ID | Rule |
  |--------|----|------|
  | `pages`    | `RF02` | every `pages/*.adoc` reachable from some `nav.adoc` (nav's own `include::partial$...[]` and cross-module links counted); the site's `start_page` is exempt |
  | `partials` | `RF03` | every tag-less `partials/` file pulled in whole by a plain/wildcarded `include::...[]` |
  | `examples` | `RF04` | every `examples/` file pulled in by an `include::example$<path>[]` in `pages/`/`partials/` |
  | `images`   | `RF05` | every `images/` file the resolved target of an `image:`/`injectSvg:`/`inlineSVG:` macro, site-wide; ends with a total count and combined size |
  | `tags`     | `RF06` | every `tag::NAME[]`/`end::NAME[]` region pulled in by some `include::...[tag=NAME]`, directly, via nesting, or via a whole-file include |

  ```bash
  ./docs_tool.py check refs --orphaned                 # all five targets
  ./docs_tool.py check refs --orphaned --in tags --page external_data_formats.adoc
  ```

  For `--in partials` and `--in tags`, pass `--external-root NAME=PATH` (repeatable) to recognize a partial or tag that's only ever consumed from a sibling Antora component's repo — e.g. run from docs-adcm, whose own `et`/`monitoring` partials render only inside docs-adb/docs-adh/docs-adpg/docs-adqm's install docs, not from anything in docs-adcm itself:

  ```bash
  ./docs_tool.py check refs --orphaned --in partials \
    --external-root ADB=../docs-adb --external-root ADH=../docs-adh \
    --external-root ADPG=../docs-adpg --external-root ADQM=../docs-adqm
  ```

  Without registering the consuming repos, the tool has no way to see those includes (they live in the *other* repos' own files) and reports the partials/tags orphaned even though they render fine on the real site.

### `style` — Arenadata style guide

Heuristic family — treat findings as a review list, not a hard gate.

- **`check style --no-yo`** · `ST01`  
  No `ru/` `pages/`/`partials/` `.adoc` file may contain `ё`/`Ё`; house style spells it out as `е` instead.
  The `:page-author:` attribute is exempt, since a real person's name can legitimately contain `ё`.

  ```bash
  ./docs_tool.py check style --no-yo
  ./docs_tool.py check style --no-yo --page resource_groups.adoc
  ```

- **`check style --file-path-italics`** · `ST02` · beta  
  Flags file/directory names mentioned in plain prose without the italics (`_..._`) house style requires: known config/archive file extensions, well-known absolute-path prefixes, bare directory basenames, underscore/slash-containing words, and common dotfiles, all checked in the relevant `a`/`an`/`the ... file/folder/...` grammatical slot.
  Deliberately narrow to keep false positives low. `-v` prints the full line for each hit.

  ```bash
  ./docs_tool.py check style --file-path-italics -v
  ./docs_tool.py check style --file-path-italics -v --page resource_groups.adoc
  ```

- **`check style --table-cell-periods`** · `ST03` · beta  
  The last sentence in a table cell shouldn't end with a period, per house style, with exceptions for cells ending in a list, an admonition, or a known abbreviation.

  ```bash
  ./docs_tool.py check style --table-cell-periods
  ./docs_tool.py check style --table-cell-periods --page resource_groups.adoc
  ```

### `terms` — controlled vocabulary

- **`check terms`** · `TM01` · beta  
  Flags an EN glossary term whose aligned RU line matches its `ru_pattern` alternatives fewer times than the term occurs on the EN line — a translator drifting onto an inconsistent or outdated Russian word for something the glossary already has a house-style answer for, including a line that uses the term (or several glossary terms) more than once and only translated some of the mentions.
  The repeat comparison can misfire where Russian legitimately avoids repeating a noun (pronoun, ellipsis) — treat it as a review list. `-v` prints the full EN/RU line pair for each hit.

  Needs a glossary: `--glossary PATH` (repeatable; pipe-delimited `en|ru|ru_pattern|note`, format documented in a `*-glossary.psv` file's own header), or `[docs_tool] glossary` in `.docs_tool.ini`, or — failing both — every `*-glossary.psv` found directly under the current directory (a note is printed to stderr when this default kicks in).

  ```bash
  ./docs_tool.py check terms -v
  ./docs_tool.py check terms -v --glossary greengagedb-glossary.psv --page resource_groups.adoc
  ```

### `l10n` — EN↔RU parity

- **`check l10n --lines`** · `LN01`  
  Every EN `pages/`/`partials/` `.adoc` file must have a RU counterpart with the same line count, and vice versa.

  ```bash
  ./docs_tool.py check l10n --lines
  ./docs_tool.py check l10n --lines --page resource_groups.adoc
  ```

- **`check l10n --structure`** · `LN02` · beta  
  Deeper structural comparison of each EN/RU `.adoc` pair (heading levels, block titles, delimited blocks, block attributes, `include::` directives), catching drift even when line counts match.
  Reports the first differing line by default; `-v` shows the full diff with file:line references.

  ```bash
  ./docs_tool.py check l10n --structure -v
  ./docs_tool.py check l10n --structure -v --page resource_groups.adoc
  ```

- **`check l10n --untranslated`** · `LN03` · beta  
  Flags `pages/`/`partials/` lines that look untranslated: RU byte-identical to its EN counterpart, skipping code, attributes, comments, table cells, and keyword-only lines.
  `-v` also flags RU lines containing common English stopwords.

  ```bash
  ./docs_tool.py check l10n --untranslated -v
  ./docs_tool.py check l10n --untranslated -v --page resource_groups.adoc
  ```

- **`check l10n --examples`** · `LN04`  
  Each module's EN and RU `examples/` must have the same files; non-`.sql` files must match byte-for-byte, `.sql` files once comment-only lines are blanked out (comments are legitimately translated).
  `-v` shows a diff for mismatched non-`.sql` files. Whole-site — ignores `--page`.

  ```bash
  ./docs_tool.py check l10n --examples -v
  ```

- **`check l10n --nav`** · `LN05`  
  Compares each module's `nav.adoc` structure (list depth, `xref:`/`include::` targets) between EN and RU, plus any included `partial$...adoc` files. Translated labels are ignored; modules without their own `nav.adoc` are skipped.
  Reports the first differing line by default; `-v` shows the full diff. Whole-site — ignores `--page`.

  ```bash
  ./docs_tool.py check l10n --nav -v
  ```

## Sync a RU page after an EN edit (beta)

Heuristic aligner, not a semantic merge — review its output before trusting it; see the caveat below.

```bash
./docs_tool.py sync en/modules/ROOT/pages/reference/utils/analyzedb.adoc

# same file, by bare filename; -n = dry run (print the diff, don't write)
./docs_tool.py sync analyzedb.adoc -n
```

`sync`'s argument works the same way `--page NAME` does: it must end with `.adoc`, and can be either the full relative path or just the bare filename — resolved by searching all discovered modules' `pages`/`partials`, same lookup `--page` uses.
If a filename matches more than one file (e.g. the same name under two different directories), qualify it with trailing directory path segments to disambiguate, same as `--page`, or pass the full path.

Only ever writes the RU counterpart; never touches EN.

- Aligns RU's structure to EN's: headings, anchors, delimited blocks, option/flag terms, code lines.
- Copies in new or changed EN lines verbatim (left untranslated) wherever RU has nothing corresponding yet.
  Run `check l10n --untranslated` afterward to find them.
- Existing RU prose is never rewritten or removed.
- Only technical tokens that must be byte-identical across languages are corrected when they've drifted (e.g. a stale `plpythonu` left behind after EN moved to `plpython3u`): flag names, code/command lines, include paths, ids, file/directory names.

This is a heuristic aligner, not a semantic merge: when an EN paragraph is reworded (not just extended), the new wording is appended after the existing translation rather than replacing it.
Review and reconcile those cases by hand.

## Pre-commit hook

Runs a subset of the checks above automatically before every `git commit`.

With the new surface this is a two-liner, using the built-in `pre-commit` profile (`chars` + `markup` block the commit; `style`, `terms`, `l10n`, `refs` warn only):

```bash
#!/usr/bin/env bash
cd "$(git rev-parse --show-toplevel)"
python3 docs_tool.py check --profile pre-commit --page UNCOMMITTED
[ $? -ge 2 ] && { echo "pre-commit: blocking check(s) failed -- commit aborted." >&2; exit 1; }
exit 0
```

Exit `2` = a blocking-family finding, `1` = warn-only, `0` = clean.

<details>
<summary>Equivalent hook using the legacy <code>--check-*</code> flags</summary>

Create `.git/hooks/pre-commit` in your local checkout with:

```bash
#!/usr/bin/env bash
# docs_tool.py pre-commit checks.
cd "$(git rev-parse --show-toplevel)"

blocking_failed=0

echo "=== blocking checks ==="
python3 docs_tool.py --page UNCOMMITTED \
  --check-pages-no-cyrillic \
  --check-pages-no-invisible-chars \
  --check-pages-no-unicode-dashes \
  --check-pages-no-yo \
  --check-pages-stray-backticks \
  --check-pages-unbalanced-delimiters || blocking_failed=1

echo
echo "=== warn-only checks (do not block commit) ==="
python3 docs_tool.py --page UNCOMMITTED \
  --check-pages-ru-latin-homoglyphs \
  --check-pages-table-cell-periods \
  --check-pages-file-path-italics \
  --check-pages-translation \
  --check-pages-structure-parity \
  --check-examples-no-cyrillic \
  --check-examples-orphaned \
  --check-examples-parity \
  --check-images-orphaned \
  --check-nav-structure-parity \
  --check-pages-broken-refs \
  --check-pages-line-parity \
  --check-pages-orphaned \
  --check-partials-orphaned \
  --check-tags-orphaned || true

if [ "$blocking_failed" -ne 0 ]; then
  echo
  echo "pre-commit: blocking docs_tool.py check(s) failed -- commit aborted." >&2
  exit 1
fi

exit 0
```

Then make it executable:

```bash
chmod +x .git/hooks/pre-commit
```

Only `--check-pages-no-cyrillic`, `--check-pages-no-invisible-chars`, `--check-pages-no-unicode-dashes`, `--check-pages-no-yo`, `--check-pages-stray-backticks`, and `--check-pages-unbalanced-delimiters` actually block the commit; the rest just print their findings.
The `(beta)` checks in the warn-only block (`pages-ru-latin-homoglyphs`, `pages-table-cell-periods`, `pages-file-path-italics`, `pages-translation`, `pages-structure-parity`) stay warn-only deliberately: each has a documented, non-zero false-positive rate, so hard-blocking on them would occasionally stop a legitimate commit over a heuristic miss.
Move one into the blocking block once it's run clean for a while in practice.
`pages-terminology` isn't included at all, deliberately: it requires `--glossary PATH` (or an auto-discovered `*-glossary.psv`), which most repos using this tool don't have.
A repo that does carry a glossary can add `--check-pages-terminology` to its own copy of this hook.
`--page UNCOMMITTED` (see [above](#scoping-to-specific-pages-with---page)) scopes every check here to just the `.adoc` files the commit is actually touching; the whole-site checks (`pages-broken-refs`, `pages-orphaned`, `examples-*`, `images-orphaned`, `nav-structure-parity`) ignore it and keep scanning everything, same as any other run.
`tags-orphaned` and `partials-orphaned` are in between: each only reports on regions/files defined in the touched files, but its usage scan still covers the whole site regardless.

</details>

## Running the tests

```bash
python3 -m unittest discover -s tests
```

`tests/test_docs_tool.py` (stdlib `unittest`, no extra dependencies) covers the trickier pure-parsing functions directly, plus fixture-based integration tests that build a throwaway Antora tree per test and run a `check_*()` function against it.
Does not touch this repo's real `en/`/`ru/` content.
