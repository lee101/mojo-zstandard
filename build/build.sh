#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "${repo_root}/dist"

# The shared toolchain exports MODULAR_HOME but no CONDA_PREFIX; zstd headers and
# libzstd live in the same prefix as the compiler, so derive it when unset.
: "${CONDA_PREFIX:=${MODULAR_HOME%/share/max}}"

cc -O3 -fPIC -I"${CONDA_PREFIX}/include/python3.13" \
    -I"${CONDA_PREFIX}/include" \
    -c "${repo_root}/src/python_output.c" \
    -o "${repo_root}/build/python_output.o"
mojo build --emit shared-lib "${repo_root}/src/zstandard.mojo" \
    -o "${repo_root}/dist/libmojo-zstandard.so" \
    -Xlinker "${repo_root}/build/python_output.o" \
    -Xlinker "-L${CONDA_PREFIX}/lib" \
    -Xlinker -lzstd
