#!/usr/bin/env python3
"""Deterministic corpus policy for Atelier semantic search.

This module owns path classification, scope membership, raw locator
generation, and read-only corpus auditing. It deliberately has no dependency
on an embedding model, an index backend, environment variables, or a private
vault path. Callers provide the corpus root explicitly.

The physical vault remains the source of truth. Raw locator cards are derived
in memory and returned as records; this module never persists them.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import stat
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence, Sized
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import sys as _s
_s.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import tier_segments  # noqa: E402
from typing import Any
from urllib.parse import unquote

# Increment whenever classification, exclusion, scope, or raw-card rendering
# changes in a way that requires existing derived indexes to be refreshed.
POLICY_VERSION = 2
POLICY_FINGERPRINT = f"semantic-corpus-v{POLICY_VERSION}"

ACTIVE_SCOPE = "active"
RAW_SCOPE = "raw"
ARCHIVE_SCOPE = "archive"
INBOX_SCOPE = "inbox"
PROCESS_SCOPE = "process"
ALL_SCOPE = "all"

INDEX_SCOPES = (
    ACTIVE_SCOPE,
    RAW_SCOPE,
    ARCHIVE_SCOPE,
    INBOX_SCOPE,
    PROCESS_SCOPE,
)
VALID_SCOPES = INDEX_SCOPES + (ALL_SCOPE,)

AUTHORED_EXTENSIONS = frozenset({".md"})
READABLE_RAW_EXTENSIONS = frozenset({".md", ".txt", ".text", ".csv", ".html", ".htm"})

AUTHORED_REPRESENTATION = "authored"
RAW_TEXT_REPRESENTATION = "raw_text"
RAW_LOCATOR_REPRESENTATION = "raw_locator"
RAW_LOCATOR_PATH_PREFIX = "@raw-locator/"

DEFAULT_MAX_CARD_CHARS = 1_600
DEFAULT_MAX_FILENAME_TERMS = 48
DEFAULT_MAX_DIGEST_PATHS = 12
DEFAULT_MAX_EXTENSION_ENTRIES = 16

_HARD_EXCLUSION_REASONS = frozenset(
    {
        "cache",
        "operational_meta",
        "routine_prompts",
        "trash",
        "orphan_stub",
        "hidden_operational",
        "operational_tools",
        "dependency_tree",
    }
)
_RAW_ASSET_OMISSION_REASONS = frozenset({"empty", "whitespace_only", "special_file"})
_FILENAME_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_REFERENCE_LEFT_BOUNDARY = frozenset("/\\ \t\r\n([?&'\"<>`{")
_REFERENCE_RIGHT_BOUNDARY = frozenset("/\\ \t\r\n)#?&'\"<>]}")
_SECRET_SPAN_RE = re.compile(
    r"(?ix)"
    r"(?:"
    r"(?:sk|rk|pk)[-_][a-z0-9_-]{8,}"
    r"|ghp_[a-z0-9]{12,}"
    r"|github_pat_[a-z0-9_]{12,}"
    r"|xox[baprs]-[a-z0-9-]{8,}"
    r"|AIza[a-z0-9_-]{12,}"
    r"|(?:AKIA|ASIA)[A-Z0-9]{12,}"
    r"|[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
    r")"
)


@dataclass(frozen=True, slots=True)
class CorpusFile:
    """Classification and filesystem metadata for one vault-relative file."""

    relative_path: str
    absolute_path: Path | None
    size: int
    mtime: float
    included: bool
    scope: str | None
    representation: str | None
    exclusion_reason: str | None
    is_raw: bool
    raw_cluster: str | None
    hard_excluded: bool
    regular_file: bool = True

    @property
    def scopes(self) -> tuple[str, ...]:
        """Scopes in which this physical file is directly retrievable."""
        if not self.included or self.scope is None:
            return ()
        return (self.scope,)

    @property
    def top_level(self) -> str:
        return top_level_path(self.relative_path)


@dataclass(frozen=True, slots=True)
class RawCluster:
    """Metadata used to render one derived raw locator card."""

    relative_path: str
    domain: str
    asset_paths: tuple[str, ...]
    extension_histogram: tuple[tuple[str, int], ...]
    filename_terms: tuple[str, ...]
    mtime_start: float
    mtime_end: float
    digest_paths: tuple[str, ...] = ()
    manifest_fingerprint: str = ""

    @property
    def asset_count(self) -> int:
        return len(self.asset_paths)


@dataclass(frozen=True, slots=True)
class CorpusRecord:
    """A unit of content offered to an indexer or lexical searcher."""

    record_id: str
    path: str
    text: str
    scope: str
    scopes: tuple[str, ...]
    representation: str
    mtime: float
    size: int
    manifest_fingerprint: str
    source_path: Path | None = None
    raw_cluster: RawCluster | None = None

    @property
    def top_level(self) -> str:
        return top_level_path(self.path)


ChunkEstimator = Callable[[str], int | Sequence[Any] | Sized]


def corpus_metadata_fingerprint(scope: str, representation: str) -> str:
    """Bind one indexed record to policy, scope, and representation."""
    return f"{POLICY_FINGERPRINT}:{scope}:{representation}"


def physical_manifest_fingerprint(
    scope: str,
    representation: str,
    mtime: float,
) -> str:
    """Bind a physical record to its policy metadata and precise timestamp.

    The index still stores the portable float ``mtime`` for query filters, but
    its manifest needs a sub-second signature.  Otherwise the historical
    one-second comparison tolerance can hide an edit made immediately after
    an index pass.
    """
    mtime_ns = int(round(mtime * 1_000_000_000))
    return f"{corpus_metadata_fingerprint(scope, representation)}:mtime-ns={mtime_ns}"


def normalize_relative_path(path: str | os.PathLike[str]) -> str:
    """Return a safe, normalized POSIX path relative to a supplied root."""
    raw = os.fspath(path).replace("\\", "/")
    normalized = PurePosixPath(raw)
    if normalized.is_absolute():
        raise ValueError(f"corpus path must be relative: {raw!r}")
    parts = normalized.parts
    if not parts or parts == (".",):
        raise ValueError("corpus path must not be empty")
    if any(part == ".." for part in parts):
        raise ValueError(f"corpus path must not escape its root: {raw!r}")
    return normalized.as_posix()


def top_level_path(path: str | os.PathLike[str]) -> str:
    """Return the first path segment used by audit groupings."""
    relative = normalize_relative_path(path)
    return PurePosixPath(relative).parts[0]


def validate_scope(scope: str) -> str:
    """Validate and normalize a public semantic scope."""
    normalized = scope.strip().lower()
    if normalized not in VALID_SCOPES:
        choices = ", ".join(VALID_SCOPES)
        raise ValueError(f"unknown corpus scope {scope!r}; expected one of {choices}")
    return normalized


def scopes_for_path(path: str | os.PathLike[str]) -> tuple[str, ...]:
    """Return zone membership using a vault-relative or synthetic path only.

    This is intentionally a zone classifier, not a full inclusion decision.
    It cannot infer emptiness, readability, or file type. Use
    :func:`classify_relative_path` when those facts are available.

    Synthetic ``@raw-locator/<cluster>`` paths belong to both ``active`` and
    ``raw``. Hard-excluded prefixes belong to no scope. Any nested ``raw/``
    path belongs to ``raw``; top-level ``archive/``, ``inbox/``, and
    ``sessions/`` map to ``archive``, ``inbox``, and ``process``. Every other
    non-hard-excluded path belongs to ``active``.
    """
    relative = normalize_relative_path(path)
    if relative.startswith(RAW_LOCATOR_PATH_PREFIX):
        return (ACTIVE_SCOPE, RAW_SCOPE)
    if _hard_exclusion_reason(relative) is not None:
        return ()
    if is_raw_path(relative):
        return (RAW_SCOPE,)
    return (_native_scope(relative, raw=False),)


def scope_matches(
    path_or_record: CorpusRecord | CorpusFile | str | os.PathLike[str],
    requested_scope: str,
) -> bool:
    """Return whether a path or classified record is visible in a query scope.

    ``CorpusRecord.scopes`` is authoritative for derived and physical records.
    ``CorpusFile`` honors its full inclusion decision, including hard
    exclusions and empty content. A string or path-like value receives the
    zone-only semantics documented by :func:`scopes_for_path`.

    ``all`` means the union of the five indexed scopes. It does not override a
    hard exclusion or make an excluded ``CorpusFile`` searchable.
    """
    requested = validate_scope(requested_scope)
    if isinstance(path_or_record, (CorpusRecord, CorpusFile)):
        scopes = path_or_record.scopes
    else:
        scopes = scopes_for_path(path_or_record)

    if requested == ALL_SCOPE:
        return bool(scopes)
    return requested in scopes


def path_prefix_matches(
    path: str | os.PathLike[str],
    prefix: str | os.PathLike[str],
) -> bool:
    """Match a physical path or a raw locator through its virtual source path."""
    relative = normalize_relative_path(path)
    requested = normalize_relative_path(prefix)
    candidates = [relative]
    if relative.startswith(RAW_LOCATOR_PATH_PREFIX):
        candidates.append(relative[len(RAW_LOCATOR_PATH_PREFIX) :])
    return any(
        candidate == requested or candidate.startswith(requested + "/")
        for candidate in candidates
    )


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _path_prefix_sql(column: str, prefix: str) -> str:
    """Build a directory-boundary prefix predicate without LIKE escaping."""
    child_start = prefix + "/"
    child_end = prefix + "0"
    return (
        f"({column} = {_sql_literal(prefix)} OR "
        f"({column} >= {_sql_literal(child_start)} AND "
        f"{column} < {_sql_literal(child_end)}))"
    )


def _legacy_scope_sql(scope: str, path_column: str) -> str:
    """Build a path-derived filter for an index without metadata columns."""
    hard_prefixes = (
        "cache",
        tier_segments().get("meta", "_meta"),
        "_routine_prompts",
        ".trash",
        "archive/orphan-stubs",
    )
    hard_parts = [_path_prefix_sql(path_column, prefix) for prefix in hard_prefixes]
    hard_parts.append(
        f"({path_column} >= {_sql_literal('.')} AND "
        f"{path_column} < {_sql_literal('/')})"
    )
    for operational_segment in (
        "cache",
        tier_segments().get("meta", "_meta"),
        "_routine_prompts",
        ".trash",
        "_tools",
        "node_modules",
        ".venv",
        "__pycache__",
    ):
        hard_parts.append(
            f"({path_column} LIKE {_sql_literal(operational_segment + '/%')} OR "
            f"{path_column} LIKE "
            f"{_sql_literal('%/' + operational_segment + '/%')})"
        )
    hard_parts.append(f"{path_column} LIKE {_sql_literal('%/.%')}")
    hard = "(" + " OR ".join(hard_parts) + ")"
    allowed = f"NOT {hard}"

    locator = _path_prefix_sql(path_column, RAW_LOCATOR_PATH_PREFIX.rstrip("/"))
    raw_file = (
        f"({path_column} LIKE {_sql_literal('raw/%')} OR "
        f"{path_column} LIKE {_sql_literal('%/raw/%')})"
    )
    raw = f"({locator} OR {raw_file})"
    archive_prefix = _path_prefix_sql(path_column, "archive")
    process_prefix = _path_prefix_sql(path_column, "sessions")
    inbox_path = (
        f"({_path_prefix_sql(path_column, 'inbox')} OR "
        f"{path_column} LIKE {_sql_literal('%/inbox/%')})"
    )
    archive = f"({archive_prefix} AND NOT {raw})"
    process = f"({process_prefix} AND NOT {raw})"
    inbox = (
        f"({inbox_path} AND NOT {raw} AND NOT {archive_prefix} "
        f"AND NOT {process_prefix})"
    )

    if scope == ALL_SCOPE:
        return allowed
    if scope == RAW_SCOPE:
        return f"({allowed} AND {raw})"
    if scope == ARCHIVE_SCOPE:
        return f"({allowed} AND {archive})"
    if scope == INBOX_SCOPE:
        return f"({allowed} AND {inbox})"
    if scope == PROCESS_SCOPE:
        return f"({allowed} AND {process})"

    non_active = f"({raw} OR {archive} OR {inbox} OR {process})"
    return f"({allowed} AND NOT {non_active})"


def scope_sql(
    scope: str,
    quote: Callable[[str], str] = lambda value: value,
    has_metadata_columns: bool = True,
) -> str:
    """Return a backend-neutral SQL predicate for Lance-compatible filters.

    With ``has_metadata_columns=True``, the additive index schema is assumed
    to expose string columns ``scope`` and ``representation``. With it set to
    ``False``, the predicate derives scope from the legacy ``path`` column and
    also filters hard-excluded prefixes. The fallback cannot infer emptiness
    or unsupported extensions.

    ``quote`` is applied only to identifier names, which lets a caller add
    dialect-specific identifier quoting. SQL string values are escaped by
    this module.

    Locator records have primary scope ``active`` and representation
    ``raw_locator``. The explicit ``raw`` predicate therefore includes both
    readable raw text and locator records.
    """
    requested = validate_scope(scope)
    if not has_metadata_columns:
        return _legacy_scope_sql(requested, quote("path"))

    scope_column = quote("scope")
    representation_column = quote("representation")
    if requested == RAW_SCOPE:
        return (
            f"({scope_column} = {_sql_literal(RAW_SCOPE)} OR "
            f"{representation_column} = {_sql_literal(RAW_LOCATOR_REPRESENTATION)})"
        )
    if requested == ALL_SCOPE:
        values = ", ".join(_sql_literal(value) for value in INDEX_SCOPES)
        return f"{scope_column} IN ({values})"
    return f"{scope_column} = {_sql_literal(requested)}"


def is_raw_path(path: str | os.PathLike[str]) -> bool:
    """Return whether the relative path contains a directory named ``raw``."""
    parts = PurePosixPath(normalize_relative_path(path)).parts
    return "raw" in parts[:-1]


def raw_cluster_path(path: str | os.PathLike[str]) -> str | None:
    """Derive the stable cluster directory for a raw asset.

    The first directory below a ``raw`` segment names the cluster. Files
    directly inside ``raw`` are grouped under that directory itself.
    """
    relative = normalize_relative_path(path)
    parts = PurePosixPath(relative).parts
    try:
        raw_index = parts[:-1].index("raw")
    except ValueError:
        return None

    parent_parts = parts[:-1]
    if len(parent_parts) > raw_index + 1:
        cluster_parts = parts[: raw_index + 2]
    else:
        cluster_parts = parts[: raw_index + 1]
    return PurePosixPath(*cluster_parts).as_posix()


def _hard_exclusion_reason(relative_path: str) -> str | None:
    parts = PurePosixPath(relative_path).parts
    top = parts[0]
    directories = parts[:-1]
    if "cache" in directories or top == "cache":
        return "cache"
    if tier_segments().get("meta", "_meta") in directories or top == tier_segments().get("meta", "_meta"):
        return "operational_meta"
    if "_routine_prompts" in directories or top == "_routine_prompts":
        return "routine_prompts"
    if ".trash" in directories or top == ".trash":
        return "trash"
    if len(parts) >= 2 and parts[:2] == ("archive", "orphan-stubs"):
        return "orphan_stub"
    if "_tools" in directories:
        return "operational_tools"
    if any(part in {"node_modules", ".venv", "__pycache__"} for part in directories):
        return "dependency_tree"
    if top.startswith(".") or any(part.startswith(".") for part in directories):
        return "hidden_operational"
    return None


def _native_scope(relative_path: str, *, raw: bool) -> str:
    if raw:
        return RAW_SCOPE
    parts = PurePosixPath(relative_path).parts
    top = parts[0]
    if top == "archive":
        return ARCHIVE_SCOPE
    if top == "sessions":
        return PROCESS_SCOPE
    if "inbox" in parts[:-1]:
        return INBOX_SCOPE
    return ACTIVE_SCOPE


def classify_relative_path(
    relative_path: str | os.PathLike[str],
    *,
    size: int,
    mtime: float = 0.0,
    has_text: bool | None = None,
    readable: bool = True,
    regular_file: bool = True,
    absolute_path: Path | None = None,
) -> CorpusFile:
    """Classify supplied metadata without touching the filesystem.

    ``has_text`` distinguishes whitespace-only content from non-empty text.
    Callers that only have metadata may leave it as ``None``; non-zero files
    with a supported text extension are then provisionally treated as text.
    """
    relative = normalize_relative_path(relative_path)
    if size < 0:
        raise ValueError("file size must not be negative")

    raw = is_raw_path(relative)
    cluster = raw_cluster_path(relative) if raw else None
    hard_reason = _hard_exclusion_reason(relative)
    if hard_reason is not None:
        return CorpusFile(
            relative_path=relative,
            absolute_path=absolute_path,
            size=size,
            mtime=mtime,
            included=False,
            scope=None,
            representation=None,
            exclusion_reason=hard_reason,
            is_raw=raw,
            raw_cluster=cluster,
            hard_excluded=True,
            regular_file=regular_file,
        )

    if not regular_file:
        return CorpusFile(
            relative_path=relative,
            absolute_path=absolute_path,
            size=size,
            mtime=mtime,
            included=False,
            scope=None,
            representation=None,
            exclusion_reason="special_file",
            is_raw=raw,
            raw_cluster=cluster,
            hard_excluded=False,
            regular_file=False,
        )

    if size == 0:
        return CorpusFile(
            relative_path=relative,
            absolute_path=absolute_path,
            size=0,
            mtime=mtime,
            included=False,
            scope=None,
            representation=None,
            exclusion_reason="empty",
            is_raw=raw,
            raw_cluster=cluster,
            hard_excluded=False,
        )

    extension = PurePosixPath(relative).suffix.lower()
    supported = (
        extension in READABLE_RAW_EXTENSIONS
        if raw
        else extension in AUTHORED_EXTENSIONS
    )
    if not supported:
        reason = "raw_binary_locator_only" if raw else "unsupported_extension"
        return CorpusFile(
            relative_path=relative,
            absolute_path=absolute_path,
            size=size,
            mtime=mtime,
            included=False,
            scope=None,
            representation=None,
            exclusion_reason=reason,
            is_raw=raw,
            raw_cluster=cluster,
            hard_excluded=False,
        )

    if not readable:
        return CorpusFile(
            relative_path=relative,
            absolute_path=absolute_path,
            size=size,
            mtime=mtime,
            included=False,
            scope=None,
            representation=None,
            exclusion_reason="unreadable",
            is_raw=raw,
            raw_cluster=cluster,
            hard_excluded=False,
        )

    if has_text is False:
        return CorpusFile(
            relative_path=relative,
            absolute_path=absolute_path,
            size=size,
            mtime=mtime,
            included=False,
            scope=None,
            representation=None,
            exclusion_reason="whitespace_only",
            is_raw=raw,
            raw_cluster=cluster,
            hard_excluded=False,
        )

    return CorpusFile(
        relative_path=relative,
        absolute_path=absolute_path,
        size=size,
        mtime=mtime,
        included=True,
        scope=_native_scope(relative, raw=raw),
        representation=(RAW_TEXT_REPRESENTATION if raw else AUTHORED_REPRESENTATION),
        exclusion_reason=None,
        is_raw=raw,
        raw_cluster=cluster,
        hard_excluded=False,
    )


def _probe_non_whitespace(path: Path) -> tuple[bool, bool]:
    """Return ``(readable, has_text)`` without retaining file content."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            while chunk := handle.read(8_192):
                if chunk.strip():
                    return True, True
        return True, False
    except OSError:
        return False, False


