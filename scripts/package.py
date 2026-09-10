"""生成赛道 B 成果提交包，不加载应用配置、不读取本地 .env。

用法：python scripts/package.py
产物：dist/地缘风险_提交包_YYYYMMDD.zip；同日重跑自动追加序号，不覆盖旧包。

采用发布白名单，仅递归收集源码、测试与种子 CSV；文档和部署配置显式列出。
对常见密钥格式做启发式检查（含 PPT 内部 XML），不能替代人工发布复核。
"""

from __future__ import annotations

import io
import re
import stat
import sys
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from xml.etree import ElementTree

# 不从 chainshield.config 导入：打包不需要、也不应该读取任何真实凭据。
ROOT = Path(__file__).resolve().parent.parent

RELEASE_FILES = (
    "README.md",
    "AGENTS.md",
    "requirements.txt",
    ".env.example",
    ".streamlit/config.toml",
    ".github/workflows/tests.yml",
    "app.py",
    "data/sources.json",
    "docs/guide.pdf",
    "docs/产品设计方案.md",
    "docs/产品介绍PPT_大纲.md",
    "docs/test_cases.md",
    "docs/iteration_log.md",
    "docs/需求调研访谈提纲.md",
)
SOURCE_TREES = {
    "chainshield": {".py"},
    "scripts": {".py"},
    "tests": {".py"},
    "data/seed": {".csv"},
}
FORMAL_PPT_NAME = re.compile(r"地缘风险_产品介绍PPT_\d{8}\.pptx\Z")
EXCLUDED_PARTS = {
    ".git", ".venv", "venv", "__pycache__", "dist", "tmp", "temp",
    "local", "private", "logs", "secrets", "credentials", "keys", "certs",
    "certificates",
}
PRIVATE_FILE_NAME = re.compile(
    r"(?:secrets?|credentials?|api[_ -]?keys?|private[_ -]?keys?)(?:[._ -]|$)",
    re.IGNORECASE,
)
TOKEN_PATTERNS = (
    re.compile(r"(?<![\w-])sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}(?![\w-])"),
    re.compile(r"(?<![\w-])(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})(?![\w-])"),
    re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"),
)
KEY_ASSIGNMENT = re.compile(
    r"(?:OPENAI|DEEPSEEK|ANTHROPIC|GEMINI)_API_KEY[\"']?\s*[=:]\s*[\"']?([A-Za-z0-9_-]{20,})",
    re.IGNORECASE,
)
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_PACKAGE_BYTES = 256 * 1024 * 1024
MAX_PPT_XML_BYTES = 32 * 1024 * 1024


class PackageError(ValueError):
    """可以安全展示的打包错误；只报告路径，不包含文件中的敏感内容。"""


@dataclass(frozen=True)
class PackageResult:
    path: Path
    file_count: int


