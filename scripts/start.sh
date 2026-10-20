#!/bin/sh
# Unified start script for macOS and Linux.
# Detects missing dependencies (Python, Node.js, FFmpeg), installs them automatically if missing, and launches AI Studio.

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

detect_package_manager() {
    if [ "$(uname -s)" = "Darwin" ]; then
        if command -v brew >/dev/null 2>&1; then
            echo "brew"
        else
            echo "brew_missing"
        fi
    elif [ "$(uname -s)" = "Linux" ]; then
        if command -v apt-get >/dev/null 2>&1; then
            echo "apt"
        elif command -v dnf >/dev/null 2>&1; then
            echo "dnf"
        elif command -v pacman >/dev/null 2>&1; then
            echo "pacman"
        elif command -v apk >/dev/null 2>&1; then
            echo "apk"
        else
            echo "unknown"
        fi
    else
        echo "unknown"
    fi
}

install_package() {
    PKG_TYPE="$1" # python, node, ffmpeg
    PM="$(detect_package_manager)"

    echo "==> Missing dependency detected: $PKG_TYPE. Attempting automatic installation..."

    case "$PM" in
        "brew")
            case "$PKG_TYPE" in
                "python") brew install python@3.11 || brew install python ;;
                "node")   brew install node ;;
                "ffmpeg") brew install ffmpeg ;;
            esac
            ;;
        "brew_missing")
            echo "Homebrew not found. Installing Homebrew first..."
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
            eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv 2>/dev/null)"
            case "$PKG_TYPE" in
                "python") brew install python ;;
                "node")   brew install node ;;
                "ffmpeg") brew install ffmpeg ;;
            esac
            ;;
        "apt")
            SUDO=""
            [ "$(id -u)" -ne 0 ] && SUDO="sudo"
            $SUDO apt-get update -qq
            case "$PKG_TYPE" in
                "python") $SUDO apt-get install -y -qq python3 python3-pip python3-venv ;;
                "node")   $SUDO apt-get install -y -qq nodejs npm ;;
                "ffmpeg") $SUDO apt-get install -y -qq ffmpeg ;;
            esac
            ;;
        "dnf")
            SUDO=""
            [ "$(id -u)" -ne 0 ] && SUDO="sudo"
            case "$PKG_TYPE" in
                "python") $SUDO dnf install -y python3 python3-pip ;;
                "node")   $SUDO dnf install -y nodejs npm ;;
                "ffmpeg") $SUDO dnf install -y ffmpeg ;;
            esac
            ;;
        "pacman")
            SUDO=""
            [ "$(id -u)" -ne 0 ] && SUDO="sudo"
            case "$PKG_TYPE" in
                "python") $SUDO pacman -S --noconfirm python python-pip ;;
                "node")   $SUDO pacman -S --noconfirm nodejs npm ;;
                "ffmpeg") $SUDO pacman -S --noconfirm ffmpeg ;;
            esac
            ;;
        "apk")
            case "$PKG_TYPE" in
                "python") apk add --no-cache python3 py3-pip ;;
                "node")   apk add --no-cache nodejs npm ;;
                "ffmpeg") apk add --no-cache ffmpeg ;;
            esac
            ;;
        *)
            echo "Could not auto-install $PKG_TYPE automatically. Please install it manually."
            ;;
    esac
}

# 1. Check Python
if ! command -v python3 >/dev/null 2>&1 && ! command -v python >/dev/null 2>&1; then
    install_package "python"
fi

# 2. Check Node / npm
if ! command -v npm >/dev/null 2>&1; then
    install_package "node"
fi

# 3. Check ffmpeg
if ! command -v ffmpeg >/dev/null 2>&1; then
    install_package "ffmpeg"
fi

# Launch start.py
if command -v python3 >/dev/null 2>&1; then
    exec python3 scripts/start.py "$@"
elif command -v python >/dev/null 2>&1; then
    exec python scripts/start.py "$@"
else
    echo "Python is still not available. Please install Python 3.10+ manually."
    exit 1
fi