def classify_file(path: Path, root: Path) -> CorpusFile:
    """Classify one filesystem path relative to ``root``."""
    corpus_root = root.expanduser().resolve()
    absolute = path.expanduser()
    if not absolute.is_absolute():
        absolute = corpus_root / absolute
    try:
        relative = absolute.relative_to(corpus_root).as_posix()
    except ValueError as exc:
        raise ValueError(f"path is outside corpus root: {absolute}") from exc

    try:
        metadata = absolute.lstat()
    except OSError:
        return classify_relative_path(
            relative,
            size=0,
            readable=False,
            regular_file=False,
            absolute_path=absolute,
        )

    regular = stat.S_ISREG(metadata.st_mode)
    if (
        _hard_exclusion_reason(relative) is not None
        or not regular
        or metadata.st_size == 0
    ):
        return classify_relative_path(
            relative,
            size=metadata.st_size,
            mtime=metadata.st_mtime,
            regular_file=regular,
            absolute_path=absolute,
        )

    extension = PurePosixPath(relative).suffix.lower()
    raw = is_raw_path(relative)
    supported_text = (
        extension in READABLE_RAW_EXTENSIONS
        if raw
        else extension in AUTHORED_EXTENSIONS
    )
    readable = True
    has_text: bool | None = None
    if regular and metadata.st_size > 0 and supported_text:
        readable, has_text = _probe_non_whitespace(absolute)

    return classify_relative_path(
        relative,
        size=metadata.st_size,
        mtime=metadata.st_mtime,
        has_text=has_text,
        readable=readable,
        regular_file=regular,
        absolute_path=absolute,
    )


