from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Sequence

from . import __version__
from .backup import list_snapshots
from .benchmark import benchmark_mirrors, fastest_result
from .catalog import (
    fetch_catalog,
    filter_mirrors,
    load_catalogs,
    mutate_custom_catalog,
    normalize_entry,
    parse_catalog,
    remove_custom_mirror,
)
from .errors import MirrorMateError, UnavailableError, UsageError
from .models import MIRROR_TYPES, Mirror
from .platform import detect_distro, invoking_user
from .service import MirrorService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mirrormate",
        description="Safely benchmark and configure package repository mirrors.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command")

    commands.add_parser("tui", help="Open the interactive terminal interface")

    listing = commands.add_parser("list", help="List available mirrors")
    listing.add_argument("mirror_type", nargs="?", choices=MIRROR_TYPES)
    listing.add_argument("--distro", choices=("ubuntu", "debian"))
    listing.add_argument("--json", action="store_true")

    status = commands.add_parser("status", help="Show active mirror settings")
    status.add_argument("mirror_type", nargs="?", choices=MIRROR_TYPES)
    status.add_argument("--json", action="store_true")

    benchmark = commands.add_parser("benchmark", help="Benchmark configured mirror candidates")
    benchmark.add_argument("mirror_type", choices=MIRROR_TYPES)
    benchmark.add_argument("--distro", choices=("ubuntu", "debian"))
    benchmark.add_argument("--attempts", type=int, default=3)
    benchmark.add_argument("--timeout", type=float, default=3.0)
    benchmark.add_argument("--json", action="store_true")

    setting = commands.add_parser("set", help="Apply a mirror")
    setting.add_argument("mirror_type", choices=MIRROR_TYPES)
    selection = setting.add_mutually_exclusive_group(required=True)
    selection.add_argument("--mirror", metavar="ID")
    selection.add_argument("--url")
    selection.add_argument("--fastest", action="store_true")
    setting.add_argument("--security-url")
    setting.add_argument("--distro", choices=("ubuntu", "debian"))
    setting.add_argument("--backup", "--make-backup", dest="backup", action="store_true")
    setting.add_argument("--dry-run", action="store_true")
    setting.add_argument("--no-refresh", action="store_true")
    setting.add_argument("--allow-insecure", action="store_true")
    setting.add_argument("--attempts", type=int, default=3)
    setting.add_argument("--timeout", type=float, default=3.0)
    setting.add_argument("--json", action="store_true")

    catalog = commands.add_parser("catalog", help="Manage custom mirror catalogs")
    catalog_commands = catalog.add_subparsers(dest="catalog_command", required=True)
    catalog_list = catalog_commands.add_parser("list", help="List the merged catalog")
    catalog_list.add_argument("mirror_type", nargs="?", choices=MIRROR_TYPES)
    catalog_list.add_argument("--json", action="store_true")

    catalog_add = catalog_commands.add_parser("add", help="Add a custom mirror")
    catalog_add.add_argument("mirror_type", choices=MIRROR_TYPES)
    catalog_add.add_argument("--id", required=True)
    catalog_add.add_argument("--name", required=True)
    catalog_add.add_argument("--url")
    catalog_add.add_argument("--distro", choices=("ubuntu", "debian"))
    catalog_add.add_argument("--archive-url")
    catalog_add.add_argument("--security-url")
    catalog_add.add_argument("--probe-url")
    catalog_add.add_argument("--insecure", action="store_true")
    catalog_add.add_argument("--system", action="store_true")
    catalog_add.add_argument("--replace", action="store_true")

    catalog_import = catalog_commands.add_parser("import", help="Import a local or remote JSON catalog")
    catalog_import.add_argument("source")
    catalog_import.add_argument("--system", action="store_true")
    catalog_import.add_argument("--replace", action="store_true")
    catalog_import.add_argument("--allow-http", action="store_true")

    catalog_remove = catalog_commands.add_parser("remove", help="Remove a custom mirror")
    catalog_remove.add_argument("mirror_id")
    catalog_remove.add_argument("--system", action="store_true")

    backups = commands.add_parser("backups", help="List or restore configuration snapshots")
    backup_commands = backups.add_subparsers(dest="backup_command", required=True)
    backup_list = backup_commands.add_parser("list", help="List snapshots")
    backup_list.add_argument("--json", action="store_true")
    backup_restore = backup_commands.add_parser("restore", help="Restore a snapshot")
    backup_restore.add_argument("backup_id")
    backup_restore.add_argument("--no-refresh", action="store_true")
    backup_restore.add_argument("--json", action="store_true")
    return parser


