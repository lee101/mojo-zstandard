"""Benchmark mojo-zstandard against the upstream Python zstandard bindings."""

from __future__ import annotations

import os
import platform
import sys
import time

import numpy as np
import zstandard as upstream

sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "python"),
)

import mojo_zstandard as mojo  # noqa: E402


def best_time(function, repetitions=7):
    function()
    best = float("inf")
    result = None
    for _ in range(repetitions):
        start = time.perf_counter()
        result = function()
        best = min(best, time.perf_counter() - start)
    return best, result


def machine():
    model = "unknown CPU"
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as cpuinfo:
            for line in cpuinfo:
                if line.startswith("model name"):
                    model = line.split(":", 1)[1].strip()
                    break
    except OSError:
        pass
    return (
        f"{model}; {platform.system()} {platform.machine()}; "
        f"Python {platform.python_version()}"
    )


def main():
    size = 8 * 1024 * 1024
    record = (
        b'{"time":"2026-07-29T12:00:00Z","level":"info",'
        b'"service":"compressor","message":"request completed","status":200}\n'
    )
    text = (record * (size // len(record) + 1))[:size]
    random_data = np.random.default_rng(7).integers(
        0, 256, size=size, dtype=np.uint8
    ).tobytes()

    mojo_level3 = mojo.ZstdCompressor(level=3)
    upstream_level3 = upstream.ZstdCompressor(level=3)
    mojo_level9 = mojo.ZstdCompressor(level=9)
    upstream_level9 = upstream.ZstdCompressor(level=9)
    mojo_decompressor = mojo.ZstdDecompressor()
    upstream_decompressor = upstream.ZstdDecompressor()

    text_frame = upstream_level3.compress(text)
    random_frame = upstream_level3.compress(random_data)

    cases = [
        (
            "compress repetitive 8 MiB, level 3",
            lambda: mojo_level3.compress(text),
            lambda: upstream_level3.compress(text),
            "compress",
            text,
        ),
        (
            "decompress repetitive 8 MiB",
            lambda: mojo_decompressor.decompress(text_frame),
            lambda: upstream_decompressor.decompress(text_frame),
            "decompress",
            text,
        ),
        (
            "compress random 8 MiB, level 3",
            lambda: mojo_level3.compress(random_data),
            lambda: upstream_level3.compress(random_data),
            "compress",
            random_data,
        ),
        (
            "decompress random 8 MiB",
            lambda: mojo_decompressor.decompress(random_frame),
            lambda: upstream_decompressor.decompress(random_frame),
            "decompress",
            random_data,
        ),
        (
            "compress repetitive 8 MiB, level 9",
            lambda: mojo_level9.compress(text),
            lambda: upstream_level9.compress(text),
            "compress",
            text,
        ),
    ]

    print(f"Machine: {machine()}")
    print(f"Mojo linked zstd: {'.'.join(map(str, mojo.ZSTD_VERSION))}")
    print(f"Upstream: zstandard {upstream.__version__}, zstd {upstream.ZSTD_VERSION}")
    print()
    print("| case | mojo-zstandard | upstream zstandard | relative |")
    print("| --- | ---: | ---: | ---: |")
    for name, mojo_function, upstream_function, kind, source in cases:
        mojo_seconds, mojo_result = best_time(mojo_function)
        upstream_seconds, upstream_result = best_time(upstream_function)
        if kind == "decompress":
            if mojo_result != source or upstream_result != source:
                raise AssertionError(f"benchmark outputs differ for {name}")
        else:
            if upstream.decompress(mojo_result) != source:
                raise AssertionError(f"Mojo output is invalid for {name}")
            if mojo.decompress(upstream_result) != source:
                raise AssertionError(f"upstream output is invalid for {name}")
        relative = upstream_seconds / mojo_seconds
        print(
            f"| {name} | {mojo_seconds * 1000:.2f} ms | "
            f"{upstream_seconds * 1000:.2f} ms | {relative:.2f}x |"
        )


if __name__ == "__main__":
    main()