def iter_file_decisions(root: Path) -> Iterator[CorpusFile]:
    """Yield deterministic decisions for regular and symlinked files.

    Version-control internals are outside the vault corpus and are not audited.
    Other excluded surfaces remain visible so the audit can account for them.
    """
    corpus_root = root.expanduser().resolve()
    if not corpus_root.is_dir():
        raise NotADirectoryError(f"corpus root is not a directory: {corpus_root}")

    for current, directory_names, file_names in os.walk(
        corpus_root, topdown=True, followlinks=False
    ):
        current_path = Path(current)
        directory_names[:] = sorted(
            name
            for name in directory_names
            if name != ".git" and not (current_path / name).is_symlink()
        )
        for name in sorted(file_names):
            yield classify_file(current_path / name, corpus_root)


def iter_corpus_files(
    root: Path,
    *,
    scope: str = ALL_SCOPE,
) -> Iterator[CorpusFile]:
    """Yield included physical text files visible in ``scope``."""
    requested = validate_scope(scope)
    for item in iter_file_decisions(root):
        if item.included and scope_matches(item, requested):
            yield item


def corpus_record_for_file(
    item: CorpusFile,
    *,
    text: str | None = None,
) -> CorpusRecord:
    """Read or wrap one included physical file as an indexable record."""
    if not item.included or item.scope is None or item.representation is None:
        raise ValueError(f"file is not included in the corpus: {item.relative_path}")
    if text is None:
        if item.absolute_path is None:
            raise ValueError("text is required when a CorpusFile has no absolute path")
        text = item.absolute_path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        raise ValueError(f"included file became empty: {item.relative_path}")

    prefix = "raw-text" if item.is_raw else "file"
    return CorpusRecord(
        record_id=f"{prefix}:{item.relative_path}",
        path=item.relative_path,
        text=text,
        scope=item.scope,
        scopes=(item.scope,),
        representation=item.representation,
        mtime=item.mtime,
        size=item.size,
        manifest_fingerprint=physical_manifest_fingerprint(
            item.scope,
            item.representation,
            item.mtime,
        ),
        source_path=item.absolute_path,
    )


