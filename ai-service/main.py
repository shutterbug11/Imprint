"""
FastAPI Microservice for Qualcomm EasyOCR Smart Auto-Placement.
Provides POST /detect-fields and GET /health.
"""

import base64
import io
import logging
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image

from detector import QualcommEasyOCRDetector

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai-service")

app = FastAPI(
    title="Imprint AI Service",
    description="Qualcomm AI Hub EasyOCR detector for automated certificate blank field detection.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Lazy-loaded singleton detector
_detector: Optional[QualcommEasyOCRDetector] = None


def get_detector() -> QualcommEasyOCRDetector:
    global _detector
    if _detector is None:
        logger.info("Initializing QualcommEasyOCRDetector...")
        _detector = QualcommEasyOCRDetector()
    return _detector


@app.get("/health")
def health():
    try:
        det = get_detector()
        return {
            "status": "ok",
            "model": "Qualcomm EasyOCR (ONNX)",
            "provider": det.active_provider,
            "target_resolution": f"{det.target_w}x{det.target_h}"
        }
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return {
            "status": "degraded",
            "error": str(e)
        }


def _process_image(pil_img: Image.Image) -> Dict[str, Any]:
    det = get_detector()
    orig_w, orig_h = pil_img.size

    # 1. Run EasyOCR CRAFT ONNX Detector
    boxes = det.detect_boxes(pil_img)

    # 2. Run blank-line & placeholder heuristics
    candidate = det.find_blank_placeholder(pil_img, boxes)

    return {
        "success": True,
        "provider": det.active_provider,
        "candidate": candidate,
        "boxes_count": len(boxes),
        "boxes": boxes[:30],  # Return top detected boxes
        "image_size": {
            "width": orig_w,
            "height": orig_h
        }
    }


@app.post("/detect-fields")
async def detect_fields(request: Request):
    """
    Accepts template image either via multipart/form-data upload or JSON base64 payload.
    Returns detected text boxes and auto-placement candidate.
    """
    try:
        content_type = request.headers.get("content-type", "")
        pil_img = None

        if "multipart/form-data" in content_type:
            form = await request.form()
            upload = form.get("file")
            if not upload:
                raise HTTPException(status_code=400, detail="No file uploaded in form.")
            contents = await upload.read()
            pil_img = Image.open(io.BytesIO(contents)).convert("RGB")
        else:
            # Parse JSON body
            body = await request.json()
            raw_b64 = body.get("image", "") if isinstance(body, dict) else ""
            if not raw_b64:
                raise HTTPException(status_code=400, detail="No image provided. Send JSON with 'image' base64 or multipart 'file'.")
            if "," in raw_b64:
                raw_b64 = raw_b64.split(",", 1)[1]
            img_bytes = base64.b64decode(raw_b64)
            pil_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")

        return _process_image(pil_img)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Field detection failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"AI Detection error: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
