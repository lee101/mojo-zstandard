"""Python API compatible with the covered subset of :mod:`zstandard`."""

from __future__ import annotations

import ctypes
import io
import threading
from dataclasses import dataclass

from ._lib import (
    CCtx,
    DCtx,
    InBuffer,
    LibraryError,
    OutBuffer,
    as_buffer,
    as_bytes,
    buffer_address,
    check,
    check_dict,
    lib,
    writable_bytes,
)

CONTENTSIZE_UNKNOWN = (1 << 64) - 1
CONTENTSIZE_ERROR = (1 << 64) - 2
MAGIC_NUMBER = 0xFD2FB528
FORMAT_ZSTD1 = 0
FORMAT_ZSTD1_MAGICLESS = 1
DICT_TYPE_AUTO = 0
DICT_TYPE_RAWCONTENT = 1
DICT_TYPE_FULLDICT = 2
FLUSH_BLOCK = 0
FLUSH_FRAME = 1
COMPRESSOBJ_FLUSH_FINISH = 0
COMPRESSOBJ_FLUSH_BLOCK = 1
MAX_COMPRESSION_LEVEL = 22
MIN_COMPRESSION_LEVEL = -131072
DEFAULT_COMPRESSION_LEVEL = 3
BLOCKSIZELOG_MAX = 17
BLOCKSIZE_MAX = 1 << BLOCKSIZELOG_MAX
WINDOWLOG_MIN = 10
WINDOWLOG_MAX = 31
COMPRESSION_RECOMMENDED_INPUT_SIZE = 131072
DECOMPRESSION_RECOMMENDED_INPUT_SIZE = 131075


class ZstdError(Exception):
    pass


def _zstd_call(function, *arguments, operation: str):
    try:
        return check(function(*arguments), operation)
    except LibraryError as exc:
        raise ZstdError(str(exc)) from exc


def _unsigned(value: int) -> int:
    return int(value) & CONTENTSIZE_UNKNOWN


def _destination(capacity: int) -> tuple[object, int, object]:
    destination, address = writable_bytes(capacity)
    return destination, address, destination


def _bytes_prefix(data, size: int) -> bytes:
    if size == len(data):
        return data
    return data[:size]


def _frame_size(data) -> int:
    source_address, source_size, keepalive = buffer_address(data)
    result = _zstd_call(
        lib().mzs_find_frame_size,
        source_address,
        source_size,
        operation="frame size discovery",
    )
    _ = keepalive
    return result


@dataclass(frozen=True)
class FrameParameters:
    content_size: int
    window_size: int
    dict_id: int
    has_checksum: bool


class ZstdCompressionDict:
    def __init__(self, data, dict_type=DICT_TYPE_AUTO):
        if int(dict_type) not in {
            DICT_TYPE_AUTO,
            DICT_TYPE_RAWCONTENT,
            DICT_TYPE_FULLDICT,
        }:
            raise ValueError("invalid dictionary type")
        self._data = as_bytes(data)
        self.dict_type = int(dict_type)

    def as_bytes(self) -> bytes:
        return self._data

    def dict_id(self) -> int:
        address, size, keepalive = buffer_address(self._data)
        result = int(lib().mzs_dict_id_from_dict(address, size))
        _ = keepalive
        return result

    def precompute_compress(self, level=0, compression_params=None):
        _ = level, compression_params
        return None

    def __len__(self):
        return len(self._data)


class ZstdCompressionParameters:
    def __init__(self, compression_level=DEFAULT_COMPRESSION_LEVEL, **kwargs):
        if kwargs:
            names = ", ".join(sorted(kwargs))
            raise NotImplementedError(
                f"advanced compression parameters are not supported: {names}"
            )
        self.compression_level = int(compression_level)

    @classmethod
    def from_level(cls, level, source_size=0, dict_size=0, **kwargs):
        _ = source_size, dict_size
        return cls(level, **kwargs)


