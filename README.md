<p align="center">
  <img src="./docs/logo.png" alt="MirrorMate logo">
</p>

# MirrorMate

MirrorMate is a safe mirror switcher for APT, PyPI, NPM, Go, and Docker. It has a shared Python core, an automation-friendly CLI, and a lightweight curses TUI. The runtime uses only the Python standard library.

## Features

- Opens the TUI when `mirrormate` is run in an interactive terminal.
- Provides non-interactive commands for servers, scripts, CI, and Docker builds.
- Benchmarks real HTTP repository endpoints instead of relying on ICMP ping.
- Supports traditional APT `.list` files and deb822 `.sources` files.
- Preserves third-party APT repositories and unrelated Docker daemon settings.
- Uses atomic writes and rolls back the current operation when validation fails.
- Creates persistent, restorable snapshots only when `--backup` is requested.
- Ships a small official catalog and supports custom mirrors from a local or remote JSON file.

Officially tested distributions:

- Ubuntu 22.04, 24.04, and 26.04
- Debian 12 and 13

Python 3.10 or newer is required.

## Installation

### Installer

The installer downloads the latest release package, verifies its SHA-256 checksum, and installs it through APT:

```bash
curl -fsSLO https://raw.githubusercontent.com/free-programmers/MirrorMate/main/install.sh
chmod +x install.sh
./install.sh
```

Review downloaded installation scripts before running them. `wget` is also supported when `curl` is unavailable.

### Debian package

Download `mirrormate_all.deb` and its checksum from GitHub Releases, verify it, then install it:

```bash
sha256sum --check mirrormate_all.deb.sha256
sudo apt-get install ./mirrormate_all.deb
```

There is currently no hosted MirrorMate APT repository, so `apt-get install mirrormate` by itself is not advertised.

### From source

```bash
git clone https://github.com/free-programmers/MirrorMate.git
cd MirrorMate
PYTHONPATH=src python3 -m mirrormate --help
```

The old entrypoint remains as a temporary compatibility shim:

```bash
./script.sh
```

## TUI

Run MirrorMate without arguments in an interactive terminal:

```bash
mirrormate
```

You can also request it explicitly:

```bash
mirrormate tui
```

The TUI includes a color dashboard and a live mirror table. Each HTTP result is shown as soon as it completes, healthy mirrors are ranked by median response time, and the fastest candidate is highlighted. The test checks a real endpoint for the selected package service rather than ICMP ping, so the result is closer to actual repository availability.

Mirror-list shortcuts:

- `r`: test every mirror in the current list concurrently
- `p`: test only the selected mirror
- `f`: test when needed, then select and apply the fastest healthy mirror
- `s`: open speed-test settings
- Arrow keys or `j`/`k`: move through the list
- Enter: open actions for the selected mirror
- `q` or Escape: go back

The Settings screen includes five built-in color themes: **Ocean**, **Forest**, **Amber**, **Violet**, and **Monochrome**. A selected theme is applied immediately and works with both basic 8-color terminals and richer 256-color terminals. The same screen can enable or disable automatic testing whenever a mirror list opens, choose one, three, or five requests per mirror, set the request timeout, and choose between catalog order and fastest-first sorting.

Settings are saved automatically in `~/.config/mirrormate/settings.json`; Ocean is the default theme and automatic testing is disabled by default to avoid unexpected network traffic.

The TUI can also apply a selection, import or add custom mirrors, inspect the active configuration, and restore backups.

When stdin or stdout is not a terminal, running with no arguments prints help and exits with status 2 instead of waiting for input.

## CLI

List available mirrors and inspect current configuration:

```bash
mirrormate list
mirrormate list apt --distro debian
mirrormate status
mirrormate status python --json
```

Benchmark without changing anything:

```bash
mirrormate benchmark python
mirrormate benchmark apt --distro ubuntu --json
```

Apply a catalog mirror, direct URL, or the fastest healthy candidate:

```bash
mirrormate set python --mirror pypi-official
mirrormate set python --url https://mirror.example.ir/pypi/simple
mirrormate set python --fastest --backup

sudo mirrormate set apt --distro debian --fastest --backup
sudo mirrormate set apt \
  --distro debian \
  --url https://mirror.example.ir/debian \
  --security-url https://mirror.example.ir/debian-security \
  --make-backup
```

`--make-backup` is an alias for `--backup`. A direct APT `--url` changes archive entries only; security entries stay unchanged unless `--security-url` is also supplied.

