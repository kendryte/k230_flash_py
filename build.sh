#!/usr/bin/env bash
#
# One entry point for the two things this repo produces:
#
#   the pip package   sdist + wheel, from the repo root
#   the desktop GUI   a PyInstaller bundle, built differently on each OS
#
# The commands themselves are not hard, but they live in three different places
# (pyproject.toml, src/gui/build_*.py, and the Linux branch of the release
# workflow), so this puts them behind one script. It mirrors what
# .github/workflows/build-and-release.yml does -- if you change one, change the
# other.
#
# Usage:
#   ./build.sh wheel                # sdist + wheel  -> dist/
#   ./build.sh gui                  # GUI for the current OS, current env
#   ./build.sh gui --venv           # GUI in an isolated venv  <- use this one
#   ./build.sh gui --appimage       # Linux only: AppImage via Docker, like CI
#   ./build.sh all                  # wheel + GUI
#   ./build.sh clean                # remove build artefacts
#
#   --venv            build the GUI in .build-venv/ with only requirements.txt.
#                     Strongly recommended: PyInstaller bundles whatever Qt it
#                     finds in the environment, so a dev env holding a second Qt
#                     (a conda base with PyQt6 and qt6-main does) yields a
#                     bundle whose Qt libraries and Qt plugins are different
#                     versions -- it builds fine and then refuses to start with
#                     "Ignoring QPA plugin due to mismatching Qt versions". The
#                     same pollution is why an unclean env can add a gigabyte of
#                     numpy/MKL to the bundle.
#   --install-deps    pip install anything missing instead of just naming it
#   --version X       stamp X into the GUI's version.txt (default: from git)

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO"

GUI_DIR="$REPO/src/gui"
DIST="$REPO/dist"
DOCKER_IMAGE="k230-gui-builder:latest"

APPIMAGE=0
INSTALL_DEPS=0
USE_VENV=0
VERSION=""
CMD=""
BUILD_VENV="$REPO/.build-venv"

# Windows/git-bash usually has `python` but no `python3`.
if command -v python3 >/dev/null 2>&1; then PY=python3; else PY=python; fi

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

# Print the header comment above, so the help text cannot drift from it. Stops
# at the first non-comment line rather than a hardcoded range, which silently
# went wrong the moment the header grew a line.
usage() {
  awk 'NR==1 && /^#!/ {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "${BASH_SOURCE[0]}"
}

# ---------------------------------------------------------------- arguments --

while [ $# -gt 0 ]; do
  case "$1" in
    wheel|gui|all|clean) CMD="$1" ;;
    --appimage)     APPIMAGE=1 ;;
    --venv)         USE_VENV=1 ;;
    --install-deps) INSTALL_DEPS=1 ;;
    --version)      shift; VERSION="${1:-}"; [ -n "$VERSION" ] || die "--version needs a value" ;;
    -h|--help)      usage; exit 0 ;;
    *)              die "unknown argument: $1 (try --help)" ;;
  esac
  shift
done
[ -n "$CMD" ] || { usage; exit 1; }

# ------------------------------------------------------------------- helpers --

os_name() {
  case "$(uname -s)" in
    Linux*)            echo linux ;;
    Darwin*)           echo macos ;;
    MINGW*|MSYS*|CYGWIN*) echo windows ;;
    *)                 echo unknown ;;
  esac
}

# Report every missing dependency at once rather than failing on the first, so
# one `--install-deps` run fixes the lot.
require_python_modules() {
  local missing=()
  for mod in "$@"; do
    "$PY" -c "import $mod" >/dev/null 2>&1 || missing+=("$mod")
  done
  [ ${#missing[@]} -eq 0 ] && return 0

  # Import name != pip name for a couple of these.
  local pkgs=()
  for mod in "${missing[@]}"; do
    case "$mod" in
      PyInstaller) pkgs+=("pyinstaller") ;;
      *)           pkgs+=("$mod") ;;
    esac
  done

  if [ "$INSTALL_DEPS" -eq 1 ]; then
    info "installing: ${pkgs[*]}"
    "$PY" -m pip install "${pkgs[@]}"
  else
    warn "missing: ${pkgs[*]}"
    warn "install them with:"
    warn "    $PY -m pip install ${pkgs[*]}"
    warn "or re-run this script with --install-deps"
    exit 1
  fi
}

# The GUI reads version.txt at runtime (src/gui/utils.py:get_version_from_file)
# and the spec bundles it, so it has to exist before PyInstaller runs. CI writes
# the release tag here; locally the best available answer is what git knows.
resolve_version() {
  [ -n "$VERSION" ] && { echo "$VERSION"; return; }
  local v
  v=$("$PY" -c 'from setuptools_scm import get_version; print(get_version())' 2>/dev/null) && [ -n "$v" ] && { echo "$v"; return; }
  v=$(git describe --tags --always --dirty 2>/dev/null) && [ -n "$v" ] && { echo "$v"; return; }
  echo dev
}