def _json(data: Any) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def _mirror_rows(mirrors: list[Mirror]) -> None:
    if not mirrors:
        print("No mirrors found.")
        return
    width = max(len(item.id) for item in mirrors)
    for mirror in mirrors:
        distro = f" [{mirror.distro}]" if mirror.distro else ""
        print(f"{mirror.id:<{width}}  {mirror.type:<7}  {mirror.name}{distro} ({mirror.source})")


def _detected_or_none() -> Any:
    try:
        return detect_distro()
    except MirrorMateError:
        return None


def _eligible(mirrors: list[Mirror], mirror_type: str, requested_distro: str | None = None) -> list[Mirror]:
    distro = _detected_or_none()
    distro_id = requested_distro
    architecture = None
    if mirror_type == "apt" and distro is not None:
        distro_id = distro_id or distro.id
        architecture = distro.architecture
    return filter_mirrors(mirrors, mirror_type, distro_id, architecture)


def _check_requested_distro(requested: str | None, actual: str) -> None:
    if requested and requested != actual:
        raise UsageError(
            f"Requested distro {requested!r} does not match detected distro {actual!r}"
        )


def _benchmark(
    mirrors: list[Mirror],
    mirror_type: str,
    *,
    requested_distro: str | None,
    attempts: int,
    timeout: float,
) -> tuple[list[Mirror], list[Any]]:
    candidates = _eligible(mirrors, mirror_type, requested_distro)
    if not candidates:
        raise UnavailableError(f"No {mirror_type} mirrors are available")
    codename = None
    if mirror_type == "apt":
        distro = detect_distro()
        _check_requested_distro(requested_distro, distro.id)
        codename = distro.codename
    try:
        results = benchmark_mirrors(
            candidates,
            codename=codename,
            attempts=attempts,
            timeout=timeout,
        )
    except ValueError as exc:
        raise UsageError(str(exc)) from exc
    return candidates, results


def _print_benchmark(results: list[Any]) -> None:
    for result in results:
        if result.healthy:
            print(f"{result.mirror_id:<28} {result.median_ms:>9.2f} ms  healthy")
        else:
            print(f"{result.mirror_id:<28} {'-':>12}  {result.error}")


def _resolve_mirror(args: argparse.Namespace, mirrors: list[Mirror]) -> tuple[Mirror, list[Any] | None]:
    mirror_type = args.mirror_type
    benchmark_results = None
    distro = detect_distro() if mirror_type == "apt" else None
    if distro:
        _check_requested_distro(args.distro, distro.id)
    if args.mirror:
        match = next((item for item in mirrors if item.id == args.mirror), None)
        if match is None:
            raise UsageError(f"Mirror not found: {args.mirror}")
        if match.type != mirror_type:
            raise UsageError(f"Mirror {match.id} has type {match.type}, not {mirror_type}")
        if distro and match.distro != distro.id:
            raise UsageError(f"Mirror {match.id} is for {match.distro}, not {distro.id}")
        if distro and match.architectures and distro.architecture not in match.architectures:
            raise UsageError(f"Mirror {match.id} does not support {distro.architecture}")
        return match, None
    if args.url:
        entry: dict[str, Any] = {
            "id": f"direct-{mirror_type}",
            "type": mirror_type,
            "name": f"Direct {mirror_type} mirror",
        }
        if mirror_type == "apt":
            entry.update(
                distro=distro.id if distro else args.distro,
                archive_url=args.url,
                security_url=args.security_url,
            )
        else:
            if args.security_url:
                raise UsageError("--security-url is only valid for APT")
            entry["url"] = args.url
            if mirror_type == "docker" and args.allow_insecure:
                entry["insecure"] = True
        return normalize_entry(entry, source="direct"), None
    candidates, benchmark_results = _benchmark(
        mirrors,
        mirror_type,
        requested_distro=args.distro,
        attempts=args.attempts,
        timeout=args.timeout,
    )
    fastest = fastest_result(benchmark_results)
    if fastest is None:
        raise UnavailableError("No reachable mirror was found; no configuration was changed")
    selected = next(item for item in candidates if item.id == fastest.mirror_id)
    return selected, benchmark_results


