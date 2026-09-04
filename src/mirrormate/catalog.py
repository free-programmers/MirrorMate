from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import replace
from importlib import resources
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from .errors import CatalogError, PermissionDeniedError
from .io import atomic_write
from .models import DISTROS, MIRROR_TYPES, Mirror
from .platform import UserContext


SCHEMA_VERSION = 1
MAX_REMOTE_CATALOG_BYTES = 1024 * 1024
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
LEGACY_TYPES = {
    "apt": "apt",
    "python": "python",
    "node.js": "npm",
    "npm": "npm",
    "go": "go",
    "docker": "docker",
}


def builtin_catalog_path() -> Path:
    return Path(resources.files("mirrormate").joinpath("data/mirrors.json"))


def user_catalog_path(user: UserContext) -> Path:
    return user.home / ".config/mirrormate/catalog.json"


def system_catalog_path(root: Path = Path("/")) -> Path:
    return root / "etc/mirrormate/catalog.json"


def _valid_url(value: str, field: str) -> str:
    if any(character.isspace() for character in value):
        raise CatalogError(f"Whitespace is not allowed in {field}")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise CatalogError(f"{field} must be an http(s) URL: {value!r}")
    if parsed.username or parsed.password:
        raise CatalogError(f"Credentials are not allowed in {field}")
    return value.rstrip("/")


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug or "mirror")[:64]


def _legacy_apt_urls(entry: dict[str, Any]) -> tuple[str | None, str | None]:
    values = entry.get("urls")
    if values is None and isinstance(entry.get("url"), str):
        values = entry["url"].replace("\\n", "\n").splitlines()
    if not isinstance(values, list):
        return None, None
    archive: str | None = None
    security: str | None = None
    for value in values:
        if not isinstance(value, str):
            continue
        parts = value.split()
        if len(parts) < 3:
            continue
        url, suite = parts[1], parts[2]
        if "security" in suite:
            security = url
        elif archive is None:
            archive = url
    return archive, security


def normalize_entry(entry: dict[str, Any], source: str = "custom", legacy: bool = False) -> Mirror:
    if not isinstance(entry, dict):
        raise CatalogError("Every mirror entry must be an object")
    allowed_fields = {
        "id",
        "type",
        "category",
        "name",
        "url",
        "urls",
        "distro",
        "archive_url",
        "security_url",
        "probe_url",
        "architectures",
        "insecure",
        "default",
    }
    unknown = sorted(set(entry) - allowed_fields)
    if unknown and not legacy:
        raise CatalogError(f"Unknown mirror fields: {', '.join(unknown)}")
    raw_type = str(entry.get("type") or entry.get("category") or "").lower()
    mirror_type = LEGACY_TYPES.get(raw_type)
    if mirror_type not in MIRROR_TYPES:
        raise CatalogError(f"Unsupported mirror type: {raw_type or 'missing'}")
    name = str(entry.get("name") or "").strip()
    if not name:
        raise CatalogError("Mirror name is required")
    if mirror_type != "docker" and (entry.get("insecure") or entry.get("default")):
        raise CatalogError("insecure and default are only valid for Docker mirrors")
    mirror_id = str(entry.get("id") or _slug(f"{mirror_type}-{name}"))
    if not ID_PATTERN.fullmatch(mirror_id):
        raise CatalogError(f"Invalid mirror id: {mirror_id!r}")

    distro = entry.get("distro")
    archive_url = entry.get("archive_url")
    security_url = entry.get("security_url")
    url = entry.get("url")
    if mirror_type == "apt":
        if not legacy and url is not None:
            raise CatalogError("Canonical APT mirrors use archive_url, not url")
        if legacy:
            legacy_archive, legacy_security = _legacy_apt_urls(entry)
            archive_url = archive_url or legacy_archive
            security_url = security_url or legacy_security
            if not distro:
                lowered = name.lower()
                distro = "debian" if "debian" in lowered else "ubuntu"
        if distro not in DISTROS:
            raise CatalogError(f"APT mirror {mirror_id} requires distro=ubuntu or distro=debian")
        if not isinstance(archive_url, str):
            raise CatalogError(f"APT mirror {mirror_id} requires archive_url")
        archive_url = _valid_url(archive_url, "archive_url")
        if security_url is not None:
            if not isinstance(security_url, str):
                raise CatalogError("security_url must be a string")
            security_url = _valid_url(security_url, "security_url")
        url = None
    else:
        if any(entry.get(field) is not None for field in ("distro", "archive_url", "security_url")):
            raise CatalogError(f"{mirror_type} mirrors cannot define APT-specific fields")
        if not isinstance(url, str):
            raise CatalogError(f"Mirror {mirror_id} requires url")
        url = _valid_url(url, "url")

    probe_url = entry.get("probe_url")
    if probe_url is not None:
        if not isinstance(probe_url, str):
            raise CatalogError("probe_url must be a string")
        probe_url = _valid_url(probe_url, "probe_url")
    architectures = entry.get("architectures") or []
    if not isinstance(architectures, list) or not all(isinstance(item, str) for item in architectures):
        raise CatalogError("architectures must be an array of strings")

    insecure = bool(entry.get("insecure", False))
    if mirror_type == "docker" and url and urlparse(url).scheme == "http" and not insecure:
        raise CatalogError("HTTP Docker mirrors must set insecure=true")

    return Mirror(
        id=mirror_id,
        type=mirror_type,
        name=name,
        url=url,
        distro=distro,
        archive_url=archive_url,
        security_url=security_url,
        probe_url=probe_url,
        architectures=tuple(architectures),
        insecure=insecure,
        default=bool(entry.get("default", False)),
        source=source,
    )


