# Stage 1: Upstream Frigate 0.18.2 (backend, compiled 0.18.2 Web UI, migrations, go2rtc 1.9.14, rootfs scripts)
FROM ghcr.io/blakeblackshear/frigate:0.18.2 AS upstream

# Stage 2: JetPack 4 (L4T R32.7.6 / t210) runtime image with Frigate 0.18.2 (< 4 GB)
FROM ghcr.io/blakeblackshear/frigate:0.15.2-tensorrt-jp4

ENV DEBIAN_FRONTEND=noninteractive
ENV PATH=/usr/local/cuda-10.2/bin:/usr/local/cuda/bin:/usr/local/go2rtc/bin:/usr/local/tempio/bin:/usr/local/nginx/sbin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# 1. Configure NVIDIA L4T r32.7 APT repository for t210 (Jetson Nano / Tegra X1)
#    instead of t194 (Xavier) and remove stale coral repo that has an expired apt key.
RUN rm -f /etc/apt/sources.list.d/coral-edgetpu.list && \
    echo "deb https://repo.download.nvidia.com/jetson/common r32.7 main" > /etc/apt/sources.list.d/nvidia-l4t-apt-source.list && \
    echo "deb https://repo.download.nvidia.com/jetson/t210 r32.7 main" >> /etc/apt/sources.list.d/nvidia-l4t-apt-source.list

