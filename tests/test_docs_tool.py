"""Unit and fixture-based integration tests for docs_tool.py.

Run with:
    python3 -m unittest discover -s tests
or a single case:
    python3 -m unittest tests.test_docs_tool.ImagesOrphanedTests

Integration tests build a throwaway Antora tree under a tempdir and point
docs_tool's module-level EN_MODULES_ROOT/RU_MODULES_ROOT at it (the same
technique used ad hoc against scratch fixtures throughout development),
instead of running against this repo's real content -- that keeps them
independent of whatever docs currently exist here.
"""
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import docs_tool as dt


class FixtureTestCase(unittest.TestCase):
    """Base class: a fresh empty Antora tree per test, with docs_tool's
    roots pointed at it. Restores real state in tearDown so tests can run
    in any order without leaking into each other or into a real repo."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="docs_tool_test_")
        self.root = Path(self._tmpdir)
        self._orig_en = dt.EN_MODULES_ROOT
        self._orig_ru = dt.RU_MODULES_ROOT
        self._orig_external = dt.EXTERNAL_COMPONENTS
        self._orig_page_filter = dt._PAGE_FILTER
        self._orig_glossary = dt.GLOSSARY
        dt.EN_MODULES_ROOT = self.root / "en" / "modules"
        dt.RU_MODULES_ROOT = self.root / "ru" / "modules"
        dt.EXTERNAL_COMPONENTS = {}
        dt._PAGE_FILTER = None
        dt.GLOSSARY = {}
        dt._OWN_COMPONENT_NAME_CACHE.clear()

    def tearDown(self):
        dt.EN_MODULES_ROOT = self._orig_en
        dt.RU_MODULES_ROOT = self._orig_ru
        dt.EXTERNAL_COMPONENTS = self._orig_external
        dt._PAGE_FILTER = self._orig_page_filter
        dt.GLOSSARY = self._orig_glossary
        dt._OWN_COMPONENT_NAME_CACHE.clear()
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def write(self, rel_path: str, content: str = "") -> Path:
        """Write a file relative to the fixture root (e.g.
        "en/modules/ROOT/pages/index.adoc"), creating parent dirs."""
        p = self.root / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def antora_yml(self, lang: str, name: str, version: str = "1.0"):
        self.write(f"{lang}/antora.yml", f"name: {name}\nversion: '{version}'\n")

    @staticmethod
    def run_check(check_fn, *args, **kwargs):
        """Runs a check_*() function with stdout captured, returning
        (ok, output_text) instead of letting findings print to the real
        terminal."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = check_fn(*args, **kwargs)
        return ok, buf.getvalue()


class ResolveModuleRefTests(unittest.TestCase):
    """Unit tests for _resolve_module_ref -- no filesystem needed."""

    def setUp(self):
        self.roots = {"ROOT": Path("en/modules/ROOT"), "how-to": Path("en/modules/how-to")}

    def test_sibling_module_resolves(self):
        result = dt._resolve_module_ref("how-to", "page.adoc", self.roots, "en")
        self.assertEqual(result, (Path("en/modules/how-to"), "page.adoc"))

    def test_unregistered_external_component_is_none(self):
        result = dt._resolve_module_ref("ADCM", "ROOT:page.adoc", self.roots, "en")
        self.assertIsNone(result)

    def test_registered_external_component_resolves_its_module(self):
        external = {"en": {"ROOT": Path("/tmp/adcm/en/modules/ROOT")}}
        try:
            dt.EXTERNAL_COMPONENTS = {"ADCM": external}
            result = dt._resolve_module_ref("ADCM", "ROOT:page.adoc", self.roots, "en")
            self.assertEqual(result, (Path("/tmp/adcm/en/modules/ROOT"), "page.adoc"))
        finally:
            dt.EXTERNAL_COMPONENTS = {}

    def test_registered_external_component_defaults_to_root_module(self):
        external = {"en": {"ROOT": Path("/tmp/adcm/en/modules/ROOT")}}
        try:
            dt.EXTERNAL_COMPONENTS = {"ADCM": external}
            result = dt._resolve_module_ref("ADCM", "page.adoc", self.roots, "en")
            self.assertEqual(result, (Path("/tmp/adcm/en/modules/ROOT"), "page.adoc"))
        finally:
            dt.EXTERNAL_COMPONENTS = {}

    def test_self_qualified_own_name_resolves_like_unqualified(self):
        """image::ADB:how-to:page.adoc[] written inside this repo's own
        content (docs-adcm's real-world image::ADCM:ROOT:...[] pattern)
        must resolve the same as the unqualified how-to:page.adoc form."""
        result = dt._resolve_module_ref("ADB", "how-to:page.adoc", self.roots, "en", own_name="ADB")
        self.assertEqual(result, (Path("en/modules/how-to"), "page.adoc"))

    def test_own_name_mismatch_is_still_unresolved(self):
        result = dt._resolve_module_ref("ADCM", "ROOT:page.adoc", self.roots, "en", own_name="ADB")
        self.assertIsNone(result)


class ParseIncludeAttrsTests(unittest.TestCase):
    def test_no_attrs_means_whole_file(self):
        tags, negated, whole_file = dt._parse_include_attrs("")
        self.assertEqual((tags, negated, whole_file), (set(), set(), True))

    def test_leveloffset_only_is_still_whole_file(self):
        tags, negated, whole_file = dt._parse_include_attrs("leveloffset=+1")
        self.assertTrue(whole_file)
        self.assertEqual(tags, set())

    def test_single_tag(self):
        tags, negated, whole_file = dt._parse_include_attrs("tag=intro")
        self.assertEqual(tags, {"intro"})
        self.assertFalse(whole_file)

    def test_tags_list_with_negation(self):
        tags, negated, whole_file = dt._parse_include_attrs("tags=parent;!child")
        self.assertEqual(tags, {"parent"})
        self.assertEqual(negated, {"child"})
        self.assertFalse(whole_file)

    def test_wildcard_tags_means_whole_file(self):
        tags, negated, whole_file = dt._parse_include_attrs("tags=**")
        self.assertTrue(whole_file)


class ParseTagRegionsTests(unittest.TestCase):
    def test_simple_region(self):
        lines = ["intro text", "tag::part-01[]", "body", "end::part-01[]", "outro"]
        regions = dt._parse_tag_regions(lines)
        self.assertEqual(regions, [("part-01", 2, 4)])

    def test_nested_regions_pair_by_name_not_stack_order(self):
        """connect.adoc's real part-02-wraps-part-03 pattern: an inner tag
        closes before its outer one, so pairing must match by name, not
        assume strict LIFO order."""
        lines = [
            "tag::outer[]",
            "tag::inner[]",
            "body",
            "end::inner[]",
            "more",
            "end::outer[]",
        ]
        regions = dt._parse_tag_regions(lines)
        self.assertEqual(set(regions), {("inner", 2, 4), ("outer", 1, 6)})


