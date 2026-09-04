"""
Seed `commentaries` and `context_cards` from the HelloAO Free Use Bible API.

VERIFIED SOURCE (checked 2026-09-04): https://bible.helloao.org — a real,
documented, no-auth-required, MIT-licensed API (confirmed via its own docs at
bible.helloao.org/docs/guide/making-requests.html and independently confirmed
via a third-party project, TJ-Frederick/TheologAI, which uses the same API and
explicitly documents in its own NOTICE.md which commentaries are public domain
vs. licensed).

Confirmed real endpoints:
  GET /api/available_commentaries.json           -> list of commentary ids
  GET /api/c/{commentary}/books.json              -> books available
  GET /api/c/{commentary}/{OSIS_BOOK}/{chapter}.json -> chapter commentary text

PUBLIC DOMAIN commentaries seeded here (confirmed via TheologAI's NOTICE.md,
which treats these as public-domain source texts): Matthew Henry,
Jamieson-Fausset-Brown (JFB), Adam Clarke, John Gill, Keil-Delitzsch (OT only).

DELIBERATELY EXCLUDED: Tyndale Open Study Notes, which the same source
confirms is CC BY-SA 4.0 (share-alike, attribution required) — a different
license tier than the rest of this Tier 1 layer. If you want Tyndale content
later, seed it separately with its own `is_public_domain = false` /
attribution handling, don't merge it into this "pure" set.

For `context_cards`: this API gives verse/chapter-level commentary prose, not
the structured (author/audience/date/location) fields the schema's other
columns are designed for. Rather than force unstructured prose into those
structured fields, this script stores the real commentary text in
`content_en` and leaves author_of_book/audience/date_written/location_written
as NULL when not cleanly extractable — an honest partial fill, not a
fabricated complete one. Uses Matthew Henry's chapter 1 remarks for each book
as the "overview" card, since Henry's commentary conventionally opens each
book with introductory context.

Run: python seed_commentaries.py
"""
import requests
from tqdm import tqdm
from _client import supabase, batch_upsert
from books_data import BOOKS

API_BASE = "https://bible.helloao.org/api"

# (commentary_id_on_helloao, author, display title, approx publication year)
PUBLIC_DOMAIN_COMMENTARIES = [
    ("matthew-henry", "Matthew Henry", "Matthew Henry's Complete Commentary on the Whole Bible", 1710),
    ("jfb", "Jamieson, Fausset & Brown", "A Commentary, Critical and Explanatory, on the Whole Bible", 1871),
    ("adam-clarke", "Adam Clarke", "Adam Clarke's Commentary on the Bible", 1831),
    ("john-gill", "John Gill", "John Gill's Exposition of the Bible", 1748),
    ("keil-delitzsch", "Keil & Delitzsch", "Commentary on the Old Testament", 1861),
]

OVERVIEW_COMMENTARY_ID = "matthew-henry"


def seed_commentary_metadata():
    """Populate the `commentaries` table. Cross-checks against the API's own
    available_commentaries.json and warns if an expected id isn't listed
    there (source projects do rename/remove things).

    NOTE: `commentaries.id` is an auto-generated serial with no other unique
    constraint in the schema, so there's nothing real to upsert against —
    using on_conflict="id" here would be pretending a constraint exists that
    doesn't. Instead, this checks for an existing row by (author, title)
    before inserting, so re-running this script doesn't silently duplicate
    rows. If you want a real upsert instead, add a unique constraint on
    (author, title) to the schema first.
    """
    resp = requests.get(f"{API_BASE}/available_commentaries.json", timeout=30)
    resp.raise_for_status()
    available = resp.json()
    available_ids = {c.get("id") for c in available} if isinstance(available, list) else set(available.keys())
    print(f"  API reports {len(available_ids)} available commentaries: {available_ids}")

    existing_resp = supabase.table("commentaries").select("id, author, title").execute()
    existing_keys = {(row["author"], row["title"]) for row in existing_resp.data}

    inserted = 0
    for commentary_id, author, title, year in PUBLIC_DOMAIN_COMMENTARIES:
        if commentary_id not in available_ids:
            print(f"  WARN '{commentary_id}' not found in available_commentaries.json — "
                  f"skipping; check the id against the live API response above")
            continue
        if (author, title) in existing_keys:
            continue  # already seeded, skip rather than duplicate
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


