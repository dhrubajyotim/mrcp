"""
parse_pdf.py — Ingests a PassMedicine PDF into the MCQ database.
Uses PyMuPDF (fitz) for fast lazy-loading of large PDFs.

Usage:
    python parse_pdf.py                        # parse all questions
    python parse_pdf.py --limit 10             # parse first 10 questions only
    python parse_pdf.py --limit 5 --debug      # parse 5 questions with verbose output
    python parse_pdf.py --peek-rects           # dump rect colors from first question page
"""

import argparse
import json
import os
import re
import sys

import fitz  # PyMuPDF

from database import SessionLocal, engine
from models import Base, Question

Base.metadata.create_all(bind=engine)

PDF_PATH = "1.Cardiology MRCP 1 Passmedicine 2024.pdf"

# ── Noise patterns ────────────────────────────────────────────────────────────

_NOISE_RE = [
    re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4},\s*\d+:\d+\s*[AP]M$"),
    re.compile(r"^https?://\S+$"),
    re.compile(r"^PassMedicine$", re.IGNORECASE),
    re.compile(r"^Discuss\s*\(\d+\)$"),
    re.compile(r"^Important\s+for\s+me\s+Less\s+important$"),
    re.compile(r"^Next\s+question$"),
    re.compile(r"^Improve$"),
    re.compile(r"^\d+/\d+$"),
]

# Inline fragments to strip from within a line (date/time, PassMedicine, page headers)
_STRIP_RE = re.compile(
    r"\d{1,2}/\d{1,2}/\d{2,4},\s*\d+:\d+\s*[AP]M\s*"
    r"|PassMedicine\s*"
    r"|Question\s+\d+\s+of\s+\d+\s*"
    r"|https?://\S+\s*"
    r"|Discuss\s*\(\d+\)\s*"
    r"|Important\s+for\s+me\s+Less\s+important\s*"
    r"|\bNext\s+question\b\s*"
    r"|\bImprove\b\s*"
    r"|\b\d+/\d+\b\s*"
)

QUESTION_HEADER_RE = re.compile(r"Question\s+(\d+)\s+of\s+\d+")
OPTION_WITH_PCT_RE = re.compile(r"^(.+?)\s+(\d{1,3})%$")
PCT_ONLY_RE        = re.compile(r"^(\d{1,3})%$")
TOPIC_RE           = re.compile(r"^[A-Z][A-Za-z /,()-]+:\s+[A-Za-z]")


def _is_noise(line: str) -> bool:
    line = line.strip()
    if not line:
        return True
    return any(p.match(line) for p in _NOISE_RE)


# ── Green detection (PyMuPDF colors are 0-1 RGB tuples) ──────────────────────

def _is_greenish(color) -> bool:
    if not color or not hasattr(color, "__len__") or len(color) < 3:
        return False
    r, g, b = float(color[0]), float(color[1]), float(color[2])
    return g > 0.35 and g > r * 1.2 and g > b * 1.2


def _correct_opt_from_drawings(page: fitz.Page, options: list[str]) -> str | None:
    """Find the correct option by matching a green drawing rect to nearby text."""
    if not options:
        return None

    # Build {y_top: line_text} from page word blocks
    words = page.get_text("words")  # (x0,y0,x1,y1,word,block,line,word_idx)
    line_map: dict[int, list[str]] = {}
    for w in words:
        y_key = round(w[1])  # y0 of word
        line_map.setdefault(y_key, []).append(w[4])

    for drawing in page.get_drawings():
        fill = drawing.get("fill")
        if not _is_greenish(fill):
            continue
        rect = drawing.get("rect")
        if not rect:
            continue
        r_top, r_bot = rect.y0, rect.y1

        for y_key, words_on_line in line_map.items():
            if r_top - 10 <= y_key <= r_bot + 10:
                line_text = " ".join(words_on_line)
                for opt in options:
                    if opt.lower() in line_text.lower() or line_text.lower() in opt.lower():
                        return opt
    return None


# ── Option extraction ─────────────────────────────────────────────────────────

def _extract_options(lines: list[str]) -> tuple[list[str], list[str]]:
    options: list[str] = []
    skip: set[int] = set()

    # Pass 1: "Option text XX%"
    for i, line in enumerate(lines):
        m = OPTION_WITH_PCT_RE.match(line)
        if m:
            options.append(m.group(1).strip())
            skip.add(i)

    # Pass 2: option on one line, "XX%" on next
    if not options:
        for i, line in enumerate(lines):
            if PCT_ONLY_RE.match(line):
                skip.add(i)
                for j in range(i - 1, -1, -1):
                    if j not in skip and lines[j].strip():
                        options.append(lines[j].strip())
                        skip.add(j)
                        break

    remaining = [l for idx, l in enumerate(lines) if idx not in skip]
    return options, remaining


