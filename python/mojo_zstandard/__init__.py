"""Zstandard compression through Mojo and libzstd."""

from .backend import (
    BLOCKSIZELOG_MAX,
    BLOCKSIZE_MAX,
    COMPRESSION_RECOMMENDED_INPUT_SIZE,
    COMPRESSOBJ_FLUSH_BLOCK,
    COMPRESSOBJ_FLUSH_FINISH,
    CONTENTSIZE_ERROR,
    CONTENTSIZE_UNKNOWN,
    DEFAULT_COMPRESSION_LEVEL,
    DECOMPRESSION_RECOMMENDED_INPUT_SIZE,
    DICT_TYPE_AUTO,
    DICT_TYPE_FULLDICT,
    DICT_TYPE_RAWCONTENT,
    FLUSH_BLOCK,
    FLUSH_FRAME,
    FORMAT_ZSTD1,
    FORMAT_ZSTD1_MAGICLESS,
    MAGIC_NUMBER,
    MAX_COMPRESSION_LEVEL,
    MIN_COMPRESSION_LEVEL,
    WINDOWLOG_MAX,
    WINDOWLOG_MIN,
    FrameParameters,
    ZstdCompressionDict,
    ZstdCompressionObj,
    ZstdCompressionParameters,
    ZstdCompressor,
    ZstdDecompressionObj,
    ZstdDecompressor,
    ZstdError,
    compress,
    decompress,
    frame_content_size,
    frame_header_size,
    get_frame_parameters,
    train_dictionary,
)
from ._lib import lib

__version__ = "0.1.0"
backend = "mojo-libzstd"
_version_number = int(lib().mzs_version_number())
ZSTD_VERSION = (
    _version_number // 10000,
    (_version_number // 100) % 100,
    _version_number % 100,
)

COMPRESSION_RECOMMENDED_OUTPUT_SIZE = int(lib().mzs_cstream_out_size())
DECOMPRESSION_RECOMMENDED_OUTPUT_SIZE = int(lib().mzs_dstream_out_size())

__all__ = [name for name in globals() if not name.startswith("_")]
