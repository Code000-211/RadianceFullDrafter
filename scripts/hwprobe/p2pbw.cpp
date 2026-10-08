// p2pbw.cpp — per-direction bandwidth: peer copy (SDMA), kernel peer write/read, local VRAM, host<->device.
#include <hip/hip_runtime.h>
#include <cstdio>
#include <cstdlib>

#define CHECK(x) do { hipError_t e = (x); if (e != hipSuccess) { fprintf(stderr, "%s:%d %s\n", __FILE__, __LINE__, hipGetErrorString(e)); exit(1); } } while (0)

__global__ void copy_kernel(const uint4* __restrict__ src, uint4* __restrict__ dst, size_t n) {
    for (size_t i = blockIdx.x * (size_t)blockDim.x + threadIdx.x; i < n; i += (size_t)gridDim.x * blockDim.x) dst[i] = src[i];
}

// Kernel on `run_dev` copies src -> dst; one side lives on the peer GPU.
static double time_kernel(void* dst, const void* src, int run_dev, size_t bytes, int iters) {
    CHECK(hipSetDevice(run_dev));
    hipEvent_t a, b;
    CHECK(hipEventCreate(&a));
    CHECK(hipEventCreate(&b));
    size_t n = bytes / sizeof(uint4);
    for (int i = 0; i < 3; ++i) copy_kernel<<<1024, 256>>>((const uint4*)src, (uint4*)dst, n);
    CHECK(hipDeviceSynchronize());
    CHECK(hipEventRecord(a, 0));
    for (int i = 0; i < iters; ++i) copy_kernel<<<1024, 256>>>((const uint4*)src, (uint4*)dst, n);
    CHECK(hipEventRecord(b, 0));
    CHECK(hipEventSynchronize(b));
    float ms = 0;
    CHECK(hipEventElapsedTime(&ms, a, b));
    return (double)bytes * iters / (ms / 1000.0) / 1e9;
}

static double time_copy(void* dst, int dst_dev, const void* src, int src_dev, size_t bytes, hipMemcpyKind kind, int iters) {
    hipEvent_t a, b;
    CHECK(hipSetDevice(src_dev >= 0 ? src_dev : dst_dev));
    CHECK(hipEventCreate(&a));
    CHECK(hipEventCreate(&b));
    auto copy = [&]() {
        if (kind == hipMemcpyDeviceToDevice) CHECK(hipMemcpyPeerAsync(dst, dst_dev, src, src_dev, bytes, 0));
        else CHECK(hipMemcpyAsync(dst, src, bytes, kind, 0));
    };
    for (int i = 0; i < 3; ++i) copy();
    CHECK(hipDeviceSynchronize());
    CHECK(hipEventRecord(a, 0));
    for (int i = 0; i < iters; ++i) copy();
    CHECK(hipEventRecord(b, 0));
    CHECK(hipEventSynchronize(b));
    float ms = 0;
    CHECK(hipEventElapsedTime(&ms, a, b));
    return (double)bytes * iters / (ms / 1000.0) / 1e9;
}

int main() {
    const size_t bytes = 256ull << 20;
    const int iters = 20;
    int n = 0;
    CHECK(hipGetDeviceCount(&n));
    if (n < 2) { fprintf(stderr, "need 2 GPUs, found %d\n", n); return 1; }

    void* d[2];
    void* h;
    for (int i = 0; i < 2; ++i) {
        CHECK(hipSetDevice(i));
        CHECK(hipMalloc(&d[i], bytes));
        int other = 1 - i, can = 0;
        CHECK(hipDeviceCanAccessPeer(&can, i, other));
        if (can) CHECK(hipDeviceEnablePeerAccess(other, 0));
        hipDeviceProp_t p;
        CHECK(hipGetDeviceProperties(&p, i));
        printf("GPU%d %s pci %04x:%02x:%02x peer_access=%d\n", i, p.name, p.pciDomainID, p.pciBusID, p.pciDeviceID, can);
    }
    CHECK(hipHostMalloc(&h, bytes, hipHostMallocDefault));

    printf("size %zu MiB, %d iters\n", bytes >> 20, iters);
    printf("GPU0 -> GPU1: %6.2f GB/s\n", time_copy(d[1], 1, d[0], 0, bytes, hipMemcpyDeviceToDevice, iters));
    printf("GPU1 -> GPU0: %6.2f GB/s\n", time_copy(d[0], 0, d[1], 1, bytes, hipMemcpyDeviceToDevice, iters));
    printf("kernel on GPU0 writes GPU1: %6.2f GB/s\n", time_kernel(d[1], d[0], 0, bytes, iters));
    printf("kernel on GPU1 writes GPU0: %6.2f GB/s\n", time_kernel(d[0], d[1], 1, bytes, iters));
    printf("kernel on GPU0 reads  GPU1: %6.2f GB/s\n", time_kernel(d[0], d[1], 0, bytes, iters));
    printf("kernel on GPU1 reads  GPU0: %6.2f GB/s\n", time_kernel(d[1], d[0], 1, bytes, iters));
    for (int i = 0; i < 2; ++i) {
        CHECK(hipSetDevice(i));
        // copy first half of the buffer into the second half: 2x (bytes/2) through VRAM
        char* base = (char*)d[i];
        printf("GPU%d local VRAM (read+write): %6.1f GB/s\n", i, 2 * time_kernel(base + bytes / 2, base, i, bytes / 2, iters));
    }
    for (int i = 0; i < 2; ++i) {
        CHECK(hipSetDevice(i));
        printf("Host -> GPU%d: %6.2f GB/s\n", i, time_copy(d[i], i, h, -1, bytes, hipMemcpyHostToDevice, iters));
        printf("GPU%d -> Host: %6.2f GB/s\n", i, time_copy(h, -1, d[i], i, bytes, hipMemcpyDeviceToHost, iters));
    }
    return 0;
}
