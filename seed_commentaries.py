"""
Seed `commentaries` and `context_cards` from the HelloAO Free Use Bible API.

FIXED 2026-09-05: the first live run inserted zero commentaries and zero
context cards despite reporting "success." Root cause found: this script's
book-code URLs used `osis_code.upper()` (this project's own codes, e.g. "Gen"
-> "GEN", "Exod" -> "EXOD"), but the HelloAO API uses the real standard USFM
3-letter book codes (e.g. Exodus is "EXO", not "EXOD"; 1 Samuel is "1SA", not
"1SAM"). Fixed with an explicit OSIS -> USFM mapping below.

SECOND FIX 2026-09-05: after fixing the book codes, the run crashed with
"sequence item 0: expected str instance, list found" -- the real API response
nests content deeper (lists inside lists) than the original extract_text()
assumed. Replaced with _flatten_to_strings(), which recursively pulls every
string leaf out of any nesting depth.

Confirmed real endpoints (https://bible.helloao.org):
  GET /api/available_commentaries.json           -> list of commentary ids
  GET /api/c/{commentary}/books.json              -> books available
  GET /api/c/{commentary}/{USFM_BOOK}/{chapter}.json -> chapter commentary text

PUBLIC DOMAIN commentaries seeded here (confirmed via TJ-Frederick/TheologAI's
own NOTICE.md): Matthew Henry, Jamieson-Fausset-Brown (JFB), Adam Clarke,
John Gill, Keil-Delitzsch (OT only).

DELIBERATELY EXCLUDED: Tyndale Open Study Notes -- confirmed CC BY-SA 4.0
(share-alike, attribution required), a different license tier than the rest
of this Tier 1 layer.

For `context_cards`: stores real commentary text in `content_en`, leaves the
structured author/audience/date/location fields NULL when not cleanly
extractable -- an honest partial fill, not a fabricated complete one.

Run: python seed_commentaries.py
"""
import json
import requests
from tqdm import tqdm
from _client import supabase, batch_upsert
from books_data import BOOKS

API_BASE = "https://bible.helloao.org/api"

PUBLIC_DOMAIN_COMMENTARIES = [
    ("matthew-henry", "Matthew Henry", "Matthew Henry's Complete Commentary on the Whole Bible", 1710),
    ("jfb", "Jamieson, Fausset & Brown", "A Commentary, Critical and Explanatory, on the Whole Bible", 1871),
    ("adam-clarke", "Adam Clarke", "Adam Clarke's Commentary on the Bible", 1831),
    ("john-gill", "John Gill", "John Gill's Exposition of the Bible", 1748),
    ("keil-delitzsch", "Keil & Delitzsch", "Commentary on the Old Testament", 1861),
]

OVERVIEW_COMMENTARY_ID = "matthew-henry"

OSIS_TO_USFM = {
    "Gen": "GEN", "Exod": "EXO", "Lev": "LEV", "Num": "NUM", "Deut": "DEU",
    "Josh": "JOS", "Judg": "JDG", "Ruth": "RUT", "1Sam": "1SA", "2Sam": "2SA",
    "1Kgs": "1KI", "2Kgs": "2KI", "1Chr": "1CH", "2Chr": "2CH", "Ezra": "EZR",
    "Neh": "NEH", "Esth": "EST", "Job": "JOB", "Ps": "PSA", "Prov": "PRO",
    "Eccl": "ECC", "Song": "SNG", "Isa": "ISA", "Jer": "JER", "Lam": "LAM",
    "Ezek": "EZK", "Dan": "DAN", "Hos": "HOS", "Joel": "JOL", "Amos": "AMO",
    "Obad": "OBA", "Jonah": "JON", "Mic": "MIC", "Nah": "NAM", "Hab": "HAB",
    "Zeph": "ZEP", "Hag": "HAG", "Zech": "ZEC", "Mal": "MAL",
    "Matt": "MAT", "Mark": "MRK", "Luke": "LUK", "John": "JHN", "Acts": "ACT",
    "Rom": "ROM", "1Cor": "1CO", "2Cor": "2CO", "Gal": "GAL", "Eph": "EPH",
    "Phil": "PHP", "Col": "COL", "1Thess": "1TH", "2Thess": "2TH",
    "1Tim": "1TI", "2Tim": "2TI", "Titus": "TIT", "Phlm": "PHM", "Heb": "HEB",
    "Jas": "JAS", "1Pet": "1PE", "2Pet": "2PE", "1John": "1JN", "2John": "2JN",
    "3John": "3JN", "Jude": "JUD", "Rev": "REV",
}


