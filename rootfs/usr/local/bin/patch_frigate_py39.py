#!/usr/bin/env python3
"""Port Frigate 0.18.x codebase to Python 3.9 on NVIDIA Jetson JetPack 4 (L4T R32.7)."""

import ast
import copy
import pathlib
import py_compile
import sys

SITECUSTOMIZE_PATH = pathlib.Path("/usr/lib/python3.9/sitecustomize.py")

SITECUSTOMIZE_CONTENT = '''"""Python 3.9 compatibility polyfills for Frigate 0.18+ on JetPack 4."""

import builtins
import datetime
import enum
import sys
import typing

# 1. Upgrade stdlib sqlite3 (3.31.1 on Ubuntu 20.04) to pysqlite3 (3.46.0)
#    Required for ALTER TABLE ... DROP COLUMN in Frigate 0.16+ migrations and vec0.
try:
    import pysqlite3
    import pysqlite3.dbapi2

    sys.modules["sqlite3"] = pysqlite3
    sys.modules["sqlite3.dbapi2"] = pysqlite3.dbapi2
except ImportError:
    pass

# 2. Polyfill datetime.UTC (added in Python 3.11)
if not hasattr(datetime, "UTC"):
    datetime.UTC = datetime.timezone.utc

# 3. Polyfill enum.StrEnum (added in Python 3.11)
if not hasattr(enum, "StrEnum"):
    class StrEnum(str, enum.Enum):
        def __new__(cls, value, *args, **kwargs):
            obj = str.__new__(cls, value)
            obj._value_ = value
            return obj

        def __str__(self) -> str:
            return str(self._value_)

        @staticmethod
        def _generate_next_value_(name, start, count, last_values):
            return name.lower()

    enum.StrEnum = StrEnum

# 4. Polyfill typing symbols added in Python 3.10-3.12 via typing_extensions
try:
    import typing_extensions

    for _sym in (
        "Self",
        "NotRequired",
        "Required",
        "TypeGuard",
        "TypeAlias",
        "Never",
        "LiteralString",
        "Unpack",
        "TypeVarTuple",
        "ParamSpec",
        "Concatenate",
        "override",
        " assert_never",
    ):
        _sym = _sym.strip()
        if not hasattr(typing, _sym) and hasattr(typing_extensions, _sym):
            setattr(typing, _sym, getattr(typing_extensions, _sym))
except ImportError:
    pass

# 5. Expose _Py39Union in builtins for AST-rewritten PEP 604 (X | Y) type unions
builtins._Py39Union = typing.Union

# 6. Alias asyncio.TimeoutError to builtins.TimeoutError (Python 3.11+ behavior)
import asyncio
import asyncio.exceptions

asyncio.TimeoutError = builtins.TimeoutError
asyncio.exceptions.TimeoutError = builtins.TimeoutError
'''


def has_bitor(node: ast.AST) -> bool:
    for n in ast.walk(node):
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr):
            return True
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and "|" in n.value:
            return True
        if (
            isinstance(n, ast.Subscript)
            and isinstance(n.value, ast.Name)
            and n.value.id in ("list", "List", "set", "Set")
            and isinstance(n.slice, ast.Tuple)
            and len(n.slice.elts) > 1
        ):
            return True
    return False


class UnionTransformer(ast.NodeTransformer):
    def __init__(self, as_tuple: bool = False):
        self.as_tuple = as_tuple

    def visit_Subscript(self, node: ast.Subscript):
        self.generic_visit(node)
        if (
            isinstance(node.value, ast.Name)
            and node.value.id in ("list", "List", "set", "Set")
            and isinstance(node.slice, ast.Tuple)
            and len(node.slice.elts) > 1
        ):
            node.slice = node.slice.elts[0]
        return node

    def visit_Constant(self, node: ast.Constant):
        if isinstance(node.value, str) and "|" in node.value:
            try:
                sub_tree = ast.parse(node.value, mode="eval")
                new_sub = UnionTransformer(as_tuple=False).visit(sub_tree)
                ast.fix_missing_locations(new_sub)
                return ast.Constant(value=ast.unparse(new_sub.body))
            except SyntaxError:
                return node
        return node

    def visit_BinOp(self, node: ast.BinOp):
        self.generic_visit(node)
        if isinstance(node.op, ast.BitOr):
            items = []

            def collect(n):
                if isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr):
                    collect(n.left)
                    collect(n.right)
                else:
                    items.append(n)

            collect(node)
            if self.as_tuple:
                return ast.Tuple(elts=items, ctx=ast.Load())
            return ast.Subscript(
                value=ast.Name(id="_Py39Union", ctx=ast.Load()),
                slice=ast.Tuple(elts=items, ctx=ast.Load()),
                ctx=ast.Load(),
            )
        return node