def _handle_catalog(args: argparse.Namespace, user: Any, mirrors: list[Mirror]) -> int:
    if args.catalog_command == "list":
        selected = filter_mirrors(mirrors, args.mirror_type)
        if args.json:
            _json([item.to_dict() for item in selected])
        else:
            _mirror_rows(selected)
        return 0
    if args.catalog_command == "add":
        entry = {
            "id": args.id,
            "type": args.mirror_type,
            "name": args.name,
            "url": args.url,
            "distro": args.distro,
            "archive_url": args.archive_url,
            "security_url": args.security_url,
            "probe_url": args.probe_url,
            "insecure": args.insecure,
        }
        mirror = normalize_entry(entry)
        path = mutate_custom_catalog(
            [mirror], user=user, system=args.system, replace=args.replace
        )
        print(f"Saved {mirror.id} to {path}")
        return 0
    if args.catalog_command == "import":
        raw = fetch_catalog(args.source, allow_http=args.allow_http)
        imported = parse_catalog(raw)
        path = mutate_custom_catalog(
            imported, user=user, system=args.system, replace=args.replace
        )
        print(f"Imported {len(imported)} mirrors into {path}")
        return 0
    if args.catalog_command == "remove":
        path = remove_custom_mirror(args.mirror_id, user=user, system=args.system)
        print(f"Removed {args.mirror_id} from {path}")
        return 0
    raise UsageError("A catalog subcommand is required")


def _handle_backups(args: argparse.Namespace, user: Any, service: MirrorService) -> int:
    if args.backup_command == "list":
        snapshots = list_snapshots(user)
        if args.json:
            _json(snapshots)
        elif snapshots:
            for item in snapshots:
                print(f"{item['id']}  {item['category']:<7}  {item['created_at']}")
        else:
            print("No backups found.")
        return 0
    result = service.restore(args.backup_id, no_refresh=args.no_refresh)
    warnings = result.get("warnings", [])
    if args.json:
        _json(result)
    else:
        print(f"Restored backup {args.backup_id} ({result['restored_files']} files)")
        for warning in warnings:
            print(f"Warning: {warning}", file=sys.stderr)
    return 0


def _run(args: argparse.Namespace) -> int:
    user = invoking_user()
    mirrors = load_catalogs(user)
    service = MirrorService(catalog=mirrors, user=user)
    if args.command == "tui":
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise UsageError("TUI mode requires an interactive terminal")
        from .tui import run_tui

        return run_tui(service)
    if args.command == "list":
        selected = _eligible(mirrors, args.mirror_type, args.distro) if args.mirror_type else mirrors
        if args.json:
            _json([item.to_dict() for item in selected])
        else:
            _mirror_rows(selected)
        return 0
    if args.command == "status":
        categories = [args.mirror_type] if args.mirror_type else list(MIRROR_TYPES)
        statuses = [service.status(category) for category in categories]
        if args.json:
            _json(statuses[0] if args.mirror_type else statuses)
        else:
            for status in statuses:
                print(f"{status['type']}: {json.dumps(status, ensure_ascii=False)}")
        return 0
    if args.command == "benchmark":
        _, results = _benchmark(
            mirrors,
            args.mirror_type,
            requested_distro=args.distro,
            attempts=args.attempts,
            timeout=args.timeout,
        )
        if args.json:
            _json([item.to_dict() for item in results])
        else:
            _print_benchmark(results)
        return 0 if fastest_result(results) else UnavailableError.exit_code
    if args.command == "set":
        mirror, benchmark_results = _resolve_mirror(args, mirrors)
        result = service.apply(
            args.mirror_type,
            mirror,
            backup=args.backup,
            dry_run=args.dry_run,
            no_refresh=args.no_refresh,
            allow_insecure=args.allow_insecure,
        )
        if benchmark_results is not None:
            result["benchmark"] = [item.to_dict() for item in benchmark_results]
        if args.json:
            _json(result)
        else:
            if benchmark_results is not None:
                _print_benchmark(benchmark_results)
            print(result["summary"])
            if args.dry_run:
                print(result.get("diff") or "No changes are required.")
            elif result["changed_files"]:
                print("Changed: " + ", ".join(result["changed_files"]))
            else:
                print("No changes are required.")
            if result.get("backup_id"):
                print(f"Backup: {result['backup_id']}")
            for warning in result.get("warnings", []):
                print(f"Warning: {warning}", file=sys.stderr)
        return 0
    if args.command == "catalog":
        return _handle_catalog(args, user, mirrors)
    if args.command == "backups":
        return _handle_backups(args, user, service)
    raise UsageError("A command is required")


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    if not arguments:
        if sys.stdin.isatty() and sys.stdout.isatty():
            arguments = ["tui"]
        else:
            parser.print_help(sys.stderr)
            return 2
    try:
        return _run(parser.parse_args(arguments))
    except MirrorMateError as exc:
        print(f"mirrormate: {exc}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("mirrormate: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
