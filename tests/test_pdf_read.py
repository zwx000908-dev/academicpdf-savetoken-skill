import importlib.util
import json
from pathlib import Path

import pytest
from PIL import Image
from reportlab.pdfgen import canvas
from pypdf import PdfReader, PdfWriter

SCRIPT = Path(__file__).parents[1] / "academicpdf-savetoken/scripts/pdf_read.py"
spec = importlib.util.spec_from_file_location("pdf_read", SCRIPT)
pdf_read = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdf_read)


@pytest.fixture
def paper(tmp_path):
    path = tmp_path / "paper with spaces.pdf"
    c = canvas.Canvas(str(path), pagesize=(400, 500))
    c.drawString(30, 460, "Synthetic paper: selective evidence retrieval")
    c.drawString(30, 430, "A quantum yield of 0.42 was measured at 450 nm.")
    c.drawString(30, 400, "This is a software test fixture, not research evidence.")
    c.showPage()
    c.drawString(30, 460, "Figure 1. A blue vector rectangle (synthetic).")
    c.setFillColorRGB(0, 0, 1)
    c.rect(40, 100, 300, 200, fill=1)
    c.showPage()
    image = Image.new("RGB", (100, 100), "red")
    from reportlab.lib.utils import ImageReader
    c.drawImage(ImageReader(image), 50, 150, width=200, height=200)
    c.showPage()
    c.save()
    return path


def test_conversion_cache_and_search(paper, tmp_path):
    first = pdf_read.prepare(paper, tmp_path / "cache")
    assert not first["cache_hit"] and first["pages"] == 3
    second = pdf_read.prepare(paper, tmp_path / "cache")
    assert second["cache_hit"] and second["cache_dir"] == first["cache_dir"]
    hits = pdf_read.search(first["cache_dir"], "QUANTUM YIELD", 12)
    assert hits["matches"][0]["page"] == 1
    assert hits["total_matches"] == 1
    assert "0.42" in hits["matches"][0]["snippet"]
    assert 3 in [w["page"] for w in first["warnings"]]


def test_read_continuation_no_loss(paper, tmp_path):
    prepared = pdf_read.prepare(paper, tmp_path / "cache")
    folder = prepared["cache_dir"]
    full = pdf_read.read_pages(folder, "1-2", 0, 100000)["text"]
    parts, offset = [], 0
    while True:
        data = pdf_read.read_pages(folder, "1-2", offset, 31)
        assert data["returned_characters"] <= 31
        parts.append(data["text"])
        if not data["truncated"]:
            break
        offset = data["next_offset"]
    assert "".join(parts) == full
    assert "physical PDF page 2" in full


def test_changed_pdf_and_corrupt_cache(paper, tmp_path):
    root = tmp_path / "cache"
    first = pdf_read.prepare(paper, root)
    md = Path(first["cache_dir"]) / "pages/0001.md"
    md.write_text("corrupted", encoding="utf-8")
    with pytest.raises(ValueError, match="integrity"):
        pdf_read.read_pages(first["cache_dir"], "1", 0, 100)
    repaired = pdf_read.prepare(paper, root)
    assert not repaired["cache_hit"]
    assert "0.42" in pdf_read.read_pages(repaired["cache_dir"], "1", 0, 10000)["text"]
    assert pdf_read.prepare(paper, root)["cache_hit"]
    paper.write_bytes(paper.read_bytes() + b"\n% new revision\n")
    changed = pdf_read.prepare(paper, root)
    assert not changed["cache_hit"] and changed["cache_dir"] != repaired["cache_dir"]


def test_render_vector_and_crop(paper, tmp_path):
    full = pdf_read.render(paper, 2, tmp_path / "visuals", 144, None)
    crop = pdf_read.render(paper, 2, tmp_path / "visuals", 144, [0, 0, 0.5, 0.5])
    assert full["pixels"] == [800, 1000]
    assert crop["pixels"] == [400, 500]
    with Image.open(full["image"]) as image:
        assert image.getpixel((200, 600))[:3] == (0, 0, 255)
    assert Path(crop["image"]).with_suffix(".json").is_file()
    assert len(list((tmp_path / "visuals").glob("*.png"))) == 2


@pytest.mark.parametrize("pages", ["0", "4", "2-1", "1-999999999", "foo"])
def test_bad_page_ranges(pages):
    with pytest.raises(ValueError):
        pdf_read.select_pages(pages, 3)


def test_bad_render_parameters(paper, tmp_path):
    with pytest.raises(ValueError):
        pdf_read.render(paper, 0, tmp_path, 144, None)
    with pytest.raises(ValueError):
        pdf_read.render(paper, 2, tmp_path, 144, [0.8, 0, 0.1, 1])


def test_encrypted_pdf(paper, tmp_path):
    writer = PdfWriter()
    writer.append(PdfReader(paper))
    writer.encrypt("test-password")
    locked = tmp_path / "locked.pdf"
    writer.write(locked)
    with pytest.raises(ValueError, match="Encrypted"):
        pdf_read.prepare(locked, tmp_path / "cache")


def test_search_limit_and_empty(paper, tmp_path):
    prepared = pdf_read.prepare(paper, tmp_path / "cache")
    hits = pdf_read.search(prepared["cache_dir"], "a", 1)
    assert len(hits["matches"]) == 1 and hits["truncated"]
    with pytest.raises(ValueError):
        pdf_read.search(prepared["cache_dir"], "", 1)