def seed_overview_context_cards():
    """One context card per book, using Matthew Henry's chapter-1 remarks as
    the overview text. Real prose from a real public-domain source — not a
    fabricated author/date/audience breakdown."""
    books_resp = supabase.table("books").select("id, osis_code, name_en").execute()
    osis_to_book = {row["osis_code"]: row for row in books_resp.data}

    # Get Matthew Henry's own commentary-id so we know it's really listed.
    books_avail_resp = requests.get(f"{API_BASE}/c/{OVERVIEW_COMMENTARY_ID}/books.json", timeout=30)
    if books_avail_resp.status_code != 200:
        print(f"  WARN could not fetch book list for '{OVERVIEW_COMMENTARY_ID}' — skipping context cards")
        return

    rows = []
    for order, testament, osis_code, name_en, chapter_count in tqdm(BOOKS, desc="Context cards"):
        book = osis_to_book.get(osis_code)
        if not book:
            continue
        url = f"{API_BASE}/c/{OVERVIEW_COMMENTARY_ID}/{osis_code.upper()}/1.json"
        resp = requests.get(url, timeout=30)
        if resp.status_code != 200:
            continue
        data = resp.json()
        # Response shape not fully pinned down in this session — grab whatever
        # text field is present and print the raw keys once so you can adjust
        # this extraction if the real shape differs.
        text = None
        if isinstance(data, dict):
            for key in ("content", "text", "commentary", "html"):
                if key in data and isinstance(data[key], str):
                    text = data[key]
                    break
            if text is None and "content" in data and isinstance(data["content"], list):
                text = " ".join(str(item) for item in data["content"])
        if not text:
            if order == 1:  # only print this diagnostic once, not for all 66 books
                print(f"  WARN unexpected response shape from {url}: keys = "
                      f"{list(data.keys()) if isinstance(data, dict) else type(data)}. "
                      f"Adjust the extraction logic in seed_overview_context_cards().")
            continue

        rows.append(
            {
                "book_id": book["id"],
                "chapter_start": 1,
                "chapter_end": 1,
                "author_of_book": None,   # not cleanly extractable from prose — honest NULL
                "audience": None,
                "date_written": None,
                "location_written": None,
                "commentary_id": None,    # set this to the real commentaries.id after seed_commentary_metadata() runs, via a lookup join if you want it populated
                "cited_page": None,
                "content_en": text[:5000],  # cap length; this is an overview card, not the full chapter
            }
        )

    if rows:
        # Same issue as commentaries: context_cards.id has no other unique
        # constraint to upsert against. Check for an existing card covering
        # this exact book+chapter range before inserting, to keep re-runs
        # idempotent instead of duplicating.
        existing_resp = supabase.table("context_cards").select("id, book_id, chapter_start, chapter_end").execute()
        existing_keys = {(r["book_id"], r["chapter_start"], r["chapter_end"]) for r in existing_resp.data}
        new_rows = [
            r for r in rows
            if (r["book_id"], r["chapter_start"], r["chapter_end"]) not in existing_keys
        ]
        for i in range(0, len(new_rows), 500):
            supabase.table("context_cards").insert(new_rows[i:i + 500]).execute()
        print(f"  inserted {len(new_rows)} new context cards ({len(rows) - len(new_rows)} already existed)")
    else:
        print("  no context cards to insert")


def run():
    print("Seeding commentary metadata...")
    seed_commentary_metadata()
    print("Seeding overview context cards...")
    seed_overview_context_cards()
    print("Commentaries + context cards seeding complete.")


if __name__ == "__main__":
    run()