# ── Question block parser ─────────────────────────────────────────────────────

def _parse_block(q_num: int, page_texts: list[str], page_objs: list[fitz.Page]) -> dict | None:
    all_lines: list[str] = []
    for txt in page_texts:
        for raw_line in txt.splitlines():
            # Strip inline noise fragments first, then check if whole line is noise
            line = _STRIP_RE.sub("", raw_line).strip()
            if not _is_noise(line):
                all_lines.append(line)

    if not all_lines:
        return None

    stem_idx = next((i for i, l in enumerate(all_lines) if l.endswith("?")), None)
    if stem_idx is None:
        return None

    scenario  = " ".join(all_lines[:stem_idx]).strip()
    stem      = all_lines[stem_idx].strip()
    after_stem = all_lines[stem_idx + 1:]

    options, remainder = _extract_options(after_stem)

    # Correct answer: green rect on first page → tagline word-match fallback
    correct_opt = _correct_opt_from_drawings(page_objs[0], options) if page_objs else None

    tagline = remainder[0].strip() if remainder else None

    if not correct_opt and tagline and options:
        tagline_lower = tagline.lower()
        best, best_score = None, 0
        for opt in options:
            score = sum(1 for w in opt.lower().split() if len(w) > 3 and w in tagline_lower)
            if score > best_score:
                best_score, best = score, opt
        if best_score > 0:
            correct_opt = best

    topic = next((l for l in remainder if TOPIC_RE.match(l)), None)
    explanation_lines = [l for l in remainder[1:] if l != topic and l.strip()]
    explanation = "\n".join(explanation_lines)

    if len(options) < 2:
        return None

    while len(options) < 5:
        options.append(None)

    return {
        "number":      q_num,
        "scenario":    scenario,
        "stem":        stem,
        "opt_1":       options[0],
        "opt_2":       options[1],
        "opt_3":       options[2],
        "opt_4":       options[3],
        "opt_5":       options[4],
        "correct_opt": correct_opt or options[0],
        "explanation": explanation or "See explanation in original material.",
        "topic":       topic,
        "tagline":     tagline,
    }


# ── PDF page grouper ──────────────────────────────────────────────────────────

def _group_pages(pdf_path: str) -> dict[int, dict]:
    groups: dict[int, dict] = {}
    current_q: int | None = None

    print(f"Opening: {pdf_path}")
    doc = fitz.open(pdf_path)
    total = len(doc)
    print(f"Total pages: {total}")

    for i in range(total):
        if i % 200 == 0:
            print(f"  Scanning page {i + 1}/{total}…")
        page = doc[i]
        # sort=True orders blocks top-to-bottom so options aren't shuffled with explanation
        text = page.get_text("text", sort=True) or ""
        m = QUESTION_HEADER_RE.search(text)
        if m:
            current_q = int(m.group(1))
            if current_q not in groups:
                groups[current_q] = {"texts": [], "pages": []}
        if current_q is not None:
            groups[current_q]["texts"].append(text)
            groups[current_q]["pages"].append(page)

    print(f"Found {len(groups)} question groups.\n")
    return groups, doc  # return doc so pages stay valid


# ── Image extraction ──────────────────────────────────────────────────────────

def _extract_question_images(doc: fitz.Document, pages: list, q_number: int) -> list:
    """Extract images ≥200×80px from a question's pages.

    Saves files under static/images/q{q_number}/ and returns relative paths
    (relative to static/) used as URL fragments: /static/images/q1/0.png
    """
    q_dir = os.path.join("static", "images", f"q{q_number}")
    os.makedirs(q_dir, exist_ok=True)

    seen_xrefs: set = set()
    paths: list = []

    for page in pages:
        # img_info tuple: (xref, smask, width, height, bpc, cs, alt_cs, name, filter, referencer)
        for img_info in page.get_images(full=True):
            xref = img_info[0]
            w    = img_info[2]
            h    = img_info[3]
            if xref in seen_xrefs or w < 200 or h < 80:
                continue
            seen_xrefs.add(xref)

            try:
                base = doc.extract_image(xref)
            except Exception:
                continue

            img_bytes = base.get("image", b"")
            if not img_bytes:
                continue

            ext      = base.get("ext", "png")
            filename = f"{len(paths)}.{ext}"
            filepath = os.path.join(q_dir, filename)
            with open(filepath, "wb") as fh:
                fh.write(img_bytes)

            paths.append(f"images/q{q_number}/{filename}")

    return paths