def train_dictionary(dict_size, samples, **kwargs) -> ZstdCompressionDict:
    if kwargs:
        raise NotImplementedError(
            "advanced dictionary training parameters are not supported"
        )
    size = int(dict_size)
    if size <= 0:
        raise ValueError("dict_size must be positive")
    sample_list = [as_bytes(sample) for sample in samples]
    if not sample_list:
        raise ValueError("samples must not be empty")
    joined = b"".join(sample_list)
    sample_sizes = (ctypes.c_size_t * len(sample_list))(
        *(len(sample) for sample in sample_list)
    )
    source_address, _, source_keepalive = buffer_address(joined)
    destination, destination_address, destination_keepalive = _destination(size)
    try:
        result = check_dict(
            lib().mzs_train_dictionary(
                destination_address,
                size,
                source_address,
                ctypes.addressof(sample_sizes),
                len(sample_list),
            )
        )
    except LibraryError as exc:
        raise ZstdError(str(exc)) from exc
    _ = source_keepalive, destination_keepalive
    return ZstdCompressionDict(_bytes_prefix(destination, result))


def frame_header_size(data) -> int:
    source = as_bytes(data)
    if len(source) < 5:
        raise ZstdError("could not determine frame header size: source is too small")
    if source[:4] != MAGIC_NUMBER.to_bytes(4, "little"):
        raise ZstdError("could not determine frame header size: invalid magic number")
    descriptor = source[4]
    if descriptor & 0x08:
        raise ZstdError("could not determine frame header size: invalid descriptor")
    single_segment = bool(descriptor & 0x20)
    dictionary_sizes = (0, 1, 2, 4)
    dictionary_size = dictionary_sizes[descriptor & 3]
    content_flag = descriptor >> 6
    if content_flag == 0:
        content_size = 1 if single_segment else 0
    else:
        content_size = 1 << content_flag
    return 5 + (not single_segment) + dictionary_size + content_size


def get_frame_parameters(data) -> FrameParameters:
    source = as_bytes(data)
    if len(source) < 5:
        raise ZstdError("not enough data for frame parameters; need 5 bytes")
    header_size = frame_header_size(source)
    if len(source) < header_size:
        raise ZstdError(
            f"not enough data for frame parameters; need {header_size} bytes"
        )
    descriptor = source[4]
    single_segment = bool(descriptor & 0x20)
    content_flag = descriptor >> 6
    position = 5
    if single_segment:
        window_size = 0
    else:
        window_descriptor = source[position]
        position += 1
        exponent = window_descriptor >> 3
        mantissa = window_descriptor & 7
        window_base = 1 << (WINDOWLOG_MIN + exponent)
        window_size = window_base + (window_base >> 3) * mantissa
    dictionary_sizes = (0, 1, 2, 4)
    dictionary_size = dictionary_sizes[descriptor & 3]
    if dictionary_size:
        dict_id = int.from_bytes(
            source[position : position + dictionary_size], "little"
        )
        position += dictionary_size
    else:
        dict_id = 0
    if content_flag == 0:
        content_size_width = 1 if single_segment else 0
    else:
        content_size_width = 1 << content_flag
    if content_size_width:
        content_size = int.from_bytes(
            source[position : position + content_size_width], "little"
        )
        if content_size_width == 2:
            content_size += 256
    else:
        content_size = CONTENTSIZE_UNKNOWN
    if single_segment:
        window_size = content_size
    return FrameParameters(
        content_size=content_size,
        window_size=window_size,
        dict_id=dict_id,
        has_checksum=bool(descriptor & 4),
    )


def frame_content_size(data) -> int:
    source = as_buffer(data)
    address, size, keepalive = buffer_address(source)
    result = _unsigned(lib().mzs_frame_content_size(address, size))
    _ = keepalive
    if result == CONTENTSIZE_ERROR:
        raise ZstdError("error when determining content size")
    if result == CONTENTSIZE_UNKNOWN:
        return -1
    return result