def _safe_path(root: Path, relative: Path) -> Path | None:
    """检查每一级路径，拒绝符号链接和 Windows junction/reparse point。"""
    if relative.is_absolute() or ".." in relative.parts:
        raise PackageError("发布清单含不安全的相对路径")
    path = root
    for part in relative.parts:
        path = path / part
        try:
            info = path.lstat()
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(info.st_mode) or (
            getattr(info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        ):
            raise PackageError(f"禁止打包链接路径：{relative.as_posix()}")
    if not path.resolve().is_relative_to(root):
        raise PackageError(f"路径超出项目目录：{relative.as_posix()}")
    return path


def _excluded(relative: Path) -> bool:
    parts = [part.casefold() for part in relative.parts]
    return (
        any(part in EXCLUDED_PARTS or part.startswith(".") for part in parts)
        or bool(PRIVATE_FILE_NAME.match(relative.name))
        or relative.name.casefold() == "events_live.csv"
    )


def _walk_source(root: Path, relative: Path, extensions: set[str]):
    source = _safe_path(root, relative)
    if source is None:
        return
    if not source.is_dir():
        raise PackageError(f"源码目录类型不正确：{relative.as_posix()}")
    for child in sorted(source.iterdir()):
        child_relative = child.relative_to(root)
        if _excluded(child_relative):
            continue
        checked = _safe_path(root, child_relative)
        if checked is None:
            raise PackageError(f"打包过程中路径消失：{child_relative.as_posix()}")
        if checked.is_dir():
            yield from _walk_source(root, child_relative, extensions)
        elif checked.is_file() and checked.suffix.casefold() in extensions:
            yield child_relative


def collect_files(root: Path) -> list[Path]:
    """返回相对于 root 的发布文件列表；未在名单中的私有文档不会被读取。"""
    root = Path(root).resolve(strict=True)
    files: set[Path] = set()
    for name in RELEASE_FILES:
        relative = Path(name)
        checked = _safe_path(root, relative)
        if checked is None:
            continue
        if not checked.is_file():
            raise PackageError(f"发布文件类型不正确：{relative.as_posix()}")
        files.add(relative)
    for name, extensions in SOURCE_TREES.items():
        files.update(_walk_source(root, Path(name), extensions))
    docs = _safe_path(root, Path("docs"))
    if docs is not None and docs.is_dir():
        for path in docs.iterdir():
            if FORMAL_PPT_NAME.fullmatch(path.name):
                relative = path.relative_to(root)
                checked = _safe_path(root, relative)
                if checked is None or not checked.is_file():
                    raise PackageError(f"PPT 文件类型不正确：{relative.as_posix()}")
                files.add(relative)
    return sorted(files, key=lambda path: path.as_posix())


def _scan_text(text: str, relative: Path) -> None:
    found = any(pattern.search(text) for pattern in TOKEN_PATTERNS)
    for match in KEY_ASSIGNMENT.finditer(text):
        value = match.group(1)
        # 保留文档中的占位说明；仅拦截看起来像真实值的长字母数字串。
        if any(char.isalpha() for char in value) and any(char.isdigit() for char in value):
            found = True
    if found:
        raise PackageError(f"发现疑似凭据，已停止打包：{relative.as_posix()}")


def _scan_bytes(data: bytes, relative: Path) -> None:
    _scan_text(data.decode("utf-8", errors="replace"), relative)
    if b"\x00" in data:
        for encoding in ("utf-16-le", "utf-16-be"):
            _scan_text(data.decode(encoding, errors="ignore"), relative)


def _scan_content(data: bytes, relative: Path) -> None:
    _scan_bytes(data, relative)
    if relative.suffix.casefold() != ".pptx":
        return
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as deck:
            entries = [entry for entry in deck.infolist() if entry.filename.endswith((".xml", ".rels"))]
            if sum(entry.file_size for entry in entries) > MAX_PPT_XML_BYTES:
                raise PackageError(f"PPT 文本超出安全扫描上限：{relative.as_posix()}")
            for entry in entries:
                xml = deck.read(entry)
                _scan_bytes(xml, relative)
                # PPT 中显示的一段文字可能被多个 run 标签拆开。
                try:
                    text = "".join(ElementTree.fromstring(xml).itertext())
                except ElementTree.ParseError:
                    raise PackageError(f"PPT XML 无法安全检查：{relative.as_posix()}") from None
                _scan_text(text, relative)
    except (zipfile.BadZipFile, RuntimeError):
        raise PackageError(f"PPT 无法安全检查：{relative.as_posix()}") from None


def build_package(root: Path = ROOT, *, today: date | None = None) -> PackageResult:
    """先审查字节快照，再创建全新 zip；root 可注入临时目录用于离线测试。"""
    root = Path(root).resolve(strict=True)
    files = collect_files(root)
    if not files:
        raise PackageError("发布清单中没有可打包文件")
    snapshots: list[tuple[Path, bytes]] = []
    total_size = 0
    for relative in files:
        path = _safe_path(root, relative)
        if path is None or not path.is_file():
            raise PackageError(f"打包过程中路径变化：{relative.as_posix()}")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise PackageError(f"文件超出安全扫描上限：{relative.as_posix()}")
        with path.open("rb") as source:
            data = source.read(MAX_FILE_BYTES + 1)
        total_size += len(data)
        if len(data) > MAX_FILE_BYTES or total_size > MAX_PACKAGE_BYTES:
            raise PackageError(f"内容超出安全扫描上限：{relative.as_posix()}")
        _scan_content(data, relative)
        snapshots.append((relative, data))

    # 输出目录本身也不能借助 junction 指向项目之外。
    out_dir = _safe_path(root, Path("dist"))
    if out_dir is None:
        out_dir = root / "dist"
        out_dir.mkdir()
    if not out_dir.is_dir():
        raise PackageError("输出路径不是目录：dist")
    stem = f"地缘风险_提交包_{(today or date.today()):%Y%m%d}"
    sequence = 1
    while True:
        suffix = "" if sequence == 1 else f"_{sequence:02d}"
        out_path = out_dir / f"{stem}{suffix}.zip"
        try:
            output = out_path.open("xb")
            break
        except FileExistsError:
            sequence += 1
    try:
        with output, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for relative, data in snapshots:
                archive.writestr(relative.as_posix(), data)
    except BaseException:
        out_path.unlink(missing_ok=True)
        raise
    return PackageResult(out_path, len(snapshots))


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        result = build_package()
    except PackageError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"打包完成：{result.path}")
    print(f"文件数：{result.file_count}，大小：{result.path.stat().st_size / 1024:.0f} KB")
    print("已执行发布白名单与常见凭据检查；请在正式提交前人工复核内容。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
