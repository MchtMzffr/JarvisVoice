"""Package initialization runs before every supported entry point.

ONNX Runtime 1.32 ships an optional 1DS telemetry uploader enabled by default.
Its bundled Privacy.md documents this process-level opt-out; it must precede
the native import. The later disable_telemetry_events API alone is insufficient.
"""
import os

os.environ["ORT_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"

__version__ = "0.2.0"