def parse_catalog(raw: Any, source: str = "custom") -> list[Mirror]:
    legacy = isinstance(raw, list)
    if legacy:
        entries = raw
    elif isinstance(raw, dict):
        unknown = sorted(set(raw) - {"schema_version", "mirrors"})
        if unknown:
            raise CatalogError(f"Unknown catalog fields: {', '.join(unknown)}")
        if raw.get("schema_version") != SCHEMA_VERSION:
            raise CatalogError(f"Unsupported catalog schema_version: {raw.get('schema_version')!r}")
        entries = raw.get("mirrors")
    else:
        raise CatalogError("Catalog must be an object or a legacy array")
    if not isinstance(entries, list):
        raise CatalogError("Catalog mirrors must be an array")
    mirrors: list[Mirror] = []
    seen: set[str] = set()
    for entry in entries:
        mirror = normalize_entry(entry, source=source, legacy=legacy)
        if mirror.id in seen:
            if not legacy or (isinstance(entry, dict) and entry.get("id")):
                raise CatalogError(f"Duplicate mirror id in catalog: {mirror.id}")
            index = 2
            candidate = f"{mirror.id[:61]}-{index}"
            while candidate in seen:
                index += 1
                candidate = f"{mirror.id[:61]}-{index}"
            mirror = replace(mirror, id=candidate)
        seen.add(mirror.id)
        mirrors.append(mirror)
    return mirrors


def read_catalog(path: Path, source: str) -> list[Mirror]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogError(f"Cannot read catalog {path}: {exc}") from exc
    return parse_catalog(raw, source)


def load_catalogs(user: UserContext, root: Path = Path("/")) -> list[Mirror]:
    groups = [
        read_catalog(builtin_catalog_path(), "builtin"),
        read_catalog(system_catalog_path(root), "system"),
        read_catalog(user_catalog_path(user), "user"),
    ]
    merged: list[Mirror] = []
    seen: dict[str, str] = {}
    for group in groups:
        for mirror in group:
            if mirror.id in seen:
                raise CatalogError(
                    f"Mirror id {mirror.id!r} exists in both {seen[mirror.id]} and {mirror.source} catalogs"
                )
            seen[mirror.id] = mirror.source
            merged.append(mirror)
    return merged


