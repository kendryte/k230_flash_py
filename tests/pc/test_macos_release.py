"""Packaging contract checks with Apple tools mocked; no signing credentials needed."""

import hashlib
import json
from pathlib import Path

import pytest

from gui import build_macos
from gui import macos_release as release


@pytest.fixture
def config(tmp_path):
    keychain = tmp_path / "signing.keychain-db"
    keychain.touch()
    return {
        "MACOS_SIGN_IDENTITY": "Developer ID Application: Example (TEAM)",
        "MACOS_KEYCHAIN": str(keychain),
        "MACOS_NOTARY_PROFILE": "K230Notary",
        "MACOS_KEYCHAIN_PASSWORD": "secret\n",
    }


@pytest.fixture
def app(tmp_path):
    app = tmp_path / "K230FlashGUI.app"
    (app / "Contents/MacOS").mkdir(parents=True)
    (app / "Contents/Info.plist").write_text("fixture")
    (app / "Contents/MacOS/k230_flash_gui").write_bytes(b"\xcf\xfa\xed\xfe" + b"binary")
    framework = app / "Contents/Frameworks/Python.framework/Versions/A"
    framework.mkdir(parents=True)
    (framework / "Python").write_bytes(b"\xcf\xfa\xed\xfe" + b"python")
    return app


def test_config_preserves_password_and_spaces(config):
    incoming = dict(config)
    for key in ("MACOS_SIGN_IDENTITY", "MACOS_KEYCHAIN", "MACOS_NOTARY_PROFILE"):
        incoming[key] += "\r\n"
    assert release.signing_config(incoming) == config


@pytest.mark.parametrize("profile", ["", "\n", "K230\nNotary"])
def test_invalid_profile_fails_before_tools(config, profile):
    config["MACOS_NOTARY_PROFILE"] = profile
    with pytest.raises(ValueError, match="MACOS_NOTARY_PROFILE"):
        release.signing_config(config)


def test_nested_code_signed_before_containers(app):
    targets = release.signing_targets(app)
    framework = app / "Contents/Frameworks/Python.framework"
    assert targets.index(framework / "Versions/A/Python") < targets.index(framework)
    assert targets[-1] == app
    assert app / "Contents/Info.plist" not in targets


def test_symlinks_not_signed_twice(app):
    framework = app / "Contents/Frameworks/Python.framework"
    try:
        (framework / "Versions/Current").symlink_to("A", target_is_directory=True)
        (framework / "Python").symlink_to("Versions/Current/Python")
    except OSError:
        pytest.skip("symlink creation not permitted")
    targets = release.signing_targets(app)
    assert framework / "Python" not in targets
    assert not any("Current" in path.parts for path in targets)


@pytest.mark.parametrize("status", ["Invalid", "In Progress", None])
def test_notarization_requires_accepted(monkeypatch, config, status):
    monkeypatch.setattr(release, "run", lambda args: json.dumps({"status": status, "id": "submission-id"}))
    with pytest.raises(RuntimeError, match="not accepted"):
        release.notarize(Path("app.zip"), config)


@pytest.mark.parametrize("fail_dmg", [False, True])
def test_package_notarizes_final_dmg_and_hashes_after_stapling(monkeypatch, config, app, tmp_path, fail_dmg):
    calls = []

    def run(args):
        calls.append(args)
        if args[:2] == ["security", "find-identity"]:
            return config["MACOS_SIGN_IDENTITY"]
        if args[:3] == ["xcrun", "notarytool", "submit"]:
            status = "Invalid" if fail_dmg and args[3].endswith(".dmg") else "Accepted"
            return json.dumps({"status": status, "id": "submission-id"})
        if args[:2] == ["hdiutil", "create"]:
            Path(args[-1]).write_bytes(b"dmg")
            staging = Path(args[args.index("-srcfolder") + 1])
            assert (staging / "Applications").is_symlink()
        if args[:3] == ["xcrun", "stapler", "staple"] and args[3].endswith(".dmg"):
            Path(args[3]).write_bytes(b"stapled-dmg")
        return ""

    monkeypatch.setattr(release, "run", run)
    output = tmp_path / "output/release.dmg"
    if fail_dmg:
        with pytest.raises(RuntimeError, match="not accepted"):
            release.package(app, output, config)
        assert not output.exists()
        assert not output.with_suffix(".dmg.sha256").exists()
        return

    release.package(app, output, config)
    submissions = [args[3] for args in calls if args[:3] == ["xcrun", "notarytool", "submit"]]
    assert len(submissions) == 2
    assert submissions[0].endswith(".zip") and submissions[1].endswith(".dmg")
    assert ["xcrun", "stapler", "validate", submissions[1]] in calls
    assert [
        "spctl",
        "--assess",
        "--type",
        "open",
        "--context",
        "context:primary-signature",
        "--verbose=4",
        submissions[1],
    ] in calls
    assert output.read_bytes() == b"stapled-dmg"
    assert output.with_suffix(".dmg.sha256").read_text() == (
        f"{hashlib.sha256(b'stapled-dmg').hexdigest()}  release.dmg\n"
    )


def test_security_failure_does_not_print_password(monkeypatch):
    def failure(*args, **kwargs):
        return release.subprocess.CompletedProcess(args[0], 1, "keychain dump", "private details")

    monkeypatch.setattr(release.subprocess, "run", failure)
    with pytest.raises(RuntimeError) as error:
        release.run(["security", "unlock-keychain", "-p", "secret"])
    assert "secret" not in str(error.value)
    assert "private details" not in str(error.value)


def test_local_app_is_adhoc_signed_and_strictly_verified(monkeypatch, app):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return release.subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(build_macos.subprocess, "run", run)
    assert build_macos.adhoc_sign_app(app)
    assert calls == [
        ["codesign", "--force", "--deep", "--sign", "-", str(app)],
        ["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)],
    ]
