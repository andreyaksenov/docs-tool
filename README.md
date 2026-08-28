# docs_tool.py

One self-contained Python script that checks an Antora docs repo's `en/` and `ru/`
trees for consistency, and aligns a RU page's structure after an EN edit. Run it
from the repo root; every module under `en/modules/` and `ru/modules/` is
discovered and scanned automatically. Run from anywhere else and `check`/`sync`
refuse to start rather than report a clean pass over files they never read.

## Get it

```bash
curl -O https://raw.githubusercontent.com/andreyaksenov/docs-tool/main/docs_tool.py
chmod +x docs_tool.py
```

Needs Python 3.7+ (no dependencies). `git` is only used by `sync`. On Windows, drop
the `chmod` and run `python docs_tool.py …`.

## Usage

```
./docs_tool.py check <family> [<family> ...] [--<rule> ...]
                     [--target NAME] [--verbose] [--page NAME ...]
                     [--glossary PATH ...] [--external-root NAME=PATH ...]

./docs_tool.py show <rule|rule-id>            # one rule's full rationale
./docs_tool.py list [rules|targets]           # the rule map, or a flat list
./docs_tool.py sync <en-file> [--dry-run]     # align a RU page to EN (beta)
```

Run with no arguments to print the full command list. A run exits `0` if everything
passed, `1` if any rule found something, `2` on a usage error. `list` labels each
family `suggest: block` / `suggest: warn` — that's advice for your pre-commit hook,
not something the tool enforces; the exit code is the same for every family.

Rules are grouped into six **families**:

| Family   | Covers                                                                                   |
|----------|------------------------------------------------------------------------------------------|
| `chars`  | invisible chars, unicode dashes, RU/Latin homoglyphs, Cyrillic in EN files               |
| `markup` | stray backticks, unbalanced block delimiters                                             |
| `refs`   | broken `xref:`/`include:`/`image:` targets, orphaned pages/partials/examples/images/tags |
| `style`  | `ё`/`Ё`, un-italicized file paths, table-cell periods                                    |
| `terms`  | EN term translated to a non-house-style RU word (glossary-driven)                        |
| `l10n`   | line-count / structure / nav parity, untranslated lines, `examples/` parity              |

```bash
./docs_tool.py check style                  # the whole style family
./docs_tool.py check style --no-yo           # narrow to one rule
./docs_tool.py check chars markup            # several families
./docs_tool.py check all
./docs_tool.py check l10n --structure --verbose --page resource_groups.adoc
```

`--target NAME` picks a scan target other than the default `pages` (`pages/` +
`partials/`) — see `list targets`.

## Rules

Every rule has a stable **rule ID**. `list` prints this section as a tree;
`show <rule|id>` (e.g. `show no-yo`, `show ST03`) prints one rule's full
rationale, exceptions, and the false positives it was tuned against. `beta` rules
are heuristics — treat their output as a review list, not a hard gate.

| ID | Command |
|----|---------|
| `CH01` | `check chars --no-cyrillic` |
| `CH03` | `check chars --no-invisible` |
| `CH04` | `check chars --dashes` |
| `CH05` | `check chars --homoglyphs` |
| `MK01` | `check markup --backticks` |
| `MK02` | `check markup --delimiters` |
| `RF01` | `check refs --broken` |
| `RF02`–`RF06` | `check refs --orphaned [--target …]` |
| `ST01` | `check style --no-yo` |
| `ST02` | `check style --file-path-italics` |
| `ST03` | `check style --table-cell-periods` |
| `TM01` | `check terms` |
| `LN01` | `check l10n --lines` |
| `LN02` | `check l10n --structure` |
| `LN03` | `check l10n --untranslated` |
| `LN04` | `check l10n --examples` |
| `LN05` | `check l10n --nav` |

### `chars` — Unicode / encoding

- **`CH01` · `check chars --no-cyrillic`** — no Cyrillic in `en/` files (RU text
  left in an EN file). `--target examples` also scans `examples/` → `CH02`.
  ```bash
  ./docs_tool.py check chars --no-cyrillic
  ./docs_tool.py check chars --no-cyrillic --page resource_groups.adoc
  ./docs_tool.py check chars --no-cyrillic --target examples
  ```

- **`CH03` · `check chars --no-invisible`** — no zero-width / invisible /
  bidi-control Unicode characters. `--verbose` marks the character in the line.
  ```bash
  ./docs_tool.py check chars --no-invisible
  ./docs_tool.py check chars --no-invisible --page auth.adoc
  ./docs_tool.py check chars --no-invisible --verbose
  ```

- **`CH04` · `check chars --dashes`** — no literal en dash (`–`) or em dash (`—`);
  house style uses `--`.
  ```bash
  ./docs_tool.py check chars --dashes
  ./docs_tool.py check chars --dashes --page resource_groups.adoc
  ```

