# docs_tool.py

One self-contained Python script that checks an Antora docs repo's `en/` and `ru/`
trees for consistency, and aligns a RU page's structure after an EN edit. Run it
from the repo root; every module under `en/modules/` and `ru/modules/` is
discovered and scanned automatically.

## Get it

```bash
curl -O https://raw.githubusercontent.com/andreyaksenov/docs-tool/main/docs_tool.py
chmod +x docs_tool.py
```

Needs Python 3.7+ (no dependencies). `git` is only used by `sync`. On Windows, drop
the `chmod` and run `python docs_tool.py …`.

## Usage

```
check <family> [<family> ...] [--<subcheck> ...] [--target NAME] [--verbose]
                              [--page NAME ...] [--glossary PATH ...] [--external-root NAME=PATH ...]
show  <subcheck|rule-id>        one check's full rationale
list [checks|targets]          the family/check map, or a flat list
sync  <en-file> [--dry-run]     align a RU page to its EN counterpart (beta)
```

`./docs_tool.py` with no arguments prints the full command list. A run exits `0` if
everything passed, `1` if any check found something.

Checks are grouped into six **families**:

| Family | Covers |
|--------|--------|
| `chars`  | invisible chars, unicode dashes, RU/Latin homoglyphs, Cyrillic in EN files |
| `markup` | stray backticks, unbalanced block delimiters |
| `refs`   | broken `xref:`/`include:`/`image:` targets, orphaned pages/partials/examples/images/tags |
| `style`  | `ё`/`Ё`, un-italicized file paths, table-cell periods |
| `terms`  | EN term translated to a non-house-style RU word (glossary-driven) |
| `l10n`   | line-count / structure / nav parity, untranslated lines, `examples/` parity |

```bash
./docs_tool.py check style                  # the whole style family
./docs_tool.py check style --no-yo           # narrow to one check
./docs_tool.py check chars markup            # several families
./docs_tool.py check all
./docs_tool.py check l10n --structure --verbose --page resource_groups.adoc
```

`--target NAME` picks a scan target other than the default `pages` (`pages/` +
`partials/`) — see `list targets`.

## Checks

Every check has a stable **rule ID**. `list` prints the table below as a tree with
one-line descriptions; `show <subcheck|id>` (e.g. `show no-yo`, `show ST03`) prints
one check's full rationale, exceptions, and the false positives it was tuned against.

| ID | Command | What |
|----|---------|------|
| `CH01` | `check chars --no-cyrillic` | no Cyrillic in `en/` files (`--target examples` → `CH02`) |
| `CH03` | `check chars --no-invisible` | no zero-width / invisible / bidi-control characters |
| `CH04` | `check chars --dashes` | no literal en/em dash — house style uses `--` |
| `CH05` | `check chars --homoglyphs` | Latin letters in RU prose that should be Cyrillic · beta |
| `MK01` | `check markup --backticks` | no line with an odd number of backticks |
| `MK02` | `check markup --delimiters` | every block delimiter closed once the include chain is flattened |
| `RF01` | `check refs --broken` | every `xref:` / `include::` / `image:` target resolves |
| `RF02`–`RF06` | `check refs --orphaned [--target …]` | flags pages / partials / examples / images / `tag::` regions that are defined but never referenced |
| `ST01` | `check style --no-yo` | no `ё`/`Ё` in `ru/` files (`:page-author:` exempt) |
| `ST02` | `check style --file-path-italics` | file / directory names in prose need `_italics_` · beta |
| `ST03` | `check style --table-cell-periods` | a table cell's last sentence shouldn't end with a period · beta |
| `TM01` | `check terms` | EN glossary term translated to a non-house-style RU word · beta |
| `LN01` | `check l10n --lines` | EN file and its RU counterpart have the same line count |
| `LN02` | `check l10n --structure` | EN and RU structural skeletons match · beta |
| `LN03` | `check l10n --untranslated` | RU line byte-identical to its EN counterpart · beta |
| `LN04` | `check l10n --examples` | EN and RU `examples/` match |
| `LN05` | `check l10n --nav` | EN and RU `nav.adoc` structure match |

Notes:

- **beta** checks are heuristics, not a real AsciiDoc parser — treat their output as
  a review list, not a hard gate.
- **`refs`** always scans the whole site. `--page` only narrows which files are
  *reported* for `--orphaned --target tags|partials`; everything else in `refs`
  ignores it.
- **`terms`** needs a glossary: `--glossary PATH` (pipe-delimited `en|ru|ru_pattern|note`),
  or any `*-glossary.psv` in the current directory.
- **`--external-root NAME=PATH`** (repeatable) resolves references into a sibling
  Antora repo, for `check refs --broken` and `--orphaned --target partials|tags`,
  e.g. `--external-root ADCM=../docs-adcm`.
- **`--verbose`** shows the full diff / hit line on the parity and heuristic checks.

## Scoping with `--page`

By default every per-file check scans the whole site. `--page NAME` (repeatable)
limits `chars`, `markup`, `style`, `terms`, and `l10n` to matching files:

```bash
./docs_tool.py check l10n --untranslated --page resource_groups.adoc   # one file (must end .adoc)
./docs_tool.py check l10n --untranslated --page reference/sql_commands # a directory, recursively
./docs_tool.py check chars markup --page UNCOMMITTED                   # whatever git says is uncommitted
```

If a bare filename matches two files, qualify it (`--page gp_toolkit/gp_ao.adoc`) or
pass the full path. `--page UNCOMMITTED` with nothing uncommitted exits `0`
immediately — which is what the pre-commit hook relies on.

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

python3 docs_tool.py check style terms l10n refs --page UNCOMMITTED || true
```

Move a family from the second line to the first once it runs clean in practice.

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
