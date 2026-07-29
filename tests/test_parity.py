import importlib
import io
import os

import numpy as np
import pytest
import zstandard as upstream

import mojo_zstandard as zstd

backend_module = importlib.import_module("mojo_zstandard.backend")


def payload(size=500_000):
    record = (
        b'{"timestamp":"2026-07-29","service":"mojo-zstandard",'
        b'"status":200,"message":"request complete"}\n'
    )
    return (record * (size // len(record) + 1))[:size]


@pytest.mark.parametrize("size", [0, 1, 17, 255, 4096, 250_000])
def test_roundtrip_sizes(size):
    source = payload(size)
    assert zstd.decompress(zstd.compress(source)) == source


@pytest.mark.parametrize("level", [-3, 1, 3, 9, 19])
def test_mojo_compresses_upstream_decompresses(level):
    source = payload()
    encoded = zstd.ZstdCompressor(level=level).compress(source)
    assert upstream.decompress(encoded) == source


@pytest.mark.parametrize("level", [-5, 1, 6, 15])
def test_upstream_compresses_mojo_decompresses(level):
    source = payload()
    encoded = upstream.ZstdCompressor(level=level).compress(source)
    assert zstd.decompress(encoded) == source


@pytest.mark.parametrize(
    "options",
    [
        {"write_checksum": True},
        {"write_content_size": False},
        {"write_dict_id": False},
        {"threads": 2},
    ],
)
def test_compressor_frame_options_match_upstream(options):
    source = payload()
    encoded = zstd.ZstdCompressor(**options).compress(source)
    maximum = len(source) if options.get("write_content_size") is False else 0
    assert upstream.decompress(encoded, max_output_size=maximum) == source
    ours = zstd.get_frame_parameters(encoded)
    theirs = upstream.get_frame_parameters(encoded)
    assert ours.content_size == theirs.content_size
    assert ours.window_size == theirs.window_size
    assert ours.dict_id == theirs.dict_id
    assert ours.has_checksum == theirs.has_checksum


def test_unknown_content_size_requires_output_bound():
    source = payload()
    encoded = upstream.ZstdCompressor(write_content_size=False).compress(source)
    assert zstd.frame_content_size(encoded) == upstream.frame_content_size(encoded) == -1
    with pytest.raises(zstd.ZstdError, match="content size"):
        zstd.decompress(encoded)
    assert zstd.decompress(encoded, max_output_size=len(source)) == source
    with pytest.raises(zstd.ZstdError):
        zstd.decompress(encoded, max_output_size=len(source) - 1)


def test_max_output_size_is_ignored_when_content_size_is_known():
    source = payload(10_000)
    encoded = upstream.compress(source)
    assert zstd.decompress(encoded, max_output_size=1) == source


def test_concatenated_frames_and_extra_data_controls():
    first, second = payload(20_000), os.urandom(30_000)
    joined = upstream.compress(first) + upstream.compress(second)
    decompressor = zstd.ZstdDecompressor()
    assert decompressor.decompress(joined) == first
    assert (
        decompressor.decompress(joined, read_across_frames=True)
        == first + second
    )
    with pytest.raises(zstd.ZstdError, match="unused data"):
        decompressor.decompress(joined, allow_extra_data=False)


def test_frame_helpers_match_upstream():
    for settings in (
        {},
        {"write_checksum": True},
        {"write_content_size": False},
    ):
        encoded = upstream.ZstdCompressor(**settings).compress(payload())
        assert zstd.frame_header_size(encoded[:5]) == upstream.frame_header_size(
            encoded[:5]
        )
        assert zstd.frame_content_size(encoded) == upstream.frame_content_size(
            encoded
        )
        ours = zstd.get_frame_parameters(encoded)
        theirs = upstream.get_frame_parameters(encoded)
        assert (
            ours.content_size,
            ours.window_size,
            ours.dict_id,
            ours.has_checksum,
        ) == (
            theirs.content_size,
            theirs.window_size,
            theirs.dict_id,
            theirs.has_checksum,
        )


def test_frame_helpers_reject_short_and_invalid_input():
    with pytest.raises(zstd.ZstdError):
        zstd.frame_header_size(b"\x28\xb5")
    with pytest.raises(zstd.ZstdError):
        zstd.get_frame_parameters(b"not zstd")
    with pytest.raises(zstd.ZstdError):
        zstd.frame_content_size(b"not zstd")


def test_frame_header_reserved_and_unused_bits():
    valid = bytearray(upstream.compress(b"x"))
    valid[4] |= 0x10
    assert zstd.frame_header_size(valid) == upstream.frame_header_size(valid)
    invalid = bytearray(valid)
    invalid[4] |= 0x08
    with pytest.raises(zstd.ZstdError):
        zstd.frame_header_size(invalid)


def _training_samples():
    return [
        (
            f'{{"index":{index},"category":"request","path":"/api/{index % 17}",'
            f'"message":"compression dictionary sample {index}"}}\n'
        ).encode()
        for index in range(600)
    ]


@pytest.fixture(scope="module")
def dictionaries():
    samples = _training_samples()
    ours = zstd.train_dictionary(8192, samples)
    theirs = upstream.ZstdCompressionDict(ours.as_bytes())
    return ours, theirs


def test_trained_dictionary_matches_upstream_metadata(dictionaries):
    ours, theirs = dictionaries
    assert len(ours.as_bytes()) <= 8192
    assert ours.dict_id() == theirs.dict_id()
    assert ours.dict_id() != 0


def test_mojo_dictionary_stream_decodes_upstream(dictionaries):
    ours, theirs = dictionaries
    source = b"".join(_training_samples()[100:300])
    encoded = zstd.ZstdCompressor(dict_data=ours).compress(source)
    assert upstream.ZstdDecompressor(dict_data=theirs).decompress(encoded) == source
    assert zstd.get_frame_parameters(encoded).dict_id == ours.dict_id()


def test_upstream_dictionary_stream_decodes_mojo(dictionaries):
    ours, theirs = dictionaries
    source = b"".join(_training_samples()[300:500])
    encoded = upstream.ZstdCompressor(dict_data=theirs).compress(source)
    assert zstd.ZstdDecompressor(dict_data=ours).decompress(encoded) == source


def test_raw_content_dictionary_cross_compatibility():
    raw = payload(20_000)
    source = raw[-5000:] * 10
    ours = zstd.ZstdCompressionDict(raw, zstd.DICT_TYPE_RAWCONTENT)
    theirs = upstream.ZstdCompressionDict(raw, upstream.DICT_TYPE_RAWCONTENT)
    encoded = zstd.ZstdCompressor(dict_data=ours).compress(source)
    assert upstream.ZstdDecompressor(dict_data=theirs).decompress(encoded) == source
    encoded = upstream.ZstdCompressor(dict_data=theirs).compress(source)
    assert zstd.ZstdDecompressor(dict_data=ours).decompress(encoded) == source


def test_incremental_mojo_compression_decodes_upstream():
    source = payload()
    obj = zstd.ZstdCompressor(write_checksum=True).compressobj(size=len(source))
    parts = [
        obj.compress(source[position : position + 7919])
        for position in range(0, len(source), 7919)
    ]
    parts.append(obj.flush())
    encoded = b"".join(parts)
    assert upstream.decompress(encoded) == source
    assert upstream.get_frame_parameters(encoded).has_checksum


def test_incremental_flush_block_keeps_frame_open():
    first, second = payload(40_000), payload(30_000)
    obj = zstd.ZstdCompressor().compressobj(size=len(first) + len(second))
    encoded = (
        obj.compress(first)
        + obj.flush(zstd.COMPRESSOBJ_FLUSH_BLOCK)
        + obj.compress(second)
        + obj.flush()
    )
    assert upstream.decompress(encoded) == first + second
    with pytest.raises(zstd.ZstdError):
        obj.compress(b"late")


def test_incremental_mojo_decompression_of_upstream_chunks():
    source = payload()
    encoded = upstream.ZstdCompressor(write_checksum=True).compress(source)
    obj = zstd.ZstdDecompressor().decompressobj(write_size=4096)
    parts = [
        obj.decompress(encoded[position : position + 7])
        for position in range(0, len(encoded), 7)
    ]
    assert b"".join(parts) + obj.flush() == source
    assert obj.eof
    assert obj.unused_data == b""
    assert obj.unconsumed_tail == b""


def test_decompression_object_reports_unused_data():
    source = payload(10_000)
    obj = zstd.ZstdDecompressor().decompressobj()
    assert obj.decompress(upstream.compress(source) + b"tail") == source
    assert obj.eof
    assert obj.unused_data == b"tail"


def test_decompression_object_reads_concatenated_frames():
    first, second = payload(5000), os.urandom(5000)
    obj = zstd.ZstdDecompressor().decompressobj(read_across_frames=True)
    result = obj.decompress(upstream.compress(first) + upstream.compress(second))
    assert result == first + second
    assert obj.eof


def test_compression_stream_writer_is_upstream_readable():
    source = payload()
    destination = io.BytesIO()
    with zstd.ZstdCompressor().stream_writer(
        destination, size=len(source), closefd=False
    ) as writer:
        assert writer.write(source[:12345]) == 12345
        assert writer.write(source[12345:]) == len(source) - 12345
    assert upstream.decompress(destination.getvalue()) == source


def test_decompression_stream_writer_reads_upstream():
    source = payload()
    encoded = upstream.compress(source)
    destination = io.BytesIO()
    with zstd.ZstdDecompressor().stream_writer(
        destination, closefd=False
    ) as writer:
        for position in range(0, len(encoded), 11):
            writer.write(encoded[position : position + 11])
    assert destination.getvalue() == source


def test_stream_readers_and_copy_stream():
    source = payload(80_000)
    with zstd.ZstdCompressor().stream_reader(source) as reader:
        encoded = reader.read()
    assert upstream.ZstdDecompressor().decompress(encoded) == source
    with zstd.ZstdDecompressor().stream_reader(encoded) as reader:
        assert reader.read() == source
    compressed_destination = io.BytesIO()
    assert zstd.ZstdCompressor().copy_stream(
        io.BytesIO(source), compressed_destination
    ) == (len(source), len(compressed_destination.getvalue()))
    output = io.BytesIO()
    assert zstd.ZstdDecompressor().copy_stream(
        io.BytesIO(compressed_destination.getvalue()), output
    ) == (len(compressed_destination.getvalue()), len(source))
    assert output.getvalue() == source


def test_read_to_iter_roundtrips():
    source = payload(90_000)
    encoded = b"".join(
        zstd.ZstdCompressor().read_to_iter(io.BytesIO(source), write_size=1000)
    )
    decoded = b"".join(
        zstd.ZstdDecompressor().read_to_iter(encoded, write_size=777)
    )
    assert decoded == source


def test_bytes_like_inputs_and_context_sizes():
    source = bytearray(payload(10_000))
    encoded = zstd.compress(memoryview(source))
    assert zstd.decompress(bytearray(encoded)) == source
    assert zstd.ZstdCompressor().memory_size() > 0
    assert zstd.ZstdDecompressor().memory_size() > 0


def test_numpy_buffers_stay_zero_copy_at_one_shot_ffi(monkeypatch):
    def reject_copy(data):
        raise AssertionError(f"unexpected copy of {type(data).__name__}")

    monkeypatch.setattr(backend_module, "as_bytes", reject_copy)
    source = np.frombuffer(payload(10_003), dtype=np.uint8)
    encoded = backend_module.ZstdCompressor().compress(source)
    encoded_array = np.frombuffer(encoded, dtype=np.uint8)
    assert (
        backend_module.ZstdDecompressor().decompress(encoded_array)
        == source.tobytes()
    )


def test_buffer_dtype_and_stride_rules_are_explicit():
    source = np.arange(513, dtype=np.uint32)
    encoded = zstd.compress(source)
    assert zstd.decompress(encoded) == source.tobytes()
    with pytest.raises(BufferError, match="C-contiguous"):
        zstd.compress(source[::2])


@pytest.mark.parametrize("size", [0, 1, 31, 32, 33, 4095, 4096, 4097])
def test_one_shot_output_is_exact_bytes_for_boundary_sizes(size):
    source = os.urandom(size)
    encoded = zstd.ZstdCompressor().compress(source)
    assert type(encoded) is bytes
    assert upstream.decompress(encoded) == source


def test_compression_parameters_from_level():
    parameters = zstd.ZstdCompressionParameters.from_level(7)
    encoded = zstd.ZstdCompressor(compression_params=parameters).compress(
        payload(1000)
    )
    assert upstream.decompress(encoded) == payload(1000)


def test_unsupported_compression_parameters_are_not_silently_ignored():
    with pytest.raises(NotImplementedError, match="window_log"):
        zstd.ZstdCompressionParameters(window_log=20)


def test_stream_argument_and_short_write_errors_are_reported():
    with pytest.raises(ValueError):
        zstd.ZstdCompressor().compressobj(size=-2)
    with pytest.raises(ValueError):
        list(zstd.ZstdCompressor().read_to_iter(b"data", write_size=0))
    with pytest.raises(ValueError):
        zstd.ZstdDecompressor().decompressobj(write_size=0)

    class ShortWriter:
        def write(self, data):
            return max(0, len(data) - 1)

        def flush(self):
            pass

    writer = zstd.ZstdCompressor().stream_writer(ShortWriter(), closefd=False)
    with pytest.raises(zstd.ZstdError, match="destination accepted"):
        writer.write(payload(200_000))
    with pytest.raises(ValueError, match="invalid flush mode"):
        writer.flush(999)
    with pytest.raises(zstd.ZstdError, match="destination accepted"):
        writer.close()

    incomplete = zstd.ZstdDecompressor().stream_writer(
        io.BytesIO(), closefd=False
    )
    incomplete.write(upstream.compress(payload())[:5])
    with pytest.raises(zstd.ZstdError, match="end-of-frame"):
        incomplete.close()


@pytest.mark.parametrize(
    "bad_data",
    [b"", b"not a zstd frame", b"\x28\xb5\x2f\xfd\x20"],
)
def test_invalid_compressed_data_raises(bad_data):
    with pytest.raises(zstd.ZstdError):
        zstd.decompress(bad_data)


def test_module_metadata_matches_linked_zstd():
    assert zstd.ZSTD_VERSION == (1, 5, 7)
    assert zstd.MAGIC_NUMBER == upstream.MAGIC_NUMBER
    assert zstd.MAX_COMPRESSION_LEVEL == upstream.MAX_COMPRESSION_LEVEL
