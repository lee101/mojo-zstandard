"""ctypes bridge to the Mojo zstandard bindings."""

from __future__ import annotations

import ctypes
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIB_PATH = os.path.join(ROOT, "dist", "libmojo-zstandard.so")

I = ctypes.c_int64
_SIGNATURES = {
    "mzs_version_number": ([], I),
    "mzs_compress_bound": ([I], I),
    "mzs_is_error": ([I], I),
    "mzs_error_code": ([I], I),
    "mzs_create_cctx": ([], I),
    "mzs_free_cctx": ([I], I),
    "mzs_configure_cctx": ([I] * 9, I),
    "mzs_compress_cctx": ([I] * 5, I),
    "mzs_compress_pybytes": ([I] * 4, ctypes.py_object),
    "mzs_reset_cctx_session": ([I, I], I),
    "mzs_compress_stream": ([I, I, I, I], I),
    "mzs_cctx_size": ([I], I),
    "mzs_create_dctx": ([], I),
    "mzs_free_dctx": ([I], I),
    "mzs_configure_dctx": ([I, I, I], I),
    "mzs_decompress_dctx": ([I] * 5, I),
    "mzs_reset_dctx_session": ([I], I),
    "mzs_decompress_stream": ([I, I, I], I),
    "mzs_dctx_size": ([I], I),
    "mzs_frame_content_size": ([I, I], I),
    "mzs_find_frame_size": ([I, I], I),
    "mzs_dict_id_from_frame": ([I, I], I),
    "mzs_dict_id_from_dict": ([I, I], I),
    "mzs_cstream_out_size": ([], I),
    "mzs_dstream_out_size": ([], I),
    "mzs_train_dictionary": ([I] * 5, I),
    "mzs_dict_is_error": ([I], I),
}


class LibraryError(RuntimeError):
    pass


class InBuffer(ctypes.Structure):
    _fields_ = [
        ("src", ctypes.c_void_p),
        ("size", ctypes.c_size_t),
        ("pos", ctypes.c_size_t),
    ]


class OutBuffer(ctypes.Structure):
    _fields_ = [
        ("dst", ctypes.c_void_p),
        ("size", ctypes.c_size_t),
        ("pos", ctypes.c_size_t),
    ]


_library: ctypes.CDLL | None = None
_py_bytes_new = ctypes.pythonapi.PyBytes_FromStringAndSize
_py_bytes_new.argtypes = [ctypes.c_void_p, ctypes.c_ssize_t]
_py_bytes_new.restype = ctypes.py_object
_py_bytes_address = ctypes.pythonapi.PyBytes_AsString
_py_bytes_address.argtypes = [ctypes.py_object]
_py_bytes_address.restype = ctypes.c_void_p


class _PyBuffer(ctypes.Structure):
    _fields_ = [
        ("buf", ctypes.c_void_p),
        ("obj", ctypes.c_void_p),
        ("len", ctypes.c_ssize_t),
        ("itemsize", ctypes.c_ssize_t),
        ("readonly", ctypes.c_int),
        ("ndim", ctypes.c_int),
        ("format", ctypes.c_char_p),
        ("shape", ctypes.POINTER(ctypes.c_ssize_t)),
        ("strides", ctypes.POINTER(ctypes.c_ssize_t)),
        ("suboffsets", ctypes.POINTER(ctypes.c_ssize_t)),
        ("internal", ctypes.c_void_p),
    ]


_py_object_get_buffer = ctypes.pythonapi.PyObject_GetBuffer
_py_object_get_buffer.argtypes = [
    ctypes.py_object,
    ctypes.POINTER(_PyBuffer),
    ctypes.c_int,
]
_py_object_get_buffer.restype = ctypes.c_int
_py_buffer_release = ctypes.pythonapi.PyBuffer_Release
_py_buffer_release.argtypes = [ctypes.POINTER(_PyBuffer)]
_py_buffer_release.restype = None


class _PinnedBuffer:
    def __init__(self, data):
        self.active = False
        self.view = _PyBuffer()
        _py_object_get_buffer(data, ctypes.byref(self.view), 0)
        self.active = True

    def close(self) -> None:
        if self.active:
            self.active = False
            _py_buffer_release(ctypes.byref(self.view))

    def __del__(self):
        self.close()


