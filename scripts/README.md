# docs_tool.py

A single Python utility for checking that the `en/` and `ru/` documentation trees stay in sync, and for syncing a RU page's structure after an EN edit.
Run it from the root of the Antora docs repo you want to check.
Requires Python 3.7+ (no third-party dependencies) — nothing to install.

Works on both single-module Antora sites (just `en/modules/ROOT`) and multi-module ones (`en/modules/ROOT`, `en/modules/how-to`, ...).
Every module under `en/modules/` and `ru/modules/` is auto-discovered, and every check scans all of them automatically.
Run `./docs_tool.py --list-modules` to see what was found.

## Get it

It's a single self-contained file.
Copy it into any Antora docs repo without cloning this repo:

```bash
curl -O https://raw.githubusercontent.com/andreyaksenov/docs-translation-tools/main/scripts/docs_tool.py && chmod +x docs_tool.py
```

Run it with an explicit path (`./docs_tool.py ...` or `python3 docs_tool.py ...`) from the repo root.
A bare `docs_tool.py` won't be found by your shell even after `chmod +x`, since the current directory isn't on `$PATH`.
That's normal shell behavior, not a broken install.

### Windows

Windows doesn't have an executable bit, so skip the `chmod` step and run the file with `python` (or the `py` launcher) instead of `./docs_tool.py`:

```powershell
Invoke-WebRequest -Uri https://raw.githubusercontent.com/andreyaksenov/docs-translation-tools/main/scripts/docs_tool.py -OutFile docs_tool.py
python docs_tool.py --check-<name>
```

`curl` also ships with modern Windows 10/11, so the `curl -O ...` command above works as-is in PowerShell or cmd too.
`--sync` shells out to `git` to detect reworded lines, so make sure Git for Windows (or any git on `PATH`) is installed.

## Usage

```bash
./docs_tool.py --check-<name> [--check-<name> ...] [-v] [--external-root NAME=PATH ...]
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
pages-structure-parity (beta)
pages-table-cell-periods (beta)
pages-translation (beta)
```

