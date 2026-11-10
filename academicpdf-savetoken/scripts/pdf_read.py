"""Local, page-addressable MarkItDown cache and bounded retrieval. Python 3.10+."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
from importlib.metadata import version

SCHEMA = 1


def digest(data):
    return hashlib.sha256(data).hexdigest()


def emit(data):
    print(json.dumps(data, ensure_ascii=False, indent=2))


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_manifest(directory):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest["schema"] != SCHEMA:
        raise ValueError("Unsupported cache schema; run prepare again")
    for name, expected in manifest["files"].items():
        target = (directory / name).resolve()
        if not target.is_relative_to(directory.resolve()):
            raise ValueError("Invalid cache path")
        if digest(target.read_bytes()) != expected:
            raise ValueError("Cache integrity check failed; run prepare again")
    return manifest


def prepare(pdf, cache):
    from markitdown import MarkItDown
    from pypdf import PdfReader, PdfWriter

    source = Path(pdf).resolve()
    raw = source.read_bytes()
    if not raw.startswith(b"%PDF-"):
        raise ValueError("Input must be a local PDF file")
    source_hash = digest(raw)
    config = {"schema": SCHEMA, "mode": "markitdown-per-page-local-no-plugins",
              "versions": {p: version(p) for p in ("markitdown", "pypdf", "pdfminer.six")},
              "implementation": digest(Path(__file__).read_bytes())}
    key = digest((source_hash + json.dumps(config, sort_keys=True)).encode())
    root = Path(cache).resolve()
    root.mkdir(parents=True, exist_ok=True)
    dest = root / key
    for candidate in [dest, *sorted(root.glob(key + "-recovered-*"))]:
        try:
            existing = load_manifest(candidate)
            if existing["source_sha256"] == source_hash and existing["config"] == config:
                return {"cache_hit": True, "cache_dir": str(candidate),
                        "pages": existing["pages"], "warnings": existing["warnings"]}
        except (OSError, ValueError, KeyError):
            pass
    reader = PdfReader(io.BytesIO(raw))
    if reader.is_encrypted:
        raise ValueError("Encrypted PDF: provide an authorized decrypted local copy")
    if not len(reader.pages):
        raise ValueError("PDF has no pages")
    converter = MarkItDown(enable_plugins=False)
    stage = Path(tempfile.mkdtemp(prefix=".building-", dir=root))
    try:
        (stage / "pages").mkdir()
        index, chunks, warnings = [], [], []
        for number, page in enumerate(reader.pages, 1):
            writer = PdfWriter()
            writer.add_page(page)
            stream = io.BytesIO()
            writer.write(stream)
            stream.seek(0)
            result = converter.convert_stream(stream, file_extension=".pdf")
            body = result.text_content.strip()
            flags = []
            if len(re.sub(r"\s", "", body)) < 80:
                flags.append("sparse_text: inspect if this page is needed; scan/figure/blank possible")
            if "\ufffd" in body or "(cid:" in body:
                flags.append("suspicious_glyphs: verify symbols visually")
            if flags:
                warnings.append({"page": number, "flags": flags})
            text = f"<!-- physical PDF page {number} -->\n\n{body}\n"
            name = f"pages/{number:04d}.md"
            (stage / name).write_text(text, encoding="utf-8")
            chunks.append(text)
            index.append({"page": number, "file": name, "characters": len(body),
                          "preview": re.sub(r"\s+", " ", body)[:160],
                          "heading_candidates": re.findall(r"(?m)^#{1,6} .+$", body)[:12],
                          "flags": flags})
        (stage / "document.md").write_text("\n".join(chunks), encoding="utf-8")
        write_json(stage / "index.json", {"source_sha256": source_hash, "pages": index})
        files = {p.relative_to(stage).as_posix(): digest(p.read_bytes())
                 for p in stage.rglob("*") if p.is_file()}
        manifest = {"schema": SCHEMA, "source_sha256": source_hash,
                    "config": config, "pages": len(index), "warnings": warnings, "files": files}
        write_json(stage / "manifest.json", manifest)
        # Never overwrite an existing cache tree: preserve damaged/older material.
        if dest.exists():
            dest = root / (key + "-recovered-" + stage.name.removeprefix(".building-"))
        stage.rename(dest)
        return {"cache_hit": False, "cache_dir": str(dest), "pages": len(index), "warnings": warnings}
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def select_pages(spec, count):
    selected = set()
    for part in spec.split(","):
        match = re.fullmatch(r"(\d+)(?:-(\d+))?", part.strip())
        if not match:
            raise ValueError("Pages must be like 2,4-6")
        first = int(match[1])
        last = int(match[2] or first)
        if not 1 <= first <= last <= count:
            raise ValueError(f"Pages must be between 1 and {count}")
        selected.update(range(first, last + 1))
    return sorted(selected)


def read_pages(directory, pages, offset, maximum):
    manifest = load_manifest(directory)
    numbers = select_pages(pages, manifest["pages"])
    text = "\n".join((Path(directory) / f"pages/{n:04d}.md").read_text(encoding="utf-8") for n in numbers)
    if not 0 <= offset <= len(text):
        raise ValueError("Offset outside selected text")
    end = min(offset + maximum, len(text))
    return {"source_sha256": manifest["source_sha256"], "pages": numbers,
            "offset": offset, "total_characters": len(text), "returned_characters": end-offset,
            "truncated": end < len(text), "next_offset": end if end < len(text) else None,
            "text": text[offset:end]}


def search(directory, query, limit):
    if not query.strip():
        raise ValueError("Search query must not be empty")
    manifest = load_manifest(directory)
    matches = []
    total = 0
    for n in range(1, manifest["pages"] + 1):
        text = (Path(directory) / f"pages/{n:04d}.md").read_text(encoding="utf-8")
        for match in re.finditer(re.escape(query), text, re.IGNORECASE):
            total += 1
            if len(matches) < limit:
                matches.append({"page": n, "line": text.count("\n", 0, match.start()) + 1,
                                "snippet": text[max(0, match.start()-120):match.start()+280]})
    return {"matches": matches, "total_matches": total, "truncated": total > limit}


def render(pdf, page_number, out, dpi, bbox):
    import pypdfium2 as pdfium

    raw = Path(pdf).read_bytes()
    source_hash = digest(raw)
    with pdfium.PdfDocument(raw) as document:
        if not 1 <= page_number <= len(document):
            raise ValueError(f"Page must be between 1 and {len(document)}")
        if bbox and not (0 <= bbox[0] < bbox[2] <= 1 and 0 <= bbox[1] < bbox[3] <= 1):
            raise ValueError("bbox must satisfy 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1")
        page = document[page_number - 1]
        try:
            bitmap = page.render(scale=dpi/72, draw_annots=True)
            try:
                picture = bitmap.to_pil().copy()
            finally:
                bitmap.close()
        finally:
            page.close()
        if bbox:
            w, h = picture.size
            picture = picture.crop((int(bbox[0]*w), int(bbox[1]*h),
                                    max(int(bbox[0]*w)+1, int(bbox[2]*w)),
                                    max(int(bbox[1]*h)+1, int(bbox[3]*h))))
        folder = Path(out).resolve()
        folder.mkdir(parents=True, exist_ok=True)
        suffix = digest(json.dumps([dpi, bbox]).encode())[:12]
        target = folder / f"{source_hash[:16]}-p{page_number:04d}-{suffix}.png"
        picture.save(target)
        metadata = {"source_sha256": source_hash, "physical_page": page_number,
                    "dpi": dpi, "bbox_top_left_normalized": bbox,
                    "image": str(target), "pixels": list(picture.size)}
        write_json(target.with_suffix(".json"), metadata)
        return metadata


def bounded_int(low, high):
    def parse(value):
        n = int(value)
        if not low <= n <= high:
            raise argparse.ArgumentTypeError(f"Expected {low}..{high}")
        return n
    return parse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare")
    p.add_argument("pdf")
    p.add_argument("--cache", default=".academicpdf-cache")
    p = commands.add_parser("read")
    p.add_argument("directory")
    p.add_argument("--pages", required=True)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--max-chars", type=bounded_int(1, 100000), default=12000)
    p = commands.add_parser("search")
    p.add_argument("directory")
    p.add_argument("query")
    p.add_argument("--limit", type=bounded_int(1, 100), default=12)
    p = commands.add_parser("render")
    p.add_argument("pdf")
    p.add_argument("--page", type=int, required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--dpi", type=bounded_int(72, 300), default=144)
    p.add_argument("--bbox", nargs=4, type=float)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            result = prepare(args.pdf, args.cache)
        elif args.command == "read":
            result = read_pages(args.directory, args.pages, args.offset, args.max_chars)
        elif args.command == "search":
            result = search(args.directory, args.query, args.limit)
        else:
            result = render(args.pdf, args.page, args.out, args.dpi, args.bbox)
        emit(result)
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
