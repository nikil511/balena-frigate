# balena-frigate (NVIDIA Jetson Nano Edition)

[Frigate](https://blakeblackshear.github.io/frigate/) is a complete and local NVR designed for Home Assistant with AI object detection.
This port runs **Frigate `v0.18.2`** specifically tailored for the **NVIDIA Jetson Nano** (4GB SD-Card Devkit, eMMC, and 2GB Devkit) running **balenaOS** (`L4T R32.7.x` / JetPack 4.6.x), with full hardware acceleration and a `< 4 GB` image footprint (`3.87 GB`):

- **Frigate `v0.18.2` on JetPack 4 (Python 3.9):** Grafts the latest Frigate `0.18.2` backend, compiled `0.18.2` Web UI, database migrations (`001`–`035`), and `go2rtc` (`1.9.14`) onto the JetPack 4 TensorRT runtime, using an automated AST transformer ([`patch_frigate_py39.py`](rootfs/usr/local/bin/patch_frigate_py39.py)) and `sitecustomize.py` polyfills (`datetime.UTC`, `enum.StrEnum`, `typing.Self`, PEP 604 unions, and `pysqlite3` `3.46.0` with `sqlite-vec`).
- **TensorRT 8.2.1 + CUDA 10.2 Object Detection:** Bundles the L4T R32.7.6 (`t210`) user-space GPU drivers, CUDA 10.2 runtime, cuDNN 8.2, and TensorRT 8.2.1 runtime inside the container (since balenaOS does not bind-mount host L4T libraries) and compiles `libyolo_layer.so` natively for the Jetson Nano's Maxwell GPU (`compute_53` / `sm_53`) with FP16 support.
- **NVDEC / NVENC (`nvmpi`) Hardware Video Acceleration:** Includes `jetson-ffmpeg` linked against L4T Multimedia (`libnvbuf_utils`, `libnvv4l2`, `libv4l2_nvvidconv`) and configures `preset-jetson-h264` by default.
- **Unified Memory Tuning:** Bounds `/dev/shm` (`256M`), `/tmp/cache` (`256m`), and TensorRT builder workspace (`256 MiB`) to prevent `nvmap` / CUDA OOM crashes on 2GB and 4GB Jetson Nano boards.

## Hardware Required

- NVIDIA Jetson Nano (4GB Devkit, eMMC, or 2GB Devkit) running balenaOS (`v4.0.9+rev2` or newer, L4T R32.7.x)
- 5V 4A power supply recommended (TensorRT model compilation on first boot stresses the Maxwell GPU)

## Getting Started

You can one-click-deploy this project to balena using the button below:

[![Deploy with balena](https://balena.io/deploy.svg)](https://dashboard.balena-cloud.com/deploy?repoUrl=https://github.com/nikil511/balena-frigate)

## Manual Deployment

Alternatively, deployment can be carried out by manually creating a [balenaCloud account](https://dashboard.balena-cloud.com) and application,
flashing a device, downloading the project and pushing it via the [balena CLI](https://github.com/balena-io/balena-cli):

```bash
balena push <fleet-name>
```

### Environment Variables & Secrets

Configure credentials and LAN upstream hosts via **balenaCloud Fleet / Device Environment Variables** so no sensitive values are stored in the repository:

- `YOLO_MODELS`: Comma-separated TensorRT YOLO models to generate on startup (default: `yolov7-tiny-416`)
- `USE_FP16`: Enable FP16 half-precision TensorRT inference on Maxwell GPU (default: `true`)
- `FRIGATE_MQTT_USER`: Replaced at runtime in `frigate.yml` (`{FRIGATE_MQTT_USER}`)
- `FRIGATE_MQTT_PASSWORD`: Replaced at runtime in `frigate.yml` (`{FRIGATE_MQTT_PASSWORD}`)
- `FRIGATE_RTSP_USER`: Replaced at runtime in `frigate.yml` (`{FRIGATE_RTSP_USER}`)
- `FRIGATE_RTSP_PASSWORD`: Replaced at runtime in `frigate.yml` (`{FRIGATE_RTSP_PASSWORD}`)
- `FRIGATE_CAM1_IP` / `FRIGATE_CAM2_IP`: Camera LAN IPs replaced at runtime in `frigate.yml` (`{FRIGATE_CAM1_IP}`, `{FRIGATE_CAM2_IP}`)
- `TZ`: Inform services of the [timezone](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones) in your location
- `SET_HOSTNAME`: Set a custom hostname on application start (default is `frigate`)
- `FRIGATE_HOST`: Upstream Frigate HTTP address for HAProxy (default: `127.0.0.1:5000`)
- `CAMERA1_HOST`: Upstream `<ip>:<port>` for Camera 1 in HAProxy
- `CAMERA2_HOST`: Upstream `<ip>:<port>` for Camera 2 in HAProxy
- `ROUTER_HOST`: Upstream `<ip>:<port>` for the LAN router in HAProxy

## Balena Public Device URL & HAProxy Routes

The `proxy` service runs HAProxy on port `80` so that the Frigate Web UI and LAN IP cameras work through the **balenaCloud Public Device URL tunnel** (`https://<uuid>.balena-devices.com`) as well as over local HTTP (`http://frigate.local`):

- `/` or `/frigate`: **Frigate Web UI** (`127.0.0.1:5000`, including `/api/*`, `/ws`, and `/live/*` WebSocket feeds)
- `/camera1` (or `/cam1`): **Camera 1 Web UI** (`CAMERA1_HOST`)
- `/camera2` (or `/cam2`): **Camera 2 Web UI** (`CAMERA2_HOST`)
- `/router`: **Router Web UI** (`ROUTER_HOST`)

## Usage/Examples

On first boot, the `trt-model-prepare` service will automatically compile `yolov7-tiny-416.trt` on the Jetson Nano's GPU (this takes ~2–4 minutes on first boot and is cached in `/config/model_cache/tensorrt/8.2.1/`) and seed a Jetson-optimized `/config/frigate.yml` if none exists yet:

```yaml
mqtt:
  enabled: false

detectors:
  tensorrt:
    type: tensorrt
    device: 0

model:
  path: /config/model_cache/tensorrt/yolov7-tiny-416.trt
  input_tensor: nchw
  input_pixel_format: rgb
  width: 416
  height: 416

ffmpeg:
  hwaccel_args: preset-jetson-h264

cameras: {}

version: 0.18-0
```

When it's done you should be able to access the app at <http://frigate.local> (or port `5000` for unauthenticated local access).

Additional usage instructions for Frigate can be found here: <https://blakeblackshear.github.io/frigate/>.

## Contributing

Please open an issue or submit a pull request with any features, fixes, or changes.