(Or `python3 docs_tool.py ...`, per the note above.)
`(beta)` checks are heuristic rather than a real AsciiDoc parser and can misfire on legitimate content — see their entries under [Checks](#checks) for details, and treat their output as a review list, not a hard gate.

Multiple `--check-*` flags can be combined in one run.
Exits `0` if every selected check passed, `1` if any check found something.

## Checks

Flags are named `--check-<target>-<check>`, where `<target>` is the directory scanned (`pages` covers `pages/` + `partials/`, `examples` covers `examples/`, `images` covers `images/`, `nav` covers `nav.adoc`) and `<check>` is what it verifies.
Every check below runs across all discovered modules automatically (see `--list-modules`), even though the examples say "EN"/"RU" for brevity.
Run `./docs_tool.py --list-checks` to see the full list.

### Examples

- `--check-examples-no-cyrillic`

  Same check as `--check-pages-no-cyrillic`, scoped to each module's `examples/` (all file types).

- `--check-examples-orphaned`

  Checks (per language, per module) that every file under `examples/` is pulled in by an `include::example$<path>[]` somewhere in `pages/` or `partials/`.

- `--check-examples-parity` (`-v` shows a diff for mismatched non-`.sql` files)

  Checks that each module's EN and RU `examples/` directories have the same files.
  Every file must exist on both sides; non-`.sql` files (data/config) must also match byte-for-byte.
  `.sql` files only require matching content once comment-only lines are blanked out, since their comments are legitimately translated.

### Images

- `--check-images-orphaned`

  Checks (per language) that every file under `images/` has its filename referenced somewhere in `pages/` or `partials/` — anywhere in that language across the whole site, not just its own module, since a page in one module can reference another module's image via a qualified `image::<module>:path[]` macro.
  Ends with a total count and combined file size of the orphaned images found, as a rough gauge of cleanup impact.

### Nav

- `--check-nav-structure-parity` (reports the first differing line by default; `-v` shows the full diff with file:line references)

  Compares the structural "skeleton" of each module's `nav.adoc` (list depth, `xref:`/`include::` targets) between EN and RU, plus any `partial$...adoc` files it includes.
  Translated labels are ignored; only the menu structure and link targets are compared.
  Modules without their own `nav.adoc` are silently skipped.

### Pages

- `--check-pages-broken-refs`

  Checks (per language) that every `xref:`, `include::`, and `injectSvg:`/`injectSvg::` reference found in `pages/`/`partials/` resolves to a real file (page, partial, example, or image) or, for anchor-only/fragment xrefs, a real anchor in the target.

  - Comments (`//` lines and `////` blocks) are skipped.
  - A `{doc-attribute}` used inside a reference target (e.g. `xref:{install-link}[]`) is substituted using that file's own `:name: value` attribute definitions before resolving.
  - A module-prefixed `xref:`/`include::` (e.g. `xref:how-to:page.adoc[]`, `include::how-to:partial$foo.adoc[]`) resolves against that sibling module if the prefix matches a discovered module.
    Otherwise it's treated as pointing outside this repo (e.g. `blog::x`, `include::ADCM:ROOT:partial$x.adoc[]`) and skipped.
  - Anchors are matched against:
    - explicit `[#id]`/`[[id]]` markers (a `[[id]]` is recognized wherever it appears on a line, including inline mid-sentence or mid-list-item, not just on a line of its own), *and*
    - headings' Asciidoctor-autogenerated IDs (tried under a few common `idprefix`/`idseparator` conventions, since the site's actual playbook attributes aren't visible to this tool).
      So `== 6.23.3` satisfies `xref:page.adoc#6-23-3[]` even with no explicit anchor written.
      Underscores in a heading (e.g. `=== gp_segment_configuration`) are kept as literal characters, not stripped as italic markup, and non-Latin headings (e.g. Cyrillic RU ones) are slugified correctly too.
  - Anchor resolution follows module- and component-qualified `include::partial$...`/`include::page$...` chains, not just same-module ones.
  - By default, a reference into a component that isn't part of this repo (e.g. `xref:ADCM:ROOT:page.adoc[]`, pulled in from a separate Antora site like an ADCM docs repo) is left unchecked rather than reported broken, since this tool can't see that component's source.
    If you have that component's repo checked out locally, pass `--external-root NAME=PATH` (repeatable) to resolve against it too, e.g. `--external-root ADCM=../docs-adcm`.

- `--check-pages-file-path-italics` (beta; `-v` also prints the full line for each hit)

  Checks (per language) for file/directory names mentioned in plain prose without the italics (`_..._`) house style requires for them: a curated whitelist of config/unit-file-style extensions (`.conf`, `.yaml`/`.yml`, `.cfg`, `.ini`, `.toml`, `.json`, `.service`, `.socket`, `.log`, `.env`, `.pem`, `.crt`, `.key`, `.properties`), well-known absolute-path prefixes (`/etc`, `/var`, `/opt`, `/usr/local`, `/usr/share`, `/home`), bare directory/file basenames (`bin`, `sbin`, `etc`, `lib`, `tmp`, `var`, `opt`, `src`) mentioned as `a`/`an`/`the <name> file/folder/directory`, any *other* underscore-containing word (e.g. `greengage_path`) in that same `a`/`an`/`the <name> file/folder/directory` slot, and common shell/tool dotfiles (`.bashrc`, `.bash_profile`, `.bash_login`, `.profile`, `.zshrc`, `.vimrc`, `.gitconfig`, `.psqlrc`, `.pgpass`, `.npmrc`, `.editorconfig`, `.gitignore`, `.env`, `.dockerignore`, `.eslintrc`, `.pylintrc`, `.htaccess`, `.htpasswd`, `.claude`, `.idea`).
  Deliberately narrow rather than exhaustive, to keep the false-positive rate low -- the basename list in particular excludes common generic-English words like `log`/`data`/`config`/`cache` ("a log file" is a generic description, not a reference to a directory literally named `log`).

  For the extension/path checks, already-formatted or non-prose spans are excluded before matching: code spans, bold, italics, bold-italics, any AsciiDoc macro (`xref:`, `link:`, `image:`/`image::`, etc.) and the `<<anchor,text>>` shorthand, and bare URLs.
  Whole code/literal blocks, `////` comment blocks, tables, headings, and block titles/captions are skipped outright, since none of these are italicized by convention regardless of what they mention.
  The basename and dotfile checks are the exception: they deliberately do *not* treat bold/code-span as already-exempt, since a directory basename or dotfile that's only ever bold or code-spanned (never italicized) is itself the finding, not something to wave through -- confirmed safe by checking that (unlike, say, `.service`/`.timer` extension matches, which turned out to have legitimate backtick use elsewhere as systemd unit names) a dotfile mention is unambiguously a literal file reference in this doc set.
  `bin`/`sbin`/`etc`/`tmp`/`opt` are additionally flagged wherever they're bold/code-spanned, with no "a/the X folder" phrase required at all (e.g. "for example, `bin`)" referring back to an earlier mention) -- `var`/`src`/`lib` stay gated behind that phrase even when marked, since they're common enough as generic variable-name/HTML-attribute/placeholder terms elsewhere (confirmed via false positives on synthetic "Declare a `var`..."/"the `src` attribute" cases) that bold/code alone isn't a reliable enough signal for them.
  The underscore-word generalization is deliberately underscore-only, not hyphen: hyphen was tried too and dropped after real hits on docs-adh turned out to be ordinary English compound adjectives ("a global-level file", "a zero-length file", "the first-level directory"), not filenames, whereas underscore had zero false positives across all four repos tested.
  A slash is also accepted as a connector alongside underscore, catching a relative path with no leading `/` that the absolute-path check above wouldn't (e.g. "the `backup/adb` folder") -- the one common English "/" idiom, "and/or", doesn't realistically combine with "file"/"folder" as its object, so this stayed clean across all four repos too.

  On top of all of the above, *any* word in a code span in the `a`/`an`/`the <name> file/folder/directory` slot is flagged regardless of whether it's on any whitelist (e.g. "the `backup` folder") -- the code-span formatting itself is the signal, since a code span is essentially never used for plain prose emphasis in AsciiDoc (unlike bold, which commonly *is* used that way, so this generalization is deliberately code-span-only). One exception within that: a camelCase match (an uppercase letter after the first character, e.g. `` `dataLogDir` ``) is excluded, since real Unix file/directory names in this doc set are essentially always lowercase -- camelCase is instead a strong signal of a config *parameter* name (confirmed via zookeeper/configure.adoc, where the exact same sentence separately calls `` `dataLogDir` `` "the `dataLogDir` **parameter**", not a literal directory).

- `--check-pages-line-parity`

  Checks that every EN `pages/`/`partials/` `.adoc` file has a RU counterpart with the same line count, and vice versa.

- `--check-pages-no-cyrillic`

  Checks that no `pages/`/`partials/` `.adoc` file under `en/modules/` contains Cyrillic characters — catches RU text accidentally left in (or pasted into) an EN file.

- `--check-pages-no-invisible-chars` (`-v` also prints each hit line with the invisible character swapped for a visible `⟦U+XXXX⟧` marker)

  Checks (per language) that no `pages/`/`partials/` `.adoc` file contains zero-width or other invisible/formatting Unicode characters — zero-width space/non-joiner/joiner, word joiner, BOM, bidi control marks, soft hyphen, and Unicode tag characters (`U+E0000`–`U+E007F`, a range with no visible glyph at all, known to be abused to smuggle hidden text past a casual read of the source).
  These render as nothing, so a hit is invisible if the line is printed as-is; without `-v` only the character's name and codepoint are shown, run with `-v` to see exactly where in the line it sits.

- `--check-pages-no-unicode-dashes`

  Checks (per language) that no `pages/`/`partials/` `.adoc` file contains a literal en dash (`–`, U+2013) or em dash (`—`, U+2014) — house style uses `--` (rendered as an em dash by AsciiDoc) instead.

- `--check-pages-orphaned`

  Checks (per language) that every `pages/*.adoc` file is reachable from some module's `nav.adoc`, resolving the `include::partial$...[]` sections nav.adoc pulls in (e.g. SQL command / utility reference lists) and allowing cross-module nav links.
  The site's `start_page` (from `antora.yml`) is exempt, since it's not expected to be in the sidebar.

- `--check-pages-structure-parity` (beta; reports the first differing line by default; `-v` shows the full diff with file:line references)

  Deeper check for `pages/`/`partials/` `.adoc` files: compares the structural "skeleton" of each EN/RU pair (heading levels, block titles, delimited blocks, block attributes, `include::` directives) so structural drift is caught even when line counts match.

- `--check-pages-table-cell-periods` (beta)

  Checks (per language) that the last sentence in a table cell doesn't end with a period, per house style.
  Exceptions, found by inspecting real tables in this doc set:

  - a cell containing a list — its last line is normal list-item prose and keeps its period (e.g. `table_compression.adoc`'s `compresslevel` cells);
  - a cell containing a NOTE/TIP/WARNING/IMPORTANT/CAUTION admonition (either the `LABEL: text` one-liner or a `[LABEL]`/`====` block);
  - a single space-free abbreviation like `Мин.`/`Макс.`, or a sentence ending in a known trailing abbreviation (`etc.`, `e.g.`, `i.e.`, `и т.д.`, `т.п.`, `и др.`) — the period there belongs to the abbreviation, not the sentence.

  Cells are tracked by lookahead rather than a real table parser: a blank line is never by itself a cell boundary (both `a|` cells and even plain `|` cells can hold several blank-line-separated paragraphs), so a line only counts as a cell's last line if the next non-blank line is `|===` or itself starts a new cell.
  A single physical line can also pack multiple `|`-separated plain cells (a compact header row like `|Algorithm |Default |Min |Max`); only a bare `|` cell (not `a|`/`m|`/etc.) is split this way.

- `--check-pages-translation` (beta; `-v` also flags RU lines containing common English stopwords)

  Checks `pages/` and `partials/` `.adoc` files for lines that look like they were never translated: walks EN and RU line-by-line and flags any prose line where RU is byte-identical to EN, skipping:

  - code blocks, attributes, and comments;
  - table cells;
  - code/keyword-only lines, such as headings and `term::` definitions;
  - a list item that's entirely a `` `code span` `` or a `*_bold-italic UI element name_*`.

This is a heuristic, not a full AsciiDoc parser.
Treat findings as a review list, not a hard failure.

## Sync a RU page after an EN edit (beta)

Heuristic aligner, not a semantic merge — review its output before trusting it; see the caveat below.

```bash
./docs_tool.py --sync en/modules/ROOT/pages/reference/utils/analyzedb.adoc
./docs_tool.py --sync <path/to/en/file.adoc> -n   # dry run: print the diff instead of writing
```

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
cd "$(git rev-parse --show-toplevel)"``

blocking_failed=0

echo "=== blocking checks ==="
python3 docs_tool.py \
  --check-pages-no-cyrillic \
  --check-pages-no-invisible-chars || blocking_failed=1

echo
echo "=== warn-only checks (do not block commit) ==="
python3 docs_tool.py \
  --check-examples-no-cyrillic \
  --check-examples-orphaned \
  --check-examples-parity \
  --check-images-orphaned \
  --check-nav-structure-parity \
  --check-pages-broken-refs \
  --check-pages-line-parity \
  --check-pages-no-unicode-dashes \
  --check-pages-orphaned || true

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

Only `--check-pages-no-cyrillic` and `--check-pages-no-invisible-chars` actually block the commit; the rest just print their findings.
Move a check from the warn-only block into the blocking one once you're ready to enforce it.