def collect_type_roots(tree: ast.AST):
    roots = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.returns and has_bitor(node.returns):
                roots.append((node.returns, False))
            for a in (
                node.args.posonlyargs
                + node.args.args
                + node.args.kwonlyargs
                + [node.args.vararg, node.args.kwarg]
            ):
                if a and a.annotation and has_bitor(a.annotation):
                    roots.append((a.annotation, False))
        elif isinstance(node, ast.AnnAssign) and node.annotation and has_bitor(node.annotation):
            roots.append((node.annotation, False))
        elif isinstance(node, ast.ClassDef):
            for b in node.bases:
                if has_bitor(b):
                    roots.append((b, False))
        elif isinstance(node, ast.Call):
            if (
                isinstance(node.func, ast.Name)
                and node.func.id == "cast"
                and len(node.args) >= 1
                and has_bitor(node.args[0])
            ):
                roots.append((node.args[0], False))
            elif (
                isinstance(node.func, ast.Name)
                and node.func.id in ("isinstance", "issubclass")
                and len(node.args) >= 2
                and has_bitor(node.args[1])
            ):
                roots.append((node.args[1], True))
        elif isinstance(node, ast.Assign):
            if isinstance(node.value, ast.BinOp) and isinstance(node.value.op, ast.BitOr):
                if any(
                    isinstance(n, ast.Constant) and n.value is None
                    for n in ast.walk(node.value)
                ):
                    roots.append((node.value, False))
    return roots


def pos_to_byte_offset(lines_bytes: list[bytes], lineno: int, col_offset: int) -> int:
    return sum(len(lines_bytes[i]) for i in range(lineno - 1)) + col_offset


def transform_file(path: pathlib.Path) -> bool:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))
    roots = collect_type_roots(tree)
    if not roots:
        return False

    src_bytes = src.encode("utf-8")
    lines_bytes = src_bytes.splitlines(keepends=True)

    spans = []
    for r, as_tuple in roots:
        start = pos_to_byte_offset(lines_bytes, r.lineno, r.col_offset)
        end = pos_to_byte_offset(lines_bytes, r.end_lineno, r.end_col_offset)
        spans.append((start, end, r, as_tuple))

    filtered = []
    for i, (s1, e1, r1, t1) in enumerate(spans):
        if any(
            i != j and s2 <= s1 and e1 <= e2 and (s2 < s1 or e1 < e2 or j < i)
            for j, (s2, e2, _, _) in enumerate(spans)
        ):
            continue
        filtered.append((s1, e1, r1, t1))

    filtered.sort(key=lambda x: x[0], reverse=True)
    new_bytes = src_bytes
    for start, end, r, as_tuple in filtered:
        new_node = UnionTransformer(as_tuple=as_tuple).visit(copy.deepcopy(r))
        ast.fix_missing_locations(new_node)
        replacement = ast.unparse(new_node).encode("utf-8")
        new_bytes = new_bytes[:start] + replacement + new_bytes[end:]

    new_src = new_bytes.decode("utf-8")
    ast.parse(new_src, filename=str(path))
    path.write_text(new_src, encoding="utf-8")
    return True