class ScanDelimiterStackTests(unittest.TestCase):
    """Unit tests for _scan_delimiter_stack -- no filesystem needed. Feeds
    plain (file, lineno, text) triples through the stream directly rather
    than via _flatten_delimiter_lines, so these exercise the balancing
    algorithm itself in isolation."""

    @staticmethod
    def stream(lines, file="f.adoc"):
        return [(file, i, l) for i, l in enumerate(lines, 1)]

    def test_balanced_nested_blocks_return_empty(self):
        lines = ["====", "content", "===="]
        self.assertEqual(dt._scan_delimiter_stack(self.stream(lines)), [])

    def test_missing_table_close_is_pinpointed_not_cascaded(self):
        """Regression test for the foreign-tables.adoc bug: a table opened
        with `|===` inside an example block, with no matching `|===`
        before the example block's own `====` closes around it. A naive
        LIFO would treat the mismatched `====` as opening a new nesting
        level and misattribute the imbalance to unrelated, far-away lines;
        this must instead pin the blame on the actual unclosed `|===`."""
        lines = [
            "====",         # 1: open example block
            "[cols=\"1\"]",  # 2
            "|===",         # 3: open table -- never closed
            "cell content",  # 4
            "====",         # 5: closes the example block, table still open
            "====",         # 6: open+close a second, unrelated example block
            "content",      # 7
            "====",         # 8
        ]
        result = dt._scan_delimiter_stack(self.stream(lines))
        self.assertEqual(result, [("|===", "f.adoc", 3)])

    def test_genuine_different_length_nesting_still_balances(self):
        """A 5-equals example block nested inside a 4-equals one (real,
        supported Asciidoctor nesting) must still balance cleanly -- the
        deeper-stack recovery must not fire when the mismatch really is a
        new nesting level, not a bug."""
        lines = ["====", "=====", "inner content", "=====", "outer content", "===="]
        self.assertEqual(dt._scan_delimiter_stack(self.stream(lines)), [])

    def test_opaque_listing_block_content_is_not_mistaken_for_delimiters(self):
        """A `----` separator row inside a psql-style ASCII table shown
        verbatim inside a listing block must not be treated as closing or
        nesting anything; only the exact `----` that opened it can close."""
        lines = ["----", "id | name", "----+------", "1  | a", "----"]
        self.assertEqual(dt._scan_delimiter_stack(self.stream(lines)), [])

    def test_unclosed_delimiter_at_eof_is_still_reported(self):
        lines = ["====", "content"]
        result = dt._scan_delimiter_stack(self.stream(lines))
        self.assertEqual(result, [("====", "f.adoc", 1)])


class ComponentPrefixRegexTests(unittest.TestCase):
    def test_plain_module_prefix(self):
        m = dt._COMPONENT_PREFIX_RE.match("how-to:page.adoc")
        self.assertEqual(m.group(0), "how-to:")

    def test_no_match_for_bare_relative_path(self):
        self.assertIsNone(dt._COMPONENT_PREFIX_RE.match("some-file.adoc"))


class AntoraFamilyAttrRegexTests(unittest.TestCase):
    def test_attachmentsdir_with_subpath(self):
        m = dt._ANTORA_FAMILY_ATTR_RE.match("{attachmentsdir}/sample.csv")
        self.assertEqual(m.group(1), "attachmentsdir")
        self.assertEqual(m.group(2), "sample.csv")

    def test_unrelated_attribute_does_not_match(self):
        self.assertIsNone(dt._ANTORA_FAMILY_ATTR_RE.match("{install-link}"))