def _token_entropy(token: str) -> float:
    counts = Counter(token)
    length = len(token)
    return -sum(
        (count / length) * math.log2(count / length) for count in counts.values()
    )


def _safe_filename_term(term: str) -> bool:
    """Reject numeric and credential-shaped filename material."""
    if not term or term == "redacted" or term.isdecimal():
        return False
    if len(term) > 48:
        return False
    if len(term) >= 16 and re.fullmatch(r"[0-9a-f]+", term, re.IGNORECASE):
        return False
    if (
        len(term) >= 16
        and any(character.isalpha() for character in term)
        and any(character.isdigit() for character in term)
        and _token_entropy(term.casefold()) >= 3.5
    ):
        return False
    return True


def _redact_locator_value(value: str) -> str:
    """Redact credential-shaped spans before text enters a locator index."""
    redacted = _SECRET_SPAN_RE.sub("[redacted]", value)

    def replace_high_entropy(match: re.Match[str]) -> str:
        token = match.group(0)
        if token.casefold() == "redacted":
            return token
        if token.isdecimal():
            return token
        if not _safe_filename_term(token.casefold()):
            return "[redacted]"
        return token

    return _FILENAME_TOKEN_RE.sub(replace_high_entropy, redacted)


def _filename_terms(
    paths: Iterable[str],
    *,
    limit: int = DEFAULT_MAX_FILENAME_TERMS,
) -> tuple[str, ...]:
    counts: Counter[str] = Counter()
    for path in paths:
        name = PurePosixPath(path).stem
        normalized = unicodedata.normalize("NFKC", name)
        normalized = _SECRET_SPAN_RE.sub(" redacted ", normalized)
        normalized = _CAMEL_BOUNDARY_RE.sub(" ", normalized)
        for match in _FILENAME_TOKEN_RE.finditer(normalized):
            term = match.group(0).casefold()[:64]
            if _safe_filename_term(term):
                counts[term] += 1
    ranked = sorted(counts, key=lambda term: (-counts[term], term))
    return tuple(ranked[: max(0, limit)])


