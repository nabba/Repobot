"""
Fast repository scanner — builds context for agents by reading
the file tree and sampling key files.
"""

import os
from pathlib import Path

# Extensions we care about for code analysis
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".rb", ".php", ".swift", ".scala",
    ".vue", ".svelte", ".html", ".css", ".scss", ".sql", ".proto",
    ".yaml", ".yml", ".toml", ".json", ".xml", ".tf", ".hcl",
    ".sh", ".bash", ".zsh", ".fish", ".ps1",
    ".dockerfile", ".Dockerfile",
}

CONFIG_FILES = {
    "package.json", "Cargo.toml", "go.mod", "pyproject.toml", "setup.py",
    "setup.cfg", "requirements.txt", "Pipfile", "Gemfile", "pom.xml",
    "build.gradle", "build.gradle.kts", "Makefile", "CMakeLists.txt",
    "docker-compose.yml", "docker-compose.yaml", "Dockerfile",
    ".env.example", "tsconfig.json", "webpack.config.js", "vite.config.ts",
    "vite.config.js", "next.config.js", "next.config.mjs",
    ".github/workflows", "Jenkinsfile", ".gitlab-ci.yml",
    "README.md", "CLAUDE.md",
}

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    ".next", ".nuxt", "dist", "build", "target", ".cache", ".tox",
    "vendor", "coverage", ".mypy_cache", ".pytest_cache",
    ".terraform", ".idea", ".vscode",
}

MAX_FILE_SIZE = 50_000  # bytes
MAX_FILES_TO_READ = 80
MAX_CONTEXT_CHARS = 60_000


def scan_repo(repo_path: str) -> dict:
    """Return tree + sampled file contents."""
    root = Path(repo_path).resolve()
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")

    tree_lines: list[str] = []
    code_files: list[Path] = []
    config_files_found: list[Path] = []

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skip dirs
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        rel_dir = Path(dirpath).relative_to(root)
        depth = len(rel_dir.parts)
        if depth > 6:
            dirnames.clear()
            continue

        indent = "  " * depth
        dir_name = rel_dir.name or root.name
        tree_lines.append(f"{indent}{dir_name}/")

        for fname in sorted(filenames):
            fpath = Path(dirpath) / fname
            rel = fpath.relative_to(root)
            tree_lines.append(f"{indent}  {fname}")

            if fname in CONFIG_FILES or str(rel) in CONFIG_FILES:
                config_files_found.append(fpath)
            elif fpath.suffix in CODE_EXTENSIONS:
                code_files.append(fpath)

    # Prioritize: config files first, then code files sorted by size (smaller first)
    config_files_found.sort(key=lambda p: p.stat().st_size)
    code_files.sort(key=lambda p: p.stat().st_size)

    files_to_read = config_files_found[:20] + code_files[:MAX_FILES_TO_READ - 20]
    file_tree = "\n".join(tree_lines[:500])

    contents: list[str] = []
    total_chars = 0
    for fpath in files_to_read:
        try:
            size = fpath.stat().st_size
            if size > MAX_FILE_SIZE or size == 0:
                continue
            text = fpath.read_text(errors="replace")
            rel = fpath.relative_to(root)
            entry = f"\n--- {rel} ---\n{text}"
            if total_chars + len(entry) > MAX_CONTEXT_CHARS:
                # Truncate this file to fit
                remaining = MAX_CONTEXT_CHARS - total_chars - 200
                if remaining > 500:
                    entry = f"\n--- {rel} (truncated) ---\n{text[:remaining]}"
                else:
                    break
            contents.append(entry)
            total_chars += len(entry)
        except (OSError, UnicodeDecodeError):
            continue

    file_contents = "\n".join(contents)

    stats = {
        "total_files": len(tree_lines),
        "code_files": len(code_files),
        "config_files": len(config_files_found),
        "files_sampled": len(contents),
    }

    context = f"FILE TREE:\n{file_tree}\n\nFILE CONTENTS:\n{file_contents}"
    return {"context": context, "tree": file_tree, "stats": stats}
