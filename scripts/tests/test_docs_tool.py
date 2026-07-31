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
import shutil
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
        dt.EN_MODULES_ROOT = self.root / "en" / "modules"
        dt.RU_MODULES_ROOT = self.root / "ru" / "modules"
        dt.EXTERNAL_COMPONENTS = {}
        dt._PAGE_FILTER = None
        dt._OWN_COMPONENT_NAME_CACHE.clear()

    def tearDown(self):
        dt.EN_MODULES_ROOT = self._orig_en
        dt.RU_MODULES_ROOT = self._orig_ru
        dt.EXTERNAL_COMPONENTS = self._orig_external
        dt._PAGE_FILTER = self._orig_page_filter
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


if __name__ == "__main__":
    unittest.main()
