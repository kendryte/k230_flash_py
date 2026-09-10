#!/usr/bin/env python3
"""Sign and notarize an existing PyInstaller app, then publish a stapled DMG."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

MACHO_MAGIC = {
    b"\xfe\xed\xfa\xce",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf",
    b"\xbf\xba\xfe\xca",
}


def run(command):
    # Never print command arguments: security commands include the password.
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        detail = "" if command[0] == "security" else result.stderr.strip()
        raise RuntimeError(f"{command[0]} {command[1]} failed (exit {result.returncode}). {detail}")
    return result.stdout


def signing_config(environ):
    config = {}
    for name in ("MACOS_SIGN_IDENTITY", "MACOS_KEYCHAIN", "MACOS_NOTARY_PROFILE"):
        value = environ.get(name, "").rstrip("\r\n")
        if not value or "\r" in value or "\n" in value:
            raise ValueError(f"{name} must be a nonempty single-line value")
        config[name] = value
    # Passwords are opaque; do not trim or normalize them.
    config["MACOS_KEYCHAIN_PASSWORD"] = environ.get("MACOS_KEYCHAIN_PASSWORD", "")
    return config


def signing_targets(app):
    targets = {app}
    for directory, dirs, files in os.walk(app, followlinks=False):
        root = Path(directory)
        dirs[:] = [name for name in dirs if not (root / name).is_symlink()]
        for name in files:
            path = root / name
            if path.is_symlink():
                continue
            with path.open("rb") as stream:
                if stream.read(4) not in MACHO_MAGIC:
                    continue
            targets.add(path)
            # Seal nested containers after their code and before the outer app.
            for parent in path.parents:
                if parent == app:
                    break
                if parent.suffix in (".app", ".framework", ".xpc", ".bundle"):
                    targets.add(parent)
    return sorted(targets, key=lambda path: (-len(path.parts), str(path)))


def sign(path, config, runtime=False):
    command = ["codesign", "--force", "--timestamp"]
    if runtime:
        command += ["--options", "runtime"]
    run(command + ["--keychain", config["MACOS_KEYCHAIN"], "--sign", config["MACOS_SIGN_IDENTITY"], str(path)])


def notarize(path, config):
    response = json.loads(
        run(
            [
                "xcrun",
                "notarytool",
                "submit",
                str(path),
                "--keychain-profile",
                config["MACOS_NOTARY_PROFILE"],
                "--keychain",
                config["MACOS_KEYCHAIN"],
                "--wait",
                "--output-format",
                "json",
            ]
        )
    )
    if response.get("status") != "Accepted":
        raise RuntimeError(
            f"Notarization was not accepted: {response.get('status')}; "
            f"submission ID: {response.get('id')}. Retrieve the notarytool log on the signing Mac."
        )
    print(f"Notarization accepted: {path.name} ({response.get('id')})")


def staple(path):
    run(["xcrun", "stapler", "staple", str(path)])
    run(["xcrun", "stapler", "validate", str(path)])


def package(app, output, config):
    app, output = app.resolve(), output.resolve()
    if app.suffix != ".app" or not (app / "Contents/Info.plist").is_file():
        raise ValueError(f"Application bundle not found: {app}")
    if output.suffix != ".dmg":
        raise ValueError("Output must be a .dmg file")
    if not Path(config["MACOS_KEYCHAIN"]).is_file():
        raise ValueError("MACOS_KEYCHAIN must name an existing keychain file on the signing Mac")
    if output.exists() or output.with_suffix(".dmg.sha256").exists():
        raise ValueError("Output already exists; choose a new output path")

    password = config["MACOS_KEYCHAIN_PASSWORD"]
    if password:
        run(["security", "unlock-keychain", "-p", password, config["MACOS_KEYCHAIN"]])
        run(
            [
                "security",
                "set-key-partition-list",
                "-S",
                "apple-tool:,apple:,codesign:",
                "-s",
                "-k",
                password,
                config["MACOS_KEYCHAIN"],
            ]
        )
    identities = run(["security", "find-identity", "-v", "-p", "codesigning", config["MACOS_KEYCHAIN"]])
    if config["MACOS_SIGN_IDENTITY"] not in identities:
        raise RuntimeError("Configured signing identity was not found in MACOS_KEYCHAIN")
    # Fail before signing if the profile is missing or its credentials are invalid.
    run(
        [
            "xcrun",
            "notarytool",
            "history",
            "--keychain-profile",
            config["MACOS_NOTARY_PROFILE"],
            "--keychain",
            config["MACOS_KEYCHAIN"],
            "--output-format",
            "json",
        ]
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="k230-macos-release-") as directory:
        work = Path(directory)
        staging = work / "dmg"
        staging.mkdir()
        staged_app = staging / app.name
        shutil.copytree(app, staged_app, symlinks=True)
        for target in signing_targets(staged_app):
            sign(target, config, runtime=True)
        run(["codesign", "--verify", "--deep", "--strict", str(staged_app)])

        archive = work / "notary.zip"
        run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(staged_app), str(archive)])
        notarize(archive, config)
        staple(staged_app)
        run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(staged_app)])
        run(["spctl", "--assess", "--type", "execute", "--verbose=4", str(staged_app)])

        (staging / "Applications").symlink_to("/Applications")
        dmg = work / output.name
        run(
            ["hdiutil", "create", "-volname", "K230 Flash GUI", "-srcfolder", str(staging), "-format", "UDZO", str(dmg)]
        )
        sign(dmg, config)
        run(["codesign", "--verify", "--strict", str(dmg)])
        notarize(dmg, config)
        staple(dmg)
        run(
            [
                "spctl",
                "--assess",
                "--type",
                "open",
                "--context",
                "context:primary-signature",
                "--verbose=4",
                str(dmg),
            ]
        )
        # Publish only after both notarization and ticket validation succeed.
        shutil.copy2(dmg, output)

    digest = hashlib.sha256()
    with output.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    output.with_suffix(".dmg.sha256").write_text(f"{digest.hexdigest()}  {output.name}\n", encoding="utf-8")
    print(f"Created signed and notarized DMG: {output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        package(args.app, args.output, signing_config(os.environ))
    except (ValueError, RuntimeError, OSError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