def patch_specific_files(frigate_root: pathlib.Path) -> None:
    # 1. frigate/const.py: default ffmpeg versions if env vars are unset
    const_py = frigate_root / "frigate" / "const.py"
    if const_py.exists():
        txt = const_py.read_text(encoding="utf-8")
        txt = txt.replace(
            'DEFAULT_FFMPEG_VERSION = os.environ.get("DEFAULT_FFMPEG_VERSION", "")',
            'DEFAULT_FFMPEG_VERSION = os.environ.get("DEFAULT_FFMPEG_VERSION", "7.0")',
        )
        txt = txt.replace(
            'INCLUDED_FFMPEG_VERSIONS = os.environ.get("INCLUDED_FFMPEG_VERSIONS", "").split(":")',
            'INCLUDED_FFMPEG_VERSIONS = os.environ.get("INCLUDED_FFMPEG_VERSIONS", "7.0:5.0").split(":")',
        )
        const_py.write_text(txt, encoding="utf-8")

    # 2. frigate/util/config.py: prefer system/jetson ffmpeg in /usr/local/bin when path == "default"
    config_py = frigate_root / "frigate" / "util" / "config.py"
    if config_py.exists():
        txt = config_py.read_text(encoding="utf-8")
        old_fn = '''    if path == "default" or (
        not path.startswith("/") and path not in INCLUDED_FFMPEG_VERSIONS
    ):
        version = DEFAULT_FFMPEG_VERSION'''
        new_fn = '''    if path == "default" or (
        not path.startswith("/") and path not in INCLUDED_FFMPEG_VERSIONS
    ):
        if shutil.which(binary) is not None:
            return shutil.which(binary)
        version = DEFAULT_FFMPEG_VERSION'''
        if old_fn in txt:
            txt = txt.replace(old_fn, new_fn)
            config_py.write_text(txt, encoding="utf-8")

    # 3. Guard optional audio/genai imports so missing optional SDKs don't break startup
    types_py = frigate_root / "frigate" / "data_processing" / "types.py"
    if types_py.exists():
        txt = types_py.read_text(encoding="utf-8")
        txt = txt.replace(
            "import sherpa_onnx\n\nfrom frigate.data_processing.real_time.whisper_online import FasterWhisperASR",
            "try:\n    import sherpa_onnx\n    from frigate.data_processing.real_time.whisper_online import FasterWhisperASR\nexcept ImportError:\n    sherpa_onnx = Any\n    FasterWhisperASR = Any",
        )
        txt = txt.replace(
            "AudioTranscriptionModel = FasterWhisperASR | sherpa_onnx.OnlineRecognizer | None",
            "AudioTranscriptionModel = Any",
        )
        types_py.write_text(txt, encoding="utf-8")

    audio_model_py = (
        frigate_root / "frigate" / "data_processing" / "common" / "audio_transcription" / "model.py"
    )
    if audio_model_py.exists():
        txt = audio_model_py.read_text(encoding="utf-8")
        txt = txt.replace(
            "import sherpa_onnx",
            "try:\n    import sherpa_onnx\nexcept ImportError:\n    sherpa_onnx = None",
        )
        audio_model_py.write_text(txt, encoding="utf-8")

    whisper_py = (
        frigate_root / "frigate" / "data_processing" / "real_time" / "whisper_online.py"
    )
    if whisper_py.exists():
        txt = whisper_py.read_text(encoding="utf-8")
        txt = txt.replace(
            "import librosa\nimport numpy as np\nimport soundfile as sf",
            "import numpy as np\ntry:\n    import librosa\n    import soundfile as sf\nexcept ImportError:\n    librosa = None\n    sf = None",
        )
        whisper_py.write_text(txt, encoding="utf-8")

    genai_init_py = frigate_root / "frigate" / "genai" / "__init__.py"
    if genai_init_py.exists():
        txt = genai_init_py.read_text(encoding="utf-8")
        txt = txt.replace(
            "            importlib.import_module(module_name)",
            "            try:\n                importlib.import_module(module_name)\n            except ImportError as e:\n                logger.debug(f'Optional GenAI provider {module_name} not available: {e}')",
        )
        genai_init_py.write_text(txt, encoding="utf-8")

    # 4. frigate/util/services.py:
    #    - Only pass -rw_timeout to ffprobe when url is a network URL ("://" in url);
    #      passing -rw_timeout on local .mp4 files causes ffprobe to fail with
    #      "Option rw_timeout not found".
    #    - Prefer ffprobe (FFmpeg 6.0) over OpenCV 4.2 (libavformat58) when probing
    #      recording segments so in-band HEVC SPS/PPS segments probe cleanly without
    #      cap_ffmpeg_impl.hpp errors.
    services_py = frigate_root / "frigate" / "util" / "services.py"
    if services_py.exists():
        txt = services_py.read_text(encoding="utf-8")
        old_probe_cmd = '''        cmd += [
            "-rw_timeout",
            "5000000",
            "-v",'''
        new_probe_cmd = '''        if "://" in url:
            cmd += ["-rw_timeout", "5000000"]
        else:
            cmd += ["-analyzeduration", "10000000", "-probesize", "10000000"]
        cmd += [
            "-v",'''
        txt = txt.replace(old_probe_cmd, new_probe_cmd)

        old_probe_branch = '''    if is_rtsp:
        # skip cv2 for RTSP: its FFmpeg backend has a hardcoded ~30s internal
        # timeout that cannot be shortened per-call, and ffprobe bounded by
        # -rw_timeout handles RTSP probing reliably
        has_video, width, height, fourcc, duration = await probe_with_ffprobe(url)
    else:
        # try cv2 first for local files, HTTP, RTMP
        has_video, width, height, fourcc, duration = probe_with_cv2(url)

        # fallback to ffprobe if needed
        if not has_video or (get_duration and duration < 0):
            has_video, width, height, fourcc, duration = await probe_with_ffprobe(url)'''
        new_probe_branch = '''    has_video, width, height, fourcc, duration = await probe_with_ffprobe(url)
    if not is_rtsp and (not has_video or (get_duration and duration < 0)):
        has_video, width, height, fourcc, duration = probe_with_cv2(url)'''
        txt = txt.replace(old_probe_branch, new_probe_branch)
        services_py.write_text(txt, encoding="utf-8")

    # 5. frigate/config/camera/camera.py:
    #    Decouple "detect" and "record" into separate FFmpeg commands when combined on a
    #    single input. On Jetson L4T, nvmpi hardware decoders (-c:v hevc_nvmpi / h264_nvmpi)
    #    do not populate codecpar->extradata during stream probing; separating the record
    #    stream (-c copy without nvmpi) ensures valid hvcC/avcC headers in MP4 segments
    #    even for cameras that send HEVC VPS/SPS/PPS in-band.
    camera_py = frigate_root / "frigate" / "config" / "camera" / "camera.py"
    if camera_py.exists():
        txt = camera_py.read_text(encoding="utf-8")
        old_build_cmds = '''    def _build_ffmpeg_cmds(self):
        """Build ffmpeg commands from the current ffmpeg config."""
        ffmpeg_cmds = []
        for ffmpeg_input in self.ffmpeg.inputs:
            ffmpeg_cmd = self._get_ffmpeg_cmd(ffmpeg_input)
            if ffmpeg_cmd is None:
                continue

            ffmpeg_cmds.append({"roles": ffmpeg_input.roles, "cmd": ffmpeg_cmd})
        self._ffmpeg_cmds = ffmpeg_cmds'''
        new_build_cmds = '''    def _build_ffmpeg_cmds(self):
        """Build ffmpeg commands from the current ffmpeg config."""
        ffmpeg_cmds = []
        for ffmpeg_input in self.ffmpeg.inputs:
            if (
                "detect" in ffmpeg_input.roles
                and "record" in ffmpeg_input.roles
                and self.record.enabled
            ):
                detect_input = ffmpeg_input.model_copy(
                    update={"roles": [r for r in ffmpeg_input.roles if r != "record"]}
                )
                detect_cmd = self._get_ffmpeg_cmd(detect_input)
                if detect_cmd is not None:
                    ffmpeg_cmds.append({"roles": detect_input.roles, "cmd": detect_cmd})
                record_input = ffmpeg_input.model_copy(
                    update={"roles": [r for r in ffmpeg_input.roles if r == "record"], "hwaccel_args": []}
                )
                record_cmd = self._get_ffmpeg_cmd(record_input)
                if record_cmd is not None:
                    ffmpeg_cmds.append({"roles": record_input.roles, "cmd": record_cmd})
                continue
            ffmpeg_cmd = self._get_ffmpeg_cmd(ffmpeg_input)
            if ffmpeg_cmd is None:
                continue

            ffmpeg_cmds.append({"roles": ffmpeg_input.roles, "cmd": ffmpeg_cmd})
        self._ffmpeg_cmds = ffmpeg_cmds'''
        txt = txt.replace(old_build_cmds, new_build_cmds)
        camera_py.write_text(txt, encoding="utf-8")


def main() -> None:
    target_root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("/opt/frigate")
    write_sitecustomize = "--no-sitecustomize" not in sys.argv

    if write_sitecustomize:
        SITECUSTOMIZE_PATH.parent.mkdir(parents=True, exist_ok=True)
        SITECUSTOMIZE_PATH.write_text(SITECUSTOMIZE_CONTENT, encoding="utf-8")
        print(f"[patch_frigate_py39] Wrote {SITECUSTOMIZE_PATH}")

    patch_specific_files(target_root)

    search_dirs = [
        target_root / "frigate",
        target_root / "migrations",
        pathlib.Path("/usr/local/ffmpeg"),
        pathlib.Path("/usr/local/go2rtc"),
        pathlib.Path("/usr/local/nginx"),
    ]

    modified = 0
    compiled = 0
    for d in search_dirs:
        if not d.exists():
            continue
        for p in sorted(d.rglob("*.py")):
            if "/test/" in str(p):
                continue
            if transform_file(p):
                modified += 1
            py_compile.compile(str(p), doraise=True)
            compiled += 1

    print(
        f"[patch_frigate_py39] Transformed {modified} files, byte-compiled {compiled} files cleanly."
    )


if __name__ == "__main__":
    main()
