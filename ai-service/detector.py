"""
EasyOCR Detector pre-optimized by Qualcomm AI Hub.
Supports Snapdragon X Elite / X Plus NPU acceleration via QNNExecutionProvider with CPU fallback.
Detects text regions, blank placeholder lines, and auto-locates recipient name fields.
"""

import os
import io
import zipfile
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import requests
import numpy as np
from PIL import Image
import scipy.ndimage as ndimage
import onnxruntime as ort

logger = logging.getLogger("ai-service.detector")
logging.basicConfig(level=logging.INFO)

QUALCOMM_ASSET_URL = "https://qaihub-public-assets.s3.us-west-2.amazonaws.com/qai-hub-models/models/easyocr/releases/v0.62.2/easyocr-onnx-float.zip"

MODELS_DIR = Path(__file__).resolve().parent / "models"
DETECTOR_ONNX_PATH = MODELS_DIR / "detector.onnx"
RECOGNIZER_ONNX_PATH = MODELS_DIR / "recognizer.onnx"


def ensure_models():
    """Download and extract Qualcomm EasyOCR ONNX models if not present."""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    if DETECTOR_ONNX_PATH.exists() and (MODELS_DIR / "detector.data").exists():
        logger.info(f"Qualcomm EasyOCR detector ONNX found at {DETECTOR_ONNX_PATH}")
        return

    logger.info(f"Downloading Qualcomm EasyOCR ONNX models from {QUALCOMM_ASSET_URL}...")
    headers = {"User-Agent": "Imprint-EasyOCR/1.0"}
    resp = requests.get(QUALCOMM_ASSET_URL, headers=headers, stream=True, timeout=120)
    resp.raise_for_status()

    content = io.BytesIO(resp.content)
    with zipfile.ZipFile(content) as z:
        for file_info in z.infolist():
            filename = Path(file_info.filename).name
            if filename in ("detector.onnx", "detector.data", "recognizer.onnx", "recognizer.data", "metadata.json"):
                target_file = MODELS_DIR / filename
                with z.open(file_info) as source, open(target_file, "wb") as target:
                    target.write(source.read())
                logger.info(f"Extracted {filename} -> {target_file}")