class IterFilesTests(unittest.TestCase):
    """Regression test for the .DS_Store bug: pathlib's rglob("*") matches
    dotfiles even though a shell glob wouldn't."""

    def test_dotfiles_and_dotdirs_are_skipped(self):
        tmpdir = tempfile.mkdtemp(prefix="docs_tool_iterfiles_")
        try:
            root = Path(tmpdir)
            (root / "sub").mkdir()
            (root / ".DS_Store").write_text("")
            (root / "real.png").write_text("")
            (root / "sub" / ".DS_Store").write_text("")
            (root / "sub" / "real2.png").write_text("")
            found = {p.name for p in dt._iter_files(root)}
            self.assertEqual(found, {"real.png", "real2.png"})
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class LoadExternalComponentsTests(unittest.TestCase):
    def test_valid_path_produces_no_warning(self):
        tmpdir = tempfile.mkdtemp(prefix="docs_tool_ext_")
        try:
            root = Path(tmpdir)
            (root / "en" / "modules" / "ROOT").mkdir(parents=True)
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                components = dt._load_external_components([f"ADCM={root}"])
            self.assertEqual(buf.getvalue(), "")
            self.assertIn("ROOT", components["ADCM"]["en"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_nonexistent_path_warns(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            components = dt._load_external_components(["ADCM=/no/such/path/at/all"])
        self.assertIn("does not exist", buf.getvalue())
        self.assertEqual(components["ADCM"]["en"], {})

    def test_path_with_no_modules_warns(self):
        tmpdir = tempfile.mkdtemp(prefix="docs_tool_ext_empty_")
        try:
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                dt._load_external_components([f"ADCM={tmpdir}"])
            self.assertIn("no en/modules or ru/modules", buf.getvalue())
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_path_that_is_a_file_warns(self):
        tmpdir = tempfile.mkdtemp(prefix="docs_tool_ext_file_")
        try:
            file_path = Path(tmpdir) / "not-a-dir"
            file_path.write_text("")
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                dt._load_external_components([f"ADCM={file_path}"])
            self.assertIn("not a directory", buf.getvalue())
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class LoadGlossaryTests(unittest.TestCase):
    def _load(self, rows_text: str):
        """rows_text is the CSV body (without header row/comments)."""
        tmpdir = tempfile.mkdtemp(prefix="docs_tool_glossary_")
        try:
            path = Path(tmpdir) / "glossary.csv"
            path.write_text("# a comment\nen,ru,ru_pattern,note\n" + rows_text, encoding="utf-8")
            return dt._load_glossary([str(path)])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_comment_and_header_lines_skipped(self):
        glossary = self._load("host,хост,хост<>,\n")
        self.assertEqual(set(glossary), {"host"})

    def test_rows_sharing_en_term_merge_with_note_ignored_for_matching(self):
        glossary = self._load(
            "session,сессия,сесси<>,generic database sense\n"
            "session,сеанс,сеанс<>,bounded maintenance-operation sense\n"
        )
        self.assertEqual(set(glossary), {"session"})
        self.assertEqual(glossary["session"]["ru_display"], {"сессия", "сеанс"})
        self.assertEqual(len(glossary["session"]["patterns"]), 2)

    def test_missing_file_exits(self):
        with self.assertRaises(SystemExit):
            dt._load_glossary(["/no/such/glossary/file.csv"])

    def test_row_missing_pattern_is_skipped_with_warning(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            glossary = self._load("host,хост,\n")
        self.assertEqual(glossary, {})
        self.assertIn("missing en/ru_pattern", buf.getvalue())


class DiscoverDefaultGlossariesTests(unittest.TestCase):
    """--glossary's fallback: every *-glossary.csv directly under the
    current directory, so a docs repo carrying its own glossary doesn't
    need --glossary spelled out on every run."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="docs_tool_discover_glossary_")
        self._orig_cwd = os.getcwd()
        os.chdir(self._tmpdir)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_no_match_returns_empty(self):
        self.assertEqual(dt._discover_default_glossaries(), [])

    def test_single_match_found(self):
        Path("greengagedb-glossary.csv").write_text("en,ru,ru_pattern,note\n", encoding="utf-8")
        self.assertEqual(dt._discover_default_glossaries(), ["greengagedb-glossary.csv"])

    def test_multiple_matches_found_sorted(self):
        Path("zzz-glossary.csv").write_text("en,ru,ru_pattern,note\n", encoding="utf-8")
        Path("aaa-glossary.csv").write_text("en,ru,ru_pattern,note\n", encoding="utf-8")
        self.assertEqual(dt._discover_default_glossaries(), ["aaa-glossary.csv", "zzz-glossary.csv"])

    def test_non_matching_files_ignored(self):
        Path("glossary.csv").write_text("en,ru,ru_pattern,note\n", encoding="utf-8")  # no "-glossary" prefix
        Path("notes-glossary.txt").write_text("irrelevant\n", encoding="utf-8")  # wrong extension
        self.assertEqual(dt._discover_default_glossaries(), [])

    def test_subdirectory_not_searched(self):
        Path("sub").mkdir()
        (Path("sub") / "nested-glossary.csv").write_text("en,ru,ru_pattern,note\n", encoding="utf-8")
        self.assertEqual(dt._discover_default_glossaries(), [])


class CompileGlossaryPatternTests(unittest.TestCase):
    def _matches(self, ru_pattern: str, ru_line: str) -> bool:
        pattern = dt._compile_glossary_pattern(ru_pattern)
        return all(regex.search(ru_line) for regex in pattern)

    def test_stem_token_matches_declined_form(self):
        self.assertTrue(self._matches("таблиц<>", "в случае читающих таблиц распаковка выполняется"))
        self.assertTrue(self._matches("таблиц<>", "это таблица"))

    def test_stem_token_requires_word_boundary(self):
        # "стол<>" must not match inside an unrelated longer word like "престол".
        self.assertFalse(self._matches("стол<>", "царский престол"))
        self.assertTrue(self._matches("стол<>", "деревянный стол"))

    def test_bare_token_requires_exact_word(self):
        self.assertTrue(self._matches("NOT NULL", "ограничение NOT NULL здесь"))
        self.assertFalse(self._matches("NOT NULL", "ограничение NOTNULL здесь"))

    def test_missing_word_does_not_match(self):
        self.assertFalse(self._matches("хеш<>", "здесь этого слова нет"))

    def test_multiword_pattern_requires_all_tokens_any_order(self):
        self.assertTrue(self._matches(
            "стоимостн<> оптимизатор<> запрос<>",
            "запросов используется новый оптимизатор, стоимостной по своей природе",
        ))
        self.assertFalse(self._matches(
            "стоимостн<> оптимизатор<> запрос<>",
            "используется новый оптимизатор запросов",  # missing "стоимостн..."
        ))

    def test_entry_satisfied_by_any_alternative_pattern(self):
        entry = {
            "ru_display": {"сессия", "сеанс"},
            "patterns": [dt._compile_glossary_pattern("сесси<>"), dt._compile_glossary_pattern("сеанс<>")],
        }
        self.assertTrue(dt._glossary_entry_satisfied(entry, "начните новый сеанс"))
        self.assertTrue(dt._glossary_entry_satisfied(entry, "текущая сессия истекла"))
        self.assertFalse(dt._glossary_entry_satisfied(entry, "текущее подключение истекло"))

    def test_do_not_translate_entry_requires_verbatim_en(self):
        entry = {"ru_display": {"не переводить"}, "patterns": [dt._compile_glossary_pattern("Greengage DB")]}
        self.assertTrue(dt._glossary_entry_satisfied(entry, "работает в Greengage DB кластере"))
        self.assertFalse(dt._glossary_entry_satisfied(entry, "работает в кластере gpdb"))


class ImagesOrphanedTests(FixtureTestCase):
    def test_duplicate_basename_only_unused_copy_is_flagged(self):
        """Regression test for the promql-prometheus-query-language_dark.png
        bug: two modules each have their own images/shared.png, only one is
        referenced -- a basename-substring check would clear both."""
        self.antora_yml("en", "TEST")
        self.write("en/modules/mod-a/pages/page-a.adoc", "image::shared.png[]\n")
        self.write("en/modules/mod-a/images/shared.png", "used")
        self.write("en/modules/mod-b/images/shared.png", "unused duplicate")

        ok, output = self.run_check(dt.check_images_orphaned)
        self.assertFalse(ok)
        self.assertIn("mod-b", output)
        self.assertIn("shared.png", output)
        self.assertNotIn(str(dt.EN_MODULES_ROOT / "mod-a" / "images" / "shared.png"), output)

    def test_substring_collision_does_not_hide_a_real_orphan(self):
        """Regression test for images/services.png being hidden by
        images/adb_add_services.png (an unrelated file whose name happens
        to end with "services.png") under the old basename-in-text check."""
        self.antora_yml("en", "TEST")
        self.write("en/modules/ROOT/pages/page.adoc", "image::adb_add_services.png[]\n")
        self.write("en/modules/ROOT/images/adb_add_services.png", "used")
        self.write("en/modules/ROOT/images/services.png", "genuinely unused")

        ok, output = self.run_check(dt.check_images_orphaned)
        self.assertFalse(ok)
        self.assertIn("services.png", output)

    def test_inlinesvg_macro_counts_as_usage(self):
        """Regression test: inlineSVG:icon.svg[] (a real macro used for
        get-started card icons) must count as usage, not just image:/
        image::/injectSvg:/injectSvg::."""
        self.antora_yml("en", "TEST")
        self.write("en/modules/ROOT/pages/page.adoc", "inlineSVG:icons/plus.svg[]\n")
        self.write("en/modules/ROOT/images/icons/plus.svg", "svg")

        ok, output = self.run_check(dt.check_images_orphaned)
        self.assertTrue(ok, output)

    def test_commented_out_reference_does_not_count_as_usage(self):
        self.antora_yml("en", "TEST")
        self.write("en/modules/ROOT/pages/page.adoc", "// image::dead.png[]\n")
        self.write("en/modules/ROOT/images/dead.png", "unused")

        ok, output = self.run_check(dt.check_images_orphaned)
        self.assertFalse(ok)
        self.assertIn("dead.png", output)


class TagsOrphanedTests(FixtureTestCase):
    def test_unused_tag_is_flagged(self):
        self.antora_yml("en", "TEST")
        self.write("en/modules/ROOT/pages/page.adoc", "intro\n")
        self.write(
            "en/modules/ROOT/partials/snippet.adoc",
            "tag::used[]\nkept\nend::used[]\ntag::orphan[]\ndead\nend::orphan[]\n",
        )
        self.write("en/modules/ROOT/pages/other.adoc", "include::partial$snippet.adoc[tag=used]\n")

        ok, output = self.run_check(dt.check_tags_orphaned)
        self.assertFalse(ok)
        self.assertIn("tag::orphan[]", output)
        self.assertNotIn("tag::used[]", output)

    def test_negated_tag_in_nested_include_is_still_orphaned(self):
        self.antora_yml("en", "TEST")
        self.write(
            "en/modules/ROOT/partials/snippet.adoc",
            "tag::parent[]\ntag::child[]\ninner\nend::child[]\nend::parent[]\n",
        )
        self.write("en/modules/ROOT/pages/page.adoc", "include::partial$snippet.adoc[tags=parent;!child]\n")

        ok, output = self.run_check(dt.check_tags_orphaned)
        self.assertFalse(ok)
        self.assertIn("tag::child[]", output)
        self.assertNotIn("tag::parent[]", output)

    def test_nested_tag_negated_by_one_include_but_used_by_another_is_not_orphaned(self):
        """Regression test for the docs-greengagedb scenario
        (compression_codecs/compression_codecs_no_compression,
        format_null/null_description/gpload_note): a nested tag negated by
        one include call site (tags=parent;!child) but pulled in plainly
        by a *different* include of the same parent (tag=parent, no
        exclusion) really does render on that second page, so it must not
        be reported orphaned just because some other call site excludes
        it -- negation has to be judged per call site, not merged into one
        blanket "ever negated in this file" verdict."""
        self.antora_yml("en", "TEST")
        self.write(
            "en/modules/ROOT/partials/snippet.adoc",
            "tag::parent[]\ntag::child[]\ninner\nend::child[]\nend::parent[]\n",
        )
        self.write("en/modules/ROOT/pages/excludes-child.adoc",
                    "include::partial$snippet.adoc[tags=parent;!child]\n")
        self.write("en/modules/ROOT/pages/includes-child.adoc",
                    "include::partial$snippet.adoc[tag=parent]\n")

        ok, output = self.run_check(dt.check_tags_orphaned)
        self.assertTrue(ok, output)

    def test_page_filter_narrows_report_but_not_usage_scan(self):
        """--page must narrow which files' own tag regions get reported
        on, but the usage scan itself still has to cover the whole site --
        a tag defined in the --page-filtered-in file, used only from a
        page --page filters out, must still be recognized as used, not
        reported as a false orphan just because its user was excluded from
        the report."""
        self.antora_yml("en", "TEST")
        self.write("en/modules/ROOT/partials/kept.adoc", "tag::kept_tag[]\nbody\nend::kept_tag[]\n")
        self.write("en/modules/ROOT/partials/other.adoc", "tag::other_tag[]\nbody\nend::other_tag[]\n")
        self.write("en/modules/ROOT/pages/user.adoc", "include::partial$kept.adoc[tag=kept_tag]\n")

        dt._PAGE_FILTER = {"kept"}
        ok, output = self.run_check(dt.check_tags_orphaned)
        self.assertTrue(ok, output)  # kept_tag used (from user.adoc, filtered out of the report but still scanned)
        self.assertNotIn("other_tag", output)  # other.adoc's own orphaned tag is filtered out of the report

    def test_cross_repo_usage_via_external_root_is_not_orphaned(self):
        """Regression test for the docs-adbes scenario: a tag defined here
        but only pulled in by a registered --external-root component's own
        content (via a self-qualified include::ADB:how-to:...[]) must not
        be reported orphaned."""
        self.antora_yml("en", "ADB")
        self.write("en/modules/how-to/pages/metrics.adoc", "tag::prometheus[]\nbody\nend::prometheus[]\n")

        external_root = Path(tempfile.mkdtemp(prefix="docs_tool_ext_repo_"))
        (external_root / "en" / "modules" / "ROOT" / "pages").mkdir(parents=True)
        (external_root / "en" / "modules" / "ROOT" / "pages" / "index.adoc").write_text(
            "include::ADB:how-to:metrics.adoc[tag=prometheus]\n", encoding="utf-8"
        )
        try:
            dt.EXTERNAL_COMPONENTS = dt._load_external_components([f"ADBES={external_root}"])
            ok, output = self.run_check(dt.check_tags_orphaned)
            self.assertTrue(ok, output)
        finally:
            shutil.rmtree(external_root, ignore_errors=True)


class PagesBrokenRefsTests(FixtureTestCase):
    def test_self_qualified_own_component_image_resolves(self):
        """Regression test for the docs-adcm scenario:
        image::ADCM:ROOT:pic.png[] written inside docs-adcm's own content
        must resolve against this repo's own modules, not be silently
        skipped as an unregistered external component."""
        self.antora_yml("en", "ADCM")
        self.write("en/modules/ROOT/partials/snippet.adoc", "image::ADCM:ROOT:pic.png[]\n")
        self.write("en/modules/ROOT/pages/page.adoc", "include::partial$snippet.adoc[]\n")
        self.write("en/modules/ROOT/images/pic.png", "real")

        ok, output = self.run_check(dt.check_pages_broken_refs)
        self.assertTrue(ok, output)

    def test_self_qualified_own_component_missing_image_is_broken(self):
        self.antora_yml("en", "ADCM")
        self.write("en/modules/ROOT/partials/snippet.adoc", "image::ADCM:ROOT:missing.png[]\n")
        self.write("en/modules/ROOT/pages/page.adoc", "include::partial$snippet.adoc[]\n")

        ok, output = self.run_check(dt.check_pages_broken_refs)
        self.assertFalse(ok)
        self.assertIn("missing.png", output)

    def test_self_qualified_explicit_empty_module_xref_resolves(self):
        """Regression test for the docs-greengagedb scenario:
        xref:docs-gg::connect_with_psql.adoc[] -- Antora's explicit-empty-
        module form ("component::page", double colon) meaning the same
        thing as "component:page" (module omitted) -- must resolve to
        ROOT, not be reported broken with a stray leading ':' left in the
        path (the bug produced exactly "xref::connect_with_psql.adoc" in
        the report, one colon short of the real target)."""
        self.antora_yml("en", "docs-gg")
        self.write("en/modules/ROOT/pages/connect_with_psql.adoc", "content\n")
        self.write("en/modules/ROOT/partials/snippet.adoc",
                    "xref:docs-gg::connect_with_psql.adoc[]\n")
        self.write("en/modules/ROOT/pages/page.adoc", "include::partial$snippet.adoc[]\n")

        ok, output = self.run_check(dt.check_pages_broken_refs)
        self.assertTrue(ok, output)

    def test_self_qualified_explicit_empty_module_missing_xref_is_broken(self):
        self.antora_yml("en", "docs-gg")
        self.write("en/modules/ROOT/partials/snippet.adoc",
                    "xref:docs-gg::missing.adoc[]\n")
        self.write("en/modules/ROOT/pages/page.adoc", "include::partial$snippet.adoc[]\n")

        ok, output = self.run_check(dt.check_pages_broken_refs)
        self.assertFalse(ok)
        self.assertIn("missing.adoc", output)

    def test_different_unregistered_component_is_left_unchecked(self):
        """A reference into a genuinely different, unregistered component
        must stay silently skipped, not get validated as if it were this
        repo's own content."""
        self.antora_yml("en", "ADCM")
        self.write("en/modules/ROOT/pages/page.adoc", "image::ADPG:ROOT:whatever.png[]\n")

        ok, output = self.run_check(dt.check_pages_broken_refs)
        self.assertTrue(ok, output)

    def test_qualified_include_without_family_marker_defaults_to_page(self):
        """Regression test: include::ADB:how-to:metrics.adoc[tag=x] (no
        page$/partial$/example$ marker) must default to the page family,
        the same way a bare xref:module:page.adoc[] already does -- not
        fall back to "relative to the including file's own directory"."""
        self.antora_yml("en", "ADB")
        self.write("en/modules/how-to/pages/metrics.adoc", "content\n")
        self.write("en/modules/ROOT/pages/page.adoc", "include::ADB:how-to:metrics.adoc[]\n")

        ok, output = self.run_check(dt.check_pages_broken_refs)
        self.assertTrue(ok, output)

    def test_link_to_attachmentsdir_resolves(self):
        self.antora_yml("en", "TEST")
        self.write("en/modules/ROOT/attachments/sample.csv", "a,b\n")
        self.write("en/modules/ROOT/pages/page.adoc", "link:{attachmentsdir}/sample.csv[Download]\n")

        ok, output = self.run_check(dt.check_pages_broken_refs)
        self.assertTrue(ok, output)

    def test_link_to_missing_attachmentsdir_file_is_broken(self):
        self.antora_yml("en", "TEST")
        self.write("en/modules/ROOT/pages/page.adoc", "link:{attachmentsdir}/missing.csv[Download]\n")

        ok, output = self.run_check(dt.check_pages_broken_refs)
        self.assertFalse(ok)
        self.assertIn("missing.csv", output)

    def test_link_to_external_url_is_skipped(self):
        self.antora_yml("en", "TEST")
        self.write("en/modules/ROOT/pages/page.adoc", "link:https://example.com/foo[External]\n")

        ok, output = self.run_check(dt.check_pages_broken_refs)
        self.assertTrue(ok, output)

    def test_link_to_missing_relative_file_is_broken(self):
        self.antora_yml("en", "TEST")
        self.write("en/modules/ROOT/pages/page.adoc", "link:missing-sibling.txt[Download]\n")

        ok, output = self.run_check(dt.check_pages_broken_refs)
        self.assertFalse(ok)
        self.assertIn("missing-sibling.txt", output)

    def test_include_tag_not_present_in_target_is_broken(self):
        """Regression test for the connections.adoc bug: the target file
        exists, but the requested tag= doesn't match any tag::NAME[] region
        in it (e.g. a rename left the include pointing at the old name).
        Asciidoctor silently renders nothing for this, so a plain
        file-exists check missed it -- it must be reported as broken."""
        self.antora_yml("en", "TEST")
        self.write(
            "en/modules/ROOT/partials/snippet.adoc",
            "tag::allow-remote-connections1[]\nbody\nend::allow-remote-connections1[]\n",
        )
        self.write("en/modules/ROOT/pages/page.adoc", "include::partial$snippet.adoc[tag=allow-remote-connections]\n")

        ok, output = self.run_check(dt.check_pages_broken_refs)
        self.assertFalse(ok)
        self.assertIn("allow-remote-connections", output)
        self.assertIn("not found", output)

    def test_include_tag_present_in_target_is_not_broken(self):
        self.antora_yml("en", "TEST")
        self.write(
            "en/modules/ROOT/partials/snippet.adoc",
            "tag::intro[]\nbody\nend::intro[]\n",
        )
        self.write("en/modules/ROOT/pages/page.adoc", "include::partial$snippet.adoc[tag=intro]\n")

        ok, output = self.run_check(dt.check_pages_broken_refs)
        self.assertTrue(ok, output)

    def test_include_without_tag_attribute_does_not_check_tags(self):
        """A plain include (no tag=/tags=) pulls in the whole file, so a
        target with no tag regions at all -- or different ones -- must not
        be flagged; only an explicit tag= request is checked."""
        self.antora_yml("en", "TEST")
        self.write("en/modules/ROOT/partials/snippet.adoc", "plain content, no tags\n")
        self.write("en/modules/ROOT/pages/page.adoc", "include::partial$snippet.adoc[]\n")

        ok, output = self.run_check(dt.check_pages_broken_refs)
        self.assertTrue(ok, output)

    def test_version_pinned_xref_is_left_unchecked(self):
        """Regression test for the docs-adbes scenario: a version-pinned
        Antora xref (e.g. "6.29.1.1@ADB:tutorials:external-db.adoc[]",
        linking to a specific past ADB release) must not be reported
        broken just because "6.29.1.1@ADB" doesn't start with a letter and
        so isn't recognized as a component prefix -- it's left unchecked
        the same way any other unregistered external component is, even
        with --external-root ADB=... registered, since that root only
        holds the current checkout, not the pinned historical version."""
        self.antora_yml("en", "TEST")
        self.write("en/modules/ROOT/pages/page.adoc",
                    "xref:6.29.1.1@ADB:tutorials:external-db.adoc[]\n")

        ok, output = self.run_check(dt.check_pages_broken_refs)
        self.assertTrue(ok, output)

        external = Path(tempfile.mkdtemp(prefix="docs_tool_ext_pin_"))
        (external / "en" / "modules" / "ROOT").mkdir(parents=True)
        try:
            dt.EXTERNAL_COMPONENTS = dt._load_external_components([f"ADB={external}"])
            ok, output = self.run_check(dt.check_pages_broken_refs)
            self.assertTrue(ok, output)
        finally:
            shutil.rmtree(external, ignore_errors=True)

    def test_version_pinned_include_does_not_count_as_tag_usage(self):
        """A tag only ever pulled in via a version-pinned include must
        still be reported orphaned -- the tool can't verify usage against
        a pinned historical version it doesn't have checked out."""
        self.antora_yml("en", "TEST")
        self.write(
            "en/modules/ROOT/partials/snippet.adoc",
            "tag::example[]\nbody\nend::example[]\n",
        )
        self.write(
            "en/modules/ROOT/pages/page.adoc",
            "include::6.29.1.1@ADB:how-to:metrics.adoc[tag=example]\n",
        )

        ok, output = self.run_check(dt.check_tags_orphaned)
        self.assertFalse(ok)
        self.assertIn("tag::example[]", output)


class PagesRuLatinHomoglyphsTests(FixtureTestCase):
    def test_mixed_script_word_is_flagged(self):
        self.write("ru/modules/ROOT/pages/page.adoc",
                    "Настройте PAMавторизацию для example входа.\n")
        ok, output = self.run_check(dt.check_pages_ru_latin_homoglyphs)
        self.assertFalse(ok)
        self.assertIn("PAMавторизацию", output)

    def test_standalone_homoglyph_letter_is_flagged(self):
        self.write("ru/modules/ROOT/pages/page.adoc",
                    "Взаимодействие c другими example службами.\n")
        ok, output = self.run_check(dt.check_pages_ru_latin_homoglyphs)
        self.assertFalse(ok)
        self.assertIn("'c'", output)

    def test_hyphenated_identifier_is_not_flagged(self):
        """gcc-c++/xerces-c-devel-style identifiers leave a bare single
        letter between hyphens -- must not be treated as a standalone
        homoglyph typo."""
        self.write("ru/modules/ROOT/pages/page.adoc",
                    "Пакет называется xerces-c-devel для example сборки.\n")
        ok, output = self.run_check(dt.check_pages_ru_latin_homoglyphs)
        self.assertTrue(ok, output)

    def test_parenthetical_enum_code_is_not_flagged(self):
        """Postgres catalog docs' own "SHARED_DEPENDENCY_OWNER (o)" enum-code
        convention must not be flagged as a typo'd Cyrillic letter."""
        self.write("ru/modules/ROOT/pages/page.adoc",
                    "Тип SHARED_DEPENDENCY_OWNER (o) example используется здесь.\n")
        ok, output = self.run_check(dt.check_pages_ru_latin_homoglyphs)
        self.assertTrue(ok, output)

    def test_pipe_delimited_short_code_is_not_flagged(self):
        """pg_dump.adoc-style "c | custom" description-list short codes must
        not be flagged."""
        self.write("ru/modules/ROOT/pages/page.adoc",
                    "c | custom example формат вывода.\n")
        ok, output = self.run_check(dt.check_pages_ru_latin_homoglyphs)
        self.assertTrue(ok, output)

    def test_bold_italic_ui_string_is_not_flagged(self):
        """DBeaver-style "*_Connect to a database_*" verbatim UI quoting is
        kept in English by convention; the standalone "a" inside it must not
        be flagged."""
        self.write("ru/modules/ROOT/pages/page.adoc",
                    "Нажмите *_Connect to a database_* example чтобы продолжить.\n")
        ok, output = self.run_check(dt.check_pages_ru_latin_homoglyphs)
        self.assertTrue(ok, output)

    def test_uppercase_c_is_not_flagged(self):
        """Uppercase Latin C collides with real usage like "the C language";
        the standalone-letter check is deliberately lowercase-only."""
        self.write("ru/modules/ROOT/pages/page.adoc",
                    "В языках, отличных от SQL и C, example используется другой синтаксис.\n")
        ok, output = self.run_check(dt.check_pages_ru_latin_homoglyphs)
        self.assertTrue(ok, output)


class PagesFilePathItalicsTests(FixtureTestCase):
    def test_extension_whitelist_match_is_flagged(self):
        self.antora_yml("en", "TEST")
        self.write("en/modules/ROOT/pages/page.adoc",
                    "Edit the postgresql.conf file to change settings.\n")
        ok, output = self.run_check(dt.check_pages_file_path_italics)
        self.assertFalse(ok)
        self.assertIn("postgresql.conf", output)

    def test_absolute_dir_path_is_flagged(self):
        self.antora_yml("en", "TEST")
        self.write("en/modules/ROOT/pages/page.adoc",
                    "The configuration lives under /etc/postgresql/data for this cluster.\n")
        ok, output = self.run_check(dt.check_pages_file_path_italics)
        self.assertFalse(ok)
        self.assertIn("/etc/postgresql/data", output)

    def test_bare_basename_with_phrase_is_flagged(self):
        """"src" is only flagged with the "a/the X folder" grammar gate,
        unlike the unambiguous basenames below."""
        self.antora_yml("en", "TEST")
        self.write("en/modules/ROOT/pages/page.adoc",
                    "Copy the compiled binaries into the src folder before packaging.\n")
        ok, output = self.run_check(dt.check_pages_file_path_italics)
        self.assertFalse(ok)
        self.assertIn("src", output)

    def test_unambiguous_basename_is_flagged_without_phrase(self):
        """"bin" is flagged on bold/code-span alone, with no "a/the X
        folder" phrase required."""
        self.antora_yml("en", "TEST")
        self.write("en/modules/ROOT/pages/page.adoc",
                    "The install places scripts under `bin` for convenience.\n")
        ok, output = self.run_check(dt.check_pages_file_path_italics)
        self.assertFalse(ok)
        self.assertIn("bin", output)

    def test_compound_underscore_or_slash_word_is_flagged(self):
        self.antora_yml("en", "TEST")
        self.write("en/modules/ROOT/pages/page.adoc",
                    "Check the greengage_path folder and the backup/adb folder for the installed binaries.\n")
        ok, output = self.run_check(dt.check_pages_file_path_italics)
        self.assertFalse(ok)
        self.assertIn("greengage_path", output)
        self.assertIn("backup/adb", output)

    def test_code_span_word_before_file_is_flagged(self):
        self.antora_yml("en", "TEST")
        self.write("en/modules/ROOT/pages/page.adoc",
                    "Delete the `backup` folder once the migration finishes.\n")
        ok, output = self.run_check(dt.check_pages_file_path_italics)
        self.assertFalse(ok)
        self.assertIn("backup", output)

    def test_camelcase_parameter_name_is_not_flagged(self):
        """A camelCase code-span word before "directory" reads as a config
        parameter name (e.g. zookeeper's `dataLogDir`), not a literal Unix
        directory name."""
        self.antora_yml("en", "TEST")
        self.write("en/modules/ROOT/pages/page.adoc",
                    "Configure the `dataLogDir` directory for dedicated disk usage.\n")
        ok, output = self.run_check(dt.check_pages_file_path_italics)
        self.assertTrue(ok, output)

    def test_generic_noun_format_descriptor_is_not_flagged(self):
        """pg_dump's own "the `directory` archive format" names a format,
        not a literal directory."""
        self.antora_yml("en", "TEST")
        self.write("en/modules/ROOT/pages/page.adoc",
                    "Parallel dumps are only supported for the `directory` archive format.\n")
        ok, output = self.run_check(dt.check_pages_file_path_italics)
        self.assertTrue(ok, output)

    def test_dotfile_mention_is_flagged(self):
        self.antora_yml("en", "TEST")
        self.write("en/modules/ROOT/pages/page.adoc",
                    "For example, edit .bashrc to update your shell startup.\n")
        ok, output = self.run_check(dt.check_pages_file_path_italics)
        self.assertFalse(ok)
        self.assertIn(".bashrc", output)

    def test_already_italicized_is_not_flagged(self):
        self.antora_yml("en", "TEST")
        self.write("en/modules/ROOT/pages/page.adoc",
                    "Edit the _postgresql.conf_ file to change settings.\n")
        ok, output = self.run_check(dt.check_pages_file_path_italics)
        self.assertTrue(ok, output)


class PagesTableCellPeriodsTests(FixtureTestCase):
    def test_last_line_of_cell_with_period_is_flagged(self):
        self.antora_yml("en", "TEST")
        self.write(
            "en/modules/ROOT/pages/table.adoc",
            "|===\n|Description\n\nSome description sentence.\n|===\n",
        )
        ok, output = self.run_check(dt.check_pages_table_cell_periods)
        self.assertFalse(ok)
        self.assertIn("Some description sentence.", output)

    def test_list_in_cell_is_exempt(self):
        self.antora_yml("en", "TEST")
        self.write(
            "en/modules/ROOT/pages/table.adoc",
            "|===\n|Options\n\n* First item.\n|===\n",
        )
        ok, output = self.run_check(dt.check_pages_table_cell_periods)
        self.assertTrue(ok, output)

    def test_admonition_in_cell_is_exempt(self):
        self.antora_yml("en", "TEST")
        self.write(
            "en/modules/ROOT/pages/table.adoc",
            "|===\n|Warning\n\nNOTE: This requires elevated privileges.\n|===\n",
        )
        ok, output = self.run_check(dt.check_pages_table_cell_periods)
        self.assertTrue(ok, output)

    def test_abbreviation_exceptions(self):
        self.antora_yml("ru", "TEST")
        self.write(
            "ru/modules/ROOT/pages/table_a.adoc",
            "|===\n|Ссылка\n\nПодробнее см. документацию и т.д.\n|===\n",
        )
        self.write(
            "ru/modules/ROOT/pages/table_b.adoc",
            "|===\n|Мин.\n|===\n",
        )
        ok, output = self.run_check(dt.check_pages_table_cell_periods)
        self.assertTrue(ok, output)

    def test_multi_cell_single_line_is_split(self):
        """A compact header-style row packs several plain "|"-cells on one
        physical line; each must be checked individually, not just the last
        one on the line."""
        self.antora_yml("en", "TEST")
        self.write(
            "en/modules/ROOT/pages/table.adoc",
            "|===\n|Algorithm |Compression ratio. |Min |Max\n|===\n",
        )
        ok, output = self.run_check(dt.check_pages_table_cell_periods)
        self.assertFalse(ok)
        self.assertIn("Compression ratio.", output)


class PagesTranslationTests(FixtureTestCase):
    def test_identical_line_is_flagged_as_untranslated(self):
        self.write("en/modules/ROOT/pages/page.adoc",
                    "This is a real sentence with enough words.\n")
        self.write("ru/modules/ROOT/pages/page.adoc",
                    "This is a real sentence with enough words.\n")
        ok, output = self.run_check(dt.check_pages_translation)
        self.assertFalse(ok)
        self.assertIn("UNTRANSLATED", output)

    def test_code_block_is_skipped(self):
        """A code block that's identical between EN and RU (as code
        legitimately is) must not be flagged as untranslated prose."""
        self.write(
            "en/modules/ROOT/pages/page.adoc",
            "----\necho hello world\n----\nThis sentence has been properly translated for real.\n",
        )
        self.write(
            "ru/modules/ROOT/pages/page.adoc",
            "----\necho hello world\n----\nЭто предложение действительно переведено на русский.\n",
        )
        ok, output = self.run_check(dt.check_pages_translation)
        self.assertTrue(ok, output)

    def test_verbose_stopword_flagging(self):
        """A leftover English stopword inside otherwise-Russian text is only
        flagged under the stricter -v/verbose heuristic."""
        self.write(
            "en/modules/ROOT/pages/page.adoc",
            "This paragraph explains the new caching behavior in detail.\n",
        )
        self.write(
            "ru/modules/ROOT/pages/page.adoc",
            "Этот абзац объясняет and новое поведение кэширования.\n",
        )
        ok, _ = self.run_check(dt.check_pages_translation, verbose=False)
        self.assertTrue(ok)

        ok, output = self.run_check(dt.check_pages_translation, verbose=True)
        self.assertFalse(ok)
        self.assertIn("SUSPECT", output)


class PagesTerminologyTests(FixtureTestCase):
    def _set_glossary(self, *rows: str):
        """Each row is an "en,ru,ru_pattern" CSV line (no trailing newline)."""
        path = self.write("glossary.csv", "en,ru,ru_pattern\n" + "\n".join(rows) + "\n")
        dt.GLOSSARY = dt._load_glossary([str(path)])

    def test_missing_glossary_exits(self):
        dt.GLOSSARY = {}
        with self.assertRaises(SystemExit):
            dt.check_pages_terminology()

    def test_correct_translation_passes(self):
        self._set_glossary("host,хост,хост<>")
        self.write("en/modules/ROOT/pages/page.adoc", "Connect to the host over SSH.\n")
        self.write("ru/modules/ROOT/pages/page.adoc", "Подключитесь к хосту по SSH.\n")
        ok, output = self.run_check(dt.check_pages_terminology)
        self.assertTrue(ok, output)

    def test_missing_translation_is_flagged(self):
        self._set_glossary("host,хост,хост<>")
        self.write("en/modules/ROOT/pages/page.adoc", "Connect to the host over SSH.\n")
        self.write("ru/modules/ROOT/pages/page.adoc", "Подключитесь к серверу по SSH.\n")
        ok, output = self.run_check(dt.check_pages_terminology)
        self.assertFalse(ok)
        self.assertIn("MISMATCH", output)
        self.assertIn("'host'", output)

    def test_duplicate_key_accepts_either_translation(self):
        self._set_glossary(
            "session,сессия,сесси<>",
            "session,сеанс,сеанс<>",
        )
        self.write("en/modules/ROOT/pages/page.adoc", "Start a new session before continuing.\n")
        self.write("ru/modules/ROOT/pages/page.adoc", "Перед продолжением начните новый сеанс.\n")
        ok, output = self.run_check(dt.check_pages_terminology)
        self.assertTrue(ok, output)

    def test_do_not_translate_term_must_stay_literal(self):
        self._set_glossary("Greengage DB,не переводить,Greengage DB")
        self.write("en/modules/ROOT/pages/page.adoc", "This is a Greengage DB cluster.\n")
        self.write("ru/modules/ROOT/pages/page.adoc", "Это кластер GPDB.\n")
        ok, output = self.run_check(dt.check_pages_terminology)
        self.assertFalse(ok)
        self.assertIn("MISMATCH", output)

        self.write("ru/modules/ROOT/pages/page.adoc", "Это кластер Greengage DB.\n")
        ok, output = self.run_check(dt.check_pages_terminology)
        self.assertTrue(ok, output)

    def test_term_inside_code_span_is_skipped(self):
        self._set_glossary("host,хост,хост<>")
        self.write("en/modules/ROOT/pages/page.adoc", "Set the `host` config option.\n")
        self.write("ru/modules/ROOT/pages/page.adoc", "Настройте параметр `host`.\n")
        ok, output = self.run_check(dt.check_pages_terminology)
        self.assertTrue(ok, output)

    def test_page_filter_scopes_check(self):
        self._set_glossary("host,хост,хост<>")
        self.write("en/modules/ROOT/pages/keep.adoc", "Connect to the host.\n")
        self.write("ru/modules/ROOT/pages/keep.adoc", "Подключитесь к серверу.\n")
        self.write("en/modules/ROOT/pages/skip.adoc", "Connect to the host.\n")
        self.write("ru/modules/ROOT/pages/skip.adoc", "Подключитесь к серверу.\n")
        dt._PAGE_FILTER = {"keep"}
        ok, output = self.run_check(dt.check_pages_terminology)
        self.assertFalse(ok)
        self.assertIn("keep.adoc", output)
        self.assertNotIn("skip.adoc", output)


class PagesStructureParityTests(FixtureTestCase):
    def test_matching_structure_passes(self):
        self.write(
            "en/modules/ROOT/pages/page.adoc",
            "== Title\n\nSome intro text.\n\n=== Sub heading\n\nMore text.\n",
        )
        self.write(
            "ru/modules/ROOT/pages/page.adoc",
            "== Заголовок\n\nНекоторый текст.\n\n=== Подзаголовок\n\nЕщё текст.\n",
        )
        ok, output = self.run_check(dt.check_pages_structure_parity)
        self.assertTrue(ok, output)

    def test_heading_level_mismatch_is_flagged(self):
        self.write(
            "en/modules/ROOT/pages/page.adoc",
            "== Title\n\nText.\n\n=== Details\n\nMore text.\n",
        )
        self.write(
            "ru/modules/ROOT/pages/page.adoc",
            "== Заголовок\n\nТекст.\n\n==== Детали\n\nЕщё текст.\n",
        )
        ok, output = self.run_check(dt.check_pages_structure_parity)
        self.assertFalse(ok)
        self.assertIn("DIFF", output)

    def test_delimited_block_mismatch_is_flagged(self):
        """A source/code block's delimiters dropped in the RU translation
        (e.g. a translator accidentally deleting "----" lines) must be
        caught even though line counts might coincidentally still match."""
        self.write(
            "en/modules/ROOT/pages/page.adoc",
            "== Title\n\n[source,sql]\n----\nSELECT 1;\n----\n\nText after.\n",
        )
        self.write(
            "ru/modules/ROOT/pages/page.adoc",
            "== Заголовок\n\nSELECT 1;\n\nТекст после.\n",
        )
        ok, output = self.run_check(dt.check_pages_structure_parity)
        self.assertFalse(ok)
        self.assertIn("DIFF", output)

    def test_include_directive_target_mismatch_is_flagged(self):
        self.write(
            "en/modules/ROOT/pages/page.adoc",
            "== Title\n\ninclude::partial$foo.adoc[]\n",
        )
        self.write(
            "ru/modules/ROOT/pages/page.adoc",
            "== Заголовок\n\ninclude::partial$bar.adoc[]\n",
        )
        ok, output = self.run_check(dt.check_pages_structure_parity)
        self.assertFalse(ok)
        self.assertIn("DIFF", output)


class SyncMergeTests(unittest.TestCase):
    """Unit tests for sync_merge -- the pure structural-alignment function
    behind --sync, no filesystem/git involved."""

    def test_new_en_section_is_inserted_untranslated(self):
        en_lines = ["== Intro", "Some text.", "== New Section", "More text."]
        ru_lines = ["== Введение", "Какой-то текст."]
        merged, inserted, replaced, pairs, force_synced, orphaned = dt.sync_merge(en_lines, ru_lines)
        self.assertEqual(merged, ["== Введение", "Какой-то текст.", "== New Section", "More text."])
        self.assertEqual(inserted, [["== New Section", "More text."]])
        self.assertEqual(replaced, [])

    def test_force_sync_type_corrects_drifted_technical_token(self):
        """A FORCE_SYNC_TYPES line (e.g. an include path) that's drifted
        between EN and RU is corrected to EN's version, the same way a
        stale `plpythonu` gets corrected to `plpython3u`."""
        en_lines = ["include::partial$new_name.adoc[]"]
        ru_lines = ["include::partial$old_name.adoc[]"]
        merged, inserted, replaced, pairs, force_synced, orphaned = dt.sync_merge(en_lines, ru_lines)
        self.assertEqual(merged, ["include::partial$new_name.adoc[]"])
        self.assertEqual(replaced, [("include::partial$old_name.adoc[]", "include::partial$new_name.adoc[]")])

    def test_prose_mismatch_is_not_overwritten(self):
        """A reworded EN paragraph must never silently overwrite existing
        RU prose via the plain structural merge -- that's handled
        separately (STALE VERSION marking) by run_sync's git-diff pass."""
        en_lines = ["Some rewritten English paragraph text here."]
        ru_lines = ["Другой русский текст здесь совершенно другой."]
        merged, inserted, replaced, pairs, force_synced, orphaned = dt.sync_merge(en_lines, ru_lines)
        self.assertEqual(merged, ru_lines)
        self.assertEqual(replaced, [])


class RunSyncTests(unittest.TestCase):
    """Integration tests for run_sync -- the --sync entry point, writing
    real files under a tempdir."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="docs_tool_sync_")
        self.root = Path(self._tmpdir)

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def write(self, rel_path: str, content: str) -> Path:
        p = self.root / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def test_dry_run_does_not_write_file(self):
        en_path = self.write(
            "en/modules/ROOT/pages/foo.adoc",
            "== Title\n\nText.\n\n== New Section\n\nNew content added later.\n",
        )
        ru_original = "== Заголовок\n\nТекст.\n"
        ru_path = self.write("ru/modules/ROOT/pages/foo.adoc", ru_original)

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            dt.run_sync(str(en_path), dry_run=True)

        self.assertEqual(ru_path.read_text(encoding="utf-8"), ru_original)
        self.assertNotIn("Updated", buf.getvalue())
        self.assertIn("New Section", buf.getvalue())

    def test_new_content_is_written_and_reported(self):
        en_path = self.write(
            "en/modules/ROOT/pages/foo.adoc",
            "== Title\n\nText.\n\n== New Section\n\nNew content added later.\n",
        )
        ru_path = self.write("ru/modules/ROOT/pages/foo.adoc", "== Заголовок\n\nТекст.\n")

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            dt.run_sync(str(en_path), dry_run=False)

        result = ru_path.read_text(encoding="utf-8")
        self.assertIn("== Заголовок", result)  # existing RU prose preserved
        self.assertIn("== New Section", result)  # new EN section copied in
        self.assertIn("New content added later.", result)
        self.assertIn("Updated", buf.getvalue())
        self.assertIn("Inserted", buf.getvalue())


class RunSyncGitRewordTests(unittest.TestCase):
    """Integration test for the git-backed reworded-paragraph detection in
    run_sync: an EN paragraph reworded (not just extended) since RU was last
    touched must be appended as new text with the old RU translation kept
    alongside as a `// STALE VERSION:` comment, not silently discarded."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="docs_tool_sync_git_")
        self._orig_cwd = os.getcwd()
        os.chdir(self._tmpdir)
        subprocess.run(["git", "init", "-q"], check=True)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _git(self, *args):
        subprocess.run(
            ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test", *args],
            check=True, capture_output=True,
        )

    def write(self, rel_path: str, content: str) -> Path:
        p = Path(rel_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def test_reworded_paragraph_marked_stale_not_overwritten_silently(self):
        en_rel = "en/modules/ROOT/pages/foo.adoc"
        ru_rel = "ru/modules/ROOT/pages/foo.adoc"
        self.write(en_rel, "== Title\n\nThis is the original explanation of caching behavior.\n")
        self.write(ru_rel, "== Заголовок\n\nЭто оригинальное объяснение поведения кэширования.\n")
        self._git("add", "-A")
        self._git("commit", "-m", "initial")

        self.write(en_rel, "== Title\n\nThis paragraph now explains caching in a completely different way.\n")
        self._git("add", "-A")
        self._git("commit", "-m", "reword EN paragraph")

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            dt.run_sync(en_rel, dry_run=False)

        result = Path(ru_rel).read_text(encoding="utf-8")
        self.assertIn("This paragraph now explains caching in a completely different way.", result)
        self.assertIn("// STALE VERSION:", result)
        self.assertIn("Это оригинальное объяснение поведения кэширования.", result)


if __name__ == "__main__":
    unittest.main()
