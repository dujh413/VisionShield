"""Owned, lazy OpenCL box filter; only explicit GPU kernel execution succeeds.

No OpenCL Python package or vendor runtime is bundled: the installed display
driver supplies OpenCL. One worker thread owns an instance and must close it.
Transient image buffers are released after every call, including failure paths.
"""
import ctypes as ct
import ctypes.util
import os
import sys
import threading

import numpy as np


MAX_GPU_RADIUS = 128
_GPU = 1 << 2
_PROFILING = 1 << 1
_MEM_READ_WRITE = 1
_MEM_WRITE_ONLY = 1 << 1
_MEM_READ_ONLY = 1 << 2
_MEM_COPY_HOST_PTR = 1 << 5
_SUCCESS = 0
_DEVICE_NOT_FOUND = -1

_SOURCE = r"""
__kernel void horizontal(__global const uchar *input, __global uint *sums,
                         int width, int height, int radius) {
    size_t id = get_global_id(0);
    size_t count = (size_t)width * height * 3;
    if (id >= count) return;
    int channel = id % 3;
    int x = (id / 3) % width;
    size_t row = (id / ((size_t)width * 3)) * (size_t)width * 3;
    uint total = 0;
    for (int offset = -radius; offset <= radius; ++offset) {
        int sample_x = clamp(x + offset, 0, width - 1);
        total += input[row + (size_t)sample_x * 3 + channel];
    }
    sums[id] = total;
}

__kernel void vertical(__global const uint *sums, __global uchar *output,
                       int width, int height, int radius) {
    size_t id = get_global_id(0);
    size_t count = (size_t)width * height * 3;
    if (id >= count) return;
    int channel = id % 3;
    int x = (id / 3) % width;
    int y = id / ((size_t)width * 3);
    uint total = 0;
    for (int offset = -radius; offset <= radius; ++offset) {
        int sample_y = clamp(y + offset, 0, height - 1);
        total += sums[((size_t)sample_y * width + x) * 3 + channel];
    }
    uint side = 2 * radius + 1;
    uint area = side * side;
    // Odd area cannot produce a halfway tie; exact integer rounding also avoids
    // different float precision on integrated and discrete GPUs.
    output[(id / 3) * 3 + 2 - channel] = (uchar)((total + area / 2) / area);
}
"""


class OpenClUnavailable(RuntimeError):
    """The GPU filter is unavailable; callers may use the CPU implementation."""


class OpenClError(RuntimeError):
    """A stage/status-only error, without image pixels or OpenCL build output."""


def _check(status, stage):
    if status != _SUCCESS:
        raise OpenClError(f'{stage}: OpenCL status {status}')


def _load_api():
    try:
        if os.name == 'nt':
            system_root = os.environ.get('SystemRoot', r'C:\Windows')
            library = ct.WinDLL(os.path.join(system_root, 'System32', 'OpenCL.dll'))
        else:
            path = ct.util.find_library('OpenCL')
            if not path:
                raise OSError('missing driver')
            library = ct.CDLL(path)
    except OSError as exc:
        raise OpenClUnavailable('OpenCL display driver unavailable') from exc
    pointer = ct.c_void_p
    uint = ct.c_uint32
    integer = ct.c_int32
    size = ct.c_size_t
    ulong = ct.c_uint64
    signatures = {
        'clGetPlatformIDs': (integer, [uint, ct.POINTER(pointer), ct.POINTER(uint)]),
        'clGetDeviceIDs': (integer, [pointer, ulong, uint, ct.POINTER(pointer), ct.POINTER(uint)]),
        'clGetDeviceInfo': (integer, [pointer, uint, size, pointer, ct.POINTER(size)]),
        'clCreateContext': (pointer, [pointer, uint, ct.POINTER(pointer), pointer, pointer, ct.POINTER(integer)]),
        'clCreateCommandQueue': (pointer, [pointer, pointer, ulong, ct.POINTER(integer)]),
        'clCreateProgramWithSource': (pointer, [pointer, uint, ct.POINTER(ct.c_char_p), ct.POINTER(size), ct.POINTER(integer)]),
        'clBuildProgram': (integer, [pointer, uint, ct.POINTER(pointer), ct.c_char_p, pointer, pointer]),
        'clCreateKernel': (pointer, [pointer, ct.c_char_p, ct.POINTER(integer)]),
        'clCreateBuffer': (pointer, [pointer, ulong, size, pointer, ct.POINTER(integer)]),
        'clSetKernelArg': (integer, [pointer, uint, size, pointer]),
        'clEnqueueNDRangeKernel': (integer, [pointer, pointer, uint, ct.POINTER(size), ct.POINTER(size), ct.POINTER(size), uint, pointer, ct.POINTER(pointer)]),
        'clEnqueueReadBuffer': (integer, [pointer, pointer, uint, size, size, pointer, uint, pointer, ct.POINTER(pointer)]),
        'clGetEventProfilingInfo': (integer, [pointer, uint, size, pointer, ct.POINTER(size)]),
        'clFinish': (integer, [pointer]),
    }
    for resource in ('MemObject', 'Event', 'Kernel', 'Program', 'CommandQueue', 'Context'):
        signatures['clRelease' + resource] = (integer, [pointer])
    try:
        for name, (restype, argtypes) in signatures.items():
            function = getattr(library, name)
            function.restype = restype
            function.argtypes = argtypes
    except AttributeError as exc:
        raise OpenClUnavailable('OpenCL 1.2 entry points unavailable') from exc
    return library