def seed_commentary_metadata():
    resp = requests.get(f"{API_BASE}/available_commentaries.json", timeout=30)
    resp.raise_for_status()
    available = resp.json()
    if isinstance(available, list):
        available_ids = {c.get("id") for c in available}
    elif isinstance(available, dict) and "commentaries" in available:
        available_ids = {c.get("id") for c in available["commentaries"]}
    else:
        available_ids = set(available.keys()) if isinstance(available, dict) else set()
    print(f"  API reports {len(available_ids)} available commentaries: {available_ids}")

    existing_resp = supabase.table("commentaries").select("id, author, title").execute()
    existing_keys = {(row["author"], row["title"]) for row in existing_resp.data}

    inserted = 0
    for commentary_id, author, title, year in PUBLIC_DOMAIN_COMMENTARIES:
        if commentary_id not in available_ids:
            print(f"  WARN '{commentary_id}' not found in available_commentaries.json -- skipping")
            continue
        if (author, title) in existing_keys:
            continue
        supabase.table("commentaries").insert(
            {
                "author": author,
                "title": title,
                "publication_year": year,
                "publisher": None,
                "is_public_domain": True,
                "source_url": f"https://bible.helloao.org/api/c/{commentary_id}/books.json",
            }
        ).execute()
        inserted += 1
    print(f"  inserted {inserted} new commentary rows ({len(existing_keys)} already existed)")


def _flatten_to_strings(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, dict):
        parts = []
        for key in ("text", "content"):
            if key in value:
                parts.extend(_flatten_to_strings(value[key]))
        return parts
    if isinstance(value, (list, tuple)):
        parts = []
        for item in value:
            parts.extend(_flatten_to_strings(item))
        return parts
    return []


def extract_text(data):
    if not isinstance(data, dict):
        return None
    for key in ("content", "text", "commentary", "html", "body"):
        if key in data:
            strings = _flatten_to_strings(data[key])
            joined = " ".join(strings).strip()
            if joined:
                return joined
    for wrapper_key in ("chapter", "commentary", "data"):
        if wrapper_key in data and isinstance(data[wrapper_key], dict):
            nested = extract_text(data[wrapper_key])
            if nested:
                return nested
    return None


def seed_overview_context_cards():
    books_resp = supabase.table("books").select("id, osis_code, name_en").execute()
    osis_to_book = {row["osis_code"]: row for row in books_resp.data}

    books_avail_resp = requests.get(f"{API_BASE}/c/{OVERVIEW_COMMENTARY_ID}/books.json", timeout=30)
    if books_avail_resp.status_code != 200:
        print(f"  WARN could not fetch book list for '{OVERVIEW_COMMENTARY_ID}' -- skipping context cards")
        return

    rows = []
    printed_sample = False
    for order, testament, osis_code, name_en, chapter_count in tqdm(BOOKS, desc="Context cards"):
        book = osis_to_book.get(osis_code)
        usfm_code = OSIS_TO_USFM.get(osis_code)
        if not book or not usfm_code:
            continue

        url = f"{API_BASE}/c/{OVERVIEW_COMMENTARY_ID}/{usfm_code}/1.json"
        resp = requests.get(url, timeout=30)
        if resp.status_code != 200:
            if not printed_sample:
                print(f"  WARN first request failed: {url} -> HTTP {resp.status_code}")
            continue

        data = resp.json()
        if not printed_sample:
            print(f"  sample response from {url}:")
            print(f"  {json.dumps(data, indent=2)[:1500]}")
            printed_sample = True

        text = extract_text(data)
        if not text:
            continue

        rows.append(
            {
                "book_id": book["id"],
                "chapter_start": 1,
                "chapter_end": 1,
                "author_of_book": None,
                "audience": None,
                "date_written": None,
                "location_written": None,
                "commentary_id": None,
                "cited_page": None,
                "content_en": text[:5000],
            }
        )

    if rows:
        existing_resp = supabase.table("context_cards").select("id, book_id, chapter_start, chapter_end").execute()
        existing_keys = {(r["book_id"], r["chapter_start"], r["chapter_end"]) for r in existing_resp.data}
        new_rows = [r for r in rows if (r["book_id"], r["chapter_start"], r["chapter_end"]) not in existing_keys]
        for i in range(0, len(new_rows), 500):
            supabase.table("context_cards").insert(new_rows[i:i + 500]).execute()
        print(f"  inserted {len(new_rows)} new context cards ({len(rows) - len(new_rows)} already existed)")
    else:
        print("  no context cards extracted -- check the sample response printed above")


def run():
    print("Seeding commentary metadata...")
    seed_commentary_metadata()
    print("Seeding overview context cards...")
    seed_overview_context_cards()
    print("Commentaries + context cards seeding complete.")


if __name__ == "__main__":
    run()