def lib() -> ctypes.CDLL:
    global _library
    if _library is None:
        if not os.path.exists(LIB_PATH):
            raise LibraryError("shared library is missing; run `pixi run build`")
        _library = ctypes.CDLL(LIB_PATH)
        for name, (argtypes, restype) in _SIGNATURES.items():
            function = getattr(_library, name)
            function.argtypes = argtypes
            function.restype = restype
    return _library


def as_bytes(data) -> bytes:
    if isinstance(data, bytes):
        return data
    try:
        view = memoryview(data)
    except TypeError as exc:
        raise TypeError("a bytes-like object is required") from exc
    if not view.c_contiguous:
        raise BufferError("source buffer is not C-contiguous")
    return view.cast("B").tobytes()


def as_buffer(data):
    if isinstance(data, bytes):
        return data
    try:
        view = memoryview(data)
    except TypeError as exc:
        raise TypeError("a bytes-like object is required") from exc
    if not view.c_contiguous:
        raise BufferError("source buffer is not C-contiguous")
    return view.cast("B")


def buffer_address(data) -> tuple[int, int, object]:
    if isinstance(data, bytes):
        return int(_py_bytes_address(data)), len(data), data
    view = as_buffer(data)
    keepalive = _PinnedBuffer(view)
    return int(keepalive.view.buf or 0), keepalive.view.len, keepalive


def bytearray_address(data: bytearray) -> tuple[int, object]:
    if not data:
        raise ValueError("cannot take the address of an empty bytearray")
    keepalive = ctypes.c_ubyte.from_buffer(data)
    return ctypes.addressof(keepalive), keepalive


def writable_bytes(capacity: int) -> tuple[bytes, int]:
    data = _py_bytes_new(None, max(1, capacity))
    return data, int(_py_bytes_address(data))


def check(code: int, operation: str = "zstd operation") -> int:
    if lib().mzs_is_error(code):
        error_code = int(lib().mzs_error_code(code))
        raise LibraryError(f"{operation} failed (libzstd error {error_code})")
    return int(code)


def check_dict(code: int, operation: str = "dictionary training") -> int:
    if lib().mzs_dict_is_error(code):
        raise LibraryError(f"{operation} failed (libzstd error result {code})")
    return int(code)


def dict_bytes(dictionary) -> bytes:
    if dictionary is None:
        return b""
    if hasattr(dictionary, "as_bytes"):
        return dictionary.as_bytes()
    raise TypeError("dict_data must be a ZstdCompressionDict")


class CCtx:
    def __init__(
        self,
        *,
        level: int,
        write_checksum: bool,
        write_content_size: bool,
        write_dict_id: bool,
        threads: int,
        dictionary,
        pledged_size: int = -1,
    ):
        self.address = int(lib().mzs_create_cctx())
        if not self.address:
            raise MemoryError("unable to allocate a zstd compression context")
        self._dictionary = dict_bytes(dictionary)
        dictionary_address, dictionary_size, keepalive = buffer_address(
            self._dictionary
        )
        try:
            check(
                lib().mzs_configure_cctx(
                    self.address,
                    int(level),
                    int(bool(write_checksum)),
                    int(bool(write_content_size)),
                    int(bool(write_dict_id)),
                    int(threads),
                    dictionary_address if dictionary_size else 0,
                    dictionary_size,
                    int(pledged_size),
                ),
                "compression context configuration",
            )
        except BaseException:
            self.close()
            raise
        finally:
            _ = keepalive

    def reset(self, pledged_size: int) -> None:
        check(
            lib().mzs_reset_cctx_session(self.address, int(pledged_size)),
            "compression context reset",
        )

    def close(self) -> None:
        address, self.address = getattr(self, "address", 0), 0
        if address:
            lib().mzs_free_cctx(address)

    def __del__(self):
        self.close()


class DCtx:
    def __init__(self, *, dictionary=None):
        self.address = int(lib().mzs_create_dctx())
        if not self.address:
            raise MemoryError("unable to allocate a zstd decompression context")
        self._dictionary = dict_bytes(dictionary)
        dictionary_address, dictionary_size, keepalive = buffer_address(
            self._dictionary
        )
        try:
            check(
                lib().mzs_configure_dctx(
                    self.address,
                    dictionary_address if dictionary_size else 0,
                    dictionary_size,
                ),
                "decompression context configuration",
            )
        except BaseException:
            self.close()
            raise
        finally:
            _ = keepalive

    def close(self) -> None:
        address, self.address = getattr(self, "address", 0), 0
        if address:
            lib().mzs_free_dctx(address)

    def __del__(self):
        self.close()
