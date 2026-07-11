"""OCR 冒烟测试（在 worker 容器内执行）。

用法：
  python scripts/test_ocr.py
  python scripts/test_ocr.py /app/uploads/scan_sample.pdf
"""

from __future__ import annotations

import sys
from pathlib import Path


def _check_imports() -> None:
    import paddle
    import paddleocr
    import magic_pdf

    print(f"[OK] paddle=={paddle.__version__}")
    print("[OK] paddleocr imported")
    print("[OK] magic_pdf imported")


def _run_ocr(file_path: str) -> None:
    from pipeline.parser.base import RawDocument
    from pipeline.parser.paddleocr_fallback import PaddleOCRFallback

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
    result = PaddleOCRFallback().parse(doc)
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