class QualcommEasyOCRDetector:
    def __init__(self):
        ensure_models()
        self.session, self.active_provider = self._init_session()
        self.input_name = self.session.get_inputs()[0].name
        self.input_shape = self.session.get_inputs()[0].shape
        # Typically [1, 3, 608, 800]
        self.target_h = self.input_shape[2] if isinstance(self.input_shape[2], int) else 608
        self.target_w = self.input_shape[3] if isinstance(self.input_shape[3], int) else 800
        logger.info(f"Detector initialized with {self.active_provider}. Target shape: ({self.target_h}, {self.target_w})")

    def _init_session(self) -> Tuple[ort.InferenceSession, str]:
        available = ort.get_available_providers()
        logger.info(f"Available ONNX providers: {available}")
        
        # Prefer Qualcomm QNNExecutionProvider for Snapdragon X Elite / X Plus
        providers_to_try = []
        if "QNNExecutionProvider" in available:
            providers_to_try.append("QNNExecutionProvider")
        providers_to_try.append("CPUExecutionProvider")

        session_opts = ort.SessionOptions()
        session_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        try:
            session = ort.InferenceSession(str(DETECTOR_ONNX_PATH), sess_options=session_opts, providers=providers_to_try)
            active = session.get_providers()[0]
            return session, active
        except Exception as e:
            logger.warning(f"Failed to initialize with {providers_to_try}: {e}. Falling back to CPU.")
            session = ort.InferenceSession(str(DETECTOR_ONNX_PATH), sess_options=session_opts, providers=["CPUExecutionProvider"])
            return session, "CPUExecutionProvider"

    def preprocess(self, img: Image.Image) -> Tuple[np.ndarray, float, float]:
        """Preprocess image for CRAFT detector."""
        orig_w, orig_h = img.size
        resized = img.resize((self.target_w, self.target_h), Image.Resampling.BILINEAR)
        arr = np.array(resized, dtype=np.float32)

        # Handle grayscale or RGBA
        if len(arr.shape) == 2:
            arr = np.stack([arr] * 3, axis=-1)
        elif arr.shape[2] == 4:
            arr = arr[:, :, :3]

        # Normalization (CRAFT standard)
        arr /= 255.0
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        arr = (arr - mean) / std

        # Transpose HWC -> CHW -> NCHW
        arr = np.transpose(arr, (2, 0, 1))
        arr = np.expand_dims(arr, axis=0).astype(np.float32)
        return arr, orig_w, orig_h

    def detect_boxes(self, img: Image.Image) -> List[Dict[str, Any]]:
        """Run inference and return detected bounding boxes."""
        tensor, orig_w, orig_h = self.preprocess(img)
        outputs = self.session.run(None, {self.input_name: tensor})
        
        # CRAFT detector outputs heatmaps: [1, H_out, W_out, 2] or [1, 2, H_out, W_out]
        feat = outputs[0]
        if feat.ndim == 4:
            if feat.shape[1] == 2:
                # [1, 2, H, W] -> [H, W, 2]
                heatmaps = np.transpose(feat[0], (1, 2, 0))
            else:
                heatmaps = feat[0]
        else:
            heatmaps = feat

        text_score = heatmaps[:, :, 0]
        link_score = heatmaps[:, :, 1]

        # Thresholding for text regions
        text_threshold = 0.6
        link_threshold = 0.35
        text_bin = text_score > text_threshold
        link_bin = link_score > link_threshold
        combined = np.clip(text_bin.astype(np.float32) + link_bin.astype(np.float32), 0, 1)

        labeled_array, num_features = ndimage.label(combined)
        boxes = []

        map_h, map_w = text_score.shape
        scale_x = orig_w / float(map_w)
        scale_y = orig_h / float(map_h)

        slices = ndimage.find_objects(labeled_array)
        for i, s in enumerate(slices):
            if s is None:
                continue
            slice_y, slice_x = s
            ymin, ymax = slice_y.start * scale_y, slice_y.stop * scale_y
            xmin, xmax = slice_x.start * scale_x, slice_x.stop * scale_x
            w = xmax - xmin
            h = ymax - ymin

            # Filter tiny artifacts
            if w < 15 or h < 8:
                continue

            boxes.append({
                "x_min": float(xmin),
                "y_min": float(ymin),
                "x_max": float(xmax),
                "y_max": float(ymax),
                "width": float(w),
                "height": float(h),
                "center_x": float((xmin + xmax) / 2.0 / orig_w),
                "center_y": float((ymin + ymax) / 2.0 / orig_h),
                "norm_width": float(w / orig_w),
                "norm_height": float(h / orig_h)
            })

        return sorted(boxes, key=lambda b: b["y_min"])

    def find_blank_placeholder(self, img: Image.Image, text_boxes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Heuristic detection for blank recipient placeholder field:
        1. Look for printed underline / dotted line in the certificate body.
        2. Analyze gaps between header text ("This is to certify that", "Awarded to") and footer.
        3. Identify optimal center position and height for recipient name.
        """
        orig_w, orig_h = img.size
        gray = np.array(img.convert("L"), dtype=np.float32)

        # Look for horizontal lines (underlines / dotted lines) in the middle vertical region (y: 35% - 65%)
        y_start = int(orig_h * 0.35)
        y_end = int(orig_h * 0.65)
        roi = gray[y_start:y_end, :]

        # Detect strong horizontal edges / dark lines on light background
        # Typical certificate background is bright (> 200), line is darker (< 160)
        dark_mask = roi < 180
        horizontal_sums = np.sum(dark_mask, axis=1)  # Length of dark pixels along each horizontal row

        # Line candidate requires a contiguous stretch of dark pixels of width >= 25% of image width
        line_candidates = []
        min_line_width = int(orig_w * 0.25)

        for rel_y, count in enumerate(horizontal_sums):
            if count >= min_line_width:
                abs_y = y_start + rel_y
        # Filter out line candidates that overlap with detected text boxes (e.g. letters in headers)
        def overlaps_text(y_val: int) -> bool:
            for b in text_boxes:
                if (b["y_min"] - 4) <= y_val <= (b["y_max"] + 4):
                    return True
            return False

        line_candidates = [y for y in line_candidates if not overlaps_text(y)]

        # If a distinct printed underline/dotted line was found outside of text regions
        if line_candidates:
            # Cluster adjacent lines
            clusters = []
            curr = [line_candidates[0]]
            for y_val in line_candidates[1:]:
                if y_val - curr[-1] <= 4:
                    curr.append(y_val)
                else:
                    clusters.append(int(np.median(curr)))
                    curr = [y_val]
            if curr:
                clusters.append(int(np.median(curr)))

            # Pick the line closest to vertical center (around y=0.45 - 0.65)
            best_line_y = min(clusters, key=lambda ly: abs(ly / orig_h - 0.52))

            # The text baseline sits right on/above the underline
            est_box_height = max(40.0, min(140.0, orig_h * 0.065))
            norm_y = (best_line_y - (est_box_height * 0.45)) / float(orig_h)

            return {
                "field": "Name",
                "x": 0.5,  # Centered horizontally
                "y": float(max(0.1, min(0.9, norm_y))),
                "width": 0.55,
                "height": float(est_box_height / orig_h),
                "fontSize": int(round(est_box_height)),
                "confidence": 0.95,
                "heuristic": "printed_underline_detected",
                "matched_line_y": int(best_line_y)
            }

        # If no explicit physical line, analyze text box layout from the detector
        # Find prompt box (e.g. "This award is presented to", "certify that") in top 30-55%
        upper_prompt_boxes = [b for b in text_boxes if b["center_y"] <= 0.53]
        last_upper_box = max(upper_prompt_boxes, key=lambda b: b["y_max"]) if upper_prompt_boxes else None

        upper_bound_y = last_upper_box["y_max"] if last_upper_box else (orig_h * 0.40)
        # Expected lower bound for body text ("for outstanding performance...") or signatures
        lower_bound_y = orig_h * 0.68

        gap_center_y = (upper_bound_y + lower_bound_y) / 2.0
        gap_height = lower_bound_y - upper_bound_y

        est_font_size = max(46.0, min(110.0, gap_height * 0.45))
        norm_y = gap_center_y / float(orig_h)

        return {
            "field": "Name",
            "x": 0.5,
            "y": float(max(0.2, min(0.8, norm_y))),
            "width": 0.55,
            "height": float(est_font_size / orig_h),
            "fontSize": int(round(est_font_size)),
            "confidence": 0.92,
            "heuristic": "central_blank_zone_detected",
            "gap_y_range": [int(upper_bound_y), int(lower_bound_y)]
        }