# -------------------------------------------------------------------- wheel --

build_wheel() {
  require_python_modules build
  info "building sdist + wheel"
  "$PY" -m build --outdir "$DIST"
  info "artefacts in $DIST:"
  ls -1sh "$DIST" | tail -n +2 | sed 's/^/    /'
  warn "version comes from git via setuptools_scm: with uncommitted changes it"
  warn "reads <last-tag>.devN+g<last-commit>.dYYYYMMDD, so the hash names the"
  warn "commit BEFORE your edits. Commit first if the version has to be exact."
}

# ---------------------------------------------------------------------- gui --

stamp_version() {
  local v="$1"
  printf '%s' "$v" > "$GUI_DIR/version.txt"
  info "version.txt = $v"
}

# Build the GUI against only what requirements.txt asks for. PyInstaller has no
# notion of "the project's dependencies" -- it bundles whatever the interpreter
# running it can see -- so this is the only way to get a bundle that does not
# depend on the state of the developer's environment.
setup_build_venv() {
  local vpy
  if [ ! -d "$BUILD_VENV" ]; then
    info "creating $BUILD_VENV (first run downloads PySide6, a few hundred MB)"
    "$PY" -m venv "$BUILD_VENV"
  fi
  case "$(os_name)" in
    windows) vpy="$BUILD_VENV/Scripts/python.exe" ;;
    *)       vpy="$BUILD_VENV/bin/python" ;;
  esac
  [ -x "$vpy" ] || die "venv looks broken; remove $BUILD_VENV and retry"

  info "syncing build venv with requirements.txt"
  "$vpy" -m pip install --quiet --upgrade pip
  "$vpy" -m pip install --quiet -r "$REPO/requirements.txt" pyinstaller
  "$vpy" -m pip install --quiet -e "$REPO"
  PY="$vpy"
}

# Name the second Qt if there is one. Not fatal -- the build may still work --
# but it is the first thing to suspect when a bundle builds and will not start.
warn_if_env_polluted() {
  local pyside_qt sys_qt
  pyside_qt=$("$PY" -c 'import PySide6, pathlib; print(pathlib.Path(PySide6.__file__).parent)' 2>/dev/null) || return 0
  sys_qt=$(ls "$(dirname "$("$PY" -c 'import sys; print(sys.executable)')")"/../lib/libQt6Core.so.6.* 2>/dev/null | head -1)
  [ -n "$sys_qt" ] || return 0
  warn "this environment has a second Qt outside PySide6:"
  warn "    $sys_qt"
  warn "PyInstaller can mix the two and produce a bundle that will not start"
  warn "(\"Ignoring QPA plugin due to mismatching Qt versions\"). Build with"
  warn "--venv to avoid it."
}

build_gui_native() {
  local os v
  os="$(os_name)"
  v="$(resolve_version)"

  if [ "$USE_VENV" -eq 1 ]; then
    setup_build_venv
  else
    warn_if_env_polluted
  fi

  # The GUI imports k230_flash in-process, so the package has to be importable
  # or PyInstaller bundles a broken app. --venv has already handled all of this.
  if [ "$USE_VENV" -eq 0 ]; then
    require_python_modules PySide6 PyInstaller loguru usb
    "$PY" -c "import k230_flash" >/dev/null 2>&1 || {
      if [ "$INSTALL_DEPS" -eq 1 ]; then
        info "installing k230_flash in editable mode"
        "$PY" -m pip install -e "$REPO"
      else
        warn "k230_flash is not importable; the GUI bundles it."
        warn "    $PY -m pip install -e $REPO"
        exit 1
      fi
    }
  fi

  stamp_version "$v"
  cd "$GUI_DIR"
  case "$os" in
    linux)
      info "PyInstaller (linux)"
      "$PY" -m PyInstaller --clean -y k230_flash_gui.spec
      info "bundle: $GUI_DIR/dist/k230_flash_gui/  ($(du -sh "$GUI_DIR/dist/k230_flash_gui" | cut -f1))"
      info "run it with: $GUI_DIR/dist/k230_flash_gui/k230_flash_gui"
      # A clean build is a few hundred MB. Much past that means the build
      # environment leaked something in -- conda's numpy drags in ~400 MB of
      # Intel MKL, for instance.
      local mb; mb=$(du -sm "$GUI_DIR/dist/k230_flash_gui" | cut -f1)
      if [ "$mb" -gt 600 ] && [ "$USE_VENV" -eq 0 ]; then
        warn "the bundle is ${mb} MB, which means the build environment leaked"
        warn "unrelated packages into it. Rebuild with --venv."
      fi
      warn "this is a plain bundle, not the distributable AppImage CI ships."
      warn "use './build.sh gui --appimage' for that."
      ;;
    windows) info "build_windows.py"; "$PY" build_windows.py ;;
    macos)   info "build_macos.py";   "$PY" build_macos.py ;;
    *)       die "unsupported OS for a GUI build: $(uname -s)" ;;
  esac
}

