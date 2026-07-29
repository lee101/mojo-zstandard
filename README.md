# mojo-zstandard

Zstandard compression and framing exposed to Python through a Mojo shared
library. The covered API follows
[`zstandard`](https://python-zstandard.readthedocs.io/) names and call patterns,
and produces ordinary zstd frames that interoperate with any conforming
implementation.

The codec engine is the production `libzstd` C library. Mojo owns the compiled
C ABI boundary and context calls; the Python layer provides the familiar
classes, frame inspection, streaming objects, and buffer handling. This is a
binding port, not a new implementation of the zstd entropy codecs.

```python
import mojo_zstandard as zstd

source = b"Mojo and zstandard"

compressed = zstd.ZstdCompressor(write_checksum=True).compress(source)
restored = zstd.ZstdDecompressor().decompress(compressed)

assert restored == source
assert zstd.get_frame_parameters(compressed).has_checksum
```

## Coverage

| upstream area | covered |
| --- | --- |
| one-shot helpers | `compress`, `decompress`, bytes-like inputs, bounded decoding for frames without a content size |
| contexts | reusable `ZstdCompressor` and `ZstdDecompressor`, levels, checksums, content-size and dictionary-ID flags, positive worker counts |
| incremental API | `compressobj`, `decompressobj`, block/frame flush, concatenated-frame decoding, `eof`, `unused_data`, `unconsumed_tail` |
| dictionaries | `ZstdCompressionDict`, raw-content and trained dictionaries, `dict_id`, basic `train_dictionary` |
| framing | `frame_header_size`, `frame_content_size`, `get_frame_parameters`, concatenated frames and extra-data control |
| file-like API | `stream_reader`, `stream_writer`, `copy_stream`, `read_to_iter` |
| metadata | common format, flush, dictionary, size, level, and zstd-version constants |

The deliberate limits are:

- Advanced `ZstdCompressionParameters` tuning is represented only by its
  compression level. Strategy, long-distance matching, and other low-level
  parameter fields are not exposed.
- `multi_compress_to_buffer`, `multi_decompress_to_buffer`, `chunker`,
  `decompress_content_dict_chain`, prefix dictionaries, prebuilt CDict/DDict
  objects, and dictionary-coverage optimization are not implemented.
- Magicless frames and a custom `max_window_size` are rejected.
- Negative `threads` selects single-threaded operation instead of upstream's
  automatic CPU count. Positive worker counts use libzstd multithreading.
- Stream writers are incremental. Stream readers and `read_to_iter` currently
  buffer their input before serving output.
- Advanced keyword tuning for `train_dictionary` is rejected; basic training
  from a target size and sample sequence is supported.

## Install and run

The repository pins Mojo and declares zstd, upstream `zstandard`, and the test
dependencies in its pixi environment:

```bash
pixi install
pixi run build
pixi run test
pixi run bench
```

`pixi run build` creates `dist/libmojo-zstandard.so`. Pixi sets
`PYTHONPATH=python`, so the usage example works directly inside the environment.

## Performance

Measured by `pixi run bench` on this machine: Intel Xeon E5-2697 v4 at
2.30 GHz, Linux x86-64, Python 3.13.14, linked zstd 1.5.7, and upstream
`zstandard` 0.25.0 using zstd 1.5.7. Each entry is the best of seven timed runs
after one warmup on the same 8 MiB input. Decompression compares the same
upstream-produced frame. Relative is upstream time divided by mojo-zstandard
time, so values above one mean mojo-zstandard was faster.

| case | mojo-zstandard | upstream zstandard | relative |
| --- | ---: | ---: | ---: |
| compress repetitive 8 MiB, level 3 | 2.23 ms | 2.17 ms | 0.98x |
| decompress repetitive 8 MiB | 0.69 ms | 0.68 ms | 0.99x |
| compress random 8 MiB, level 3 | 6.01 ms | 5.98 ms | 1.00x |
| decompress random 8 MiB | 2.00 ms | 0.99 ms | 0.50x |
| compress repetitive 8 MiB, level 9 | 10.47 ms | 8.76 ms | 0.84x |

Both packages execute the same zstd release, so these results primarily measure
allocation and language-boundary costs. Results vary with CPU load; run the
benchmark locally instead of treating this single run as a general speed claim.

Profiling found no port-owned bulk arithmetic loop to vectorize or parallelize:
the entropy codec loops execute inside libzstd, while the binding performs
pointer setup, frame metadata checks, and output-buffer handling. The port
intentionally remains CPU-only and does not add a GPU runtime dependency.

## How it works

`src/zstandard.mojo` is one compilation unit. Its exported functions use
`@export("name")` and the C ABI, accept source and destination addresses as
`Int`, and invoke the stable libzstd context, one-shot, streaming, frame, and
dictionary-training APIs. A small CPython output shim shrinks one-shot
compression results without copying them. The build links both pieces to the
zstd library supplied by pixi and writes one shared object.

Python owns context lifetimes and every source and destination allocation.
Contiguous input buffers remain alive for each call. Destination `bytes`
objects are allocated through CPython's C API, filled through their address
before they are exposed to user code, and resized in C to avoid a Python-level
full-buffer slice copy. Streaming calls pass the standard three-field zstd input
and output buffer structures through `ctypes`; Mojo never retains a Python
address.

Frame descriptors are parsed in Python using the published zstd framing layout.
The parser handles single-segment frames, window descriptors, all dictionary-ID
widths, all content-size encodings, and checksum flags. Actual frame boundaries,
validation, compression, and decompression remain libzstd operations.

## License

MIT