class ZstdCompressor:
    def __init__(
        self,
        level=DEFAULT_COMPRESSION_LEVEL,
        dict_data=None,
        compression_params=None,
        write_checksum=False,
        write_content_size=True,
        write_dict_id=True,
        threads=0,
    ):
        if compression_params is not None:
            if level != DEFAULT_COMPRESSION_LEVEL:
                raise ValueError("cannot define compression_params and level")
            level = compression_params.compression_level
        self.level = int(level)
        self.dict_data = dict_data
        self.write_checksum = bool(write_checksum)
        self.write_content_size = bool(write_content_size)
        self.write_dict_id = bool(write_dict_id)
        self.threads = int(threads)
        if self.threads < 0:
            self.threads = 0
        try:
            self._context = CCtx(
                level=self.level,
                write_checksum=self.write_checksum,
                write_content_size=self.write_content_size,
                write_dict_id=self.write_dict_id,
                threads=self.threads,
                dictionary=self.dict_data,
            )
        except LibraryError as exc:
            raise ZstdError(str(exc)) from exc
        self._lock = threading.Lock()

    def _new_context(self, size=-1) -> CCtx:
        try:
            return CCtx(
                level=self.level,
                write_checksum=self.write_checksum,
                write_content_size=self.write_content_size,
                write_dict_id=self.write_dict_id,
                threads=self.threads,
                dictionary=self.dict_data,
                pledged_size=int(size),
            )
        except LibraryError as exc:
            raise ZstdError(str(exc)) from exc

    def compress(self, data) -> bytes:
        source = as_buffer(data)
        source_address, source_size, source_keepalive = buffer_address(source)
        status = ctypes.c_int64()
        with self._lock:
            try:
                destination = lib().mzs_compress_pybytes(
                    self._context.address,
                    source_address,
                    source_size,
                    ctypes.addressof(status),
                )
                if status.value < 0:
                    check(status.value, "compression")
            except LibraryError as exc:
                raise ZstdError(str(exc)) from exc
        _ = source_keepalive
        return destination

    def compressobj(self, size=-1):
        size = int(size)
        if size < -1:
            raise ValueError("size must be -1 or non-negative")
        return ZstdCompressionObj(self, size)

    def memory_size(self):
        return int(lib().mzs_cctx_size(self._context.address))

    def frame_progression(self):
        return (0, 0, 0)

    def stream_writer(
        self,
        writer,
        size=-1,
        write_size=COMPRESSION_RECOMMENDED_INPUT_SIZE,
        write_return_read=True,
        closefd=True,
    ):
        _ = write_size
        return _CompressionWriter(
            self,
            writer,
            int(size),
            bool(write_return_read),
            bool(closefd),
        )

    def stream_reader(
        self,
        source,
        size=-1,
        read_size=COMPRESSION_RECOMMENDED_INPUT_SIZE,
        closefd=True,
    ):
        raw, owner = _read_source(source)
        result = self.compress(raw)
        return _ResultReader(result, owner if closefd else None)

    def copy_stream(
        self,
        ifh,
        ofh,
        size=-1,
        read_size=COMPRESSION_RECOMMENDED_INPUT_SIZE,
        write_size=COMPRESSION_RECOMMENDED_INPUT_SIZE,
    ):
        _ = size, read_size, write_size
        source = ifh.read()
        encoded = self.compress(source)
        _write_all(ofh, encoded)
        return len(source), len(encoded)

    def read_to_iter(
        self,
        reader,
        size=-1,
        read_size=COMPRESSION_RECOMMENDED_INPUT_SIZE,
        write_size=COMPRESSION_RECOMMENDED_INPUT_SIZE,
    ):
        _ = size, read_size
        write_size = int(write_size)
        if write_size <= 0:
            raise ValueError("write_size must be positive")
        source, _ = _read_source(reader)
        encoded = self.compress(source)
        for position in range(0, len(encoded), write_size):
            yield encoded[position : position + write_size]


class ZstdCompressionObj:
    def __init__(self, compressor: ZstdCompressor, size: int):
        self._context = compressor._new_context(size)
        self._finished = False
        self._output_size = max(1, int(lib().mzs_cstream_out_size()))

    def compress(self, data) -> bytes:
        if self._finished:
            raise ZstdError("cannot call compress() after compressor finished")
        return self._run(as_buffer(data), 0, flushing=False)

    def flush(self, mode=COMPRESSOBJ_FLUSH_FINISH) -> bytes:
        if self._finished:
            raise ZstdError("compressor object already finished")
        if mode == COMPRESSOBJ_FLUSH_FINISH:
            directive = 2
            self._finished = True
        elif mode == COMPRESSOBJ_FLUSH_BLOCK:
            directive = 1
        else:
            raise ValueError("invalid flush mode")
        return self._run(b"", directive, flushing=True)

    def _run(self, source, directive: int, flushing: bool) -> bytes:
        source_address, source_size, source_keepalive = buffer_address(source)
        input_buffer = InBuffer(source_address, source_size, 0)
        parts = []
        while input_buffer.pos < input_buffer.size or flushing:
            destination, destination_address, destination_keepalive = _destination(
                self._output_size
            )
            output_buffer = OutBuffer(
                destination_address, self._output_size, 0
            )
            result = _zstd_call(
                lib().mzs_compress_stream,
                self._context.address,
                ctypes.addressof(output_buffer),
                ctypes.addressof(input_buffer),
                directive,
                operation="stream compression",
            )
            parts.append(_bytes_prefix(destination, output_buffer.pos))
            _ = destination_keepalive
            if flushing and result == 0:
                break
            if not flushing and input_buffer.pos == input_buffer.size:
                break
        _ = source_keepalive
        return b"".join(parts)


