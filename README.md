# docs_tool.py

A single Python utility for checking that the `en/` and `ru/` documentation trees stay in sync, and for syncing a RU page's structure after an EN edit.
Run it from the root of the Antora docs repo you want to check.
Requires Python 3.7+ (no third-party dependencies) — nothing to install. (Tab completion is opt-in and needs the `argcomplete` package — see [Tab completion](#tab-completion-optional).)

Works on both single-module Antora sites (just `en/modules/ROOT`) and multi-module ones (`en/modules/ROOT`, `en/modules/how-to`, ...).
Every module under `en/modules/` and `ru/modules/` is auto-discovered, and every check scans all of them automatically.
Run `./docs_tool.py --list-modules` to see what was found.

## Get it

It's a single self-contained file.
Copy it into any Antora docs repo without cloning this repo:

```bash
curl -O https://raw.githubusercontent.com/andreyaksenov/docs-tool/main/docs_tool.py && chmod +x docs_tool.py
```

Run it with an explicit path (`./docs_tool.py ...` or `python3 docs_tool.py ...`) from the repo root.
A bare `docs_tool.py` won't be found by your shell even after `chmod +x`, since the current directory isn't on `$PATH`.
That's normal shell behavior, not a broken install.

### Windows

Windows doesn't have an executable bit, so skip the `chmod` step and run the file with `python` (or the `py` launcher) instead of `./docs_tool.py`:

```powershell
Invoke-WebRequest -Uri https://raw.githubusercontent.com/andreyaksenov/docs-tool/main/docs_tool.py -OutFile docs_tool.py
python docs_tool.py --check-<name>
```

`curl` also ships with modern Windows 10/11, so the `curl -O ...` command above works as-is in PowerShell or cmd too.
`--sync` shells out to `git` to detect reworded lines, so make sure Git for Windows (or any git on `PATH`) is installed.

## Tab completion (optional)

`docs_tool.py` supports shell tab completion for every flag. This is optional; the tool works exactly the same without it.

```bash
pip install --user argcomplete   # one-time, not required to run the tool itself
```

Add this to `~/.zshrc` (or `~/.bashrc`), then open a new shell (or `source` it):

```bash
eval "$(python3 -m argcomplete.scripts.register_python_argcomplete docs_tool.py)"
```

```bash
./docs_tool.py --check-<TAB>
```

lists every matching `--check-*` flag. `--page` and `--sync` also complete with real filenames and directories from the current site, e.g. `--page reference/gp_toolkit/gp_ao<TAB>`.

Known issue on zsh: completing right after typing a trailing `/` yourself can fall back to normal file completion — completing before the `/` (e.g. `reference/gp_tool<TAB>`) works reliably instead.

## Usage

```bash
./docs_tool.py --check-<name> [--check-<name> ...] [-v] [--page NAME ...] [--external-root NAME=PATH ...] [--glossary PATH ...]
./docs_tool.py --all-checks [-v]
./docs_tool.py --sync <path/to/en/file.adoc> [-n] [--since REF]
./docs_tool.py --list-checks
./docs_tool.py --list-modules
```

`<name>` is one of:

```
examples-no-cyrillic
examples-orphaned
examples-parity
images-orphaned
nav-structure-parity
pages-broken-refs
pages-file-path-italics (beta)
pages-line-parity
pages-no-cyrillic
pages-no-invisible-chars
pages-no-unicode-dashes
pages-orphaned
pages-ru-latin-homoglyphs (beta)
pages-stray-backticks
pages-structure-parity (beta)
pages-table-cell-periods (beta)
pages-terminology (beta)
pages-translation (beta)
pages-unbalanced-delimiters
tags-orphaned
```

(Or `python3 docs_tool.py ...`, per the note above.)
`(beta)` checks are heuristic rather than a real AsciiDoc parser and can misfire on legitimate content — see their entries under [Checks](#checks) for details, and treat their output as a review list, not a hard gate.

Multiple `--check-*` flags can be combined in one run.
Exits `0` if every selected check passed, `1` if any check found something.

### Scoping to specific pages with `--page`

By default, every check scans the whole site.
Pass `--page NAME` (repeatable) to limit the per-file EN/RU checks — `pages-translation`, `pages-line-parity`, `pages-structure-parity`, `pages-no-cyrillic`, `pages-no-unicode-dashes`, `pages-no-invisible-chars`, `pages-ru-latin-homoglyphs`, `pages-stray-backticks`, `pages-unbalanced-delimiters`, `pages-table-cell-periods`, `pages-file-path-italics`, `pages-terminology` — to just the page(s)/partial(s) whose filename matches `NAME`, e.g.:

```bash
./docs_tool.py --check-pages-translation -v --page resource_groups.adoc
```

`NAME` must end with `.adoc` — AsciiDoc/Antora has no separate topic-id distinct from the filename, so unlike some other doc systems there's no shorter identifier to accept; matching is by the path relative to `pages`/`partials` (never the module itself), so the same name in two different modules is scoped together. If a bare filename matches more than one file (e.g. the same name under two different directories), qualify it with as much of the trailing directory path as needed to disambiguate, e.g. `--page reference/gp_toolkit/gp_ao.adoc` or just `--page gp_toolkit/gp_ao.adoc`.

A `NAME` that *doesn't* end with `.adoc` scopes a whole directory instead, recursively, e.g. `--page reference/sql_commands` matches every page/partial under any module's `pages/reference/sql_commands/` or `partials/reference/sql_commands/` (and any subdirectory below it) — matched by the path relative to `pages`/`partials`, so again the same directory in different modules is scoped together. File and directory forms can be mixed across repeated `--page` flags:

```bash
./docs_tool.py --check-pages-translation -v --page reference/sql_commands
```

`--check-tags-orphaned` also honors `--page`, but only to narrow *which files' own `tag::`/`end::` regions get reported on* — the usage scan (which file includes which tag) still covers the whole site regardless, since a tag defined in the filtered-in file can be pulled in from any other page:

```bash
./docs_tool.py --check-tags-orphaned --page external_data_formats.adoc
```

Whole-site checks (`pages-broken-refs`, `pages-orphaned`, `examples-*`, `images-orphaned`, `nav-structure-parity`) build a site-wide corpus (nav links, partial includers) before reporting, so `--page` doesn't narrow them at all — they always scan and report on everything regardless.

Pass the special value `--page UNCOMMITTED` instead of a name to scope to whatever `.adoc` files currently have uncommitted changes — staged, unstaged, or untracked — per `git status`.
If nothing's uncommitted, the check prints `OK: no uncommitted .adoc changes to check.` and exits `0` immediately.
This is what the [pre-commit hook](#pre-commit-hook) below uses, so a commit only gets checked against what it's actually touching instead of the whole site.

## Checks

Flags are named `--check-<target>-<check>`, where `<target>` is the directory scanned (`pages` covers `pages/` + `partials/`, `examples` covers `examples/`, `images` covers `images/`, `nav` covers `nav.adoc`, `tags` covers `tag::`/`end::` regions across `pages/` + `partials/` + `examples/`) and `<check>` is what it verifies.
Every check below runs across all discovered modules automatically (see `--list-modules`), even though the examples say "EN"/"RU" for brevity.
Run `./docs_tool.py --list-checks` to see the full list.

Each check's heuristics, exceptions, and the false positives they were tuned against are documented in `docs_tool.py` itself, in that `check_*` function's docstring (and, for the more elaborate ones, in comments on the regexes/helpers just above it) — read the source if you need the full rationale behind why something is or isn't flagged. What follows here is just what each check does and how to run it.

### Examples

- `--check-examples-no-cyrillic` — same check as `--check-pages-no-cyrillic`, scoped to each module's `examples/` (all file types).
- `--check-examples-orphaned` — every file under `examples/` must be pulled in by an `include::example$<path>[]` somewhere in `pages/` or `partials/`.
- `--check-examples-parity` (`-v` shows a diff for mismatched non-`.sql` files) — each module's EN and RU `examples/` must have the same files; non-`.sql` files must match byte-for-byte, `.sql` files once comment-only lines are blanked out (comments are legitimately translated).

### Images

- `--check-images-orphaned` — every file under `images/` must be the actual resolved target of an `image:`/`image::`/`injectSvg:`/`injectSvg::`/`inlineSVG:`/`inlineSVG::` macro somewhere in that language, site-wide (not just its own module). Ends with a total count and combined file size, as a rough cleanup gauge.

### Nav

- `--check-nav-structure-parity` (reports the first differing line by default; `-v` shows the full diff with file:line references) — compares each module's `nav.adoc` structure (list depth, `xref:`/`include::` targets) between EN and RU, plus any included `partial$...adoc` files. Translated labels are ignored. Modules without their own `nav.adoc` are skipped.

### Pages

- `--check-pages-broken-refs` — every `xref:`, `include::`, `image:`/`image::`, `injectSvg:`/`injectSvg::`, `inlineSVG:`/`inlineSVG::`, and `link:`/`link::` reference in `pages/`/`partials/` must resolve to a real file or anchor. Cross-module references resolve against sibling modules automatically. A reference into a component outside this repo (e.g. a separate ADCM docs repo) is left unchecked unless you pass `--external-root NAME=PATH` (repeatable, e.g. `--external-root ADCM=../docs-adcm`) to resolve against a local checkout of it.

- `--check-pages-file-path-italics` (beta; `-v` also prints the full line for each hit) — flags file/directory names mentioned in plain prose without the italics (`_..._`) house style requires: known config/archive file extensions, well-known absolute-path prefixes, bare directory basenames, underscore/slash-containing words, and common dotfiles, all checked in the relevant `a`/`an`/`the ... file/folder/...` grammatical slot. Deliberately narrow to keep false positives low.

- `--check-pages-line-parity` — every EN `pages/`/`partials/` `.adoc` file must have a RU counterpart with the same line count, and vice versa.

- `--check-pages-no-cyrillic` — no `pages/`/`partials/` `.adoc` file under `en/modules/` may contain Cyrillic characters (catches RU text left in an EN file).

- `--check-pages-no-invisible-chars` (`-v` also prints each hit line with the invisible character swapped for a visible `⟦U+XXXX⟧` marker) — no `pages/`/`partials/` `.adoc` file may contain zero-width or other invisible/formatting Unicode characters.

- `--check-pages-no-unicode-dashes` — no `pages/`/`partials/` `.adoc` file may contain a literal en dash (`–`) or em dash (`—`); house style uses `--` instead.

- `--check-pages-orphaned` — every `pages/*.adoc` file must be reachable from some module's `nav.adoc` (including nav's own `include::partial$...[]` sections and cross-module links). The site's `start_page` is exempt.

- `--check-pages-ru-latin-homoglyphs` (beta; `-v` also prints the full line for each hit) — flags Latin letters in `ru/` prose that look like they were meant to be Cyrillic: a word mixing both scripts, or a standalone Latin letter matching one of four Cyrillic/Latin homoglyph pairs that double as real one-letter Russian words (`а`/`о`/`с`/`у`). Found dozens of real typos across every repo tested during development.

- `--check-pages-stray-backticks` — no `pages/`/`partials/` `.adoc` line may have an odd number of backticks (almost always a missing or stray `` ` `` around an inline monospace span).

- `--check-pages-structure-parity` (beta; reports the first differing line by default; `-v` shows the full diff with file:line references) — deeper structural comparison of each EN/RU `.adoc` pair (heading levels, block titles, delimited blocks, block attributes, `include::` directives), catching drift even when line counts match.

- `--check-pages-table-cell-periods` (beta) — the last sentence in a table cell shouldn't end with a period, per house style, with exceptions for cells ending in a list, an admonition, or a known abbreviation.

- `--check-pages-terminology` (beta; `-v` also prints the full EN/RU line pair for each hit) — requires `--glossary PATH` (repeatable; a pipe-delimited file with `en|ru|ru_pattern|note` columns, format documented in a `*-glossary.psv` file's own header — `|` rather than `,` specifically so ordinary prose, which routinely contains commas, never needs quoting/escaping). If `--glossary` is omitted, it defaults to every `*-glossary.psv` file found directly under the current directory — so a docs repo carrying its own glossary (e.g. `greengagedb-glossary.psv`) doesn't need the path spelled out on every run; a note is printed to stderr when this default kicks in. Flags an EN glossary term whose aligned RU line doesn't match any of its `ru_pattern` alternatives — a translator drifting onto an inconsistent or outdated Russian word for something the glossary already has a house-style answer for. Each pattern is hand-authored, not guessed: a `word<>` token requires that stem plus any suffix (tolerating declension/conjugation), a bare `word` token requires that exact word (used for do-not-translate terms and invariant tokens like SQL keywords). See `check_pages_terminology`'s docstring in `docs_tool.py` for the full matching rationale.

- `--check-pages-translation` (beta; `-v` also flags RU lines containing common English stopwords) — flags `pages/`/`partials/` lines that look untranslated: RU byte-identical to its EN counterpart, skipping code, attributes, comments, table cells, and keyword-only lines.

- `--check-pages-unbalanced-delimiters` — every AsciiDoc block delimiter (open `--`, listing `----`, literal `....`, example `====`, sidebar `****`, quote `____`, passthrough `++++`, table `|===`, comment `////`) must be properly closed once a page's full include chain is flattened into the single document Asciidoctor actually renders. An unclosed one is almost always a forgotten closing delimiter, which silently swallows everything after it once rendered.

The `(beta)` checks above are heuristic rather than a real AsciiDoc parser and can misfire on legitimate content — treat their output as a review list, not a hard gate.

### Tags

- `--check-tags-orphaned` — finds `tag::NAME[]`/`end::NAME[]` regions (in `examples/`, `pages/`, or `partials/`) never actually pulled in by any `include::...[tag=NAME]`/`[tags=NAME;...]` elsewhere in the site, whether directly, via nesting inside another used region, or via a whole-file include. `--page NAME` narrows which files' own tag regions get reported on, but the usage scan always covers the whole site (see [above](#scoping-to-specific-pages-with---page)). Like `--check-pages-broken-refs`, pass `--external-root NAME=PATH` to recognize a tag that's only ever consumed from a sibling Antora component's repo.

## Sync a RU page after an EN edit (beta)

Heuristic aligner, not a semantic merge — review its output before trusting it; see the caveat below.

```bash
./docs_tool.py --sync en/modules/ROOT/pages/reference/utils/analyzedb.adoc
./docs_tool.py --sync analyzedb.adoc -n   # same file, by bare filename -- dry run: print the diff instead of writing
```

`--sync`'s argument works the same way `--page NAME` does: it must end with `.adoc`, and can be either the full relative path or just the bare filename — resolved by searching all discovered modules' `pages`/`partials`, same lookup `--page` uses. If a filename matches more than one file (e.g. the same name under two different directories), qualify it with trailing directory path segments to disambiguate, same as `--page`, or pass the full path.

Only ever writes the RU counterpart; never touches EN.

- Aligns RU's structure to EN's: headings, anchors, delimited blocks, option/flag terms, code lines.
- Copies in new or changed EN lines verbatim (left untranslated) wherever RU has nothing corresponding yet.
  Run `--check-pages-translation` afterward to find them.
- Existing RU prose is never rewritten or removed.
- Only technical tokens that must be byte-identical across languages are corrected when they've drifted (e.g. a stale `plpythonu` left behind after EN moved to `plpython3u`): flag names, code/command lines, include paths, ids, file/directory names.

This is a heuristic aligner, not a semantic merge: when an EN paragraph is reworded (not just extended), the new wording is appended after the existing translation rather than replacing it.
Review and reconcile those cases by hand.

## Pre-commit hook

Runs a subset of the checks above automatically before every `git commit`.

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
  --check-pages-stray-backticks \
  --check-pages-unbalanced-delimiters || blocking_failed=1

echo
echo "=== warn-only checks (do not block commit) ==="
python3 docs_tool.py --page UNCOMMITTED \
  --check-pages-ru-latin-homoglyphs \
  --check-pages-table-cell-periods \
  --check-pages-file-path-italics \
  --check-examples-no-cyrillic \
  --check-examples-orphaned \
  --check-examples-parity \
  --check-images-orphaned \
  --check-nav-structure-parity \
  --check-pages-broken-refs \
  --check-pages-line-parity \
  --check-pages-orphaned \
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

Only `--check-pages-no-cyrillic`, `--check-pages-no-invisible-chars`, `--check-pages-no-unicode-dashes`, `--check-pages-stray-backticks`, and `--check-pages-unbalanced-delimiters` actually block the commit; the rest just print their findings.
The other three checks that carry a `(beta)` tag above (`pages-ru-latin-homoglyphs`, `pages-table-cell-periods`, `pages-file-path-italics`) stay warn-only deliberately: each has a documented, non-zero false-positive rate, so hard-blocking on them would occasionally stop a legitimate commit over a heuristic miss. Move one into the blocking block once it's run clean for a while in practice.
`--page UNCOMMITTED` (see [above](#scoping-to-specific-pages-with---page)) scopes every check here to just the `.adoc` files the commit is actually touching; the whole-site checks (`pages-broken-refs`, `pages-orphaned`, `examples-*`, `images-orphaned`, `nav-structure-parity`) ignore it and keep scanning everything, same as any other run. `tags-orphaned` is in between: it only reports on tag regions defined in the touched files, but its usage scan still covers the whole site regardless.

## Running the tests

```bash
python3 -m unittest discover -s tests
```

`tests/test_docs_tool.py` (stdlib `unittest`, no extra dependencies) covers the trickier pure-parsing functions directly, plus fixture-based integration tests that build a throwaway Antora tree per test and run a `check_*()` function against it — including regression tests for bugs found along the way (a basename shared by two different modules' `images/`, `inlineSVG:` not being recognized as usage, a self-qualified `image::ADCM:ROOT:...[]` reference being treated as an unregistered external component instead of this repo's own content). Does not touch this repo's real `en/`/`ru/` content.
