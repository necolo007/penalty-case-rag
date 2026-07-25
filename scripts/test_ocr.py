"""OCR 冒烟测试（仅在 OCR Worker 容器内执行）。

用法：docker compose run --rm worker python scripts/test_ocr.py [/app/uploads/x.pdf]
"""

from __future__ import annotations

import sys
from pathlib import Path


def _check_imports() -> None:
    try:
        from rapidocr_onnxruntime import RapidOCR  # noqa: F401
        print("[OK] rapidocr_onnxruntime imported")
    except ImportError:
        print("[MISS] rapidocr_onnxruntime — run inside Docker OCR Worker")
        raise SystemExit(1)

    try:
        import fitz
        print(f"[OK] pymupdf imported ({getattr(fitz, 'version', ('?',))[0]})")
    except ImportError:
        print("[MISS] pymupdf")
        raise SystemExit(1)


def _run_ocr(file_path: str) -> None:
    from pipeline.parser.base import RawDocument
    from pipeline.parser.paddleocr_fallback import OCRFallback

    path = Path(file_path)
    if not path.is_file():
        raise SystemExit(f"file not found: {file_path}")

    mime = "application/pdf" if path.suffix.lower() == ".pdf" else "image/png"
    doc = RawDocument(
        file_id="ocr-test",
        file_path=str(path),
        file_name=path.name,
        mime_type=mime,
    )
    result = OCRFallback().parse(doc)
    print(f"success={result.success} confidence={result.confidence:.3f}")
    print(f"parser={result.metadata.get('parser')}")
    if result.error:
        print(f"error={result.error}")
    preview = (result.markdown or "").strip().replace("\n", " ")[:300]
    print(f"text_preview={preview!r}")


def main() -> None:
    _check_imports()
    if len(sys.argv) > 1:
        _run_ocr(sys.argv[1])
    else:
        print("[SKIP] no file arg — import check only")


if __name__ == "__main__":
    main()