class ZstdDecompressor:
    def __init__(self, dict_data=None, max_window_size=0, format=FORMAT_ZSTD1):
        if int(format) != FORMAT_ZSTD1:
            raise NotImplementedError("FORMAT_ZSTD1_MAGICLESS is not supported")
        if int(max_window_size) != 0:
            raise NotImplementedError("max_window_size is not supported")
        self.dict_data = dict_data
        self.max_window_size = int(max_window_size)
        self.format = int(format)
        try:
            self._context = DCtx(dictionary=dict_data)
        except LibraryError as exc:
            raise ZstdError(str(exc)) from exc
        self._lock = threading.Lock()

    def _new_context(self):
        try:
            return DCtx(dictionary=self.dict_data)
        except LibraryError as exc:
            raise ZstdError(str(exc)) from exc

    def _decompress_frame(self, source, capacity: int) -> bytes:
        source_address, source_size, source_keepalive = buffer_address(source)
        destination, destination_address, destination_keepalive = _destination(
            capacity
        )
        with self._lock:
            result = _zstd_call(
                lib().mzs_decompress_dctx,
                self._context.address,
                destination_address,
                capacity,
                source_address,
                source_size,
                operation="decompression",
            )
        _ = source_keepalive, destination_keepalive
        return _bytes_prefix(destination, result)

    def _decompress_first(self, source, capacity: int) -> tuple[bytes, int]:
        source_address, source_size, source_keepalive = buffer_address(source)
        destination, destination_address, destination_keepalive = _destination(
            capacity
        )
        input_buffer = InBuffer(source_address, source_size, 0)
        output_buffer = OutBuffer(destination_address, capacity, 0)
        with self._lock:
            _zstd_call(
                lib().mzs_reset_dctx_session,
                self._context.address,
                operation="decompression context reset",
            )
            previous = (-1, -1)
            result = 1
            while result != 0:
                result = _zstd_call(
                    lib().mzs_decompress_stream,
                    self._context.address,
                    ctypes.addressof(output_buffer),
                    ctypes.addressof(input_buffer),
                    operation="decompression",
                )
                progress = (input_buffer.pos, output_buffer.pos)
                if result != 0 and progress == previous:
                    raise ZstdError(
                        "compressed input ended before the end-of-frame"
                    )
                previous = progress
        _ = source_keepalive, destination_keepalive
        return _bytes_prefix(destination, output_buffer.pos), input_buffer.pos

    def decompress(
        self,
        data,
        max_output_size=0,
        read_across_frames=False,
        allow_extra_data=True,
    ) -> bytes:
        source = as_buffer(data)
        maximum = int(max_output_size)
        if maximum < 0:
            raise ValueError("max_output_size must be non-negative")
        if not source:
            raise ZstdError("error determining content size from frame header")
        if not read_across_frames:
            content_size = frame_content_size(source)
            if content_size == -1:
                if maximum == 0:
                    raise ZstdError(
                        "could not determine content size in frame header"
                    )
                capacity = maximum
            else:
                capacity = content_size
            decoded, consumed = self._decompress_first(source, capacity)
            if not allow_extra_data and consumed != len(source):
                raise ZstdError("compressed input contains unused data")
            return decoded
        parts = []
        position = 0
        while position < len(source):
            frame = source[position:]
            span = _frame_size(frame)
            content_size = frame_content_size(frame[:span])
            if content_size == -1:
                if maximum == 0:
                    raise ZstdError(
                        "could not determine content size in frame header"
                    )
                capacity = maximum - sum(map(len, parts))
            else:
                capacity = content_size
            if capacity < 0:
                raise ZstdError("decompressed data exceeds max_output_size")
            parts.append(self._decompress_frame(frame[:span], capacity))
            position += span
            if not read_across_frames:
                if not allow_extra_data and position != len(source):
                    raise ZstdError("compressed input contains unused data")
                break
        if not parts:
            raise ZstdError("error determining content size from frame header")
        return b"".join(parts)

    def decompressobj(
        self,
        write_size=DECOMPRESSION_RECOMMENDED_INPUT_SIZE,
        read_across_frames=False,
    ):
        write_size = int(write_size)
        if write_size <= 0:
            raise ValueError("write_size must be positive")
        return ZstdDecompressionObj(self, write_size, bool(read_across_frames))

    def memory_size(self):
        return int(lib().mzs_dctx_size(self._context.address))

    def stream_reader(
        self,
        source,
        read_size=DECOMPRESSION_RECOMMENDED_INPUT_SIZE,
        read_across_frames=False,
        closefd=True,
    ):
        _ = read_size
        raw, owner = _read_source(source)
        obj = self.decompressobj(read_across_frames=read_across_frames)
        result = obj.decompress(raw) + obj.flush()
        if not obj.eof:
            raise ZstdError("compressed stream ended before the end-of-frame")
        return _ResultReader(result, owner if closefd else None)

    def stream_writer(
        self,
        writer,
        write_size=DECOMPRESSION_RECOMMENDED_INPUT_SIZE,
        write_return_read=True,
        closefd=True,
    ):
        return _DecompressionWriter(
            self,
            writer,
            int(write_size),
            bool(write_return_read),
            bool(closefd),
        )

    def copy_stream(
        self,
        ifh,
        ofh,
        read_size=DECOMPRESSION_RECOMMENDED_INPUT_SIZE,
        write_size=DECOMPRESSION_RECOMMENDED_INPUT_SIZE,
    ):
        _ = read_size, write_size
        source = ifh.read()
        obj = self.decompressobj(read_across_frames=True)
        decoded = obj.decompress(source)
        if not obj.eof:
            raise ZstdError("compressed stream ended before the end-of-frame")
        _write_all(ofh, decoded)
        return len(source), len(decoded)

    def read_to_iter(
        self,
        reader,
        read_size=DECOMPRESSION_RECOMMENDED_INPUT_SIZE,
        write_size=DECOMPRESSION_RECOMMENDED_INPUT_SIZE,
        skip_bytes=0,
        read_across_frames=False,
    ):
        _ = read_size
        write_size = int(write_size)
        skip_bytes = int(skip_bytes)
        if write_size <= 0:
            raise ValueError("write_size must be positive")
        if skip_bytes < 0:
            raise ValueError("skip_bytes must be non-negative")
        source, _ = _read_source(reader)
        source = source[skip_bytes:]
        obj = self.decompressobj(
            write_size=write_size, read_across_frames=read_across_frames
        )
        decoded = obj.decompress(source)
        if not obj.eof:
            raise ZstdError("compressed stream ended before the end-of-frame")
        for position in range(0, len(decoded), write_size):
            yield decoded[position : position + write_size]