- **`CH05` · `check chars --homoglyphs`** · beta — Latin letters in `ru/` prose
  that should be Cyrillic: a mixed-script word, or a lone `а`/`о`/`с`/`у` look-alike.
  ```bash
  ./docs_tool.py check chars --homoglyphs
  ./docs_tool.py check chars --homoglyphs --page resource_groups.adoc
  ./docs_tool.py check chars --homoglyphs --verbose
  ```

### `markup` — AsciiDoc syntax

- **`MK01` · `check markup --backticks`** — no line with an odd number of
  backticks (usually a stray or missing `` ` `` around inline monospace).
  ```bash
  ./docs_tool.py check markup --backticks
  ./docs_tool.py check markup --backticks --page resource_groups.adoc
  ```

- **`MK02` · `check markup --delimiters`** — every AsciiDoc block delimiter
  (`----`, `====`, `|===`, `////`, …) closed, checked on the flattened include chain.
  ```bash
  ./docs_tool.py check markup --delimiters
  ./docs_tool.py check markup --delimiters --page resource_groups.adoc
  ```

### `refs` — Antora reference resolution

Always scans the whole site. `--page` only narrows *which files are reported* for
`--orphaned --target tags|partials`; everything else in `refs` ignores it. Bare
`check refs` runs `--broken` plus every orphan target.

- **`RF01` · `check refs --broken`** — every `xref:` / `include::` / `image:` /
  `link:` reference resolves to a real file or anchor. `--external-root NAME=PATH`
  (repeatable) resolves references into a sibling Antora repo checked out locally.
  ```bash
  ./docs_tool.py check refs --broken
  ./docs_tool.py check refs --broken --external-root ADCM=../docs-adcm
  ```
  A reference into a component with no `--external-root` can't be resolved either
  way, so it's left unchecked rather than called broken. The run ends by naming
  those components on stderr — an unverified component otherwise looks exactly
  like a verified one:
  ```
  note: 2 referenced component(s) left unchecked -- docs-backup, docs-pxf
        pass --external-root NAME=PATH for each one you have checked out locally
  ```

- **`RF02`–`RF06` · `check refs --orphaned [--target …]`** — flags content that is
  defined but never referenced. `check refs --orphaned` runs all five; `--target`
  picks one:

  | `--target` | ID | Flags a … |
  |------------|----|-----------|
  | `pages`    | `RF02` | `pages/*.adoc` not reachable from any `nav.adoc` (`start_page` exempt) |
  | `partials` | `RF03` | tag-less `partials/` file never `include::`d whole |
  | `examples` | `RF04` | `examples/` file never pulled in via `include::example$…[]` |
  | `images`   | `RF05` | `images/` file that is no `image:` / `injectSvg:` macro's target |
  | `tags`     | `RF06` | `tag::NAME[]` region never pulled in via `include::…[tag=NAME]` |

  ```bash
  ./docs_tool.py check refs --orphaned
  ./docs_tool.py check refs --orphaned --target tags
  ./docs_tool.py check refs --orphaned --target partials \
    --external-root ADB=../docs-adb --external-root ADH=../docs-adh
  ```

### `style` — Arenadata style guide

Heuristic family — treat findings as a review list, not a hard gate.

- **`ST01` · `check style --no-yo`** — no `ё`/`Ё` in `ru/` files; house style
  spells it `е`. The `:page-author:` attribute is exempt.
  ```bash
  ./docs_tool.py check style --no-yo
  ./docs_tool.py check style --no-yo --page resource_groups.adoc
  ```

- **`ST02` · `check style --file-path-italics`** · beta — file / directory names
  in plain prose that should be in `_italics_` per house style.
  ```bash
  ./docs_tool.py check style --file-path-italics
  ./docs_tool.py check style --file-path-italics --page resource_groups.adoc
  ./docs_tool.py check style --file-path-italics --verbose
  ```

- **`ST03` · `check style --table-cell-periods`** · beta — a table cell's last
  sentence shouldn't end with a period (lists, admonitions, abbreviations exempt).
  ```bash
  ./docs_tool.py check style --table-cell-periods
  ./docs_tool.py check style --table-cell-periods --page resource_groups.adoc
  ```

### `terms` — controlled vocabulary

Needs a glossary: `--glossary PATH` (pipe-delimited `en|ru|ru_pattern|note`), or any
`*-glossary.psv` in the current directory (auto-discovered).

- **`TM01` · `check terms`** · beta — flags an EN glossary term whose aligned RU
  line uses a non-house-style translation (or leaves some repeats untranslated).
  `--verbose` prints the EN/RU line pair.
  ```bash
  ./docs_tool.py check terms
  ./docs_tool.py check terms --glossary greengagedb-glossary.psv
  ./docs_tool.py check terms --verbose --page resource_groups.adoc
  ```

### `l10n` — EN↔RU parity

- **`LN01` · `check l10n --lines`** — every EN `.adoc` has a RU counterpart with
  the same line count, and vice versa.
  ```bash
  ./docs_tool.py check l10n --lines
  ./docs_tool.py check l10n --lines --page resource_groups.adoc
  ```

- **`LN02` · `check l10n --structure`** · beta — EN/RU structural skeletons
  (headings, blocks, `include::`) must match, catching drift when line counts don't.
  Prints a 20-line diff preview per file; `--verbose` shows the full diff.
  ```bash
  ./docs_tool.py check l10n --structure
  ./docs_tool.py check l10n --structure --page resource_groups.adoc
  ./docs_tool.py check l10n --structure --verbose
  ```

- **`LN03` · `check l10n --untranslated`** · beta — RU lines byte-identical to
  their EN counterpart (`UNTRANSLATED`), plus RU lines carrying English stopwords
  like `the`/`and`/`with` (`SUSPECT`). `--verbose` names the matched stopword.
  ```bash
  ./docs_tool.py check l10n --untranslated
  ./docs_tool.py check l10n --untranslated --page resource_groups.adoc
  ./docs_tool.py check l10n --untranslated --verbose
  ```

- **`LN04` · `check l10n --examples`** — EN and RU `examples/` must hold the same
  files (byte-for-byte; `.sql` comments may differ). Whole-site — ignores `--page`.
  ```bash
  ./docs_tool.py check l10n --examples
  ./docs_tool.py check l10n --examples --verbose
  ```

- **`LN05` · `check l10n --nav`** — EN and RU `nav.adoc` structure (list depth,
  `xref:`/`include::` targets) must match; translated labels ignored. Ignores `--page`.
  ```bash
  ./docs_tool.py check l10n --nav
  ./docs_tool.py check l10n --nav --verbose
  ```

## Scoping with `--page`

By default, every per-file rule scans the whole site. `--page NAME` (repeatable)
limits `chars`, `markup`, `style`, `terms`, and `l10n` to matching files:

```bash
./docs_tool.py check l10n --untranslated --page resource_groups.adoc   # one file (must end .adoc)
./docs_tool.py check l10n --untranslated --page reference/sql_commands # a directory, recursively
./docs_tool.py check chars markup --page UNCOMMITTED                   # whatever git says is uncommitted
```

If a bare filename matches two files, qualify it (`--page gp_toolkit/gp_ao.adoc`) or
pass the full path. `--page UNCOMMITTED` with nothing uncommitted exits `0`
immediately — which is what the pre-commit hook relies on.

A `--page` value that matches no file aborts the run with exit `2` — an empty run
otherwise looks identical to a clean one, so a typo in a CI invocation would pass
green. `--page UNCOMMITTED` resolving to nothing is exempt: that's the normal
"no `.adoc` changes" case, and still exits `0`.

## Sync

`sync` aligns a RU page's structure to its EN counterpart. Heuristic aligner, not a
semantic merge — review the diff.

```bash
./docs_tool.py sync analyzedb.adoc            # full path or bare filename, like --page
./docs_tool.py sync analyzedb.adoc --dry-run  # print the diff, don't write
```

Only ever writes the RU file. It aligns structure (headings, anchors, blocks, code
lines), copies in new/changed EN lines untranslated (run `check l10n --untranslated`
after to find them), and fixes drifted technical tokens (flag names, ids, paths).
Existing RU prose is never rewritten. When an EN paragraph is **reworded** (not just
extended), the new text is appended after the old translation with a
`// STALE VERSION:` marker — reconcile those by hand.

## Pre-commit hook

Two `check` calls scoped to the commit — the deterministic families block, the rest
just report. Put this in `.git/hooks/pre-commit` (and `chmod +x` it):

```bash
#!/usr/bin/env bash
cd "$(git rev-parse --show-toplevel)"

python3 docs_tool.py check chars markup --page UNCOMMITTED \
  || { echo "pre-commit: blocking check(s) failed" >&2; exit 1; }

python3 docs_tool.py check style terms l10n --page UNCOMMITTED || true
```

Move a family from the second line to the first once it runs clean in practice.

**Don't put `refs` in the hook.** It ignores `--page` and always scans the whole
site (see above), so every commit touching one `.adoc` would print every orphan and
broken reference in the repo. Run `check refs` in CI, or by hand before a release.

## Legacy `--check-*` flags

The pre-subcommand interface still works: `--check-<name>`, `--all-checks`,
`--sync`, `--list-checks`, `--list-modules`. See the
[migration map](docs/proposals/cli-redesign.md#4-full-migration-map) for the
`check <family>` equivalent of each `--check-*` flag, or run `./docs_tool.py --list-checks`.

## Tab completion (optional)

<details>
<summary>argcomplete setup</summary>

```bash
pip install --user argcomplete        # or: sudo apt install python3-argcomplete
```

Add to `~/.zshrc` / `~/.bashrc` and open a new shell:

```bash
eval "$(register-python-argcomplete docs_tool.py)"
```

Then `./docs_tool.py <TAB>` completes subcommands, families, and flags; `--page` and
`sync`'s file argument complete real filenames from the current site.
</details>

## Tests

```bash
python3 -m unittest discover -s tests
```

Stdlib `unittest`, no dependencies; fixture-based, never touches this repo's real content.
