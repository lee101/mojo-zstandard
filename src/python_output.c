#include <Python.h>
#include <stdint.h>
#include <zstd.h>

PyObject *mzs_compress_pybytes(
    int64_t context_address,
    int64_t source_address,
    int64_t source_size,
    int64_t status_address
) {
    ZSTD_CCtx *context = (ZSTD_CCtx *)(uintptr_t)context_address;
    const void *source = (const void *)(uintptr_t)source_address;
    int64_t *status = (int64_t *)(uintptr_t)status_address;
    size_t capacity = ZSTD_compressBound((size_t)source_size);
    PyGILState_STATE gil = PyGILState_Ensure();
    PyObject *result = PyBytes_FromStringAndSize(NULL, (Py_ssize_t)capacity);
    char *destination = result == NULL ? NULL : PyBytes_AS_STRING(result);
    PyGILState_Release(gil);
    if (result == NULL) {
        return NULL;
    }

    size_t written = ZSTD_compress2(
        context,
        destination,
        capacity,
        source,
        (size_t)source_size
    );
    *status = (int64_t)written;

    gil = PyGILState_Ensure();
    if (ZSTD_isError(written)) {
        Py_DECREF(result);
        result = Py_NewRef(Py_None);
    } else if (_PyBytes_Resize(&result, (Py_ssize_t)written) != 0) {
        result = NULL;
    }
    PyGILState_Release(gil);
    return result;
}