class ZstdDecompressionObj:
    def __init__(
        self,
        decompressor: ZstdDecompressor,
        write_size: int,
        read_across_frames: bool,
    ):
        self._context = decompressor._new_context()
        self._output_size = max(
            1,
            write_size
            if write_size > 0
            else int(lib().mzs_dstream_out_size()),
        )
        self._read_across_frames = read_across_frames
        self.eof = False
        self.unused_data = b""
        self.unconsumed_tail = b""

    def decompress(self, data) -> bytes:
        if self.eof and not self._read_across_frames:
            raise ZstdError("cannot use a decompressobj after the frame is finished")
        source = as_buffer(data)
        source_address, source_size, source_keepalive = buffer_address(source)
        input_buffer = InBuffer(source_address, source_size, 0)
        parts = []
        result = 1
        while input_buffer.pos < input_buffer.size:
            destination, destination_address, destination_keepalive = _destination(
                self._output_size
            )
            output_buffer = OutBuffer(
                destination_address, self._output_size, 0
            )
            result = _zstd_call(
                lib().mzs_decompress_stream,
                self._context.address,
                ctypes.addressof(output_buffer),
                ctypes.addressof(input_buffer),
                operation="stream decompression",
            )
            parts.append(_bytes_prefix(destination, output_buffer.pos))
            _ = destination_keepalive
            if result == 0:
                self.eof = True
                if not self._read_across_frames:
                    self.unused_data = bytes(source[input_buffer.pos :])
                    break
                if input_buffer.pos < input_buffer.size:
                    self.eof = False
        _ = source_keepalive
        self.unconsumed_tail = b""
        return b"".join(parts)

    def flush(self, length=0) -> bytes:
        if length < 0:
            raise ValueError("length must be non-negative")
        return b""