Preview exact file changes:

```bash
mirrormate set python --mirror pypi-official --dry-run
sudo mirrormate set apt --distro ubuntu --mirror ubuntu-official --dry-run
```

APT refreshes package metadata after a successful change. `--no-refresh` skips that validation for controlled environments. Docker configuration is validated and the active daemon is reloaded when possible; MirrorMate never forces a Docker restart.

APT and Docker changes require root. User-level Python, NPM, and Go changes do not. A CLI command never opens a sudo prompt; rerun a system command with `sudo` when instructed. The TUI offers sudo only after you confirm a system-level change.

## Custom catalogs

The built-in read-only catalog contains official endpoints only. Custom entries are stored in:

- User: `~/.config/mirrormate/catalog.json`
- System: `/etc/mirrormate/catalog.json` when `--system` is used

Manage entries from the CLI:

```bash
mirrormate catalog list
mirrormate catalog add python \
  --id iran-pypi \
  --name "Iran PyPI" \
  --url https://mirror.example.ir/pypi/simple

mirrormate catalog add apt \
  --id iran-debian \
  --name "Iran Debian" \
  --distro debian \
  --archive-url https://mirror.example.ir/debian \
  --security-url https://mirror.example.ir/debian-security

mirrormate catalog import ./mirrors.json
mirrormate catalog import https://example.ir/mirrors.json
mirrormate catalog remove iran-pypi
```

Remote catalogs must use HTTPS unless `--allow-http` is explicitly supplied. Imports are validated before an atomic save. Duplicate IDs fail unless `--replace` is used, and built-in IDs cannot be replaced.

Canonical catalog format:

```json
{
  "schema_version": 1,
  "mirrors": [
    {
      "id": "company-pypi",
      "type": "python",
      "name": "Company PyPI",
      "url": "https://packages.example.com/pypi/simple",
      "probe_url": "https://packages.example.com/pypi/simple/pip/"
    },
    {
      "id": "company-debian",
      "type": "apt",
      "name": "Company Debian",
      "distro": "debian",
      "archive_url": "https://packages.example.com/debian",
      "security_url": "https://packages.example.com/debian-security"
    }
  ]
}
```

The old top-level array format in `mirros/mirrors.json` is accepted during import and converted to the new schema. It is no longer downloaded automatically on every run.

## Backup and restore

Persistent snapshots are opt-in:

```bash
mirrormate set npm --mirror npm-official --backup
mirrormate backups list
mirrormate backups restore 20260904T120000Z-a1b2c3
```

For an offline APT recovery, `mirrormate backups restore ID --no-refresh` restores the files without running `apt-get update`.

User configuration snapshots are stored below `~/.local/state/mirrormate/backups`. APT and Docker snapshots are stored below `/var/lib/mirrormate/backups` and require root to restore.

Each manifest records checksums, ownership, permissions, and whether a target originally existed. Restore therefore removes files that were created by the original operation when appropriate.

Even without `--backup`, MirrorMate holds an in-memory transaction snapshot while applying a change. A failed APT refresh or Docker validation restores all files touched by that operation.

## Dockerfiles

APT, Python, NPM, and Go commands are non-interactive and can be used in a Dockerfile after MirrorMate is installed:

```dockerfile
RUN mirrormate set python --url https://mirror.example.ir/pypi/simple

RUN mirrormate set apt \
      --distro debian \
      --url https://mirror.example.ir/debian \
      --security-url https://mirror.example.ir/debian-security \
      --no-refresh \
    && apt-get update
```

For reproducible builds, prefer an explicit mirror ID or URL over `--fastest`.

Docker registry mirrors are a setting of the host Docker daemon. Running `mirrormate set docker` inside a Dockerfile cannot change the daemon that is building the image; run it on the Docker host instead.

## Exit codes

| Code | Meaning |
| ---: | --- |
| 0 | Success |
| 2 | Invalid command, catalog, or unsupported platform |
| 3 | No eligible or reachable mirror |
| 4 | Configuration, validation, or command failure |
| 77 | Root permission required |
| 130 | Interrupted by the user |

## Development

Run the standard-library test suite:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Build the architecture-independent Debian package:

```bash
sh scripts/build-deb.sh
```

The CI matrix runs tests and package smoke checks on the supported Ubuntu and Debian releases.

## License

MirrorMate is released under the [MIT License](LICENSE).
