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

## Tab completion (optional)

`docs_tool.py` supports shell tab completion for every flag, including all `--check-<name>` options — generated live from the script's own argument parser, so it never drifts out of sync when checks are added or renamed. This is optional; the tool works exactly the same without it.

```bash
pip install --user argcomplete   # one-time, not required to run the tool itself
```

Then add this to `~/.zshrc` (or `~/.bashrc`):

```bash
eval "$(python3 -m argcomplete.scripts.register_python_argcomplete docs_tool.py)"
```

Two details that matter here:

- Register the **bare filename** `docs_tool.py`, not `./docs_tool.py`. zsh resolves any path-qualified command (`./docs_tool.py`, `../foo/docs_tool.py`, an absolute path, ...) down to its basename before looking up which completer to run, so a registration under `./docs_tool.py` silently never matches and completion just beeps.
- The `python3 -m ...` form is used instead of the `register-python-argcomplete` binary because `pip install --user` often installs it to a directory that isn't on `$PATH` (e.g. `~/Library/Python/3.x/bin` on macOS); invoking the module directly sidesteps that.

Open a new shell (or `source ~/.zshrc`), then:

```bash
./docs_tool.py --check-<TAB>
```

lists every matching `--check-*` flag (as well as `--all-checks`, `--list-checks`, etc.). If `argcomplete` isn't installed, the script silently skips wiring it up and runs as normal.

## Usage

