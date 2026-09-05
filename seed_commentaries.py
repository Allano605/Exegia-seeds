"""
Seed `commentaries` and `context_cards` from the HelloAO Free Use Bible API.

FIXED 2026-09-05: the first live run inserted zero commentaries and zero
context cards despite reporting "success." Root cause found: this script's
book-code URLs used `osis_code.upper()` (this project's own codes, e.g. "Gen"
-> "GEN", "Exod" -> "EXOD"), but the HelloAO API uses the real standard USFM
3-letter book codes (e.g. Exodus is "EXO", not "EXOD"; 1 Samuel is "1SA", not
"1SAM"). For Genesis specifically the two schemes coincide ("GEN" either way),
which is why the very first book didn't visibly 404 and the mismatch wasn't
obvious from a quick look -- but the content still wasn't being extracted
correctly, and every other multi-letter book's URL was wrong. Confirmed the
real USFM codes from a Rust crate's own documentation ("faith" crate: "USFM
66-book canonical table with HelloAO ID mapping") describing exactly this
scheme. Fixed below with an explicit OSIS -> USFM mapping (reusing the same
real mapping already verified for seed_vulgate.py's USFX codes, since USFX and
USFM use the same 3-letter book abbreviations).

Confirmed real endpoints (https://bible.helloao.org):
  GET /api/available_commentaries.json           -> list of commentary ids
  GET /api/c/{commentary}/books.json              -> books available
  GET /api/c/{commentary}/{USFM_BOOK}/{chapter}.json -> chapter commentary text

PUBLIC DOMAIN commentaries seeded here (confirmed via TJ-Frederick/TheologAI's
own NOTICE.md, which documents licensing per commentary against this same
API): Matthew Henry, Jamieson-Fausset-Brown (JFB), Adam Clarke, John Gill,
Keil-Delitzsch (OT only).

DELIBERATELY EXCLUDED: Tyndale Open Study Notes -- confirmed CC BY-SA 4.0
(share-alike, attribution required), a different license tier than the rest
of this Tier 1 layer. Seed separately with honest attribution if wanted.

For `context_cards`: this API gives verse/chapter-level commentary prose, not
the structured (author/audience/date/location) fields the schema's other
columns are designed for. This script stores the real commentary text in
`content_en` and leaves author_of_book/audience/date_written/location_written
as NULL when not cleanly extractable -- an honest partial fill, not a
fabricated complete one. Uses Matthew Henry's chapter 1 remarks for each book
as the "overview" card, since Henry's commentary conventionally opens each
book with introductory context.

The exact JSON field holding the chapter text still hasn't been confirmed
against a live fetch of this specific commentary endpoint (only the Bible-TEXT
endpoint's field name, "content", was confirmed via a third-party Lua wrapper).
This script tries several plausible field names AND prints the full raw JSON
of the very first successful response, so if the real field name still
doesn't match, the fix is immediately visible in the logs rather than another
silent zero.

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
    """Populate the `commentaries` table. `commentaries.id` has no other
    unique constraint, so this checks by (author, title) before inserting to
    keep re-runs idempotent rather than duplicating."""
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
            print(f"  WARN '{commentary_id}' not found in available_commentaries.json -- "
                  f"skipping; check the id against the live API response above")
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


def extract_text(data):
    """Try several plausible field names/shapes for the chapter commentary
    text. Returns None if nothing usable is found."""
    if not isinstance(data, dict):
        return None
    for key in ("content", "text", "commentary", "html", "body"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val
        if isinstance(val, list) and val:
            parts = []
            for item in val:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    parts.append(item.get("text") or item.get("content") or "")
            joined = " ".join(p for p in parts if p)
            if joined.strip():
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
        print("  no context cards extracted -- check the sample response printed above "
              "and adjust extract_text() to match its real shape")


def run():
    print("Seeding commentary metadata...")
    seed_commentary_metadata()
    print("Seeding overview context cards...")
    seed_overview_context_cards()
    print("Commentaries + context cards seeding complete.")


if __name__ == "__main__":
    run()
