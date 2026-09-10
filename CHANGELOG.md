# Changelog

All notable changes to this project are documented in this file.

## 1.4.0 - 2026-09-10

### Added

- Added Developer ID signing, notarization, and ticket stapling for Intel and
  Apple Silicon macOS GUI release DMGs using a self-hosted signing runner.
- Added SHA-256 checksums for the final stapled DMGs and packaging regression
  tests for signing order, notarization failures, and symlink handling.
- Documented macOS signing secrets and notarization profile setup.

### Changed

- Updated the Intel macOS build runner to `macos-15-intel`.
- Separated unsigned intermediate macOS apps from signed release assets and
  labeled local and manual branch DMG builds as unsigned.
- Routed manual macOS workflow builds through the Developer ID signing and
  notarization job instead of publishing unsigned validation DMGs.

### Fixed

- Preserved application bundle symlinks when staging unsigned DMGs.
- Added Gatekeeper assessment for final notarized DMGs and refreshed ad-hoc
  signatures for local macOS validation packages.
- Repaired missing GUI configuration sections and defaults at startup,
  preventing first-launch failures on macOS and other platforms.
- Made workflow and GUI configuration tests portable across UTF-8 and minimal
  cross-platform CI environments.

## 1.3.0

### Added

- Added a hardware-independent test suite with a simulated two-stage K230 USB
  device, plus opt-in tests for real hardware.
- Added continuous integration across Linux, macOS, and Windows on Python 3.9
  and 3.12.
- Added `python -m k230_flash` support and a unified build script for Python and
  GUI artifacts.
- Added native GUI builds for both Intel and Apple Silicon macOS systems.

### Changed

- Reworked the BootROM-to-U-Boot transition as an explicit state machine that
  handles USB re-enumeration correctly on Linux and Windows.
- Streamed `.kdimg` partitions during flashing to substantially reduce peak
  memory use while preserving pre-write SHA-256 verification.
- Validated media names, files, partition selections, and image capacity before
  waiting for or writing to a device.
- Improved CLI failures with concise diagnostics and meaningful exit codes.
- Made Linux GUI artifacts self-contained and verified them at runtime on
  supported distributions.

### Fixed

- Verified the device response after completing a write and surfaced detailed
  probe and write errors reported by the device.
- Fixed stale `.kdimg` parser state causing later images in the same process to
  reuse the first image's partition table.
- Fixed flashing of compressed `.zip` and `.tar.gz` images whose temporary
  extraction directory was removed too early.
- Prevented invalid `--kdimg-select` values and oversized raw images from
  starting a partial flash.
- Fixed corrupt-image log messages that omitted their diagnostic values.
- Fixed GUI release builds and artifact names across current Linux, Windows,
  and macOS runners.

## 1.2.0

### Added

- Added batch flashing mode to the GUI.

### Changed

- Improved GUI documentation and shortened the loader transition delay.

## 1.1.0

### Fixed

- Added the missing GUI PyInstaller specification.

[1.4.0]: https://github.com/kendryte/k230_flash_py/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/kendryte/k230_flash_py/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/kendryte/k230_flash_py/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/kendryte/k230_flash_py/releases/tag/v1.1.0
