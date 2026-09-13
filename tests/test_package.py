"""发布包安全边界：只在临时目录中生成合成文件，不读取本地凭据。"""

from __future__ import annotations

import io
import stat
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import package as release


class PackageTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.sandbox = Path(temporary.name)
        self.root = self.sandbox / "project"
        self.root.mkdir()
        self.today = date(2026, 9, 13)
        self.base_files = {
            "README.md": "# Isolated release fixture\n",
            "AGENTS.md": "Offline synthetic fixture only.\n",
            "requirements.txt": "pandas>=2.0\n",
            ".env.example": "OPENAI_API_KEY=\n",
            "app.py": "print('offline fixture')\n",
            "chainshield/__init__.py": '"""Synthetic package."""\n',
            "data/sources.json": '{"include_samples": true, "feeds": []}\n',
        }
        for name, text in self.base_files.items():
            self.write_text(name, text)
        for name in (
            "components", "suppliers", "dependencies", "orders", "order_lines",
            "pipeline", "events",
        ):
            relative = f"data/seed/{name}.csv"
            self.base_files[relative] = "fixture_id\nexample\n"
            self.write_text(relative, self.base_files[relative])

    def write_text(self, relative: str, text: str, *, encoding: str = "utf-8") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode(encoding))
        return path

    def write_bytes(self, relative: str, data: bytes) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    @staticmethod
    def synthetic_token() -> str:
        # 运行时拼接，避免测试源码本身被发布扫描误认为含有真实凭据。
        return "sk-" + "NotARealCredential123" * 2

    @staticmethod
    def ppt_bytes(xml: str) -> bytes:
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("ppt/slides/slide1.xml", xml)
        return output.getvalue()

    def build(self) -> release.PackageResult:
        return release.build_package(self.root, today=self.today)

    def assert_no_output(self) -> None:
        self.assertFalse((self.root / "dist").exists())

    def make_symlink(self, link: Path, target: Path, *, directory: bool = False) -> None:
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Symbolic links are unavailable on this runner: {type(exc).__name__}")

    def test_release_allowlist_excludes_private_and_runtime_files(self) -> None:
        included = {
            ".streamlit/config.toml": "[server]\nheadless = true\n",
            ".github/workflows/tests.yml": "name: offline-fixture\n",
            "scripts/check.py": "pass\n",
            "tests/test_example.py": "pass\n",
        }
        for name, text in included.items():
            self.write_text(name, text)
        excluded = (
            ".env", ".env.local", ".streamlit/secrets.toml",
            "data/events_live.csv", "docs/private_notes.md", "docs/draft.pptx",
            "chainshield/private/settings.py", "chainshield/secrets.py",
            "chainshield/credentials.json", "chainshield/.hidden.py",
            "chainshield/__pycache__/cache.py", "scripts/tmp/helper.py",
            "tests/local/credentials.py", "data/seed/events_live.csv",
            ".venv/helper.py", "dist/previous.zip",
        )
        for name in excluded:
            # 若误包含任一私有文件，凭据扫描也应让本测试立即失败。
            self.write_text(name, self.synthetic_token())
        ppt_name = "docs/地缘风险_产品介绍PPT_20260913.pptx"
        self.write_bytes(ppt_name, self.ppt_bytes("<slide><text>合成演示</text></slide>"))

        result = self.build()
        with zipfile.ZipFile(result.path) as archive:
            expected = set(self.base_files) | set(included) | {ppt_name}
            self.assertEqual(set(archive.namelist()), expected)
            self.assertEqual(result.file_count, len(expected))
            self.assertIsNone(archive.testzip())
            self.assertEqual(archive.read(".env.example"), b"OPENAI_API_KEY=\n")

    def test_repeated_build_does_not_overwrite_existing_archive(self) -> None:
        first = self.build()
        original_bytes = first.path.read_bytes()
        second = self.build()
        self.assertFalse(first.path.samefile(second.path))
        self.assertTrue(second.path.name.endswith("_02.zip"))
        self.assertEqual(first.path.read_bytes(), original_bytes)
        self.assertEqual(first.file_count, second.file_count)
        with zipfile.ZipFile(second.path) as archive:
            self.assertFalse(any(name.startswith("dist/") for name in archive.namelist()))

    def test_credentials_block_output_without_echoing_values(self) -> None:
        synthetic_values = (
            self.synthetic_token(),
            "ghp_" + "A1" * 20,
            "github_pat_" + "B2" * 20,
            "-----BEGIN " + "RSA PRIVATE KEY-----",
            "OPENAI_API_KEY=" + "C3" * 20,
        )
        for index, value in enumerate(synthetic_values):
            with self.subTest(kind=index):
                self.write_text("chainshield/sample.py", value)
                with self.assertRaises(release.PackageError) as caught:
                    self.build()
                self.assertIn("chainshield/sample.py", str(caught.exception))
                self.assertNotIn(value, str(caught.exception))
                self.assert_no_output()

    def test_utf16_credentials_are_scanned(self) -> None:
        token = self.synthetic_token()
        self.write_text("chainshield/sample.py", token, encoding="utf-16")
        with self.assertRaises(release.PackageError) as caught:
            self.build()
        self.assertNotIn(token, str(caught.exception))
        self.assert_no_output()

    def test_ppt_credentials_split_across_xml_runs_are_scanned(self) -> None:
        token = self.synthetic_token()
        xml = f"<slide><text>{token[:8]}</text><text>{token[8:]}</text></slide>"
        self.write_bytes("docs/地缘风险_产品介绍PPT_20260913.pptx", self.ppt_bytes(xml))
        with self.assertRaises(release.PackageError) as caught:
            self.build()
        self.assertNotIn(token, str(caught.exception))
        self.assert_no_output()

    def test_malformed_ppt_or_xml_is_rejected_before_output(self) -> None:
        for data in (b"not a zip archive", self.ppt_bytes("<slide><unclosed>")):
            with self.subTest(is_zip=data.startswith(b"PK")):
                self.write_bytes("docs/地缘风险_产品介绍PPT_20260913.pptx", data)
                with self.assertRaises(release.PackageError):
                    self.build()
                self.assert_no_output()

    def test_linked_source_cannot_escape_project(self) -> None:
        outside = self.sandbox / "outside.py"
        outside.write_text("outside fixture", encoding="utf-8")
        self.make_symlink(self.root / "chainshield/linked.py", outside)
        with self.assertRaises(release.PackageError):
            self.build()
        self.assert_no_output()

    def test_linked_output_cannot_write_outside_project(self) -> None:
        outside = self.sandbox / "outside_output"
        outside.mkdir()
        self.make_symlink(self.root / "dist", outside, directory=True)
        with self.assertRaises(release.PackageError):
            self.build()
        self.assertEqual(list(outside.iterdir()), [])

    def test_windows_reparse_attribute_is_rejected(self) -> None:
        # 在 Linux CI 也覆盖 Windows junction 的属性检查，不创建真实 junction。
        info = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        with patch.object(Path, "lstat", return_value=info):
            with self.assertRaises(release.PackageError):
                release._safe_path(self.root, Path("dist"))

    def test_unsafe_relative_paths_are_rejected(self) -> None:
        for relative in (Path("../outside.py"), self.sandbox / "outside.py"):
            with self.subTest(relative=str(relative)):
                with self.assertRaises(release.PackageError):
                    release._safe_path(self.root, relative)

    def test_file_and_total_size_limits_prevent_output(self) -> None:
        for name, limit in (("MAX_FILE_BYTES", 4), ("MAX_PACKAGE_BYTES", 20)):
            with self.subTest(limit=name), patch.object(release, name, limit):
                with self.assertRaises(release.PackageError):
                    self.build()
                self.assert_no_output()

    def test_ppt_xml_size_limit_prevents_output(self) -> None:
        self.write_bytes(
            "docs/地缘风险_产品介绍PPT_20260913.pptx",
            self.ppt_bytes("<slide><text>synthetic text</text></slide>"),
        )
        with patch.object(release, "MAX_PPT_XML_BYTES", 4):
            with self.assertRaises(release.PackageError):
                self.build()
        self.assert_no_output()

    def test_zip_write_failure_removes_only_partial_new_archive(self) -> None:
        first = self.build()
        original_bytes = first.path.read_bytes()
        with patch.object(zipfile.ZipFile, "writestr", side_effect=OSError("synthetic write failure")):
            with self.assertRaises(OSError):
                self.build()
        self.assertEqual(first.path.read_bytes(), original_bytes)
        remaining = list((self.root / "dist").iterdir())
        self.assertEqual(len(remaining), 1)
        # Windows 临时目录可能同时使用 8.3 短路径与长路径，比较实际文件身份。
        self.assertTrue(remaining[0].samefile(first.path))

    def test_package_writes_the_scanned_snapshot_not_later_file_changes(self) -> None:
        original_text = "print('safe scanned fixture')\n"
        source = self.write_text("chainshield/sample.py", original_text)
        original_scan = release._scan_content

        def scan_then_change(data: bytes, relative: Path) -> None:
            original_scan(data, relative)
            if relative == Path("chainshield/sample.py"):
                source.write_text(self.synthetic_token(), encoding="utf-8")

        with patch.object(release, "_scan_content", side_effect=scan_then_change):
            result = self.build()
        with zipfile.ZipFile(result.path) as archive:
            self.assertEqual(archive.read("chainshield/sample.py"), original_text.encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