# 2. Install CUDA 10.2 runtime, cuDNN 8.2, and TensorRT 8.2.1 runtime libraries,
#    extract L4T R32.7.6 (JetPack 4.6.6) t210 user-space GPU & multimedia libraries
#    directly into /usr/lib/aarch64-linux-gnu/tegra (required on balenaOS since the
#    host OS does not bind-mount them), and rebuild libyolo_layer.so natively for
#    Jetson Nano's Maxwell GPU (sm_53).
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        dpkg \
        zstd \
        binutils \
        xz-utils \
        git \
        ca-certificates \
        kmod \
        udev \
        libegl1 \
        libgles2 \
        libglvnd0 \
        libv4l-0 \
        libglib2.0-0 \
        libcairo2 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libpangoft2-1.0-0 \
        libasound2 \
        libgstreamer1.0-0 \
        libgstreamer-plugins-base1.0-0 \
        libgstreamer-plugins-bad1.0-0 \
        cuda-cudart-10-2 \
        cuda-nvrtc-10-2 \
        cuda-nvtx-10-2 \
        libcublas10 \
        libcudnn8 \
        libnvinfer8 \
        libnvinfer-plugin8 \
        libnvparsers8 \
        libnvonnxparsers8 \
        cuda-nvcc-10-2 \
        cuda-cudart-dev-10-2 \
        libnvinfer-dev \
        libnvinfer-plugin-dev \
        libnvparsers-dev \
        libnvonnxparsers-dev \
        libcudnn8-dev \
        libcublas-dev \
        build-essential && \
    mkdir -p /tmp/l4t-debs /tmp/l4t-extract && chmod 777 /tmp/l4t-debs && cd /tmp/l4t-debs && \
    apt-get download \
        nvidia-l4t-core \
        nvidia-l4t-cuda \
        nvidia-l4t-3d-core \
        nvidia-l4t-multimedia-utils \
        nvidia-l4t-multimedia \
        nvidia-l4t-firmware \
        nvidia-l4t-configs && \
    for deb in /tmp/l4t-debs/*.deb; do \
        dpkg-deb -x "$deb" /tmp/l4t-extract; \
    done && \
    for dir in bin sbin lib lib64; do \
        if [ -d "/tmp/l4t-extract/$dir" ]; then \
            mkdir -p "/usr/$dir" && \
            cp -a "/tmp/l4t-extract/$dir/." "/usr/$dir/" && \
            rm -rf "/tmp/l4t-extract/$dir"; \
        fi; \
    done && \
    tar -C /tmp/l4t-extract -cf - . | tar --keep-directory-symlink -C / -xf - && \
    cd / && rm -rf /tmp/l4t-debs /tmp/l4t-extract && \
    ln -sfn /usr/local/cuda-10.2 /usr/local/cuda && \
    ln -sf libcuda.so.1.1 /usr/lib/aarch64-linux-gnu/tegra/libcuda.so.1 && \
    ln -sf libcuda.so.1.1 /usr/lib/aarch64-linux-gnu/tegra/libcuda.so && \
    ln -sf tegra/libcuda.so.1.1 /usr/lib/aarch64-linux-gnu/libcuda.so.1 && \
    ln -sf tegra/libcuda.so /usr/lib/aarch64-linux-gnu/libcuda.so && \
    ln -sf libnvidia-ptxjitcompiler.so.440.18 /usr/lib/aarch64-linux-gnu/tegra/libnvidia-ptxjitcompiler.so.1 && \
    ln -sf libnvidia-fatbinaryloader.so.440.18 /usr/lib/aarch64-linux-gnu/tegra/libnvidia-fatbinaryloader.so.1 && \
    ln -sf libnvbuf_utils.so.1.0.0 /usr/lib/aarch64-linux-gnu/tegra/libnvbuf_utils.so.1 && \
    ln -sf libnvbuf_utils.so.1.0.0 /usr/lib/aarch64-linux-gnu/tegra/libnvbuf_utils.so && \
    ln -sf libnvbufsurface.so.1.0.0 /usr/lib/aarch64-linux-gnu/tegra/libnvbufsurface.so.1 && \
    ln -sf libnvbufsurftransform.so.1.0.0 /usr/lib/aarch64-linux-gnu/tegra/libnvbufsurftransform.so.1 && \
    ln -sf libnvdsbufferpool.so.1.0.0 /usr/lib/aarch64-linux-gnu/tegra/libnvdsbufferpool.so.1 && \
    ln -sf libnvid_mapper.so.1.0.0 /usr/lib/aarch64-linux-gnu/tegra/libnvid_mapper.so.1 && \
    # Rebuild libyolo_layer.so specifically for Jetson Nano's Maxwell GPU (compute_53 / sm_53)
    sed -i 's/__GNUC__ > 8/__GNUC__ > 12/g' /usr/local/cuda/include/crt/host_config.h && \
    git clone --depth 1 https://github.com/NateMeyer/tensorrt_demos.git -b conditional_download /tmp/tensorrt_demos && \
    cd /tmp/tensorrt_demos/plugins && \
    make all -j$(nproc) computes="53" && \
    cp libyolo_layer.so /usr/local/lib/libyolo_layer.so && \
    cp libyolo_layer.so /usr/local/src/tensorrt_demos/plugins/libyolo_layer.so && \
    cd / && rm -rf /tmp/tensorrt_demos && \
    # Reduce TensorRT builder workspace from 1 GiB to 256 MiB to avoid nvmap OOM on 2GB/4GB Nano
    sed -i 's/1 << 30/1 << 28/g' /usr/local/src/tensorrt_demos/yolo/onnx_to_tensorrt.py && \
    # Remove build-only *-dev packages and unused cuDNN training/RNN libraries to keep final image < 4 GB
    apt-get purge -y \
        git \
        cuda-nvcc-10-2 \
        cuda-cudart-dev-10-2 \
        libnvinfer-dev \
        libnvinfer-plugin-dev \
        libnvparsers-dev \
        libnvonnxparsers-dev \
        libcudnn8-dev \
        libcublas-dev \
        build-essential && \
    apt-get autoremove -y && \
    apt-get clean && \
    rm -f /usr/lib/aarch64-linux-gnu/libcudnn_*_train.so* \
          /usr/lib/aarch64-linux-gnu/libcudnn_adv_infer.so* \
          /usr/lib/aarch64-linux-gnu/tegra/libnvidia-glcore.so* \
          /usr/lib/aarch64-linux-gnu/tegra/libnvidia-eglcore.so* \
          /usr/lib/aarch64-linux-gnu/tegra/libnvidia-glvkspirv.so* \
          /usr/local/cuda-10.2/targets/aarch64-linux/lib/*.a && \
    strip --strip-debug /usr/lib/aarch64-linux-gnu/libnvinfer*.so* \
                        /usr/lib/aarch64-linux-gnu/libcudnn*.so* \
                        /usr/local/cuda-10.2/targets/aarch64-linux/lib/*.so* 2>/dev/null || true && \
    rm -rf /var/lib/apt/lists/* /usr/share/doc/* /usr/share/man/*

# 3. Register Tegra, CUDA, and local library paths with dynamic linker
RUN echo "/usr/lib/aarch64-linux-gnu/tegra" > /etc/ld.so.conf.d/nvidia-tegra.conf && \
    echo "/usr/lib/aarch64-linux-gnu/tegra-egl" >> /etc/ld.so.conf.d/nvidia-tegra.conf && \
    echo "/usr/local/cuda-10.2/targets/aarch64-linux/lib" > /etc/ld.so.conf.d/nvidia-cuda.conf && \
    echo "/usr/local/lib" > /etc/ld.so.conf.d/usr-local.conf && \
    ldconfig

# 4. Upgrade Frigate application, Web UI, migrations, labelmaps, go2rtc, and nginx config from Frigate 0.18.2
RUN rm -rf /opt/frigate/frigate /opt/frigate/migrations /opt/frigate/web
COPY --from=upstream /opt/frigate /opt/frigate
COPY --from=upstream /labelmap /labelmap
COPY --from=upstream /usr/local/go2rtc/bin/go2rtc /usr/local/go2rtc/bin/go2rtc
COPY --from=upstream /usr/local/go2rtc/create_config.py /usr/local/go2rtc/create_config.py
COPY --from=upstream /usr/local/ffmpeg/get_ffmpeg_path.py /usr/local/ffmpeg/get_ffmpeg_path.py
COPY --from=upstream /usr/local/nginx/conf /usr/local/nginx/conf
COPY --from=upstream /usr/local/nginx/templates /usr/local/nginx/templates
COPY --from=upstream /usr/local/nginx/get_nginx_settings.py /usr/local/nginx/get_nginx_settings.py
COPY --from=upstream /etc/s6-overlay/s6-rc.d/go2rtc/run /etc/s6-overlay/s6-rc.d/go2rtc/run
COPY --from=upstream /etc/s6-overlay/s6-rc.d/nginx/run /etc/s6-overlay/s6-rc.d/nginx/run

# 5. Copy Jetson rootfs overrides (trt-model-prepare s6 service and Python 3.9 AST patcher)
COPY rootfs/ /

# 6. Install Frigate 0.18.2 Python dependencies, apply Python 3.9 AST port, and run build-time verification
RUN chmod +x /usr/local/bin/patch_frigate_py39.py /etc/s6-overlay/s6-rc.d/trt-model-prepare/run && \
    python3 -m pip install --no-cache-dir \
        aiofiles \
        python-multipart==0.0.20 \
        prometheus-client \
        titlecase \
        eval-type-backport \
        pyclipper \
        rapidfuzz \
        shapely && \
    python3 /usr/local/bin/patch_frigate_py39.py /opt/frigate && \
    PYTHONPATH=/opt/frigate python3 -c "\
import os, sys; sys.modules['tensorrt'] = None; \
import sqlite3, frigate.version, frigate.models, frigate.config, frigate.api.app, frigate.app; \
from peewee_migrate import Router; \
from playhouse.sqlite_ext import SqliteExtDatabase; \
print('Verified Frigate version:', frigate.version.VERSION, 'SQLite:', sqlite3.sqlite_version); \
assert frigate.version.VERSION.startswith('0.18'), f'Unexpected version {frigate.version.VERSION}'; \
db = SqliteExtDatabase('/tmp/verify_migrations.db'); \
Router(db, migrate_dir='/opt/frigate/migrations').run(); \
db.close(); \
os.remove('/tmp/verify_migrations.db'); \
print('All 35 database migrations and Frigate 0.18.2 modules verified on Python 3.9!') \
"

ENV LD_PRELOAD=/usr/lib/aarch64-linux-gnu/libstdc++.so.6
ENV LD_LIBRARY_PATH=/usr/lib/aarch64-linux-gnu/tegra:/usr/lib/aarch64-linux-gnu/tegra-egl:/usr/local/cuda-10.2/targets/aarch64-linux/lib:/usr/local/lib:${LD_LIBRARY_PATH}
ENV YOLO_MODELS="yolov7-tiny-416"
ENV USE_FP16="true"