def _extension_histogram(paths: Iterable[str]) -> tuple[tuple[str, int], ...]:
    counts: Counter[str] = Counter()
    for path in paths:
        extension = PurePosixPath(path).suffix.casefold() or "[none]"
        counts[extension] += 1
    return tuple(sorted(counts.items(), key=lambda row: (-row[1], row[0])))


def _raw_domain(cluster_path: str) -> str:
    parts = PurePosixPath(cluster_path).parts
    raw_index = parts.index("raw")
    return PurePosixPath(*parts[:raw_index]).as_posix() if raw_index else "(root)"


def _is_raw_asset(item: CorpusFile) -> bool:
    if not item.is_raw or item.hard_excluded or not item.regular_file:
        return False
    if item.size == 0 or item.exclusion_reason in _RAW_ASSET_OMISSION_REASONS:
        return False
    return item.raw_cluster is not None


def build_raw_clusters(
    files: Iterable[CorpusFile],
    *,
    digest_references: Mapping[str, Iterable[str]] | None = None,
    max_filename_terms: int = DEFAULT_MAX_FILENAME_TERMS,
) -> tuple[RawCluster, ...]:
    """Build stable raw-cluster metadata from already classified files."""
    grouped: dict[str, list[CorpusFile]] = defaultdict(list)
    for item in files:
        if _is_raw_asset(item) and item.raw_cluster is not None:
            grouped[item.raw_cluster].append(item)

    references = digest_references or {}
    clusters: list[RawCluster] = []
    for cluster_path in sorted(grouped):
        assets = sorted(grouped[cluster_path], key=lambda item: item.relative_path)
        asset_paths = tuple(item.relative_path for item in assets)
        mtimes = tuple(item.mtime for item in assets)
        digest_paths = tuple(
            sorted(
                {
                    normalize_relative_path(path)
                    for path in references.get(cluster_path, ())
                }
            )
        )
        manifest_hasher = hashlib.sha256()
        manifest_hasher.update(POLICY_FINGERPRINT.encode("ascii"))
        manifest_hasher.update(b"\0raw-locator-manifest\0")
        for item in assets:
            manifest_hasher.update(item.relative_path.encode("utf-8"))
            manifest_hasher.update(b"\0")
            manifest_hasher.update(str(item.size).encode("ascii"))
            manifest_hasher.update(b"\0")
            manifest_hasher.update(item.mtime.hex().encode("ascii"))
            manifest_hasher.update(b"\n")
        for digest_path in digest_paths:
            manifest_hasher.update(b"digest\0")
            manifest_hasher.update(digest_path.encode("utf-8"))
            manifest_hasher.update(b"\n")
        clusters.append(
            RawCluster(
                relative_path=cluster_path,
                domain=_raw_domain(cluster_path),
                asset_paths=asset_paths,
                extension_histogram=_extension_histogram(asset_paths),
                filename_terms=_filename_terms(asset_paths, limit=max_filename_terms),
                mtime_start=min(mtimes),
                mtime_end=max(mtimes),
                digest_paths=digest_paths,
                manifest_fingerprint=manifest_hasher.hexdigest(),
            )
        )
    return tuple(clusters)


def _reference_text(text: str) -> str:
    return unicodedata.normalize("NFKC", unquote(text)).replace("\\", "/").casefold()


def _contains_path_reference(text: str, needle: str) -> bool:
    """Match a path without letting ``raw/foo`` match ``raw/foobar``."""
    start = 0
    while True:
        index = text.find(needle, start)
        if index < 0:
            return False
        end = index + len(needle)
        left_ok = index == 0 or text[index - 1] in _REFERENCE_LEFT_BOUNDARY
        right_ok = end == len(text) or text[end] in _REFERENCE_RIGHT_BOUNDARY
        if left_ok and right_ok:
            return True
        start = index + 1


def discover_authored_digest_references(
    clusters: Iterable[RawCluster],
    files: Iterable[CorpusFile],
) -> dict[str, tuple[str, ...]]:
    """Find active authored Markdown files that explicitly mention a cluster."""
    cluster_rows: list[tuple[str, str | None, str]] = []
    for cluster in clusters:
        parts = PurePosixPath(cluster.relative_path).parts
        raw_index = parts.index("raw")
        local_path = PurePosixPath(*parts[raw_index:]).as_posix()
        if local_path == "raw":
            local_path = None
        cluster_rows.append(
            (
                _reference_text(cluster.relative_path),
                _reference_text(local_path) if local_path else None,
                cluster.relative_path,
            )
        )

    references: dict[str, set[str]] = defaultdict(set)
    authored = sorted(
        (
            item
            for item in files
            if item.included
            and item.scope == ACTIVE_SCOPE
            and item.representation == AUTHORED_REPRESENTATION
            and item.absolute_path is not None
        ),
        key=lambda item: item.relative_path,
    )
    for item in authored:
        assert item.absolute_path is not None
        try:
            text = _reference_text(
                item.absolute_path.read_text(encoding="utf-8", errors="replace")
            )
        except OSError:
            continue
        item_top = item.top_level
        for full_path, local_path, cluster_path in cluster_rows:
            cluster_top = top_level_path(cluster_path)
            matched = _contains_path_reference(text, full_path)
            if not matched and local_path is not None and item_top == cluster_top:
                matched = _contains_path_reference(text, local_path)
            if matched:
                references[cluster_path].add(item.relative_path)

    return {
        cluster_path: tuple(sorted(paths))
        for cluster_path, paths in sorted(references.items())
    }


