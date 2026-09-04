"""
Seed `cross_references` from the Treasury of Scripture Knowledge dataset.

CORRECTED SCHEMA UNDERSTANDING (fixed 2026-09-04 after the first live run
failed with a 404, which led to properly confirming the real file structure
instead of re-guessing): the real `cross_reference` table does NOT use book
NAME strings as this script originally assumed. It uses a compact NUMERIC
verse-id: BOOK(2 digits) + CHAPTER(3 digits) + VERSE(3 digits), e.g.
Genesis 1:1 = 01001001, Exodus 2:3 = 02002003 — confirmed directly from the
source project's own README ("Verse ID System" section, revans/bible_databases
and geauxtigers/bible_databases, both long-lived forks of the original
scrollmapper project predating its 2025 schema rewrite). Book numbers 1-66
follow the standard Protestant canon order (1=Genesis ... 66=Revelation),
which matches this project's own `books.book_order` column directly — no
name-matching needed, just decode the digits.

The MySQL dump's INSERT statements for this table are therefore 4-column
tuples: (id, from_id, to_id, votes) — NOT the 9-column
(id, from_book, from_chapter, from_verse, to_book, to_chapter, to_verse,
to_verse_end, votes) shape this script originally assumed. Fixed below.

File location: `cross_references-mysql.sql` at the REPO ROOT — confirmed
directly from two independent forks' own file listings (not the original
scrollmapper/bible_databases repo, whose exact branch/path for this era
couldn't be pinned down after multiple attempts — these forks are
long-standing, well-known mirrors of the same original project and MIT
licensed same as the original).

License: CC BY — attribution to openbible.info required in-app. Underlying TSK
data itself is public domain.

Run: python seed_tsk_crossrefs.py
"""
import re
import requests
from tqdm import tqdm
from _client import supabase, batch_upsert

# Real, confirmed-to-exist mirrors of the original scrollmapper project, both
# describing this exact file at repo root in their own file listings.
CANDIDATE_URLS = [
    "https://raw.githubusercontent.com/geauxtigers/bible_databases/master/cross_references-mysql.sql",
    "https://raw.githubusercontent.com/revans/bible_databases/master/cross_references-mysql.sql",
]

# Matches: (id, from_id, to_id, votes) — all four are plain integers.
INSERT_ROW_RE = re.compile(r"\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(-?\d+)\s*\)")


def decode_verse_id(numeric_id):
    """01001001 -> (book_order=1, chapter=1, verse=1)."""
    s = str(numeric_id).zfill(8)
    book_order = int(s[0:2])
    chapter = int(s[2:5])
    verse = int(s[5:8])
    return book_order, chapter, verse


def get_verse_id_map():
    """canonical (book_id, chapter, verse) -> our internal verses.id, plus
    book_order -> book_id."""
    books_resp = supabase.table("books").select("id, book_order").execute()
    book_id_by_order = {row["book_order"]: row["id"] for row in books_resp.data}

    verse_map = {}
    start = 0
    page_size = 1000
    while True:
        resp = (
            supabase.table("verses")
            .select("id, book_id, chapter, verse")
            .range(start, start + page_size - 1)
            .execute()
        )
        if not resp.data:
            break
        for row in resp.data:
            verse_map[(row["book_id"], row["chapter"], row["verse"])] = row["id"]
        if len(resp.data) < page_size:
            break
        start += page_size

    return book_id_by_order, verse_map


def run():
    print("Loading book and verse maps...")
    book_id_by_order, verse_map = get_verse_id_map()
    if not verse_map:
        raise RuntimeError("verses table is empty — run seed_kjv.py first.")
    print(f"  loaded {len(book_id_by_order)} books, {len(verse_map)} verses")

    print("Fetching TSK cross-references SQL dump...")
    sql_text = None
    working_url = None
    for url in CANDIDATE_URLS:
        try:
            resp = requests.get(url, timeout=120)
            if resp.status_code == 200 and len(resp.text) > 1000:
                sql_text = resp.text
                working_url = url
                print(f"  found it at: {url}")
                break
            else:
                print(f"  x {url} -> HTTP {resp.status_code}")
        except requests.RequestException as e:
            print(f"  x {url} -> {e}")

    if sql_text is None:
        raise RuntimeError(
            "None of the candidate URLs worked. Manually check "
            "https://github.com/geauxtigers/bible_databases in a browser "
            "for the real current file path and add it to CANDIDATE_URLS."
        )
    print(f"  downloaded {len(sql_text) / 1e6:.1f} MB from {working_url}")

    # Narrow to just the cross_reference table's INSERT block if the dump
    # contains multiple tables, so the regex doesn't accidentally match
    # unrelated numeric tuples elsewhere in the file.
    table_start = sql_text.lower().find("insert into `cross_reference`")
    if table_start == -1:
        table_start = sql_text.lower().find("insert into cross_reference")
    search_text = sql_text[table_start:] if table_start != -1 else sql_text

    matches = INSERT_ROW_RE.findall(search_text)
    print(f"  regex matched {len(matches)} candidate rows")
    if not matches:
        raise RuntimeError(
            "0 rows matched -- the INSERT statement format differs from what "
            "INSERT_ROW_RE expects. Inspect the first part of the downloaded "
            "file to see the real format and adjust the regex."
        )

    rows = []
    skipped = 0
    for id_str, from_id_str, to_id_str, votes_str in tqdm(matches, desc="Mapping"):
        from_book_order, from_ch, from_v = decode_verse_id(from_id_str)
        to_book_order, to_ch, to_v = decode_verse_id(to_id_str)

        from_book_id = book_id_by_order.get(from_book_order)
        to_book_id = book_id_by_order.get(to_book_order)
        from_vid = verse_map.get((from_book_id, from_ch, from_v))
        to_vid = verse_map.get((to_book_id, to_ch, to_v))
        if not from_vid or not to_vid:
            skipped += 1
            continue

        rows.append(
            {
                "from_verse_id": from_vid,
                "to_verse_id": to_vid,
                "source": "tsk",
                "relevance_rank": int(votes_str),
            }
        )

    print(f"  mapped {len(rows)} cross-references ({skipped} skipped -- book/verse not matched, "
          f"expected for any refs outside the 66-book canon)")
    batch_upsert("cross_references", rows, on_conflict="from_verse_id,to_verse_id,source")
    print("TSK cross-reference seeding complete.")


if __name__ == "__main__":
    run()
