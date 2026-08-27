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
        """rows_text is the pipe-delimited body (without header row/comments)."""
        tmpdir = tempfile.mkdtemp(prefix="docs_tool_glossary_")
        try:
            path = Path(tmpdir) / "glossary.psv"
            path.write_text("# a comment\nen|ru|ru_pattern|note\n" + rows_text, encoding="utf-8")
            return dt._load_glossary([str(path)])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_comment_and_header_lines_skipped(self):
        glossary = self._load("host|хост|хост<>|\n")
        self.assertEqual(set(glossary), {"host"})

    def test_rows_sharing_en_term_merge_with_note_ignored_for_matching(self):
        glossary = self._load(
            "session|сессия|сесси<>|generic database sense\n"
            "session|сеанс|сеанс<>|bounded maintenance-operation sense\n"
        )
        self.assertEqual(set(glossary), {"session"})
        self.assertEqual(glossary["session"]["ru_display"], {"сессия", "сеанс"})
        self.assertEqual(len(glossary["session"]["patterns"]), 2)

    def test_missing_file_exits(self):
        with self.assertRaises(SystemExit):
            dt._load_glossary(["/no/such/glossary/file.psv"])

    def test_row_missing_pattern_is_skipped_with_warning(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            glossary = self._load("host|хост||\n")
        self.assertEqual(glossary, {})
        self.assertIn("missing en/ru_pattern", buf.getvalue())

    def test_row_with_wrong_field_count_is_skipped_with_warning(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            glossary = self._load("host|хост|хост<>\n")  # only 3 fields, missing note
        self.assertEqual(glossary, {})
        self.assertIn("expected 4 '|'-separated fields", buf.getvalue())

    def test_comma_in_field_needs_no_escaping(self):
        glossary = self._load("session|сессия, сеанс|сесси<>|a note, with a comma\n")
        self.assertEqual(glossary["session"]["ru_display"], {"сессия, сеанс"})


class DiscoverDefaultGlossariesTests(unittest.TestCase):
    """--glossary's fallback: every *-glossary.psv directly under the
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
        Path("greengagedb-glossary.psv").write_text("en|ru|ru_pattern|note\n", encoding="utf-8")
        self.assertEqual(dt._discover_default_glossaries(), ["greengagedb-glossary.psv"])

    def test_multiple_matches_found_sorted(self):
        Path("zzz-glossary.psv").write_text("en|ru|ru_pattern|note\n", encoding="utf-8")
        Path("aaa-glossary.psv").write_text("en|ru|ru_pattern|note\n", encoding="utf-8")
        self.assertEqual(dt._discover_default_glossaries(), ["aaa-glossary.psv", "zzz-glossary.psv"])

    def test_non_matching_files_ignored(self):
        Path("glossary.psv").write_text("en|ru|ru_pattern|note\n", encoding="utf-8")  # no "-glossary" prefix
        Path("notes-glossary.txt").write_text("irrelevant\n", encoding="utf-8")  # wrong extension
        self.assertEqual(dt._discover_default_glossaries(), [])

    def test_subdirectory_not_searched(self):
        Path("sub").mkdir()
        (Path("sub") / "nested-glossary.psv").write_text("en|ru|ru_pattern|note\n", encoding="utf-8")
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

        dt._PAGE_FILTER = {"names": {("kept",)}, "dirs": set()}
        ok, output = self.run_check(dt.check_tags_orphaned)
        self.assertTrue(ok, output)  # kept_tag used (from user.adoc, filtered out of the report but still scanned)
        self.assertNotIn("other_tag", output)  # other.adoc's own orphaned tag is filtered out of the report

    def test_tag_used_only_from_nav_adoc_is_not_orphaned(self):
        """_collect_tag_usage (shared with check_partials_orphaned) must
        scan nav.adoc for include::...[] macros too, not just pages/ and
        partials/ -- nav.adoc can pull in a tagged region the same as any
        page can."""
        self.antora_yml("en", "TEST")
        self.write(
            "en/modules/ROOT/partials/snippet.adoc",
            "tag::used[]\nkept\nend::used[]\n",
        )
        self.write("en/modules/ROOT/nav.adoc", "include::partial$snippet.adoc[tag=used]\n")

        ok, output = self.run_check(dt.check_tags_orphaned)
        self.assertTrue(ok, output)

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


class PartialsOrphanedTests(FixtureTestCase):
    def test_whole_file_partial_with_no_tags_and_no_include_is_orphaned(self):
        """Regression test: a partials/ file with no tag::/end:: markers at
        all -- content meant to be pulled in only as a whole file via a
        bare include::...[] -- must be reported orphaned once nothing
        includes it anymore. Previously check_tags_orphaned's
        `if not regions: continue` skipped such files entirely, so a
        whole-file partial left behind after its last
        include::partial$...[] was deleted was invisible to every
        orphaned-content check (docs-adb's hosts-online.adoc)."""
        self.antora_yml("en", "TEST")
        self.write(
            "en/modules/ROOT/partials/hosts-online.adoc",
            "IMPORTANT: some plain content, no tag markers\n",
        )
        self.write("en/modules/ROOT/pages/page.adoc", "intro\n")

        ok, output = self.run_check(dt.check_partials_orphaned)
        self.assertFalse(ok)
        self.assertIn("hosts-online.adoc", output)

    def test_whole_file_partial_included_plainly_is_not_orphaned(self):
        self.antora_yml("en", "TEST")
        self.write(
            "en/modules/ROOT/partials/hosts-online.adoc",
            "IMPORTANT: some plain content, no tag markers\n",
        )
        self.write("en/modules/ROOT/pages/page.adoc", "include::partial$hosts-online.adoc[]\n")

        ok, output = self.run_check(dt.check_partials_orphaned)
        self.assertTrue(ok, output)

    def test_tagged_partial_is_left_to_tags_orphaned_check(self):
        """A partial that has its own tag::/end:: regions is judged
        tag-by-tag by check_tags_orphaned instead -- check_partials_orphaned
        must not also flag it as a whole-file orphan just because it isn't
        pulled in via a plain/wildcarded include."""
        self.antora_yml("en", "TEST")
        self.write(
            "en/modules/ROOT/partials/snippet.adoc",
            "tag::used[]\nkept\nend::used[]\n",
        )
        self.write("en/modules/ROOT/pages/page.adoc", "include::partial$snippet.adoc[tag=used]\n")

        ok, output = self.run_check(dt.check_partials_orphaned)
        self.assertTrue(ok, output)

    def test_whole_file_partial_included_only_from_nav_adoc_is_not_orphaned(self):
        """Regression test for the docs-greengagedb false positive:
        nav_reference_utils.adoc/nav_reference_admin_schemas.adoc are each
        pulled in only via include::partial$...[] from nav.adoc itself (a
        long submenu factored out of the main nav tree), never from any
        pages/partials file. _collect_tag_usage only scanned pages/ and
        partials/ for include macros, so nav.adoc's own includes were
        invisible to the usage scan and this whole-file partial was
        wrongly reported orphaned."""
        self.antora_yml("en", "TEST")
        self.write(
            "en/modules/ROOT/partials/nav_reference_utils.adoc",
            "* xref:reference/utils/foo.adoc[]\n",
        )
        self.write("en/modules/ROOT/nav.adoc", "* xref:index.adoc[]\ninclude::partial$nav_reference_utils.adoc[]\n")

        ok, output = self.run_check(dt.check_partials_orphaned)
        self.assertTrue(ok, output)

    def test_cross_repo_usage_via_external_root_is_not_orphaned(self):
        self.antora_yml("en", "ADB")
        self.write("en/modules/ROOT/partials/hosts-online.adoc", "plain content, no tag markers\n")

        external_root = Path(tempfile.mkdtemp(prefix="docs_tool_ext_repo_"))
        (external_root / "en" / "modules" / "ROOT" / "pages").mkdir(parents=True)
        (external_root / "en" / "modules" / "ROOT" / "pages" / "index.adoc").write_text(
            "include::ADB:ROOT:partial$hosts-online.adoc[]\n", encoding="utf-8"
        )
        try:
            dt.EXTERNAL_COMPONENTS = dt._load_external_components([f"ADBES={external_root}"])
            ok, output = self.run_check(dt.check_partials_orphaned)
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


class PagesNoYoTests(FixtureTestCase):
    def test_yo_is_flagged(self):
        self.write("ru/modules/ROOT/pages/page.adoc", "Настройте параметр для Ёлка и ёж.\n")
        ok, output = self.run_check(dt.check_pages_no_yo)
        self.assertFalse(ok)
        self.assertIn("page.adoc:1:", output)

    def test_no_yo_passes(self):
        self.write("ru/modules/ROOT/pages/page.adoc", "Настройте параметр елка.\n")
        ok, _ = self.run_check(dt.check_pages_no_yo)
        self.assertTrue(ok)

    def test_page_author_attribute_is_exempt(self):
        self.write("ru/modules/ROOT/pages/page.adoc", ":page-author: Фёдоров\n\nОбычный текст.\n")
        ok, _ = self.run_check(dt.check_pages_no_yo)
        self.assertTrue(ok)

    def test_page_author_exemption_does_not_leak_to_other_lines(self):
        self.write("ru/modules/ROOT/pages/page.adoc", ":page-author: Фёдоров\n\nОн живёт здесь.\n")
        ok, output = self.run_check(dt.check_pages_no_yo)
        self.assertFalse(ok)
        self.assertIn("живёт", output)

    def test_en_pages_are_not_scanned(self):
        self.write("en/modules/ROOT/pages/page.adoc", "This mentions ёж as a loanword.\n")
        ok, _ = self.run_check(dt.check_pages_no_yo)
        self.assertTrue(ok)


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

    def test_description_attribute_value_is_flagged(self):
        """:description:/:page-htmltitle: are ":"-prefixed structural
        attribute lines that _iter_prose_lines skips wholesale, but their
        values render as real Russian prose (<meta description>/<title>)
        and must still be scanned for homoglyph typos."""
        self.write("ru/modules/ROOT/pages/page.adoc",
                    ":description: Работа c example базой данных.\n"
                    "\n"
                    "Текст страницы.\n")
        ok, output = self.run_check(dt.check_pages_ru_latin_homoglyphs)
        self.assertFalse(ok)
        self.assertIn("'c'", output)

    def test_other_attribute_lines_still_not_scanned(self):
        """Non-prose attribute lines (e.g. :page-author:) must stay out of
        scope -- only :description:/:page-htmltitle: values are scanned."""
        self.write("ru/modules/ROOT/pages/page.adoc",
                    ":page-author: c example\n"
                    "\n"
                    "Текст страницы.\n")
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

    def test_description_attribute_untranslated_is_flagged(self):
        """:description:/:page-htmltitle: are ":"-prefixed structural
        attribute lines that _is_skip_line treats as non-prose, but their
        values render as real page <meta description>/<title> text and
        must still be checked for copy-pasted English."""
        self.write("en/modules/ROOT/pages/page.adoc",
                    ":description: This page explains the new caching behavior.\n")
        self.write("ru/modules/ROOT/pages/page.adoc",
                    ":description: This page explains the new caching behavior.\n")
        ok, output = self.run_check(dt.check_pages_translation)
        self.assertFalse(ok)
        self.assertIn("UNTRANSLATED", output)

    def test_description_attribute_translated_passes(self):
        self.write("en/modules/ROOT/pages/page.adoc",
                    ":description: This page explains the new caching behavior.\n")
        self.write("ru/modules/ROOT/pages/page.adoc",
                    ":description: На этой странице описано новое поведение кэширования.\n")
        ok, output = self.run_check(dt.check_pages_translation)
        self.assertTrue(ok, output)

    def test_other_attribute_lines_still_not_scanned(self):
        """Non-prose attribute lines outside the description/title
        carve-out must stay excluded, even when copied verbatim and long
        enough to pass the word-count threshold."""
        self.write("en/modules/ROOT/pages/page.adoc",
                    ":page-partial: This attribute is not real page prose.\n")
        self.write("ru/modules/ROOT/pages/page.adoc",
                    ":page-partial: This attribute is not real page prose.\n")
        ok, output = self.run_check(dt.check_pages_translation)
        self.assertTrue(ok, output)


class ContentRelpathTests(unittest.TestCase):
    def test_finds_subpath_after_pages(self):
        p = Path("en/modules/ROOT/pages/reference/sql_commands/create_role.adoc")
        self.assertEqual(dt._content_relpath(p), Path("reference/sql_commands/create_role.adoc"))

    def test_finds_subpath_after_partials(self):
        p = Path("en/modules/ROOT/partials/reference/shared.adoc")
        self.assertEqual(dt._content_relpath(p), Path("reference/shared.adoc"))

    def test_top_level_page_has_no_leading_directory(self):
        p = Path("en/modules/ROOT/pages/index.adoc")
        self.assertEqual(dt._content_relpath(p), Path("index.adoc"))

    def test_none_when_neither_pages_nor_partials_in_path(self):
        self.assertIsNone(dt._content_relpath(Path("en/modules/ROOT/examples/foo.sql")))


class ContentRelpartsStemTests(unittest.TestCase):
    def test_strips_adoc_extension_from_final_segment_only(self):
        p = Path("en/modules/ROOT/pages/reference/gp_toolkit/gp_ao_diskquota_no_perm_map.adoc")
        self.assertEqual(dt._content_relparts_stem(p), ("reference", "gp_toolkit", "gp_ao_diskquota_no_perm_map"))

    def test_bare_top_level_file(self):
        p = Path("en/modules/ROOT/pages/index.adoc")
        self.assertEqual(dt._content_relparts_stem(p), ("index",))

    def test_none_when_not_under_pages_or_partials(self):
        self.assertIsNone(dt._content_relparts_stem(Path("en/modules/ROOT/examples/foo.sql")))


class EndsWithPartsTests(unittest.TestCase):
    def test_bare_single_segment_matches_last_segment_only(self):
        self.assertTrue(dt._ends_with_parts(("reference", "gp_toolkit", "gp_ao"), ("gp_ao",)))

    def test_multi_segment_suffix_must_match_in_order(self):
        self.assertTrue(dt._ends_with_parts(("reference", "gp_toolkit", "gp_ao"), ("gp_toolkit", "gp_ao")))
        self.assertFalse(dt._ends_with_parts(("reference", "gp_toolkit", "gp_ao"), ("gp_ao", "gp_toolkit")))

    def test_suffix_longer_than_parts_never_matches(self):
        self.assertFalse(dt._ends_with_parts(("gp_ao",), ("reference", "gp_toolkit", "gp_ao")))

    def test_non_matching_middle_segment_fails(self):
        self.assertFalse(dt._ends_with_parts(("reference", "gp_toolkit", "gp_ao"), ("reference", "utils", "gp_ao")))


class PageAllowedDirectoryFilterTests(unittest.TestCase):
    """_page_allowed's directory-matching half of --page: recursive,
    content-relative, module-agnostic."""

    def setUp(self):
        self._orig_page_filter = dt._PAGE_FILTER

    def tearDown(self):
        dt._PAGE_FILTER = self._orig_page_filter

    def test_direct_child_matches(self):
        dt._PAGE_FILTER = {"names": set(), "dirs": {("reference", "sql_commands")}}
        p = Path("en/modules/ROOT/pages/reference/sql_commands/create_role.adoc")
        self.assertTrue(dt._page_allowed(p))

    def test_nested_grandchild_also_matches_recursively(self):
        dt._PAGE_FILTER = {"names": set(), "dirs": {("reference",)}}
        p = Path("en/modules/ROOT/pages/reference/sql_commands/create_role.adoc")
        self.assertTrue(dt._page_allowed(p))

    def test_sibling_directory_does_not_match(self):
        dt._PAGE_FILTER = {"names": set(), "dirs": {("reference", "sql_commands")}}
        p = Path("en/modules/ROOT/pages/reference/utils/gpstate.adoc")
        self.assertFalse(dt._page_allowed(p))

    def test_segment_prefix_does_not_falsely_match(self):
        """"reference/sql" must not match "reference/sql_commands/..." --
        matching is by whole path segment, not a raw string prefix."""
        dt._PAGE_FILTER = {"names": set(), "dirs": {("reference", "sql")}}
        p = Path("en/modules/ROOT/pages/reference/sql_commands/create_role.adoc")
        self.assertFalse(dt._page_allowed(p))

    def test_matches_regardless_of_module_or_language(self):
        dt._PAGE_FILTER = {"names": set(), "dirs": {("reference", "sql_commands")}}
        for root in (
            "en/modules/ROOT/pages/reference/sql_commands/create_role.adoc",
            "ru/modules/ROOT/pages/reference/sql_commands/create_role.adoc",
            "en/modules/how-to/pages/reference/sql_commands/create_role.adoc",
        ):
            self.assertTrue(dt._page_allowed(Path(root)), root)

    def test_file_filter_and_directory_filter_both_apply(self):
        dt._PAGE_FILTER = {"names": {("index",)}, "dirs": {("reference",)}}
        self.assertTrue(dt._page_allowed(Path("en/modules/ROOT/pages/index.adoc")))
        self.assertTrue(dt._page_allowed(Path("en/modules/ROOT/pages/reference/gpstate.adoc")))
        self.assertFalse(dt._page_allowed(Path("en/modules/ROOT/pages/unrelated.adoc")))

    def test_bare_filename_matches_regardless_of_directory(self):
        """Unqualified single-segment NAME (the pre-existing form, e.g.
        --page foo.adoc) must keep matching a file with that stem in ANY
        directory -- no behavior change for the common case."""
        dt._PAGE_FILTER = {"names": {("gp_ao",)}, "dirs": set()}
        self.assertTrue(dt._page_allowed(Path("en/modules/ROOT/pages/reference/gp_toolkit/gp_ao.adoc")))
        self.assertTrue(dt._page_allowed(Path("en/modules/ROOT/pages/gp_ao.adoc")))

    def test_qualified_name_disambiguates_same_stem_in_different_directories(self):
        """The actual bug this was built to fix: a directory-qualified NAME
        (--page reference/gp_toolkit/gp_ao.adoc) must select only the file
        under that directory, not silently match a same-named file
        elsewhere too."""
        dt._PAGE_FILTER = {"names": {("gp_toolkit", "gp_ao")}, "dirs": set()}
        self.assertTrue(dt._page_allowed(Path("en/modules/ROOT/pages/reference/gp_toolkit/gp_ao.adoc")))
        self.assertFalse(dt._page_allowed(Path("en/modules/ROOT/pages/reference/utils/gp_ao.adoc")))
        self.assertFalse(dt._page_allowed(Path("en/modules/ROOT/pages/gp_ao.adoc")))

    def test_fully_qualified_name_is_also_module_agnostic(self):
        """The module name is never part of the matched path (see
        _content_relpath), so even a fully directory-qualified name still
        matches the same subpath in any module -- consistent with the
        directory filter's own module-agnostic behavior."""
        dt._PAGE_FILTER = {"names": {("reference", "gp_toolkit", "gp_ao")}, "dirs": set()}
        self.assertTrue(dt._page_allowed(Path("en/modules/ROOT/pages/reference/gp_toolkit/gp_ao.adoc")))
        self.assertTrue(dt._page_allowed(Path("en/modules/how-to/pages/reference/gp_toolkit/gp_ao.adoc")))
        self.assertFalse(dt._page_allowed(Path("en/modules/ROOT/pages/reference/utils/gp_ao.adoc")))


class ResolvePageStemQualifiedNameTests(unittest.TestCase):
    """--sync's fallback (_resolve_page_stem) gets the same suffix-matching
    treatment as --page, for the same reason: a bare filename can be
    ambiguous across directories, and a qualifying prefix should actually
    disambiguate instead of being silently dropped."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="docs_tool_resolve_stem_")
        self._orig_cwd = os.getcwd()
        os.chdir(self._tmpdir)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def write(self, rel_path: str) -> Path:
        p = Path(self._tmpdir) / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("", encoding="utf-8")
        return p

    def test_bare_name_matches_across_directories_ambiguously(self):
        self.write("en/modules/ROOT/pages/reference/gp_toolkit/gp_ao.adoc")
        self.write("en/modules/ROOT/pages/reference/utils/gp_ao.adoc")
        matches = dt._resolve_page_stem(("gp_ao",))
        self.assertEqual(len(matches), 2)

    def test_qualified_name_disambiguates(self):
        self.write("en/modules/ROOT/pages/reference/gp_toolkit/gp_ao.adoc")
        self.write("en/modules/ROOT/pages/reference/utils/gp_ao.adoc")
        matches = dt._resolve_page_stem(("gp_toolkit", "gp_ao"))
        self.assertEqual(matches, [Path("en/modules/ROOT/pages/reference/gp_toolkit/gp_ao.adoc")])

    def test_run_sync_accepts_qualified_name_end_to_end(self):
        self.write("en/modules/ROOT/pages/reference/gp_toolkit/gp_ao.adoc")
        self.write("en/modules/ROOT/pages/reference/utils/gp_ao.adoc")
        self.write("ru/modules/ROOT/pages/reference/gp_toolkit/gp_ao.adoc")

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            dt.run_sync("reference/gp_toolkit/gp_ao.adoc", dry_run=True)
        self.assertIn("reference/gp_toolkit/gp_ao.adoc", buf.getvalue())
        self.assertIn("already matches", buf.getvalue())

    def test_run_sync_bare_name_still_ambiguous(self):
        self.write("en/modules/ROOT/pages/reference/gp_toolkit/gp_ao.adoc")
        self.write("en/modules/ROOT/pages/reference/utils/gp_ao.adoc")
        with self.assertRaises(SystemExit) as ctx:
            dt.run_sync("gp_ao.adoc", dry_run=True)
        self.assertIn("matches multiple files", str(ctx.exception))


class PagesTerminologyTests(FixtureTestCase):
    def _set_glossary(self, *rows: str):
        """Each row is an "en|ru|ru_pattern" pipe-delimited line (no note, no trailing newline)."""
        path = self.write("glossary.psv", "en|ru|ru_pattern|note\n" + "\n".join(r + "|" for r in rows) + "\n")
        dt.GLOSSARY = dt._load_glossary([str(path)])

    def test_missing_glossary_exits(self):
        dt.GLOSSARY = {}
        with self.assertRaises(SystemExit):
            dt.check_pages_terminology()

    def test_missing_glossary_in_multi_check_run_skips_not_aborts(self):
        """`check all` / `--all-checks` / a profile sweeps terminology in; with
        no glossary it must be dropped with a note, not abort the run."""
        self.write("ru/modules/ROOT/pages/page.adoc", "Обычный текст.\n")
        cwd = os.getcwd()
        os.chdir(self._tmpdir)  # away from this repo's own greengagedb-glossary.psv
        try:
            err = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                ok = dt._run_selected(["pages-no-yo", "pages-terminology"], False, None)
        finally:
            os.chdir(cwd)
        self.assertTrue(ok)
        self.assertIn("skipping terminology check", err.getvalue())

    def test_correct_translation_passes(self):
        self._set_glossary("host|хост|хост<>")
        self.write("en/modules/ROOT/pages/page.adoc", "Connect to the host over SSH.\n")
        self.write("ru/modules/ROOT/pages/page.adoc", "Подключитесь к хосту по SSH.\n")
        ok, output = self.run_check(dt.check_pages_terminology)
        self.assertTrue(ok, output)

    def test_missing_translation_is_flagged(self):
        self._set_glossary("host|хост|хост<>")
        self.write("en/modules/ROOT/pages/page.adoc", "Connect to the host over SSH.\n")
        self.write("ru/modules/ROOT/pages/page.adoc", "Подключитесь к серверу по SSH.\n")
        ok, output = self.run_check(dt.check_pages_terminology)
        self.assertFalse(ok)
        self.assertIn("MISMATCH", output)
        self.assertIn("'host'", output)

    def test_duplicate_key_accepts_either_translation(self):
        self._set_glossary(
            "session|сессия|сесси<>",
            "session|сеанс|сеанс<>",
        )
        self.write("en/modules/ROOT/pages/page.adoc", "Start a new session before continuing.\n")
        self.write("ru/modules/ROOT/pages/page.adoc", "Перед продолжением начните новый сеанс.\n")
        ok, output = self.run_check(dt.check_pages_terminology)
        self.assertTrue(ok, output)

    def test_do_not_translate_term_must_stay_literal(self):
        self._set_glossary("Greengage DB|не переводить|Greengage DB")
        self.write("en/modules/ROOT/pages/page.adoc", "This is a Greengage DB cluster.\n")
        self.write("ru/modules/ROOT/pages/page.adoc", "Это кластер GPDB.\n")
        ok, output = self.run_check(dt.check_pages_terminology)
        self.assertFalse(ok)
        self.assertIn("MISMATCH", output)

        self.write("ru/modules/ROOT/pages/page.adoc", "Это кластер Greengage DB.\n")
        ok, output = self.run_check(dt.check_pages_terminology)
        self.assertTrue(ok, output)

    def test_term_inside_code_span_is_skipped(self):
        self._set_glossary("host|хост|хост<>")
        self.write("en/modules/ROOT/pages/page.adoc", "Set the `host` config option.\n")
        self.write("ru/modules/ROOT/pages/page.adoc", "Настройте параметр `host`.\n")
        ok, output = self.run_check(dt.check_pages_terminology)
        self.assertTrue(ok, output)

    def test_page_filter_scopes_check(self):
        self._set_glossary("host|хост|хост<>")
        self.write("en/modules/ROOT/pages/keep.adoc", "Connect to the host.\n")
        self.write("ru/modules/ROOT/pages/keep.adoc", "Подключитесь к серверу.\n")
        self.write("en/modules/ROOT/pages/skip.adoc", "Connect to the host.\n")
        self.write("ru/modules/ROOT/pages/skip.adoc", "Подключитесь к серверу.\n")
        dt._PAGE_FILTER = {"names": {("keep",)}, "dirs": set()}
        ok, output = self.run_check(dt.check_pages_terminology)
        self.assertFalse(ok)
        self.assertIn("keep.adoc", output)
        self.assertNotIn("skip.adoc", output)

    def test_page_filter_scopes_check_by_directory(self):
        self._set_glossary("host|хост|хост<>")
        self.write("en/modules/ROOT/pages/reference/sql_commands/keep.adoc", "Connect to the host.\n")
        self.write("ru/modules/ROOT/pages/reference/sql_commands/keep.adoc", "Подключитесь к серверу.\n")
        self.write("en/modules/ROOT/pages/reference/utils/skip.adoc", "Connect to the host.\n")
        self.write("ru/modules/ROOT/pages/reference/utils/skip.adoc", "Подключитесь к серверу.\n")
        dt._PAGE_FILTER = {"names": set(), "dirs": {("reference", "sql_commands")}}
        ok, output = self.run_check(dt.check_pages_terminology)
        self.assertFalse(ok)
        self.assertIn("keep.adoc", output)
        self.assertNotIn("skip.adoc", output)

    def test_description_attribute_mismatch_is_flagged(self):
        """:description:/:page-htmltitle: values render as real page
        <meta description>/<title> prose despite being ":"-prefixed
        structural attribute lines that _is_skip_line otherwise treats as
        non-prose -- a glossary violation inside them must still be caught."""
        self._set_glossary("host|хост|хост<>")
        self.write("en/modules/ROOT/pages/page.adoc",
                    ":description: Learn how to connect to the host.\n")
        self.write("ru/modules/ROOT/pages/page.adoc",
                    ":description: Узнайте, как подключиться к серверу.\n")
        ok, output = self.run_check(dt.check_pages_terminology)
        self.assertFalse(ok)
        self.assertIn("MISMATCH", output)
        self.assertIn("'host'", output)

    def test_description_attribute_correct_translation_passes(self):
        self._set_glossary("host|хост|хост<>")
        self.write("en/modules/ROOT/pages/page.adoc",
                    ":description: Learn how to connect to the host.\n")
        self.write("ru/modules/ROOT/pages/page.adoc",
                    ":description: Узнайте, как подключиться к хосту.\n")
        ok, output = self.run_check(dt.check_pages_terminology)
        self.assertTrue(ok, output)

    def test_term_inside_allcaps_command_name_is_skipped(self):
        """An SQL command name like "ALTER RESOURCE QUEUE" is kept
        untranslated by house style and appears unmarked-up (no code span)
        in :page-htmltitle:/:description: values -- a glossary term whose
        words happen to compose part of that name (e.g. "resource queue")
        must not be flagged just because the RU side rightly left the
        command name in English too."""
        self._set_glossary("resource queue|ресурсная очередь|ресурсн<> очеред<>")
        self.write("en/modules/ROOT/pages/page.adoc",
                    ":page-htmltitle: Overview of the ALTER RESOURCE QUEUE SQL command\n")
        self.write("ru/modules/ROOT/pages/page.adoc",
                    ":page-htmltitle: Обзор SQL-команды ALTER RESOURCE QUEUE\n")
        ok, output = self.run_check(dt.check_pages_terminology)
        self.assertTrue(ok, output)

    def test_other_attribute_lines_still_not_scanned(self):
        self._set_glossary("host|хост|хост<>")
        self.write("en/modules/ROOT/pages/page.adoc",
                    ":page-partial: Connect to the host over SSH.\n")
        self.write("ru/modules/ROOT/pages/page.adoc",
                    ":page-partial: Connect to the server over SSH.\n")
        ok, output = self.run_check(dt.check_pages_terminology)
        self.assertTrue(ok, output)

    def test_repeated_term_translated_every_time_passes(self):
        self._set_glossary("host|хост|хост<>")
        self.write("en/modules/ROOT/pages/page.adoc",
                    "The primary host talks to the standby host.\n")
        self.write("ru/modules/ROOT/pages/page.adoc",
                    "Основной хост общается с резервным хостом.\n")
        ok, output = self.run_check(dt.check_pages_terminology)
        self.assertTrue(ok, output)

    def test_repeated_term_translated_once_is_flagged(self):
        self._set_glossary("host|хост|хост<>")
        self.write("en/modules/ROOT/pages/page.adoc",
                    "The primary host talks to the standby host.\n")
        self.write("ru/modules/ROOT/pages/page.adoc",
                    "Основной хост общается с резервным сервером.\n")
        ok, output = self.run_check(dt.check_pages_terminology)
        self.assertFalse(ok)
        self.assertIn("MISMATCH", output)
        self.assertIn("'host'", output)
        self.assertIn("2x", output)
        self.assertIn("1x", output)

    def test_several_different_terms_each_checked_on_one_line(self):
        self._set_glossary(
            "commit|фиксация|фиксац<>",
            "rollback|откат|откат<>",
        )
        self.write("en/modules/ROOT/pages/page.adoc",
                    "You can commit or rollback the change.\n")
        self.write("ru/modules/ROOT/pages/page.adoc",
                    "Вы можете выполнить фиксацию или отменить изменение.\n")
        ok, output = self.run_check(dt.check_pages_terminology)
        self.assertFalse(ok)
        self.assertNotIn("'commit'", output)  # "фиксацию" satisfies the commit entry
        self.assertIn("'rollback'", output)   # "отменить" is not the house-style "откат"

    def test_multiword_term_repeated_counts_by_scarcest_token(self):
        self._set_glossary("resource queue|ресурсная очередь|ресурсн<> очеред<>")
        self.write("en/modules/ROOT/pages/page.adoc",
                    "A resource queue limits load; each resource queue has a name.\n")
        self.write("ru/modules/ROOT/pages/page.adoc",
                    "Ресурсная очередь ограничивает нагрузку; ресурсная очередь имеет имя.\n")
        ok, output = self.run_check(dt.check_pages_terminology)
        self.assertTrue(ok, output)

    def test_ru_count_helper_counts_scarcest_token(self):
        entry = {
            "ru_display": {"ресурсная очередь"},
            "patterns": [dt._compile_glossary_pattern("ресурсн<> очеред<>")],
        }
        self.assertEqual(
            dt._glossary_entry_ru_count(entry, "ресурсная очередь и ресурсная очередь"), 2)
        self.assertEqual(
            dt._glossary_entry_ru_count(entry, "ресурсная и ресурсная очередь"), 1)
        self.assertEqual(
            dt._glossary_entry_ru_count(entry, "здесь ничего нет"), 0)


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


class RunSyncStemResolutionTests(unittest.TestCase):
    """--sync's fallback: when its argument isn't an existing path, resolve
    it as a bare filename (must end in .adoc, same as --page NAME) against
    discovered EN pages/partials, same lookup --page uses. Needs a real cwd
    change (unlike RunSyncTests) since module_roots() resolves
    EN_MODULES_ROOT/RU_MODULES_ROOT relative to the current directory."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="docs_tool_sync_stem_")
        self._orig_cwd = os.getcwd()
        os.chdir(self._tmpdir)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def write(self, rel_path: str, content: str) -> Path:
        p = Path(self._tmpdir) / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def test_bare_filename_with_adoc_suffix_resolves(self):
        self.write("en/modules/ROOT/pages/foo.adoc", "== Title\n\nText.\n")
        self.write("ru/modules/ROOT/pages/foo.adoc", "== Заголовок\n\nТекст.\n")

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            dt.run_sync("foo.adoc", dry_run=True)
        self.assertIn("already matches", buf.getvalue())

    def test_name_without_adoc_suffix_is_rejected(self):
        """AsciiDoc/Antora has no separate topic-id -- the filename is the
        identifier, so a bare stem (no .adoc) must be rejected outright,
        not silently treated as a stem to search for."""
        self.write("en/modules/ROOT/pages/foo.adoc", "== Title\n\nText.\n")

        with self.assertRaises(SystemExit) as ctx:
            dt.run_sync("foo", dry_run=True)
        self.assertIn("must end with .adoc", str(ctx.exception))

    def test_ambiguous_filename_across_modules_exits_with_candidate_list(self):
        self.write("en/modules/ROOT/pages/foo.adoc", "== Title\n\nText.\n")
        self.write("en/modules/how-to/pages/foo.adoc", "== Title\n\nText.\n")

        with self.assertRaises(SystemExit) as ctx:
            dt.run_sync("foo.adoc", dry_run=True)
        message = str(ctx.exception)
        self.assertIn("matches multiple files", message)
        self.assertIn("ROOT", message)
        self.assertIn("how-to", message)

    def test_unresolvable_filename_exits_with_clear_error(self):
        self.write("en/modules/ROOT/pages/foo.adoc", "== Title\n\nText.\n")

        with self.assertRaises(SystemExit) as ctx:
            dt.run_sync("no-such-page.adoc", dry_run=True)
        self.assertIn("no page/partial named", str(ctx.exception))

    def test_full_path_still_takes_precedence_over_filename_search(self):
        """An existing full path is used as-is, without going through
        filename resolution at all -- so it works even where a bare
        filename would be ambiguous."""
        en_path = self.write("en/modules/ROOT/pages/foo.adoc", "== Title\n\nText.\n")
        self.write("en/modules/how-to/pages/foo.adoc", "== Title\n\nText.\n")
        self.write("ru/modules/ROOT/pages/foo.adoc", "== Заголовок\n\nТекст.\n")

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            dt.run_sync(str(en_path), dry_run=True)
        self.assertIn("already matches", buf.getvalue())


class MainPageValueFormTests(unittest.TestCase):
    """CLI-level routing in main(): a --page NAME ending in .adoc is a file
    filter, one that doesn't is a directory filter (AsciiDoc/Antora has no
    separate topic-id, so there's no ambiguity to worry about), and
    UNCOMMITTED is still the special sentinel. This routing happens before
    any filesystem/module scanning, so no fixture tree is needed -- just
    isolate real argv/cwd and the _PAGE_FILTER global."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="docs_tool_main_page_")
        self._orig_cwd = os.getcwd()
        os.chdir(self._tmpdir)
        self._orig_argv = sys.argv
        self._orig_page_filter = dt._PAGE_FILTER

    def tearDown(self):
        sys.argv = self._orig_argv
        dt._PAGE_FILTER = self._orig_page_filter
        os.chdir(self._orig_cwd)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_name_with_adoc_suffix_becomes_a_file_filter(self):
        sys.argv = ["docs_tool.py", "--check-pages-no-cyrillic", "--page", "resource_groups.adoc"]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit):
                dt.main()
        self.assertEqual(dt._PAGE_FILTER, {"names": {("resource_groups",)}, "dirs": set()})

    def test_bare_name_becomes_a_directory_filter(self):
        sys.argv = ["docs_tool.py", "--check-pages-no-cyrillic", "--page", "reference/sql_commands"]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit):
                dt.main()
        self.assertEqual(dt._PAGE_FILTER, {"names": set(), "dirs": {("reference", "sql_commands")}})

    def test_trailing_slash_on_directory_is_ignored(self):
        sys.argv = ["docs_tool.py", "--check-pages-no-cyrillic", "--page", "reference/sql_commands/"]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit):
                dt.main()
        self.assertEqual(dt._PAGE_FILTER, {"names": set(), "dirs": {("reference", "sql_commands")}})

    def test_uncommitted_sentinel_still_accepted(self):
        subprocess.run(["git", "init", "-q"], check=True)
        sys.argv = ["docs_tool.py", "--check-pages-no-cyrillic", "--page", "UNCOMMITTED"]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as ctx:
                dt.main()
        self.assertIn("no uncommitted", str(buf.getvalue()) + str(ctx.exception))


class CompletePageNameTests(FixtureTestCase):
    """--page/--sync's argcomplete tab-completion source: every EN/RU
    pages/partials .adoc filename across all discovered modules."""

    def test_collects_en_and_ru_filenames_deduplicated(self):
        self.antora_yml("en", "TEST")
        self.write("en/modules/ROOT/pages/foo.adoc", "")
        self.write("en/modules/ROOT/partials/bar.adoc", "")
        self.write("ru/modules/ROOT/pages/foo.adoc", "")  # same name as EN -- deduplicated
        self.write("ru/modules/ROOT/pages/baz.adoc", "")  # RU-only

        names = dt._complete_page_name()
        self.assertEqual(names, sorted(names))  # sorted for stable completion order
        self.assertEqual(set(names), {"foo.adoc", "bar.adoc", "baz.adoc"})

    def test_page_action_and_sync_action_wired_to_the_right_completer(self):
        """--page also accepts a directory (see _content_relpath), --sync
        doesn't -- each gets the completer matching what it actually accepts."""
        parser = dt.build_parser()
        actions_by_flag = {opt: a for a in parser._actions for opt in a.option_strings}
        self.assertIs(actions_by_flag["--page"].completer, dt._complete_page_or_dir_name)
        self.assertIs(actions_by_flag["--sync"].completer, dt._complete_page_name)

    def test_dir_completer_includes_every_nesting_level_with_trailing_slash(self):
        """Trailing "/" on every directory candidate (not "reference",
        "reference/") -- otherwise completion goes dead the instant the
        user types the "/" themselves, since nothing in the candidate list
        would start with what's already typed."""
        self.antora_yml("en", "TEST")
        self.write("en/modules/ROOT/pages/reference/sql_commands/create_role.adoc", "")

        names, dirs = dt._discover_page_completions()
        self.assertIn("create_role.adoc", names)
        self.assertEqual(dirs, {"reference/", "reference/sql_commands/"})

    def test_file_candidates_include_every_qualified_suffix_form(self):
        """A nested file gets one candidate per suffix length -- bare
        filename, then each directory-qualified form up to the full
        content-relative path -- so completion can keep narrowing down
        after a directory prefix instead of stopping at the bare name."""
        self.antora_yml("en", "TEST")
        self.write("en/modules/ROOT/pages/reference/gp_toolkit/gp_ao_diskquota_no_perm_map.adoc", "")

        names, _ = dt._discover_page_completions()
        self.assertEqual(names, {
            "gp_ao_diskquota_no_perm_map.adoc",
            "gp_toolkit/gp_ao_diskquota_no_perm_map.adoc",
            "reference/gp_toolkit/gp_ao_diskquota_no_perm_map.adoc",
        })


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


class FamilySelectionTests(unittest.TestCase):
    """_resolve_family_selection: the routing layer that maps
    `check <family> [--sub] [--target]` to legacy CHECKS keys."""

    def test_every_family_and_subcheck_maps_to_a_real_check(self):
        for fam, subs in dt.FAMILIES.items():
            for sc, targets in subs.items():
                for key in targets.values():
                    self.assertIn(key, dt.CHECKS, f"{fam} --{sc} -> {key}")

    def test_all_22_checks_are_reachable_through_some_family(self):
        reachable = {k for subs in dt.FAMILIES.values()
                     for t in subs.values() for k in t.values()}
        self.assertEqual(reachable, set(dt.CHECKS))

    def test_subcheck_names_are_unique_across_families(self):
        seen = [sc for subs in dt.FAMILIES.values() for sc in subs]
        self.assertEqual(len(seen), len(set(seen)))

    def test_whole_family_runs_every_target(self):
        self.assertEqual(
            set(dt._resolve_family_selection("style", None, None)),
            {"pages-no-yo", "pages-file-path-italics", "pages-table-cell-periods"},
        )
        self.assertEqual(
            set(dt._resolve_family_selection("refs", None, None)),
            {"pages-broken-refs", "pages-orphaned", "partials-orphaned",
             "examples-orphaned", "images-orphaned", "tags-orphaned"},
        )

    def test_subcheck_without_target_defaults_to_pages(self):
        self.assertEqual(
            dt._resolve_family_selection("chars", {"no-cyrillic"}, None),
            ["pages-no-cyrillic"],
        )

    def test_subcheck_with_target_picks_it(self):
        self.assertEqual(
            dt._resolve_family_selection("chars", {"no-cyrillic"}, "examples"),
            ["examples-no-cyrillic"],
        )

    def test_target_all_expands_every_target(self):
        self.assertEqual(
            set(dt._resolve_family_selection("chars", {"no-cyrillic"}, "all")),
            {"pages-no-cyrillic", "examples-no-cyrillic"},
        )

    def test_target_filters_whole_family(self):
        self.assertEqual(
            dt._resolve_family_selection("refs", None, "images"),
            ["images-orphaned"],
        )

    def test_family_all_spans_every_family(self):
        self.assertEqual(
            set(dt._resolve_family_selection("all", None, None)),
            set(dt.CHECKS),
        )

    def test_no_matching_target_yields_empty(self):
        self.assertEqual(dt._resolve_family_selection("style", None, "images"), [])

    def test_selection_is_deduplicated_and_ordered(self):
        got = dt._resolve_family_selection("all", None, None)
        self.assertEqual(len(got), len(set(got)))

    def test_family_of(self):
        self.assertEqual(dt._family_of("no-yo"), "style")
        self.assertEqual(dt._family_of("structure"), "l10n")
        self.assertIsNone(dt._family_of("nonsense"))


class CliV2RoutingTests(unittest.TestCase):
    """main() dispatch: `check|sync|list` route to the new surface,
    everything else stays on the legacy --check-* parser."""

    def setUp(self):
        self._argv = sys.argv
        self._pf = dt._PAGE_FILTER
        self._tmp = tempfile.mkdtemp(prefix="docs_tool_cli_")
        self._cwd = os.getcwd()
        os.chdir(self._tmp)

    def tearDown(self):
        sys.argv = self._argv
        dt._PAGE_FILTER = self._pf
        os.chdir(self._cwd)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _run(self, *args):
        sys.argv = ["docs_tool.py", *args]
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                dt.main()
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        return code, out.getvalue(), err.getvalue()

    def test_list_prints_the_family_map(self):
        code, out, _ = self._run("list")
        self.assertEqual(code, 0)
        self.assertIn("chars", out)
        self.assertIn("--no-yo", out)
        self.assertIn("CH01", out)
        self.assertIn("no Cyrillic", out)          # a SUMMARIES blurb
        self.assertNotIn("pages-no-cyrillic", out) # no legacy-key line in the tree

    def test_list_subcheck_prints_its_rationale(self):
        code, out, _ = self._run("list", "no-yo")
        self.assertEqual(code, 0)
        self.assertIn("ST01", out)
        self.assertIn("check style --no-yo", out)
        self.assertIn("ё", out)                    # from the docstring

    def test_list_rule_id_prints_its_rationale(self):
        code, out, _ = self._run("list", "ln02")   # case-insensitive
        self.assertEqual(code, 0)
        self.assertIn("check l10n --structure", out)

    def test_list_unknown_name_errors(self):
        code, _, err = self._run("list", "not-a-check")
        self.assertEqual(code, 2)
        self.assertIn("unknown check", err)

    def test_list_modules_points_at_legacy_flag(self):
        code, _, err = self._run("list", "modules")
        self.assertEqual(code, 2)
        self.assertIn("--list-modules", err)

    def test_check_requires_a_family(self):
        code, _, err = self._run("check")
        self.assertEqual(code, 2)
        self.assertIn("FAMILY", err)  # argparse: "the following arguments are required: FAMILY"

    def test_check_accepts_multiple_families(self):
        code, out, err = self._run("check", "chars", "markup")
        self.assertEqual(code, 0, err)   # no fixture tree -> nothing found

    def test_subcheck_with_multiple_families_is_rejected(self):
        code, _, err = self._run("check", "chars", "markup", "--backticks")
        self.assertEqual(code, 2)
        self.assertIn("exactly one family", err)

    def test_wrong_subcheck_for_family_is_rejected(self):
        code, _, err = self._run("check", "chars", "--no-yo")
        self.assertEqual(code, 2)
        self.assertIn("--no-yo", err)

    def test_check_sets_page_filter_then_runs(self):
        # no fixture tree here -> checks just find nothing, but routing +
        # --page parsing must work and exit 0.
        code, out, _ = self._run("check", "l10n", "--structure", "--page", "foo.adoc")
        self.assertEqual(dt._PAGE_FILTER, {"names": {("foo",)}, "dirs": set()})
        self.assertEqual(code, 0)

    def test_target_flag_is_accepted(self):
        code, _, err = self._run("check", "refs", "--orphaned", "--target", "images")
        self.assertEqual(code, 0, err)

    def test_bad_target_value_is_rejected(self):
        code, _, err = self._run("check", "chars", "--target", "bogus")
        self.assertEqual(code, 2)
        self.assertIn("bogus", err)

    def test_legacy_flags_still_route_to_legacy(self):
        code, out, _ = self._run("--check-pages-no-yo")
        self.assertEqual(code, 0)
        self.assertIn("OK:", out)

    def test_list_checks_prints_commands_sorted_by_id(self):
        code, out, _ = self._run("list", "checks")
        self.assertEqual(code, 0)
        self.assertIn("CH01  check chars --no-cyrillic", out)
        self.assertIn("RF04  check refs --orphaned --target examples", out)
        self.assertIn("TM01  check terms", out)
        self.assertNotIn("pages-no-cyrillic", out)   # no internal registry keys
        lines = [l for l in out.splitlines() if l[:2] in ("CH", "MK", "RF", "ST", "TM", "LN")]
        self.assertEqual(lines, sorted(lines))

    def test_bare_invocation_prints_the_new_surface(self):
        code, out, _ = self._run()
        self.assertEqual(code, 0)
        self.assertIn("check <family>", out)
        self.assertIn("{check,sync,list}", out)

    def test_top_level_help_routes_to_new_surface(self):
        code, out, _ = self._run("--help")
        self.assertEqual(code, 0)
        self.assertIn("check <family>", out)

    def test_legacy_flag_still_gets_legacy_help(self):
        code, out, _ = self._run("--all-checks", "--help")
        self.assertEqual(code, 0)
        self.assertIn("Legacy flag interface", out)


class RuleIdRegistryTests(unittest.TestCase):
    def test_every_check_has_a_unique_id(self):
        self.assertEqual(set(dt.RULE_IDS), set(dt.CHECKS))
        self.assertEqual(len(set(dt.RULE_IDS.values())), len(dt.CHECKS))

    def test_ids_are_family_prefixed(self):
        prefix = {"chars": "CH", "markup": "MK", "refs": "RF",
                  "style": "ST", "terms": "TM", "l10n": "LN"}
        for fam, subs in dt.FAMILIES.items():
            for targets in subs.values():
                for key in targets.values():
                    self.assertTrue(dt.RULE_IDS[key].startswith(prefix[fam]),
                                    f"{key} -> {dt.RULE_IDS[key]} (family {fam})")

    def test_list_one_check_accepts_an_id(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            dt._list_one_check("ST01")
        self.assertIn("check style --no-yo", out.getvalue())

    def test_resolve_check_name(self):
        self.assertEqual(dt._resolve_check_name("no-yo"), "pages-no-yo")
        self.assertEqual(dt._resolve_check_name("LN02"), "pages-structure-parity")
        self.assertEqual(dt._resolve_check_name("examples-orphaned"), "examples-orphaned")
        self.assertIsNone(dt._resolve_check_name("nonsense"))


if __name__ == "__main__":
    unittest.main()
