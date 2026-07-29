"""Libzstd bindings exposed through a stable C ABI for Python."""

from std.ffi import external_call


@always_inline
def is_error(code: Int) -> Bool:
    return external_call["ZSTD_isError", Int](code) != 0


@always_inline
def configure_cctx(
    context: Int,
    level: Int,
    write_checksum: Int,
    write_content_size: Int,
    write_dict_id: Int,
    threads: Int,
    dictionary: Int,
    dictionary_size: Int,
    pledged_size: Int,
) -> Int:
    var result = external_call["ZSTD_CCtx_reset", Int](context, Int(3))
    if is_error(result):
        return result
    result = external_call["ZSTD_CCtx_setParameter", Int](
        context, Int(100), level
    )
    if is_error(result):
        return result
    result = external_call["ZSTD_CCtx_setParameter", Int](
        context, Int(200), write_content_size
    )
    if is_error(result):
        return result
    result = external_call["ZSTD_CCtx_setParameter", Int](
        context, Int(201), write_checksum
    )
    if is_error(result):
        return result
    result = external_call["ZSTD_CCtx_setParameter", Int](
        context, Int(202), write_dict_id
    )
    if is_error(result):
        return result
    if threads != 0:
        result = external_call["ZSTD_CCtx_setParameter", Int](
            context, Int(400), threads
        )
        if is_error(result):
            return result
    result = external_call["ZSTD_CCtx_loadDictionary", Int](
        context, dictionary, dictionary_size
    )
    if is_error(result):
        return result
    return external_call["ZSTD_CCtx_setPledgedSrcSize", Int](
        context, pledged_size
    )


@export("mzs_version_number")
def mzs_version_number() abi("C") -> Int:
    return external_call["ZSTD_versionNumber", Int]()


@export("mzs_compress_bound")
def mzs_compress_bound(size: Int) abi("C") -> Int:
    return external_call["ZSTD_compressBound", Int](size)


@export("mzs_is_error")
def mzs_is_error(code: Int) abi("C") -> Int:
    return 1 if is_error(code) else 0


@export("mzs_error_code")
def mzs_error_code(code: Int) abi("C") -> Int:
    return external_call["ZSTD_getErrorCode", Int](code)


@export("mzs_create_cctx")
def mzs_create_cctx() abi("C") -> Int:
    return external_call["ZSTD_createCCtx", Int]()


@export("mzs_free_cctx")
def mzs_free_cctx(context: Int) abi("C") -> Int:
    return external_call["ZSTD_freeCCtx", Int](context)


@export("mzs_configure_cctx")
def mzs_configure_cctx(
    context: Int,
    level: Int,
    write_checksum: Int,
    write_content_size: Int,
    write_dict_id: Int,
    threads: Int,
    dictionary: Int,
    dictionary_size: Int,
    pledged_size: Int,
) abi("C") -> Int:
    return configure_cctx(
        context,
        level,
        write_checksum,
        write_content_size,
        write_dict_id,
        threads,
        dictionary,
        dictionary_size,
        pledged_size,
    )


@export("mzs_compress_cctx")
def mzs_compress_cctx(
    context: Int,
    dst: Int,
    dst_capacity: Int,
    src: Int,
    src_size: Int,
) abi("C") -> Int:
    return external_call["ZSTD_compress2", Int](
        context, dst, dst_capacity, src, src_size
    )


@export("mzs_reset_cctx_session")
def mzs_reset_cctx_session(context: Int, pledged_size: Int) abi("C") -> Int:
    var result = external_call["ZSTD_CCtx_reset", Int](context, Int(1))
    if is_error(result):
        return result
    return external_call["ZSTD_CCtx_setPledgedSrcSize", Int](
        context, pledged_size
    )


@export("mzs_compress_stream")
def mzs_compress_stream(
    context: Int,
    output_buffer: Int,
    input_buffer: Int,
    directive: Int,
) abi("C") -> Int:
    return external_call["ZSTD_compressStream2", Int](
        context, output_buffer, input_buffer, directive
    )


@export("mzs_cctx_size")
def mzs_cctx_size(context: Int) abi("C") -> Int:
    return external_call["ZSTD_sizeof_CCtx", Int](context)


@export("mzs_create_dctx")
def mzs_create_dctx() abi("C") -> Int:
    return external_call["ZSTD_createDCtx", Int]()


@export("mzs_free_dctx")
def mzs_free_dctx(context: Int) abi("C") -> Int:
    return external_call["ZSTD_freeDCtx", Int](context)


@export("mzs_configure_dctx")
def mzs_configure_dctx(
    context: Int,
    dictionary: Int,
    dictionary_size: Int,
) abi("C") -> Int:
    var result = external_call["ZSTD_DCtx_reset", Int](context, Int(3))
    if is_error(result):
        return result
    return external_call["ZSTD_DCtx_loadDictionary", Int](
        context, dictionary, dictionary_size
    )


@export("mzs_decompress_dctx")
def mzs_decompress_dctx(
    context: Int,
    dst: Int,
    dst_capacity: Int,
    src: Int,
    src_size: Int,
) abi("C") -> Int:
    return external_call["ZSTD_decompressDCtx", Int](
        context, dst, dst_capacity, src, src_size
    )


@export("mzs_reset_dctx_session")
def mzs_reset_dctx_session(context: Int) abi("C") -> Int:
    return external_call["ZSTD_DCtx_reset", Int](context, Int(1))


@export("mzs_decompress_stream")
def mzs_decompress_stream(
    context: Int,
    output_buffer: Int,
    input_buffer: Int,
) abi("C") -> Int:
    return external_call["ZSTD_decompressStream", Int](
        context, output_buffer, input_buffer
    )


@export("mzs_dctx_size")
def mzs_dctx_size(context: Int) abi("C") -> Int:
    return external_call["ZSTD_sizeof_DCtx", Int](context)


@export("mzs_frame_content_size")
def mzs_frame_content_size(src: Int, src_size: Int) abi("C") -> Int:
    return external_call["ZSTD_getFrameContentSize", Int](src, src_size)


@export("mzs_find_frame_size")
def mzs_find_frame_size(src: Int, src_size: Int) abi("C") -> Int:
    return external_call["ZSTD_findFrameCompressedSize", Int](src, src_size)


@export("mzs_dict_id_from_frame")
def mzs_dict_id_from_frame(src: Int, src_size: Int) abi("C") -> Int:
    return external_call["ZSTD_getDictID_fromFrame", Int](src, src_size)


@export("mzs_dict_id_from_dict")
def mzs_dict_id_from_dict(src: Int, src_size: Int) abi("C") -> Int:
    return external_call["ZSTD_getDictID_fromDict", Int](src, src_size)


@export("mzs_cstream_out_size")
def mzs_cstream_out_size() abi("C") -> Int:
    return external_call["ZSTD_CStreamOutSize", Int]()


@export("mzs_dstream_out_size")
def mzs_dstream_out_size() abi("C") -> Int:
    return external_call["ZSTD_DStreamOutSize", Int]()


@export("mzs_train_dictionary")
def mzs_train_dictionary(
    destination: Int,
    destination_capacity: Int,
    samples: Int,
    sample_sizes: Int,
    sample_count: Int,
) abi("C") -> Int:
    return external_call["ZDICT_trainFromBuffer", Int](
        destination,
        destination_capacity,
        samples,
        sample_sizes,
        sample_count,
    )


@export("mzs_dict_is_error")
def mzs_dict_is_error(code: Int) abi("C") -> Int:
    return external_call["ZDICT_isError", Int](code)