# Mirrors the Linux branch of build-and-release.yml. Docker is not a preference
# here: the AppImage has to be built against an older glibc than a current dev
# box has, or it will not start on the distros it is meant to support.
build_gui_appimage() {
  [ "$(os_name)" = linux ] || die "--appimage is Linux only (it builds an ELF AppImage)"
  command -v docker >/dev/null 2>&1 || die "docker not found; needed for --appimage"
  docker info >/dev/null 2>&1 || die "docker is installed but not usable by this user"

  local v; v="$(resolve_version)"
  mkdir -p "$DIST"

  if ! docker image inspect "$DOCKER_IMAGE" >/dev/null 2>&1; then
    info "building the builder image (first run only, this takes a while)"
    docker build -f "$REPO/docker/Dockerfile.ubuntu2204" -t "$DOCKER_IMAGE" "$REPO/docker"
  fi

  info "building AppImage $v in $DOCKER_IMAGE"
  # --privileged: appimagetool needs FUSE. Runs as root inside, so the last
  # step hands the generated files back to the invoking user -- otherwise the
  # next non-root build trips over root-owned dist/ and build/ directories.
  docker run --rm --privileged \
    -v "$REPO":/workspace -w /workspace \
    -e VERSION="$v" -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
    "$DOCKER_IMAGE" bash -euo pipefail -c '
      python3 -m pip install --quiet -r requirements.txt
      python3 -m pip install --quiet -e .

      if ! command -v appimagetool >/dev/null 2>&1; then
        wget -q https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage \
             -O /usr/local/bin/appimagetool
        chmod +x /usr/local/bin/appimagetool
      fi

      cd src/gui
      printf "%s" "$VERSION" > version.txt
      pyinstaller --clean -y k230_flash_gui.spec
      test -d dist/k230_flash_gui || { echo "PyInstaller produced no bundle"; exit 1; }

      APPDIR=$(pwd)/AppDir
      rm -rf "$APPDIR"
      mkdir -p "$APPDIR/usr/bin"
      cp -r dist/k230_flash_gui/* "$APPDIR/usr/bin/"
      [ -d package/AppDir ] && cp -r package/AppDir/* "$APPDIR/"
      mkdir -p "$APPDIR/usr/share/pixmaps"
      [ -d assets ] && cp -r assets "$APPDIR/usr/share/"

      # gdk-pixbuf loaders have to be inside the AppImage and re-indexed, or
      # icons silently fail to load on the target machine.
      mkdir -p "$APPDIR/usr/lib/gdk-pixbuf-2.0/2.10.0/loaders"
      cp -r /usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/2.10.0/loaders/* \
            "$APPDIR/usr/lib/gdk-pixbuf-2.0/2.10.0/loaders/"
      cp /usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/gdk-pixbuf-query-loaders "$APPDIR/usr/bin/"
      "$APPDIR/usr/bin/gdk-pixbuf-query-loaders" > "$APPDIR/usr/lib/gdk-pixbuf-2.0/2.10.0/loaders.cache"

      OUT="/workspace/dist/k230_flash_gui-linux-${VERSION}.AppImage"
      mkdir -p /workspace/dist
      ARCH=x86_64 appimagetool --no-appstream "$APPDIR" "$OUT"

      chown -R "$HOST_UID:$HOST_GID" /workspace/dist src/gui/build src/gui/dist "$APPDIR" 2>/dev/null || true
      ls -lh "$OUT"
    '
  info "AppImage in $DIST"
}

# -------------------------------------------------------------------- clean --

do_clean() {
  info "removing build artefacts"
  # Everything here is gitignored or generated; nothing tracked is touched.
  rm -rf "$DIST" "$REPO/build" "$REPO"/*.egg-info "$REPO/src"/*.egg-info \
         "$GUI_DIR/build" "$GUI_DIR/dist" "$GUI_DIR/AppDir" "$GUI_DIR/version.txt"
  find "$REPO/src" "$REPO/tests" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
  # Deliberately kept: it is a cache, and rebuilding it re-downloads PySide6.
  if [ -d "$BUILD_VENV" ]; then
    info "kept $BUILD_VENV ($(du -sh "$BUILD_VENV" | cut -f1)); remove it by hand to force a fresh one"
  fi
  info "done"
}

# ---------------------------------------------------------------------- main --

case "$CMD" in
  wheel) build_wheel ;;
  gui)   if [ "$APPIMAGE" -eq 1 ]; then build_gui_appimage; else build_gui_native; fi ;;
  all)   build_wheel; build_gui_native ;;
  clean) do_clean ;;
esac
