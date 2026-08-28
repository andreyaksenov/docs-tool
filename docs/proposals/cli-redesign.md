# Proposal: regroup the `docs_tool` CLI around the writing-quality pyramid

**Status:** implemented on branch `cli-redesign` for review · legacy `--check-*` flags kept working
**Scope:** CLI surface + rule IDs — no check *logic* changes
**Visual version:** [artifact](https://claude.ai/code/artifact/17a8e6b6-e251-411d-adf8-8e726809df3c)

New design proposals for this tool go in `docs/proposals/`.

**On this branch:** the `check`/`show`/`list`/`sync` surface, six families, `--target`,
multi-family `check chars markup`, and stable rule IDs (`CH01`…, shown by `list`; `show <id>`
prints one rule's full rationale).
**Deferred:** unified output format, `--format json`/`sarif`, inline `// docs_tool-ignore`
suppressions, the baseline file — all of which need every check refactored to emit structured
findings, a large separate change (see §6).
**Prototyped and dropped:** `--fix` (a check that reports shouldn't also mutate files), a
`.docs_tool.ini` config file (flags are enough), `--profile` (one hardcoded value),
`--lang en|ru` (`--page` covers "check what I touched"), and `sync --since REF` (nobody used it).

---

## 1. The problem

The flag namespace is organized by the wrong axis: `--check-<target-dir>-<what>`.
"Which directory it scans" is an implementation detail. That framing produces:

- 22 sibling flags with no visible structure — you consult `--list-checks` every time;
- `--check-examples-no-cyrillic` and `--check-pages-no-cyrillic` as separate flags for
  what the README itself calls "the same check";
- the block-vs-warn distinction — the one thing a writer actually reasons about — living
  *nowhere in the tool*. It is encoded in the pre-commit hook's shell script, by which of
  two `python3 docs_tool.py` invocations a check is listed under.

The useful axis is **where a rule's authority comes from**. That also predicts how
deterministic a check is, whether it is safe to hard-block, its language scope, and whether
`--page` can narrow it.

## 2. The model — a six-level pyramid

| Lvl | Family | Tier | Authority | Checks it holds today | Default |
|----:|--------|------|-----------|-----------------------|---------|
| L0 | `chars`  | universal  | Unicode / encoding | no-invisible-chars, no-unicode-dashes, ru-latin-homoglyphs, no-cyrillic (EN) | block |
| L1 | `markup` | universal  | AsciiDoc spec | stray-backticks, unbalanced-delimiters | block |
| L2 | `refs`   | universal  | Antora reference resolution | broken-refs, pages/partials/examples/images/tags-orphaned | block |
| L3 | `style`  | house      | Arenadata style guide | no-yo, file-path-italics, table-cell-periods | warn |
| L4 | `terms`  | house      | controlled vocabulary (glossary) | pages-terminology *(+ future monolingual term rules)* | warn |
| L5 | `l10n`   | relational | "RU must mirror EN" | line-parity, structure-parity, translation, examples-parity, nav-structure-parity | warn |

Each level assumes the ones below it hold — there is no point flagging a terminology drift
in a file whose markup does not parse.

- **universal** (chars, markup, refs) — deterministic, language-agnostic → block by default
- **house** (style, terms) — per-vendor rules → warn by default
- **relational** (l10n) — needs both trees aligned → warn by default

### Why `terms` is its own family

Mechanically `pages-terminology` looks like `l10n` (it walks EN/RU by aligned line index and
inherits the same drift-misalignment failure mode). But by authority it is a third thing —
a **controlled vocabulary**. A terminology hit is not drift (the translation can be faithful
and still use a rejected synonym) and it is not formatting. The deciding factor is the
growth path: the glossary is the natural home for *monolingual* term rules — product-name
casing, forbidden-word lists — which are neither drift nor style. Folding `terms` into
`l10n` strands those. Do **not** merge it into `style`: that family's value is being
monolingual and `--page`-scopeable, and terminology breaks both.

## 3. The command surface

```
docs_tool check <family> [<family> ...] [--<rule> ...] [--target NAME] [--verbose]
                                        [--page NAME ...] [--glossary PATH ...] [--external-root NAME=PATH ...]
docs_tool show <rule|rule-id>     # one rule's full rationale (docstring)
docs_tool list                   # the family/rule map, one line per rule
docs_tool list rules             # every rule as a `check ...` command
docs_tool list targets           # what each --target value scopes to
docs_tool sync <en-file> [--dry-run]
```

`list` enumerates; `show` describes one item — the `git branch` / `git show` split.

No short flag aliases — every option is spelled out (`--verbose`, not `-v`) so a command
or a CI log reads for itself. `-h` is the one exception, since argparse provides it.

Selection rules:

| Invocation | Runs |
|---|---|
| `check <family> [<family> ...]` | every rule in each family, all scan targets |
| `check all` | every family |
| `check <family> --<rule>` | that rule, target `pages` (or its sole target) — one family only |
| `check <family> --<rule> --target X` | that rule, target `X` |
| `check <family> --target X` | every rule in the family that has a target `X` |
| `--target all` | every target of whatever is selected |

Default `--target` is `pages` (which means `pages/` + `partials/`, as today). `refs` always
scans the whole site regardless of `--page`.

### Whole families — the ergonomic win

```bash
docs_tool check chars              # invisible + dashes + homoglyphs + cyrillic-in-EN + examples
docs_tool check markup             # stray-backticks + unbalanced-delimiters
docs_tool check refs               # broken-refs + every orphan check
docs_tool check refs --orphaned --target all   # every orphan target, no broken-refs
docs_tool check style              # the Arenadata house-style set
docs_tool check terms              # glossary check (needs a *-glossary.psv)
docs_tool check l10n               # all EN<->RU drift checks
docs_tool check all                # everything
```

### The `--page` paragraph shrinks to one sentence

> `--page` narrows `chars`, `markup`, `style`, `terms`, and `l10n`; `refs` always scans site-wide.

### The pre-commit hook, before → after

Today: two ~15-line `python3 docs_tool.py` invocations, block/warn split implied by which
one a check sits in. After — the split is explicit in the hook, two `check` calls:

```bash
docs_tool check chars markup --page UNCOMMITTED \
  || { echo "blocked" >&2; exit 1; }        # deterministic -> block the commit
docs_tool check style terms l10n refs --page UNCOMMITTED || true   # heuristic -> report only
```

`list` marks each family `block` / `warn by default` (from `TIERS`), so the hook author knows
which is which. A `check --profile <name>` flag and a `PROFILES` table were prototyped and
dropped — one hardcoded profile is just machinery for two lines of shell, and the config file
that would have made custom profiles worthwhile is gone too (below).

A `.docs_tool.ini` config file was prototyped (INI, glossary / external-root defaults,
`[profile:*]` sections) and dropped — flags are explicit and discoverable, and the config
file's only real payoff was baking in docs-adcm's four `--external-root` values, which a
shell alias handles just as well.

## 4. Full migration map

Every current flag → its replacement. Nothing is dropped; the old flags still work.

| # | Today | After |
|--:|-------|-------|
|  1 | `--check-examples-no-cyrillic`          | `docs_tool check chars --no-cyrillic --target examples` |
|  2 | `--check-examples-orphaned`             | `docs_tool check refs --orphaned --target examples` |
|  3 | `--check-examples-parity`               | `docs_tool check l10n --examples` |
|  4 | `--check-images-orphaned`               | `docs_tool check refs --orphaned --target images` |
|  5 | `--check-nav-structure-parity`          | `docs_tool check l10n --nav` |
|  6 | `--check-pages-broken-refs`             | `docs_tool check refs --broken` |
|  7 | `--check-pages-file-path-italics` *(beta)* | `docs_tool check style --file-path-italics` |
|  8 | `--check-pages-line-parity`             | `docs_tool check l10n --lines` |
|  9 | `--check-pages-no-cyrillic`             | `docs_tool check chars --no-cyrillic` |
| 10 | `--check-pages-no-invisible-chars`      | `docs_tool check chars --no-invisible` |
| 11 | `--check-pages-no-unicode-dashes`       | `docs_tool check chars --dashes` |
| 12 | `--check-pages-no-yo`                   | `docs_tool check style --no-yo` |
| 13 | `--check-pages-orphaned`                | `docs_tool check refs --orphaned --target pages` |
| 14 | `--check-pages-ru-latin-homoglyphs` *(beta)* | `docs_tool check chars --homoglyphs` |
| 15 | `--check-pages-stray-backticks`         | `docs_tool check markup --backticks` |
| 16 | `--check-pages-structure-parity` *(beta)* | `docs_tool check l10n --structure` |
| 17 | `--check-pages-table-cell-periods` *(beta)* | `docs_tool check style --table-cell-periods` |
| 18 | `--check-pages-terminology` *(beta)*    | `docs_tool check terms` |
| 19 | `--check-pages-translation` *(beta)*    | `docs_tool check l10n --untranslated` |
| 20 | `--check-pages-unbalanced-delimiters`   | `docs_tool check markup --delimiters` |
| 21 | `--check-partials-orphaned`             | `docs_tool check refs --orphaned --target partials` |
| 22 | `--check-tags-orphaned`                 | `docs_tool check refs --orphaned --target tags` |

## 5. `sync`

Lifts to a top-level verb — `docs_tool sync <en-file> [--dry-run]`, bare-filename resolution
unchanged. `align` would be the more honest name (the README calls it "a heuristic aligner,
not a semantic merge"), but the accuracy gain is not worth the churn across ~12 vendored
copies. Not hidden under `check` (it writes files). Not direction-namespaced (`sync ru`) —
it never touches EN. `--since REF` (override the reworded-line baseline) was dropped —
nobody used it, and the default (last commit touching RU) is right in the common case.

## 6. Orthogonal improvements

Ranked by value; independent of the grouping.

Done on this branch:

- **Stable rule IDs** — `CH01`/`MK01`/`RF02`/`ST01`/`TM01`/`LN02`… in `RULE_IDS`, shown by `list`.
- **`--target`** scan-target flag instead of `pages-` vs `examples-` prefixes.
- **`list` / `show`** — `list` is the one-line-per-rule family map (a `SUMMARIES` blurb each),
  plus `list rules` / `list targets`; `show <rule|id>` prints one rule's full docstring.
  (`explain` was folded into `list`, then split back out as `show` — `list` enumerates, `show` describes.)
- **"rule"** is the user-facing name for one check (`--no-yo`, `ST01`); families group rules.
  Internally the function registry is still `CHECKS` and the functions `check_*`.
- **multi-family `check`** — `check chars markup` runs both; `check all` runs everything.
- **`--all-checks` / `check all` no longer abort** when `terms` is swept in without a glossary —
  it's dropped with a note; a bare `check terms` still errors.

Deferred — each needs every check refactored to *return* structured `Finding` objects instead
of `print()`ing, a large change that also rewrites the output-assertion tests (the safety net)
and bloats the branch:

- **One output format everywhere** — `<LEVEL> <rule-id> <path>:<line>:<col>: <message>`.
  Today there are four formats and some are not IDE-clickable.
- **`--format json` / `--format sarif`** — SARIF gives GitHub code-scanning annotations for free.
- **Inline suppressions** — `// docs_tool-ignore: CH04` in the `.adoc`. Biggest usability win
  for the beta checks.
- **Baseline file** — `docs_tool baseline` snapshots findings; later runs report only new ones.

Considered and rejected:

- **`--fix`** (in-place autofix for the deterministic char rules). A check's job is to
  report, not mutate files; if autofix is wanted later it belongs in a separate
  `docs_tool fix` verb.
- **`.docs_tool.ini` config file** (glossary / external-root defaults, `[profile:*]`
  sections). Flags are explicit and discoverable; the only real payoff was baking in
  docs-adcm's four `--external-root` values, which a shell alias covers.
- **`check --profile <name>`** + a `PROFILES` table. One hardcoded profile is just machinery
  for two lines of shell; the hook expresses block-vs-warn with two `check` calls, and `list`
  labels each family so the author knows which is which.

## 7. Migration & compatibility

`docs_tool.py` is copied — untracked — into ~12 sibling repos at drifting versions,
refreshed by hand. So:

- **Fewer, bigger moves.** Every change propagates by manual copy.
- **Every `--check-<old>` flag still works**, routed through the legacy parser (`main()`
  dispatches on `argv[0]`: `check`/`show`/`list`/`sync` → new surface, anything else → legacy).
  `docs_tool.py --list-checks` still prints the old flag list; `docs_tool list rules`
  prints the new `check ...` command for each, one per line, sorted by rule ID.

Not done: over-nesting (two levels — family then rule — is the limit). Exit codes are a
plain `0` clean / `1` findings everywhere — no severity tiers in the exit code.

## 8. Suggested sequencing

| Phase | Work | Status |
|------:|------|--------|
| 1 | Rule IDs + unified output format + JSON | rule IDs **done**; output format + JSON deferred |
| 2 | Subcommand restructure with back-compat aliases | **this branch** |
| 3 | ~~Named profiles~~ → hook expresses block/warn in shell | reverted; `--profile` dropped |
| 4 | Inline suppressions + baseline → promote betas to blocking | deferred (needs the findings refactor) |
| — | multi-family `check` (extra) | **this branch** |

## Open questions

- Family name for L3: `style` (vendor-neutral, room for `style_guide = "arenadata"` later)
  vs `arenadata-guidelines` (honest about whose rules these are).
- Six families or five (folding `terms` into `l10n --terminology`).
- Named check sets: needed at all, or is "two `check` calls in the hook" enough? Dropped for now.
- Rule-ID scheme: `CH01` (2-letter family + 2 digits) vs `L10N002`-style. Current choice keeps
  IDs short; renumbering later is a breaking change for anything that pins them.