def _utc_date(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat()


def render_raw_locator_card(
    cluster: RawCluster,
    *,
    max_chars: int = DEFAULT_MAX_CARD_CHARS,
    max_digest_paths: int = DEFAULT_MAX_DIGEST_PATHS,
    max_extension_entries: int = DEFAULT_MAX_EXTENSION_ENTRIES,
) -> str:
    """Render a deterministic, visibly bounded raw locator card."""
    if max_chars < 256:
        raise ValueError("raw locator card budget must be at least 256 characters")

    extensions = list(cluster.extension_histogram[:max_extension_entries])
    omitted_extensions = cluster.extension_histogram[max_extension_entries:]
    extension_text = ", ".join(
        f"{extension}={count}" for extension, count in extensions
    )
    if omitted_extensions:
        extension_text += f", [other]={sum(count for _, count in omitted_extensions)}"

    digests = list(cluster.digest_paths[:max_digest_paths])
    omitted_digests = len(cluster.digest_paths) - len(digests)
    digest_text = (
        "; ".join(_redact_locator_value(path) for path in digests)
        if digests
        else "[none]"
    )
    if omitted_digests:
        digest_text += f"; [+{omitted_digests} more]"

    lines = [
        "Raw cluster locator",
        f"Domain: {_redact_locator_value(cluster.domain)}",
        f"Directory: {_redact_locator_value(cluster.relative_path)}",
        f"Assets: {cluster.asset_count}",
        f"Extensions: {extension_text or '[none]'}",
        (
            "Modified UTC: "
            f"{_utc_date(cluster.mtime_start)} to {_utc_date(cluster.mtime_end)}"
        ),
        (
            "Filename terms: "
            + (" ".join(cluster.filename_terms) if cluster.filename_terms else "[none]")
        ),
        f"Authored digests: {digest_text}",
    ]
    card = "\n".join(lines)
    if len(card) <= max_chars:
        return card
    marker = "\n[truncated]"
    return card[: max_chars - len(marker)].rstrip() + marker


def _raw_locator_id(cluster_path: str) -> str:
    digest = hashlib.sha256(cluster_path.encode("utf-8")).hexdigest()[:20]
    return f"raw-locator:{digest}"


def _raw_locator_path(cluster_path: str) -> str:
    safe_path = _redact_locator_value(cluster_path)
    if safe_path != cluster_path:
        suffix = hashlib.sha256(cluster_path.encode("utf-8")).hexdigest()[:8]
        safe_path = f"{safe_path}--{suffix}"
    return RAW_LOCATOR_PATH_PREFIX + safe_path


def build_raw_locator_records(
    root: Path,
    *,
    files: Iterable[CorpusFile] | None = None,
    digest_references: Mapping[str, Iterable[str]] | None = None,
    max_card_chars: int = DEFAULT_MAX_CARD_CHARS,
) -> tuple[CorpusRecord, ...]:
    """Generate raw locator records in memory without extracting raw content."""
    decisions = tuple(files) if files is not None else tuple(iter_file_decisions(root))
    clusters = build_raw_clusters(decisions)
    references = (
        {key: tuple(value) for key, value in digest_references.items()}
        if digest_references is not None
        else discover_authored_digest_references(clusters, decisions)
    )
    clusters = build_raw_clusters(decisions, digest_references=references)

    records: list[CorpusRecord] = []
    for cluster in clusters:
        text = render_raw_locator_card(cluster, max_chars=max_card_chars)
        records.append(
            CorpusRecord(
                record_id=_raw_locator_id(cluster.relative_path),
                path=_raw_locator_path(cluster.relative_path),
                text=text,
                scope=ACTIVE_SCOPE,
                scopes=(ACTIVE_SCOPE, RAW_SCOPE),
                representation=RAW_LOCATOR_REPRESENTATION,
                mtime=cluster.mtime_end,
                size=len(text.encode("utf-8")),
                manifest_fingerprint=(
                    f"{corpus_metadata_fingerprint(ACTIVE_SCOPE, RAW_LOCATOR_REPRESENTATION)}:"
                    f"{cluster.manifest_fingerprint}"
                ),
                source_path=None,
                raw_cluster=cluster,
            )
        )
    return tuple(records)


def iter_raw_locator_records(
    root: Path,
    *,
    files: Iterable[CorpusFile] | None = None,
    digest_references: Mapping[str, Iterable[str]] | None = None,
    max_card_chars: int = DEFAULT_MAX_CARD_CHARS,
) -> Iterator[CorpusRecord]:
    """Iterator form of :func:`build_raw_locator_records`."""
    yield from build_raw_locator_records(
        root,
        files=files,
        digest_references=digest_references,
        max_card_chars=max_card_chars,
    )


def iter_corpus_records(
    root: Path,
    *,
    scope: str = ACTIVE_SCOPE,
    files: Iterable[CorpusFile] | None = None,
    include_locators: bool = True,
    max_card_chars: int = DEFAULT_MAX_CARD_CHARS,
) -> Iterator[CorpusRecord]:
    """Yield deterministic physical and derived records visible in ``scope``."""
    requested = validate_scope(scope)
    decisions = tuple(files) if files is not None else tuple(iter_file_decisions(root))
    records: list[CorpusRecord] = []

    for item in decisions:
        if not item.included or not scope_matches(item, requested):
            continue
        try:
            records.append(corpus_record_for_file(item))
        except (OSError, UnicodeError, ValueError):
            continue

    if include_locators and requested in {ACTIVE_SCOPE, RAW_SCOPE, ALL_SCOPE}:
        records.extend(
            record
            for record in build_raw_locator_records(
                root, files=decisions, max_card_chars=max_card_chars
            )
            if scope_matches(record, requested)
        )

    records.sort(
        key=lambda record: (record.path, record.representation, record.record_id)
    )
    yield from records


def _new_count() -> dict[str, int]:
    return {"files": 0, "bytes": 0}


def _increment(counter: dict[str, int], *, size: int) -> None:
    counter["files"] += 1
    counter["bytes"] += size


def _estimate_chunks(estimator: ChunkEstimator, text: str) -> int:
    estimate = estimator(text)
    if isinstance(estimate, bool):
        raise TypeError("chunk estimator must not return bool")
    if isinstance(estimate, int):
        count = estimate
    else:
        count = len(estimate)
    if count < 0:
        raise ValueError("chunk estimator returned a negative count")
    return count


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _summarize_duplicate_groups(
    hashes: Mapping[str, Sequence[tuple[str, int]]],
    *,
    basis: str,
    considered_files: int,
    considered_bytes: int,
    hashed_files: int,
    unreadable_files: int,
    sample_limit: int,
) -> dict[str, Any]:
    duplicate_groups = [
        (digest, sorted(rows)) for digest, rows in hashes.items() if len(rows) > 1
    ]
    duplicate_groups.sort(key=lambda row: (-len(row[1]), row[0]))
    duplicate_files = sum(len(rows) for _, rows in duplicate_groups)
    duplicate_bytes = sum(sum(size for _, size in rows) for _, rows in duplicate_groups)
    redundant_bytes = sum(
        sum(size for _, size in rows[1:]) for _, rows in duplicate_groups
    )
    samples = [
        {
            "sha256": digest,
            "files": len(rows),
            "bytes": sum(size for _, size in rows),
            "paths": [path for path, _ in rows[:20]],
        }
        for digest, rows in duplicate_groups[:sample_limit]
    ]
    return {
        "basis": basis,
        "considered_files": considered_files,
        "considered_bytes": considered_bytes,
        "hashed_files": hashed_files,
        "unreadable_files": unreadable_files,
        "groups": len(duplicate_groups),
        "files": duplicate_files,
        "bytes": duplicate_bytes,
        "redundant_bytes": redundant_bytes,
        "samples": samples,
    }


def _duplicate_summary(
    files: Iterable[CorpusFile],
    *,
    sample_limit: int,
) -> dict[str, Any]:
    """Hash all regular physical files that could have an exact-size peer."""
    regular_files = [
        item for item in files if item.regular_file and item.absolute_path is not None
    ]
    by_size: dict[int, list[CorpusFile]] = defaultdict(list)
    for item in regular_files:
        by_size[item.size].append(item)

    all_hashes: dict[str, list[tuple[str, int]]] = defaultdict(list)
    included_hashes: dict[str, list[tuple[str, int]]] = defaultdict(list)
    hashed_files = 0
    included_hashed_files = 0
    unreadable_files = 0
    included_unreadable_files = 0

    for size, same_size_files in sorted(by_size.items()):
        if len(same_size_files) < 2:
            continue
        for item in sorted(same_size_files, key=lambda row: row.relative_path):
            assert item.absolute_path is not None
            try:
                digest = (
                    hashlib.sha256(b"").hexdigest()
                    if size == 0
                    else _hash_file(item.absolute_path)
                )
            except OSError:
                unreadable_files += 1
                if item.included:
                    included_unreadable_files += 1
                continue
            hashed_files += 1
            all_hashes[digest].append((item.relative_path, size))
            if item.included:
                included_hashed_files += 1
                included_hashes[digest].append((item.relative_path, size))

    included_files = [item for item in regular_files if item.included]
    summary = _summarize_duplicate_groups(
        all_hashes,
        basis="all_regular_physical_files",
        considered_files=len(regular_files),
        considered_bytes=sum(item.size for item in regular_files),
        hashed_files=hashed_files,
        unreadable_files=unreadable_files,
        sample_limit=sample_limit,
    )
    summary["included_text"] = _summarize_duplicate_groups(
        included_hashes,
        basis="included_physical_text_files",
        considered_files=len(included_files),
        considered_bytes=sum(item.size for item in included_files),
        hashed_files=included_hashed_files,
        unreadable_files=included_unreadable_files,
        sample_limit=sample_limit,
    )
    return summary


def audit_corpus(
    root: Path,
    *,
    chunk_estimator: ChunkEstimator | None = None,
    duplicate_sample_limit: int = 10,
    sample_limit: int = 20,
    max_card_chars: int = DEFAULT_MAX_CARD_CHARS,
) -> dict[str, Any]:
    """Return a read-only, model-free corpus audit.

    ``chunk_estimator`` may return either an integer count or a sized sequence,
    so callers can pass ``lambda text: len(chunk_markdown(text))`` or the real
    chunker directly.
    """
    corpus_root = root.expanduser().resolve()
    decisions = tuple(iter_file_decisions(corpus_root))
    locators = build_raw_locator_records(
        corpus_root, files=decisions, max_card_chars=max_card_chars
    )
    physical_records = tuple(
        iter_corpus_records(
            corpus_root,
            scope=ALL_SCOPE,
            files=decisions,
            include_locators=False,
        )
    )
    records = physical_records + locators

    included = _new_count()
    excluded = _new_count()
    by_reason: dict[str, dict[str, int]] = defaultdict(_new_count)
    by_top_level: dict[str, dict[str, Any]] = {}
    file_scope_counts = {scope: _new_count() for scope in VALID_SCOPES}
    zero_paths: list[str] = []
    whitespace_paths: list[str] = []
    unreadable_paths: list[str] = []

    for item in decisions:
        top = item.top_level
        top_row = by_top_level.setdefault(
            top,
            {
                "files": 0,
                "bytes": 0,
                "included_files": 0,
                "included_bytes": 0,
                "excluded_files": 0,
                "excluded_bytes": 0,
                "locator_records": 0,
                "locator_bytes": 0,
                "scopes": {scope: _new_count() for scope in INDEX_SCOPES},
            },
        )
        top_row["files"] += 1
        top_row["bytes"] += item.size
        if item.included:
            _increment(included, size=item.size)
            top_row["included_files"] += 1
            top_row["included_bytes"] += item.size
            assert item.scope is not None
            _increment(file_scope_counts[item.scope], size=item.size)
            _increment(file_scope_counts[ALL_SCOPE], size=item.size)
            _increment(top_row["scopes"][item.scope], size=item.size)
        else:
            _increment(excluded, size=item.size)
            top_row["excluded_files"] += 1
            top_row["excluded_bytes"] += item.size
            reason = item.exclusion_reason or "unknown"
            _increment(by_reason[reason], size=item.size)

        if item.exclusion_reason == "empty":
            zero_paths.append(item.relative_path)
        elif item.exclusion_reason == "whitespace_only":
            whitespace_paths.append(item.relative_path)
        elif item.exclusion_reason == "unreadable":
            unreadable_paths.append(item.relative_path)

    record_scope_counts = {scope: {"records": 0, "bytes": 0} for scope in VALID_SCOPES}
    estimated_by_scope = {scope: 0 for scope in VALID_SCOPES}
    for record in records:
        estimate = (
            _estimate_chunks(chunk_estimator, record.text)
            if chunk_estimator is not None
            else None
        )
        for requested in VALID_SCOPES:
            if not scope_matches(record, requested):
                continue
            record_scope_counts[requested]["records"] += 1
            record_scope_counts[requested]["bytes"] += len(record.text.encode("utf-8"))
            if estimate is not None:
                estimated_by_scope[requested] += estimate

        if record.representation == RAW_LOCATOR_REPRESENTATION:
            locator_top = (
                top_level_path(record.raw_cluster.relative_path)
                if record.raw_cluster is not None
                else record.top_level
            )
            top_row = by_top_level.setdefault(
                locator_top,
                {
                    "files": 0,
                    "bytes": 0,
                    "included_files": 0,
                    "included_bytes": 0,
                    "excluded_files": 0,
                    "excluded_bytes": 0,
                    "locator_records": 0,
                    "locator_bytes": 0,
                    "scopes": {scope: _new_count() for scope in INDEX_SCOPES},
                },
            )
            top_row["locator_records"] += 1
            top_row["locator_bytes"] += record.size

    by_scope: dict[str, dict[str, int]] = {}
    for scope in VALID_SCOPES:
        by_scope[scope] = {
            "files": file_scope_counts[scope]["files"],
            "file_bytes": file_scope_counts[scope]["bytes"],
            "records": record_scope_counts[scope]["records"],
            "record_bytes": record_scope_counts[scope]["bytes"],
        }
        if chunk_estimator is not None:
            by_scope[scope]["estimated_chunks"] = estimated_by_scope[scope]

    raw_assets = [
        item
        for item in decisions
        if item.is_raw and not item.hard_excluded and item.regular_file
    ]
    locator_assets = [item for item in raw_assets if _is_raw_asset(item)]
    readable_raw = [
        item
        for item in locator_assets
        if item.included and item.representation == RAW_TEXT_REPRESENTATION
    ]
    binary_raw = [
        item
        for item in locator_assets
        if item.exclusion_reason == "raw_binary_locator_only"
    ]
    raw_digest_paths = {
        path
        for locator in locators
        if locator.raw_cluster is not None
        for path in locator.raw_cluster.digest_paths
    }

    result: dict[str, Any] = {
        "policy_version": POLICY_VERSION,
        "root": str(corpus_root),
        "summary": {
            "files": len(decisions),
            "bytes": sum(item.size for item in decisions),
            "included_files": included["files"],
            "included_bytes": included["bytes"],
            "excluded_files": excluded["files"],
            "excluded_bytes": excluded["bytes"],
            "records": len(records),
            "record_bytes": sum(len(record.text.encode("utf-8")) for record in records),
        },
        "by_scope": by_scope,
        "by_top_level": {key: by_top_level[key] for key in sorted(by_top_level)},
        "by_exclusion_reason": {key: by_reason[key] for key in sorted(by_reason)},
        "raw": {
            "assets": len(raw_assets),
            "asset_bytes": sum(item.size for item in raw_assets),
            "locator_assets": len(locator_assets),
            "omitted_empty_or_whitespace_assets": sum(
                item.exclusion_reason in {"empty", "whitespace_only"}
                for item in raw_assets
            ),
            "clusters": len(locators),
            "locator_records": len(locators),
            "locator_bytes": sum(locator.size for locator in locators),
            "readable_files": len(readable_raw),
            "readable_bytes": sum(item.size for item in readable_raw),
            "binary_locator_only_files": len(binary_raw),
            "binary_locator_only_bytes": sum(item.size for item in binary_raw),
            "authored_digest_files": len(raw_digest_paths),
        },
        "empty": {
            "zero_byte_files": len(zero_paths),
            "whitespace_only_files": len(whitespace_paths),
            "unreadable_files": len(unreadable_paths),
            "samples": {
                "zero_byte": sorted(zero_paths)[:sample_limit],
                "whitespace_only": sorted(whitespace_paths)[:sample_limit],
                "unreadable": sorted(unreadable_paths)[:sample_limit],
            },
        },
        "exact_duplicates": _duplicate_summary(
            decisions, sample_limit=duplicate_sample_limit
        ),
        "estimated_chunks": {
            "available": chunk_estimator is not None,
            "unique_records": (
                estimated_by_scope[ALL_SCOPE] if chunk_estimator is not None else None
            ),
            "by_scope": (estimated_by_scope if chunk_estimator is not None else None),
        },
    }
    return result


__all__ = [
    "ACTIVE_SCOPE",
    "ALL_SCOPE",
    "ARCHIVE_SCOPE",
    "AUTHORED_EXTENSIONS",
    "AUTHORED_REPRESENTATION",
    "CorpusFile",
    "CorpusRecord",
    "DEFAULT_MAX_CARD_CHARS",
    "INDEX_SCOPES",
    "INBOX_SCOPE",
    "POLICY_VERSION",
    "POLICY_FINGERPRINT",
    "PROCESS_SCOPE",
    "RAW_LOCATOR_REPRESENTATION",
    "RAW_LOCATOR_PATH_PREFIX",
    "RAW_SCOPE",
    "RAW_TEXT_REPRESENTATION",
    "READABLE_RAW_EXTENSIONS",
    "RawCluster",
    "VALID_SCOPES",
    "audit_corpus",
    "build_raw_clusters",
    "build_raw_locator_records",
    "classify_file",
    "classify_relative_path",
    "corpus_metadata_fingerprint",
    "physical_manifest_fingerprint",
    "corpus_record_for_file",
    "discover_authored_digest_references",
    "is_raw_path",
    "iter_corpus_files",
    "iter_corpus_records",
    "iter_file_decisions",
    "iter_raw_locator_records",
    "normalize_relative_path",
    "raw_cluster_path",
    "render_raw_locator_card",
    "scope_matches",
    "path_prefix_matches",
    "scope_sql",
    "scopes_for_path",
    "top_level_path",
    "validate_scope",
]
