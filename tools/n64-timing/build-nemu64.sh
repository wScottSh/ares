#!/usr/bin/env bash
# Builds the three nemu64-test ROMs (timing, cycle, cop0hazard) in a pinned Rust Docker image.
# Output: $N64_TIMING_HOME/roms/nemu64-{timing,cycle,cop0hazard}.z64
set -euo pipefail

N64_TIMING_HOME="${N64_TIMING_HOME:-$HOME/n64-timing}"
NEMU64_COMMIT="${NEMU64_COMMIT:-9a8b9f7}"
NEMU64_URL="https://github.com/thelemmy/nemu64-test"
SETS="${*:-timing cycle cop0hazard}"

src="$N64_TIMING_HOME/nemu64-test"
out="$N64_TIMING_HOME/roms"
mkdir -p "$out"
if [ ! -d "$src/.git" ]; then git clone -q "$NEMU64_URL" "$src"; fi
git -C "$src" fetch -q origin || true
git -C "$src" checkout -q --detach "$NEMU64_COMMIT"

winpath() { if command -v cygpath >/dev/null; then cygpath -w "$1"; else echo "$1"; fi; }

# Docker Desktop's credential helper fails from non-interactive Windows sessions
# ("A specified logon session does not exist"). Public images need no credentials,
# so point the CLI at a stub helper that reports none.
if command -v cygpath >/dev/null; then
  cfg="$N64_TIMING_HOME/docker-config"
  mkdir -p "$cfg"
  echo '{"credsStore":"none"}' > "$cfg/config.json"
  printf '@echo off\r\nif "%%1"=="list" (echo {}& exit /b 0)\r\nif "%%1"=="get" (echo credentials not found in native keychain& exit /b 1)\r\nexit /b 0\r\n' > "$cfg/docker-credential-none.cmd"
  export PATH="$cfg:$PATH" DOCKER_CONFIG="$(cygpath -w "$cfg")"
fi

for set in $SETS; do
  echo "== building nemu64-test --features $set"
  MSYS_NO_PATHCONV=1 docker run --rm \
    -v "$(winpath "$src"):/src:ro" \
    -v "$(winpath "$out"):/out" \
    -v n64timing-cargo:/usr/local/cargo/registry \
    -v n64timing-rustup:/usr/local/rustup \
    -v n64timing-bin:/opt/cargo-bin \
    -v n64timing-target:/target \
    -e SET="$set" \
    rust:1-bookworm bash -euc '
      export PATH=/opt/cargo-bin/bin:$PATH CARGO_TARGET_DIR=/target/$SET
      command -v nust64 >/dev/null || cargo +stable install --root /opt/cargo-bin nust64 --version 0.4.1 --locked --force
      rm -rf /work && cp -r /src /work && cd /work
      cargo run --release --no-default-features --features "$SET" >/tmp/run.log 2>&1 || { tail -40 /tmp/run.log; exit 1; }
      tail -3 /tmp/run.log
      rom=$(ls -t /target/$SET/mips-nintendo64-none/release/*.z64 | head -1)
      cp "$rom" "/out/nemu64-$SET.z64"
      sha256sum "/out/nemu64-$SET.z64"
    '
done
