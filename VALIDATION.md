# Validation record

Date: 2026-11-10 (Asia/Hong_Kong).

- Windows, Python 3.13.13; MarkItDown 0.1.9, pypdf 6.21.4, pypdfium2 5.15.2, Pillow 13.0.0.
- `python -m pytest -q`: **12 passed** (13.56 seconds).
- Skill creator `quick_validate.py`: **Skill is valid!** Run with `python -X utf8` on Windows if the system default encoding is not UTF-8.
- CLI `prepare` smoke test: produced a 3-page Markdown cache; warned on the sparse vector-figure page and the image-only page.
- Visual inspection: rendered PDF page 2 retained the synthetic figure caption and blue vector rectangle, with correct orientation.

The synthetic fixture contains prose with a known numerical value, a vector diagram with a caption, and an image-only page. Tests cover cache hits, source changes, corrupted-cache recovery, physical page retrieval, bounded search, exact reconstruction from read continuations, rendering/cropping, invalid ranges, and encrypted-input rejection.

The GitHub Actions workflow is configured for Windows and Ubuntu on Python 3.11 and 3.13; its remote execution status must be checked separately. Local success does not establish those results.

Not validated: representative real-paper corpus accuracy, multi-column order fidelity, OCR accuracy, scientific interpretation, or real provider token/billing savings. No copyrighted papers are distributed.