def _device_info(api, device, name, value_type=None):
    length = ct.c_size_t()
    _check(api.clGetDeviceInfo(device, name, 0, None, ct.byref(length)), 'device query')
    if value_type is None:
        value = ct.create_string_buffer(length.value)
        _check(api.clGetDeviceInfo(device, name, length.value, value, None), 'device query')
        return value.value.decode('utf-8', errors='replace')
    value = value_type()
    _check(api.clGetDeviceInfo(device, name, ct.sizeof(value), ct.byref(value), None), 'device query')
    return value.value


def _select_device(api):
    count = ct.c_uint32()
    status = api.clGetPlatformIDs(0, None, ct.byref(count))
    if status == -1001 or not count.value:
        raise OpenClUnavailable('No OpenCL platform')
    _check(status, 'platform query')
    platforms = (ct.c_void_p * count.value)()
    _check(api.clGetPlatformIDs(count.value, platforms, None), 'platform query')
    candidates = []
    for platform in platforms:
        count = ct.c_uint32()
        status = api.clGetDeviceIDs(platform, _GPU, 0, None, ct.byref(count))
        if status == _DEVICE_NOT_FOUND:
            continue
        _check(status, 'GPU query')
        devices = (ct.c_void_p * count.value)()
        _check(api.clGetDeviceIDs(platform, _GPU, count.value, devices, None), 'GPU query')
        for device in devices:
            if not _device_info(api, device, 0x1027, ct.c_uint32):  # AVAILABLE
                continue
            if not _device_info(api, device, 0x1028, ct.c_uint32):  # COMPILER_AVAILABLE
                continue
            name = _device_info(api, device, 0x102B)  # NAME
            vendor = _device_info(api, device, 0x102C)  # VENDOR
            unified = _device_info(api, device, 0x1035, ct.c_uint32)
            memory = _device_info(api, device, 0x101F, ct.c_uint64)
            candidates.append(((not unified, 'NVIDIA' in vendor.upper(), memory), device, name))
    if not candidates:
        raise OpenClUnavailable('No available OpenCL GPU')
    _, device, name = max(candidates, key=lambda item: item[0])
    return device, name


