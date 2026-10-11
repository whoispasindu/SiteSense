"""Report issue classifier: data, training and export."""

import os

# onnxruntime's Linux build sends usage telemetry to Microsoft unless this is set before it is imported.
os.environ["ORT_DISABLE_TELEMETRY"] = "1"
