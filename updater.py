"""Opt-in, GitHub-release updater for the per-user Inno Setup installation.

The app never updates itself in-process. It downloads only the published
installer asset, verifies its SHA-256, then hands off to an external PowerShell
helper that waits for this process to exit, runs Setup, and relaunches the app.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPOSITORY = "B1progame/Auto-PDF-Form"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
USER_AGENT = "AutoPDFForm-Updater"
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")


class UpdateError(RuntimeError):
    """Update check, verification, or handoff failed safely."""


class UpdateCancelled(UpdateError):
    """The user cancelled a release download."""


def version_key(version: str):
    match = _VERSION.fullmatch(str(version).strip())
    if not match:
        raise UpdateError(f"Unsupported release version: {version!r}")
    major, minor, patch = (int(match.group(index)) for index in (1, 2, 3))
    # Stable releases sort above pre-releases for the same numeric version.
    prerelease = match.group(4)
    return major, minor, patch, (1, "") if prerelease is None else (0, prerelease.lower())


def default_update_dir() -> Path:
    """Keep downloaded setup files in a predictable per-user cache."""
    root = os.environ.get("LOCALAPPDATA")
    return (Path(root) if root else Path.home() / ".cache") / "AutoPDFForm" / "updates"


def check_latest(current_version: str, *, timeout: float = 12.0, opener=urlopen):
    """Fetch the latest public stable GitHub release; return UI-safe metadata."""
    request = Request(API_URL, headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT, "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with opener(request, timeout=timeout) as response:
            release = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("GitHub has no published stable release yet.") from exc
        raise UpdateError(f"GitHub update check failed (HTTP {exc.code}).") from exc
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise UpdateError(f"Could not reach GitHub to check for updates: {exc}") from exc

    if release.get("draft") or release.get("prerelease"):
        raise UpdateError("GitHub returned a draft or prerelease where a stable release was expected.")
    tag = str(release.get("tag_name", ""))
    latest = tag.removeprefix("v")
    newer = version_key(latest) > version_key(current_version)
    assets = release.get("assets") or []
    setup_name = f"AutoPDFForm-Setup-{latest}.exe"
    sums_asset = next((a for a in assets if a.get("name") == "SHA256SUMS.txt"), None)
    installer = next((a for a in assets if a.get("name") == setup_name), None)
    if newer and (installer is None or sums_asset is None):
        raise UpdateError(f"Release {tag} is missing its installer or checksum manifest; it cannot be installed safely.")
    return {
        "currentVersion": current_version,
        "latestVersion": latest,
        "available": newer,
        "releaseUrl": release.get("html_url", f"https://github.com/{REPOSITORY}/releases/tag/{tag}"),
        "releaseNotes": str(release.get("body") or "")[:12000],
        "installer": installer,
        "checksums": sums_asset,
        "publishedAt": release.get("published_at"),
    }


def _read_asset(asset: dict, *, timeout: float, opener):
    url = asset.get("browser_download_url")
    if not isinstance(url, str) or not url.startswith("https://github.com/"):
        raise UpdateError("GitHub returned an unexpected release asset URL.")
    request = Request(url, headers={"Accept": "application/octet-stream", "User-Agent": USER_AGENT})
    try:
        with opener(request, timeout=timeout) as response:
            return response.read()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"Could not download the release checksum file: {exc}") from exc


def expected_digest(update: dict, *, timeout: float = 30, opener=urlopen):
    installer = update.get("installer") or {}
    name = installer.get("name")
    sums = _read_asset(update.get("checksums") or {}, timeout=timeout, opener=opener).decode("ascii", errors="strict")
    for line in sums.splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?(.+?)\s*", line)
        if match and match.group(2) == name:
            manifest_hash = match.group(1).lower()
            api_digest = installer.get("digest")
            if api_digest and str(api_digest).lower() != f"sha256:{manifest_hash}":
                raise UpdateError("GitHub's asset digest does not match the release checksum manifest.")
            return manifest_hash
    raise UpdateError(f"The release checksum manifest does not contain {name}.")


def download_installer(update: dict, destination: str | Path, *, progress=None,
                       cancel: threading.Event | None = None, chunk_size=1024 * 1024,
                       timeout=30, opener=urlopen):
    """Download to a temporary sibling, verify, then atomically publish it."""
    installer = update.get("installer") or {}
    expected_size = int(installer.get("size") or 0)
    expected_hash = expected_digest(update, timeout=timeout, opener=opener)
    url = installer.get("browser_download_url")
    if not isinstance(url, str) or not url.startswith("https://github.com/"):
        raise UpdateError("GitHub returned an unexpected installer URL.")
    target = Path(destination).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    received = 0
    request = Request(url, headers={"Accept": "application/octet-stream", "User-Agent": USER_AGENT})
    try:
        with opener(request, timeout=timeout) as response, temporary.open("wb") as stream:
            while True:
                if cancel and cancel.is_set():
                    raise UpdateCancelled("Update download cancelled.")
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                stream.write(chunk)
                digest.update(chunk)
                received += len(chunk)
                if progress:
                    progress(received, expected_size)
        if expected_size and received != expected_size:
            raise UpdateError(f"Installer download is incomplete ({received} of {expected_size} bytes).")
        if digest.hexdigest() != expected_hash:
            raise UpdateError("Installer SHA-256 verification failed. The downloaded file was discarded.")
        temporary.replace(target)
        if progress:
            progress(received, expected_size or received)
        return target
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"Installer download failed: {exc}") from exc
    finally:
        if temporary.exists():
            temporary.unlink()


def installed_app_info(executable: str | Path | None = None):
    """Return update handoff paths only for an installed Inno Setup copy."""
    if os.name != "nt":
        raise UpdateError("In-app updates are currently available only for the Windows installer build.")
    app_exe = Path(executable or sys.executable).resolve()
    install_dir = app_exe.parent
    uninstaller = install_dir / "unins000.exe"
    if not app_exe.is_file() or not uninstaller.is_file():
        raise UpdateError("This copy is not an Inno Setup installation. Install the app with AutoPDFForm-Setup.exe to use in-app updates.")
    return {"appExe": str(app_exe), "installDir": str(install_dir)}


_HANDOFF_SCRIPT = r'''param([Parameter(Mandatory=$true)][string]$ConfigBase64)
$ErrorActionPreference = 'Stop'
$config = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($ConfigBase64)) | ConvertFrom-Json
$log = Join-Path $env:LOCALAPPDATA 'AutoPDFForm\update.log'
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
try {
  "$(Get-Date -Format o) Waiting for app process $($config.parentPid)" | Add-Content -LiteralPath $log
  while (Get-Process -Id ([int]$config.parentPid) -ErrorAction SilentlyContinue) { Start-Sleep -Milliseconds 500 }
  $args = @('/SP-', '/SILENT', '/NORESTART', '/CLOSEAPPLICATIONS', ('/DIR="' + $config.installDir + '"'))
  $setup = Start-Process -FilePath $config.installer -ArgumentList $args -Wait -PassThru
  if ($setup.ExitCode -ne 0) { throw "Installer exited with code $($setup.ExitCode)" }
  Start-Process -FilePath $config.appExe
  "$(Get-Date -Format o) Update installed and app relaunched." | Add-Content -LiteralPath $log
} catch {
  "$(Get-Date -Format o) Update failed: $_" | Add-Content -LiteralPath $log
  if (Test-Path -LiteralPath $config.appExe) { Start-Process -FilePath $config.appExe }
  Add-Type -AssemblyName PresentationFramework
  [System.Windows.MessageBox]::Show("The update could not be installed. The previous app has been reopened.`n`n$($_.Exception.Message)`n`nLog: $log", 'Auto PDF Form update failed', 'OK', 'Warning') | Out-Null
} finally {
  Remove-Item -LiteralPath $config.installer -Force -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
}
'''


def start_installer_handoff(installer: str | Path, *, app_exe: str | Path,
                            install_dir: str | Path, parent_pid: int | None = None,
                            runner=None):
    """Start an external helper that installs after exit, then relaunches.

    The helper lives in the system temp folder so the installer can safely
    replace application files. The caller must first confirm/save user work.
    """
    if os.name != "nt":
        raise UpdateError("In-app installer handoff is Windows-only.")
    import subprocess
    import tempfile as _tempfile
    helper_fd, helper_name = _tempfile.mkstemp(prefix="AutoPDFForm-update-", suffix=".ps1")
    os.close(helper_fd)
    helper = Path(helper_name)
    helper.write_text(_HANDOFF_SCRIPT, encoding="utf-8")
    payload = {
        "installer": str(Path(installer).resolve()),
        "appExe": str(Path(app_exe).resolve()),
        "installDir": str(Path(install_dir).resolve()),
        "parentPid": int(parent_pid or os.getpid()),
    }
    encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(helper), "-ConfigBase64", encoded]
    try:
        if runner is None:
            subprocess.Popen(command, close_fds=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            runner(command)
    except OSError as exc:
        helper.unlink(missing_ok=True)
        raise UpdateError(f"Could not start the update helper: {exc}") from exc
    return helper