class OpenClBoxBlur:
    """One-thread GPU renderer; create lazily, reuse kernels, close explicitly."""

    def __init__(self):
        self._owner = threading.get_ident()
        self._api = None
        self._context = self._queue = self._program = None
        self._kernels = []
        self._pending_buffers = []
        self._pending_events = []
        self._closed = False
        self._released = False
        self.device = ''
        self.last_gpu_ms = 0.0
        self.last_kernel_events = 0
        try:
            self._api = _load_api()
            device, self.device = _select_device(self._api)
            selected = (ct.c_void_p * 1)(device)
            status = ct.c_int32()
            self._context = self._api.clCreateContext(None, 1, selected, None, None, ct.byref(status))
            _check(status.value, 'context creation')
            self._queue = self._api.clCreateCommandQueue(self._context, device, _PROFILING, ct.byref(status))
            _check(status.value, 'queue creation')
            source = _SOURCE.encode('ascii')
            strings = (ct.c_char_p * 1)(source)
            sizes = (ct.c_size_t * 1)(len(source))
            self._program = self._api.clCreateProgramWithSource(self._context, 1, strings, sizes, ct.byref(status))
            _check(status.value, 'program creation')
            _check(self._api.clBuildProgram(self._program, 1, selected, b'-cl-std=CL1.2', None, None), 'program compilation')
            for name in (b'horizontal', b'vertical'):
                kernel = self._api.clCreateKernel(self._program, name, ct.byref(status))
                _check(status.value, 'kernel creation')
                self._kernels.append(kernel)
        except Exception as original_error:
            try:
                self.close()
            except OpenClError as cleanup_error:
                raise original_error from cleanup_error
            raise

    @staticmethod
    def supports(image, radius):
        return (type(radius) is int and 1 <= radius <= MAX_GPU_RADIUS
                and isinstance(image, np.ndarray) and image.dtype == np.uint8
                and image.ndim == 3 and image.shape[2] == 3 and image.size > 0
                and image.shape[0] < 2 ** 31 - MAX_GPU_RADIUS
                and image.shape[1] < 2 ** 31 - MAX_GPU_RADIUS)

    def _assert_owner(self):
        if threading.get_ident() != self._owner:
            raise RuntimeError('OpenCL renderer must stay on its owner thread')
        if self._closed:
            raise RuntimeError('OpenCL renderer is closed')

    def blur_bgr(self, image, radius):
        self._assert_owner()
        if not self.supports(image, radius):
            raise ValueError('Unsupported GPU box image or radius')
        # COPY_HOST_PTR takes an owned snapshot; never mutate the caller's data.
        source = np.ascontiguousarray(image)
        output = np.empty_like(source)
        height, width, _ = source.shape
        count = source.size
        buffers = []
        events = []
        submitted = False
        self.last_gpu_ms = 0.0
        self.last_kernel_events = 0
        status = ct.c_int32()
        api = self._api
        try:
            for flags, size, host in (
                (_MEM_READ_ONLY | _MEM_COPY_HOST_PTR, count, source.ctypes.data),
                (_MEM_READ_WRITE, count * 4, None),
                (_MEM_WRITE_ONLY, count, None),
            ):
                buffer = api.clCreateBuffer(self._context, flags, size, host, ct.byref(status))
                _check(status.value, 'buffer allocation')
                buffers.append(buffer)
            for index, kernel in enumerate(self._kernels):
                arguments = (ct.c_void_p(buffers[index]), ct.c_void_p(buffers[index + 1]),
                             ct.c_int32(width), ct.c_int32(height), ct.c_int32(radius))
                for position, value in enumerate(arguments):
                    _check(api.clSetKernelArg(kernel, position, ct.sizeof(value), ct.byref(value)), 'kernel argument')
                global_size = (ct.c_size_t * 1)(count)
                event = ct.c_void_p()
                _check(api.clEnqueueNDRangeKernel(self._queue, kernel, 1, None, global_size, None,
                                                0, None, ct.byref(event)), 'kernel submission')
                submitted = True
                events.append(event)
            _check(api.clEnqueueReadBuffer(self._queue, buffers[2], 1, 0, count,
                                          output.ctypes.data, 0, None, None), 'result download')
            _check(api.clFinish(self._queue), 'GPU completion')
            nanoseconds = 0
            for event in events:
                start, end = ct.c_uint64(), ct.c_uint64()
                _check(api.clGetEventProfilingInfo(event, 0x1282, ct.sizeof(start), ct.byref(start), None), 'kernel start profiling')
                _check(api.clGetEventProfilingInfo(event, 0x1283, ct.sizeof(end), ct.byref(end), None), 'kernel end profiling')
                if end.value < start.value:
                    raise OpenClError('Invalid GPU kernel timestamps')
                nanoseconds += end.value - start.value
            self.last_gpu_ms = nanoseconds / 1_000_000
            self.last_kernel_events = len(events)
            return output
        finally:
            # Wait before releasing buffers even if submission/read/profiling fails.
            original_error = sys.exc_info()[1]
            cleanup_error = None
            if submitted:
                finish_status = api.clFinish(self._queue)
                if finish_status != _SUCCESS:
                    cleanup_error = OpenClError(f'GPU cleanup completion: OpenCL status {finish_status}')
            for event in reversed(events):
                release_status = api.clReleaseEvent(event)
                if release_status != _SUCCESS:
                    self._pending_events.append(event)
                    cleanup_error = cleanup_error or OpenClError(
                        f'event release: OpenCL status {release_status}')
            for buffer in reversed(buffers):
                release_status = api.clReleaseMemObject(buffer)
                if release_status != _SUCCESS:
                    self._pending_buffers.append(buffer)
                    cleanup_error = cleanup_error or OpenClError(
                        f'image buffer release: OpenCL status {release_status}')
            if cleanup_error:
                self._closed = True
                self.last_gpu_ms = 0.0
                self.last_kernel_events = 0
                if original_error is not None:
                    raise original_error from cleanup_error
                raise cleanup_error

    def close(self):
        if threading.get_ident() != self._owner:
            raise RuntimeError('OpenCL renderer must close on its owner thread')
        if self._released:
            return
        self._closed = True
        api = self._api
        if api is None:
            self._released = True
            return
        cleanup_error = None
        if self._queue:
            status = api.clFinish(self._queue)
            if status != _SUCCESS:
                cleanup_error = OpenClError(f'GPU close completion: OpenCL status {status}')
        for values, release, stage in (
                (self._pending_events, api.clReleaseEvent, 'event release'),
                (self._pending_buffers, api.clReleaseMemObject, 'image buffer release'),
                (self._kernels, api.clReleaseKernel, 'kernel release')):
            failed = []
            for value in reversed(values):
                status = release(value)
                if status != _SUCCESS:
                    failed.append(value)
                    cleanup_error = cleanup_error or OpenClError(f'{stage}: OpenCL status {status}')
            values[:] = failed
        for attribute, release in (('_program', api.clReleaseProgram),
                                   ('_queue', api.clReleaseCommandQueue),
                                   ('_context', api.clReleaseContext)):
            value = getattr(self, attribute)
            if value:
                status = release(value)
                if status == _SUCCESS:
                    setattr(self, attribute, None)
                else:
                    cleanup_error = cleanup_error or OpenClError(
                        f'{attribute[1:]} release: OpenCL status {status}')
        self._released = not any((self._context, self._queue, self._program,
                                  self._kernels, self._pending_buffers, self._pending_events))
        if cleanup_error:
            raise cleanup_error

    def __enter__(self):
        self._assert_owner()
        return self

    def __exit__(self, *_):
        self.close()