# ── Images-only updater (skips text re-parse) ─────────────────────────────────

def extract_images_only(limit: int | None = None, debug: bool = False):
    """Scan the PDF and fill the images column for all existing DB questions."""
    from database import SessionLocal, run_migrations
    run_migrations()

    doc = fitz.open(PDF_PATH)
    total = len(doc)
    print(f"Opening {PDF_PATH} ({total} pages) — images-only mode")

    groups: dict = {}
    current_q: int | None = None
    for i in range(total):
        if i % 200 == 0:
            print(f"  Scanning page {i + 1}/{total}…")
        page = doc[i]
        text = page.get_text("text") or ""
        m = QUESTION_HEADER_RE.search(text)
        if m:
            current_q = int(m.group(1))
            if current_q not in groups:
                groups[current_q] = []
        if current_q is not None:
            groups[current_q].append(page)

    db = SessionLocal()
    q_numbers = sorted(groups.keys())
    if limit:
        q_numbers = q_numbers[:limit]

    updated = 0
    for q_num in q_numbers:
        q = db.query(Question).filter(Question.number == q_num).first()
        if not q:
            continue
        imgs = _extract_question_images(doc, groups[q_num], q_num)
        q.images = json.dumps(imgs) if imgs else None
        db.commit()
        updated += 1
        if debug and imgs:
            print(f"  Q{q_num}: {len(imgs)} image(s) -> {imgs}")

    doc.close()
    db.close()
    print(f"\nDone. Updated images for {updated} questions.")


# ── Diagnostic ────────────────────────────────────────────────────────────────

def peek_rects(pdf_path: str):
    doc = fitz.open(pdf_path)
    for i in range(min(15, len(doc))):
        page = doc[i]
        text = page.get_text("text") or ""
        if QUESTION_HEADER_RE.search(text):
            print("=== Drawings on first question page ===")
            for d in page.get_drawings():
                fill = d.get("fill")
                rect = d.get("rect")
                print(f"  rect={rect}  fill={fill}  green={_is_greenish(fill)}")
            break
    doc.close()


# ── Main ──────────────────────────────────────────────────────────────────────

def run(limit: int | None = None, debug: bool = False):
    groups, doc = _group_pages(PDF_PATH)
    q_numbers = sorted(groups.keys())
    if limit:
        q_numbers = q_numbers[:limit]

    db = SessionLocal()
    inserted = skipped = failed = 0

    for q_num in q_numbers:
        if db.query(Question).filter(Question.number == q_num).first():
            skipped += 1
            continue

        parsed = _parse_block(q_num, groups[q_num]["texts"], groups[q_num]["pages"])
        if not parsed:
            print(f"  FAILED to parse Q{q_num}")
            failed += 1
            continue

        if debug:
            opts = [o for o in [parsed["opt_1"], parsed["opt_2"], parsed["opt_3"],
                                 parsed["opt_4"], parsed["opt_5"]] if o]
            stem_preview = parsed["stem"][:70]
            print(f"Q{q_num}: {stem_preview}…")
            print(f"  Options : {opts}")
            print(f"  Correct : {parsed['correct_opt']}")
            print(f"  Topic   : {parsed['topic']}")
            print()
        imgs = _extract_question_images(doc, groups[q_num]["pages"], q_num)
        parsed["images"] = json.dumps(imgs) if imgs else None
        db.add(Question(**parsed))
        db.commit()
        inserted += 1

    doc.close()
    db.close()
    print(f"\nDone. Inserted={inserted}  Skipped(already in DB)={skipped}  Failed={failed}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Parse PassMedicine PDF into MCQ database.")
    parser.add_argument("--limit", type=int, default=None, help="Only parse first N questions")
    parser.add_argument("--debug", action="store_true", help="Print each parsed question")
    parser.add_argument("--peek-rects", action="store_true", help="Dump drawing colors and exit")
    parser.add_argument("--images-only", action="store_true",
                        help="Only extract/update images for existing DB questions (skip text re-parse)")
    args = parser.parse_args()

    if args.peek_rects:
        peek_rects(PDF_PATH)
        sys.exit(0)

    if args.images_only:
        extract_images_only(limit=args.limit, debug=args.debug)
        sys.exit(0)

    run(limit=args.limit, debug=args.debug)