```bash
./docs_tool.py --check-<name> [--check-<name> ...] [-v] [--page NAME ...] [--external-root NAME=PATH ...]
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
Pass `--page NAME` (repeatable) to limit the per-file EN/RU checks — `pages-translation`, `pages-line-parity`, `pages-structure-parity`, `pages-no-cyrillic`, `pages-no-unicode-dashes`, `pages-no-invisible-chars`, `pages-ru-latin-homoglyphs`, `pages-stray-backticks`, `pages-unbalanced-delimiters`, `pages-table-cell-periods`, `pages-file-path-italics` — to just the page(s)/partial(s) whose filename stem matches `NAME`, e.g.:

```bash
./docs_tool.py --check-pages-translation -v --page resource_groups
```

`--check-tags-orphaned` also honors `--page`, but only to narrow *which files' own `tag::`/`end::` regions get reported on* — the usage scan (which file includes which tag) still covers the whole site regardless, since a tag defined in the filtered-in file can be pulled in from any other page:

```bash
./docs_tool.py --check-tags-orphaned --page external_data_formats
```

Whole-site checks (`pages-broken-refs`, `pages-orphaned`, `examples-*`, `images-orphaned`, `nav-structure-parity`) build a site-wide corpus (nav links, partial includers) before reporting, so `--page` doesn't narrow them at all — they always scan and report on everything regardless.

Pass the special value `--page UNCOMMITTED` instead of a name to scope to whatever `.adoc` files currently have uncommitted changes — staged, unstaged, or untracked — per `git status`.
If nothing's uncommitted, the check prints `OK: no uncommitted .adoc changes to check.` and exits `0` immediately.
This is what the [pre-commit hook](#pre-commit-hook) below uses, so a commit only gets checked against what it's actually touching instead of the whole site.

## Checks

Flags are named `--check-<target>-<check>`, where `<target>` is the directory scanned (`pages` covers `pages/` + `partials/`, `examples` covers `examples/`, `images` covers `images/`, `nav` covers `nav.adoc`, `tags` covers `tag::`/`end::` regions across `pages/` + `partials/` + `examples/`) and `<check>` is what it verifies.
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

  Checks (per language) that every file under `images/` is the actual resolved target of some `image:`/`image::`/`injectSvg:`/`injectSvg::`/`inlineSVG:`/`inlineSVG::` macro somewhere in `pages/` or `partials/` — anywhere in that language across the whole site, not just its own module, since a page in one module can reference another module's image via a qualified `image::<module>:path[]` macro, or, for a partial's image, via whichever module(s) actually include that partial.
  Ends with a total count and combined file size of the orphaned images found, as a rough gauge of cleanup impact.
  Dotfiles/dotdirs (e.g. macOS' `.DS_Store`, a stray `.git`) are skipped everywhere this tool scans a directory tree, not just here — they're never real Antora content.
  Resolution-based, not a basename-in-text match: if two different modules each have their own `images/foo.png`, only the one an actual reference resolves to counts as used, so a genuinely-unused duplicate is still caught even though its filename appears elsewhere in the site's text.

### Nav

- `--check-nav-structure-parity` (reports the first differing line by default; `-v` shows the full diff with file:line references)

  Compares the structural "skeleton" of each module's `nav.adoc` (list depth, `xref:`/`include::` targets) between EN and RU, plus any `partial$...adoc` files it includes.
  Translated labels are ignored; only the menu structure and link targets are compared.
  Modules without their own `nav.adoc` are silently skipped.

### Pages

- `--check-pages-broken-refs`

  Checks (per language) that every `xref:`, `include::`, `image:`/`image::`, `injectSvg:`/`injectSvg::`, `inlineSVG:`/`inlineSVG::`, and `link:`/`link::` reference found in `pages/`/`partials/` resolves to a real file (page, partial, example, image, or attachment) or, for anchor-only/fragment xrefs, a real anchor in the target.

  - Comments (`//` lines and `////` blocks) are skipped.
  - A `{doc-attribute}` used inside a reference target (e.g. `xref:{install-link}[]`) is substituted using that file's own `:name: value` attribute definitions before resolving.
  - `link:`/`link::` targets are checked as local files, not URLs -- an `http://`/`https://` target, a `mailto:` target, or a same-page `#anchor` target is skipped.
    A target using one of Antora's family attributes (`{attachmentsdir}`, `{examplesdir}`, `{imagesdir}`, `{partialsdir}` -- e.g. `link:{attachmentsdir}/sample.csv[]`, the common form for downloadable files) is resolved against that family's directory for the current module (or whichever module(s) actually include the file, if it's a partial).
    A target using any other `{attribute}` (one this tool can't see, e.g. something only the site's playbook defines) is left unchecked; a target with no attribute at all is a plain path relative to the including file, same as an unqualified `include::`.
  - A module-prefixed `xref:`/`include::`/`image:`/`image::` (e.g. `xref:how-to:page.adoc[]`, `include::how-to:partial$foo.adoc[]`, `image::get-started:connections/foo.png[]`) resolves against that sibling module if the prefix matches a discovered module.
    A reference fully qualified with this repo's own component name (e.g. `image::ADCM:ROOT:x.png[]` written inside docs-adcm itself -- a real, existing pattern, not just a hypothetical one) resolves the same way, against this repo's own modules.
    Otherwise it's treated as pointing outside this repo (e.g. `blog::x`, a genuinely different component like `include::ADPG:ROOT:partial$x.adoc[]` written from inside docs-adcm) and skipped.
  - `image:`/`image::` targets starting with `http://`/`https://` (a remote image) are skipped, not checked against the local `images/` directory.
  - An `image:`/`image::` written inside a partial is checked against the module(s) that actually include that partial (same `partial_includers` context used for bare xref/include resolution), not the partial file's own module -- Antora resolves it that way, so a partial's image only needs to exist in at least one includer's `images/`.
  - Anchors are matched against:
    - explicit `[#id]`/`[[id]]` markers (a `[[id]]` is recognized wherever it appears on a line, including inline mid-sentence or mid-list-item, not just on a line of its own), *and*
    - headings' Asciidoctor-autogenerated IDs (tried under a few common `idprefix`/`idseparator` conventions, since the site's actual playbook attributes aren't visible to this tool).
      So `== 6.23.3` satisfies `xref:page.adoc#6-23-3[]` even with no explicit anchor written.
      Underscores in a heading (e.g. `=== gp_segment_configuration`) are kept as literal characters, not stripped as italic markup, and non-Latin headings (e.g. Cyrillic RU ones) are slugified correctly too.
  - Anchor resolution follows module- and component-qualified `include::partial$...`/`include::page$...` chains, not just same-module ones.
  - By default, a reference into a component that isn't part of this repo (e.g. `xref:ADCM:ROOT:page.adoc[]`, pulled in from a separate Antora site like an ADCM docs repo) is left unchecked rather than reported broken, since this tool can't see that component's source.
    If you have that component's repo checked out locally, pass `--external-root NAME=PATH` (repeatable) to resolve against it too, e.g. `--external-root ADCM=../docs-adcm`.
    A typo'd or otherwise wrong `PATH` doesn't fail the run -- it just silently falls back to the same "unregistered, skip" behavior as not passing the flag at all, so a warning is printed to stderr at startup if `PATH` doesn't exist, isn't a directory, or has no `en/modules`/`ru/modules` under it.

- `--check-pages-file-path-italics` (beta; `-v` also prints the full line for each hit)

  Checks (per language) for file/directory names mentioned in plain prose without the italics (`_..._`) house style requires for them: a curated whitelist of config/unit-file-style extensions (`.conf`, `.yaml`/`.yml`, `.cfg`, `.ini`, `.toml`, `.json`, `.xml`, `.service`, `.socket`, `.log`, `.env`, `.pem`, `.crt`, `.key`, `.properties`, `.jar`, `.war`, `.rpm`, `.deb`, `.tar`, `.gz`, `.tgz`, `.whl`, `.zip`, `.h`, `.keytab`), well-known absolute-path prefixes (`/etc`, `/var`, `/opt`, `/usr/local`, `/usr/share`, `/home`), bare directory/file basenames (`bin`, `sbin`, `etc`, `lib`, `tmp`, `var`, `opt`, `src`) mentioned as `a`/`an`/`the <name> file/folder/directory/script/archive`, any *other* underscore- or slash-containing word (e.g. `greengage_path`, `backup/adb`) in that same slot, and common shell/tool dotfiles (`.bashrc`, `.bash_profile`, `.bash_login`, `.profile`, `.zshrc`, `.vimrc`, `.gitconfig`, `.psqlrc`, `.pgpass`, `.npmrc`, `.editorconfig`, `.gitignore`, `.env`, `.dockerignore`, `.eslintrc`, `.pylintrc`, `.htaccess`, `.htpasswd`, `.claude`, `.idea`).
  Deliberately narrow rather than exhaustive, to keep the false-positive rate low -- the basename list in particular excludes common generic-English words like `log`/`data`/`config`/`cache` ("a log file" is a generic description, not a reference to a directory literally named `log`).

  For the extension/path checks, already-formatted or non-prose spans are excluded before matching: code spans, bold, italics, bold-italics, any AsciiDoc macro (`xref:`, `link:`, `image:`/`image::`, etc.) and the `<<anchor,text>>` shorthand, and bare URLs.
  Whole code/literal blocks, `////` comment blocks, tables, headings, and block titles/captions are skipped outright, since none of these are italicized by convention regardless of what they mention.
  The basename and dotfile checks are the exception: they deliberately do *not* treat bold/code-span as already-exempt, since a directory basename or dotfile that's only ever bold or code-spanned (never italicized) is itself the finding, not something to wave through -- confirmed safe by checking that (unlike, say, `.service`/`.timer` extension matches, which turned out to have legitimate backtick use elsewhere as systemd unit names) a dotfile mention is unambiguously a literal file reference in this doc set.
  `bin`/`sbin`/`etc`/`tmp`/`opt` are additionally flagged wherever they're bold/code-spanned, with no "a/the X folder" phrase required at all (e.g. "for example, `bin`)" referring back to an earlier mention) -- `var`/`src`/`lib` stay gated behind that phrase even when marked, since they're common enough as generic variable-name/HTML-attribute/placeholder terms elsewhere (confirmed via false positives on synthetic "Declare a `var`..."/"the `src` attribute" cases) that bold/code alone isn't a reliable enough signal for them.
  The underscore-word generalization is deliberately underscore-only, not hyphen: hyphen was tried too and dropped after real hits on docs-adh turned out to be ordinary English compound adjectives ("a global-level file", "a zero-length file", "the first-level directory"), not filenames, whereas underscore had zero false positives across all four repos tested.
  A slash is also accepted as a connector alongside underscore, catching a relative path with no leading `/` that the absolute-path check above wouldn't (e.g. "the `backup/adb` folder") -- the one common English "/" idiom, "and/or", doesn't realistically combine with "file"/"folder" as its object, so this stayed clean across all four repos too.
  The trailing noun itself was also extended from file/folder/directory to include script/archive, backed by real, consistently-italicized usage across all four repos ("`_bin/yarn_` script", "`_.har_` archive", "`_tar.gz_` archives"). `package` was tried too and dropped: an OS package *name* (`oidentd`, `tzdata`, `libpam-ldapd`) is consistently kept in backticks throughout this doc set, never italicized -- a different, established convention, the same "stays in code spans" pattern as systemd unit names and config parameter names. A package *file* (e.g. "the `_.deb_` package") is still caught separately by the dotfile/extension checks either way.

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

- `--check-pages-ru-latin-homoglyphs` (beta; `-v` also prints the full line for each hit)

  Checks `ru/` pages/partials for Latin letters that look like they were meant to be Cyrillic — the mirror image of `--check-pages-no-cyrillic` (which only looks for Cyrillic contaminating `en/`; the reverse direction there, a stray Cyrillic letter inside an otherwise-Latin word like "A Сlient ID", is already caught by that check's broad scan, so it isn't repeated here).
  Two patterns, both requiring an actual script mix rather than flagging "any Latin in `ru/`" (which would flag every legitimate product name/command and be useless):

  - a word containing *both* Cyrillic and Latin letters — token boundary is any non-letter, so `PAM-аутентификация` is two clean single-script tokens, not one mixed one, a very common pattern in this doc set that must not misfire;
  - a standalone single Latin letter matching one of four Cyrillic/Latin homoglyph pairs that double as real one-letter Russian words: `а` ("and/but"), `о` ("about"), `с` ("with"), `у` ("at/by"). Requires true word boundaries — not adjacent to a letter *or* a hyphen — since a hyphenated identifier can otherwise leave a bare single letter as its own "word" (`gcc-c++`, `xerces-c-devel`, real package names, both false positives without this). Deliberately lowercase-only: uppercase `C` collided for real with "the C language" in a UDF/C-function doc.

  Two more exclusions for the standalone-letter pattern, both found via real false positives and both checked as an exact structural match rather than a loose "nearby punctuation" rule, so a genuine typo elsewhere in the same kind of sentence still gets flagged:

  - a single-letter code that's the *entire* content of a parenthetical, e.g. Postgres catalog docs' own `DEPENDENCY_AUTO (a)`/`SHARED_DEPENDENCY_OWNER (o)` convention for showing an enum's underlying char code (this also incidentally cleared the `config.y(a)ml` case noted below);
  - a single-letter code at the very start of a line immediately followed by `" | "`, e.g. `pg_dump.adoc`'s own `p | plain:::`/`c | custom:::`/`d | directory:::`/`t | tar:::` description-list enumerating `-F`/`--format`'s short codes.

  Found dozens of real typos across every repo tested during development (product/tool names like `ADСM`, `Сron`, `BlockСache`, `Сlient`, `Сoordinator`, `Сommunity` with a stray Cyrillic letter; recurring `с`/`а` preposition typos; abbreviations like `см.`/`МБ` with a stray Latin letter) — a strong, evidence-backed heuristic overall, with a small amount of known residual noise: rare bare parenthetical English phrases/acronym expansions (e.g. "(a server instance)", "Data Platform as a Service") that aren't wrapped in any excludable markup.
  Bold-italic (`*_..._*`) is excluded from the scan: this doc family uses it for verbatim third-party UI strings kept in English by convention (e.g. DBeaver's own "*_Connect to a database_*" dialog title), and real typos never occur inside that quoting convention.

- `--check-pages-stray-backticks`

  Checks (per language) that no `pages/`/`partials/` `.adoc` line has an odd number of backticks — almost always a missing or stray `` ` `` around an inline monospace span (e.g. a trailing `` ` `` left dangling after an `xref:...[]`, or a closing `` ` `` dropped from `` `code` ``).
  Lines inside comments (`//`, `////`) and listing/literal blocks (`----`, `....`) are skipped, and `` ++...++ `` passthrough spans are stripped before counting, since that's AsciiDoc's own way to embed a literal backtick inside a span (e.g. `` `++`++` `` to show the literal `` ` `` character) and would otherwise make a correctly paired line look unbalanced.

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

- `--check-pages-unbalanced-delimiters`

  Checks that every AsciiDoc block delimiter — open `--`, listing `----`, literal `....`, example `====`, sidebar `****`, quote `____`, passthrough `++++`, table `|===`, comment `////` — is properly closed once a page's full `include::partial$/page$/example$` chain is flattened (recursively, honoring `tag=`/`tags=` filtering and component/module qualification) into the single continuous document Asciidoctor actually renders.
  An unclosed one is almost always a forgotten closing delimiter, which silently swallows every following line into that block (or, for a table, corrupts everything after it) once rendered.

  Checking each file in isolation would misfire both ways on a block deliberately split across an include boundary — a real, existing pattern in this doc family: a shared partial opens a table and relies on whichever page includes it to supply the closing `|===`. Flattening first means the partial isn't wrongly reported as broken on its own, and the page isn't wrongly reported as broken for supplying a "stray" closing delimiter that's actually closing something the partial opened. Partials never reached by any page's include chain (in that language) — typically genuinely orphaned content, also caught by `--check-pages-orphaned`/`--check-examples-orphaned` for other reasons — are still checked standalone afterward, so a partial that isn't wired up anywhere doesn't silently lose delimiter coverage entirely.

  Tracked with a LIFO stack keyed by the delimiter's exact matched text (not just its family), mirroring how Asciidoctor itself lets you nest a *container* block (example/sidebar/quote/open/table) inside a same-type container by using a different length for the inner one (e.g. a 5-equals `=====` example block nested inside a 4-equals `====` one) — so only a line matching the text that opened the current innermost container can close it; a same-family line of a different length instead opens a new, independent nesting level.

  Listing, literal, and comment blocks are different: Asciidoctor treats them as verbatim/opaque leaves that can't contain a nested block of any kind, so once one is open, any other delimiter-looking line is just its raw content, not a real delimiter — e.g. a `psql` ASCII-art table's own `----` separator row, or an arbitrary run of dashes/dots/equals shown inside a terminal-output `....` block. Only a line matching the *exact* text that opened it can close such a block.

  A table cell's style prefix (`a|`, `e|`, `h|`, `l|`, `m|`, `s|`, `d|`) can be glued directly onto an opening delimiter with no space (e.g. `a|....` opening an AsciiDoc-cell's own literal block) — Asciidoctor re-parses that cell's content as its own mini-document starting right after the prefix, so the delimiter is recognized as if it were alone on its own line; the matching close is always written on its own plain line with no prefix.

  Known limitation: a commented-out `include::` line (inside a `////` block, or `//`-prefixed on its own) isn't specially detected and would incorrectly be resolved as if live. Also, since this is a LIFO stack rather than a real parser, a genuinely broken document could in principle have a stray unclosed delimiter accidentally "cancelled out" by an unrelated same-text delimiter much later in the same flattened document — not observed in practice, but a structural limit of this approach.

### Tags

- `--check-tags-orphaned`

  Finds `tag::NAME[]`/`end::NAME[]` regions (in `examples/`, `pages/`, or `partials/`) that are never actually pulled in by any `include::...[tag=NAME]` / `[tags=NAME;...]` elsewhere in the site — e.g. an example script defines a boilerplate `tag::teardown[]` block that no page ever includes, or a partial's tagged region gets orphaned after the page that used to include it is reworked to drop that tag.

  A tag counts as used if:

  - some `include::` names it directly via `tag=`/`tags=` (a `tags=` list can name several, `;`-separated, Asciidoctor style);
  - it's nested inside another region that is itself directly used this way — tag markers are just comments, so including the outer region pulls in everything between its `tag::`/`end::` pair, nested markers included;
  - the whole file is pulled in without a tag filter (a plain `include::...[]`, or a wildcarded `tags=**`/`tags=*`).

  A `!name` exclusion in a `tags=` list (`tags=parent;!child`) overrides nesting for that specific `include::` call site: a nested tag that's *only* ever pulled in by includes that immediately exclude it again is still orphaned, even though its enclosing region is used elsewhere. This is judged per call site, not merged across every include of the file — if one page does `tags=parent;!child` but another page does plain `tag=parent` (no exclusion), `child` is correctly recognized as used via that second page.

  `--page NAME` narrows which files' own tag regions get reported on (not the usage scan, which always covers the whole site — see [above](#scoping-to-specific-pages-with---page)).

  `include::` macros inside a commented-out line or a `////` block comment don't count as usage (they're dead in the rendered site too); macros inside a `----`/`....` listing block *do* count, since `include::example$file[tag=x]` living inside a source block — so the pulled-in snippet renders as code — is the normal way this is written, not illustrative text.

  Usage isn't limited to this repo's own content either: a tag defined here can be pulled in from a sibling Antora component instead, e.g. a docs-adbes page writing `include::ADB:how-to:metrics.adoc[tag=view_metrics_prometheus]`. Pass `--external-root NAME=PATH` (same flag as `--check-pages-broken-refs`, e.g. `--external-root ADBES=../docs-adbes`) and that component's `pages`/`partials` are scanned for `include::` macros too, so a tag only ever consumed that way is correctly recognized as used instead of reported orphaned. Without `--external-root`, such usage is invisible to this tool and the tag is reported orphaned even though it renders fine on the other site — same false-positive shape as an unregistered external component in `--check-pages-broken-refs`.

  A component/module-qualified `include::` with no family marker (e.g. `include::ADB:how-to:metrics.adoc[]`, `include::how-to:metrics.adoc[]`) defaults to the page family, the same way a bare `xref:module:page.adoc[]` already does — both `--check-tags-orphaned` and `--check-pages-broken-refs` resolve it that way.

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