def compress(data, level=DEFAULT_COMPRESSION_LEVEL) -> bytes:
    return ZstdCompressor(level=level).compress(data)


def decompress(data, max_output_size=0) -> bytes:
    return ZstdDecompressor().decompress(data, max_output_size=max_output_size)


def _read_source(source) -> tuple[bytes, object | None]:
    if hasattr(source, "read"):
        return as_bytes(source.read()), source
    return as_bytes(source), None


def _write_all(writer, data: bytes) -> None:
    if not data:
        return
    written = writer.write(data)
    if written is not None and written != len(data):
        raise ZstdError(
            f"destination accepted {written} of {len(data)} output bytes"
        )


class _ResultReader(io.BytesIO):
    def __init__(self, data: bytes, owner=None):
        super().__init__(data)
        self._owner = owner

    def close(self):
        if not self.closed:
            super().close()
            if self._owner is not None:
                self._owner.close()


class _CompressionWriter(io.BufferedIOBase):
    def __init__(
        self,
        compressor,
        writer,
        size,
        write_return_read,
        closefd,
    ):
        self._writer = writer
        self._object = compressor.compressobj(size=size)
        self._write_return_read = write_return_read
        self._closefd = closefd

    def writable(self):
        return True

    def write(self, data):
        source = as_buffer(data)
        encoded = self._object.compress(source)
        _write_all(self._writer, encoded)
        return len(source) if self._write_return_read else len(encoded)

    def flush(self, mode=FLUSH_BLOCK):
        if self.closed:
            raise ValueError("flush of closed stream")
        if mode not in (FLUSH_BLOCK, FLUSH_FRAME):
            raise ValueError("invalid flush mode")
        if not self._object._finished:
            directive = (
                COMPRESSOBJ_FLUSH_FINISH
                if mode == FLUSH_FRAME
                else COMPRESSOBJ_FLUSH_BLOCK
            )
            encoded = self._object.flush(directive)
            _write_all(self._writer, encoded)
        if hasattr(self._writer, "flush"):
            self._writer.flush()

    def close(self):
        if self.closed:
            return
        try:
            if not self._object._finished:
                _write_all(
                    self._writer, self._object.flush(COMPRESSOBJ_FLUSH_FINISH)
                )
            if hasattr(self._writer, "flush"):
                self._writer.flush()
        finally:
            super().close()
            if self._closefd:
                self._writer.close()


class _DecompressionWriter(io.BufferedIOBase):
    def __init__(
        self,
        decompressor,
        writer,
        write_size,
        write_return_read,
        closefd,
    ):
        self._writer = writer
        self._object = decompressor.decompressobj(
            write_size=write_size, read_across_frames=True
        )
        self._write_return_read = write_return_read
        self._closefd = closefd

    def writable(self):
        return True

    def write(self, data):
        source = as_buffer(data)
        decoded = self._object.decompress(source)
        _write_all(self._writer, decoded)
        return len(source) if self._write_return_read else len(decoded)

    def flush(self):
        if hasattr(self._writer, "flush"):
            self._writer.flush()

    def close(self):
        if self.closed:
            return
        if not self._object.eof:
            super().close()
            if self._closefd:
                self._writer.close()
            raise ZstdError("compressed stream ended before the end-of-frame")
        if hasattr(self._writer, "flush"):
            self._writer.flush()
        super().close()
        if self._closefd:
            self._writer.close()
