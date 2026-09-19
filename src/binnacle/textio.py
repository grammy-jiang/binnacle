"""Text and byte helpers shared by file tools.

BOM handling and binary detection: docs/tools/read_file.md §3 (Gemini's
.ts MIME-trap lesson: the known-text allowlist runs before any sniff).
"""

from pathlib import Path

# Order matters: UTF-32 BOMs start with the UTF-16 ones.
_BOMS = (
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe", "utf-16-le"),
    (b"\xfe\xff", "utf-16-be"),
)

KNOWN_TEXT_EXTENSIONS = {
    ".bash",
    ".c",
    ".cc",
    ".cfg",
    ".cjs",
    ".conf",
    ".cpp",
    ".css",
    ".csv",
    ".cts",
    ".diff",
    ".el",
    ".env",
    ".go",
    ".h",
    ".hpp",
    ".hs",
    ".htm",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsonl",
    ".jsx",
    ".kt",
    ".lock",
    ".log",
    ".lua",
    ".md",
    ".mjs",
    ".mts",
    ".patch",
    ".php",
    ".pl",
    ".py",
    ".pyi",
    ".r",
    ".rb",
    ".rs",
    ".rst",
    ".scala",
    ".service",
    ".sh",
    ".socket",
    ".sql",
    ".svg",
    ".swift",
    ".timer",
    ".toml",
    ".ts",
    ".tsv",
    ".tsx",
    ".txt",
    ".vim",
    ".xml",
    ".yaml",
    ".yml",
    ".zsh",
}
KNOWN_TEXT_NAMES = {"Makefile", "Dockerfile", ".gitignore", ".bashrc", ".profile"}


def decode_text(data: bytes, path: Path) -> tuple[str, bool] | None:
    """Decode file bytes. Returns (text, lossy) or None for binary."""
    for bom, codec in _BOMS:
        if data.startswith(bom):
            body = data if codec == "utf-8-sig" else data[len(bom) :]
            try:
                return body.decode(codec), False
            except UnicodeDecodeError:
                return body.decode(codec, errors="replace"), True
    is_known_text = (
        path.suffix.lower() in KNOWN_TEXT_EXTENSIONS or path.name in KNOWN_TEXT_NAMES
    )
    if not is_known_text and b"\0" in data[:8192]:
        return None
    try:
        return data.decode("utf-8"), False
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace"), True


def human_size(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} bytes"