def filter_mirrors(
    mirrors: Iterable[Mirror],
    mirror_type: str | None = None,
    distro: str | None = None,
    architecture: str | None = None,
) -> list[Mirror]:
    result = []
    for mirror in mirrors:
        if mirror_type and mirror.type != mirror_type:
            continue
        if distro and mirror.type == "apt" and mirror.distro != distro:
            continue
        if architecture and mirror.architectures and architecture not in mirror.architectures:
            continue
        result.append(mirror)
    return result


def catalog_document(mirrors: Iterable[Mirror], include_source: bool = False) -> dict[str, Any]:
    entries = []
    for mirror in mirrors:
        data = mirror.to_dict()
        if not include_source:
            data.pop("source", None)
        entries.append(data)
    return {"schema_version": SCHEMA_VERSION, "mirrors": entries}


def write_catalog(path: Path, mirrors: Iterable[Mirror], user: UserContext | None = None) -> None:
    content = (json.dumps(catalog_document(mirrors), indent=2, sort_keys=True) + "\n").encode()
    atomic_write(
        path,
        content,
        mode=0o644 if user is None else 0o600,
        uid=user.uid if user else None,
        gid=user.gid if user else None,
    )


def fetch_catalog(source: str, allow_http: bool = False, timeout: float = 10.0) -> Any:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        if parsed.scheme != "https" and not allow_http:
            raise CatalogError("Remote catalogs must use HTTPS; pass --allow-http to override")
        request = urllib.request.Request(source, headers={"User-Agent": "MirrorMate/2"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                final_scheme = urlparse(response.geturl()).scheme
                if final_scheme != "https" and not allow_http:
                    raise CatalogError("Remote catalog redirected to a non-HTTPS URL")
                content = response.read(MAX_REMOTE_CATALOG_BYTES + 1)
        except OSError as exc:
            raise CatalogError(f"Cannot download catalog: {exc}") from exc
        if len(content) > MAX_REMOTE_CATALOG_BYTES:
            raise CatalogError("Remote catalog is larger than 1 MiB")
        try:
            return json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CatalogError(f"Remote catalog is not valid JSON: {exc}") from exc
    path = Path(source).expanduser()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogError(f"Cannot read catalog {path}: {exc}") from exc


def mutate_custom_catalog(
    incoming: Iterable[Mirror],
    *,
    user: UserContext,
    root: Path = Path("/"),
    system: bool = False,
    replace: bool = False,
) -> Path:
    if system and os.geteuid() != 0:
        raise PermissionDeniedError("Changing the system catalog requires root")
    path = system_catalog_path(root) if system else user_catalog_path(user)
    source_name = "system" if system else "user"
    existing = read_catalog(path, source_name)
    builtins = {item.id for item in read_catalog(builtin_catalog_path(), "builtin")}
    by_id = {item.id: item for item in existing}
    for mirror in incoming:
        if mirror.id in builtins:
            raise CatalogError(f"Built-in mirror {mirror.id!r} cannot be replaced")
        normalized = Mirror(**{**mirror.to_dict(), "architectures": mirror.architectures, "source": source_name})
        if normalized.id in by_id and not replace:
            raise CatalogError(f"Mirror id {normalized.id!r} already exists; pass --replace")
        by_id[normalized.id] = normalized
    write_catalog(path, by_id.values(), None if system else user)
    return path


def remove_custom_mirror(
    mirror_id: str,
    *,
    user: UserContext,
    root: Path = Path("/"),
    system: bool = False,
) -> Path:
    if system and os.geteuid() != 0:
        raise PermissionDeniedError("Changing the system catalog requires root")
    path = system_catalog_path(root) if system else user_catalog_path(user)
    source_name = "system" if system else "user"
    existing = read_catalog(path, source_name)
    remaining = [item for item in existing if item.id != mirror_id]
    if len(remaining) == len(existing):
        raise CatalogError(f"Custom mirror not found: {mirror_id}")
    write_catalog(path, remaining, None if system else user)
    return path
