"""
Seed KJV text into `manuscript_texts` (source='kjv'), creating the canonical
`verses` rows as a side effect (KJV is used as the verse-numbering backbone since
it's the most complete/standard versification).

Source: aruljohn/Bible-kjv (GitHub) — one JSON file per book, public domain text.
https://github.com/aruljohn/Bible-kjv

NOTE: verify the exact JSON key names against the current repo before running —
GitHub raw file layout can shift. Expected shape per book file:
{
  "book": "Genesis",
  "chapters": [
    {"chapter": 1, "verses": [{"verse": 1, "text": "In the beginning..."}, ...]},
    ...
  ]
}

Run: python seed_kjv.py
"""
import requests
from tqdm import tqdm
from _client import supabase, batch_upsert
from books_data import BOOKS

RAW_BASE = "https://raw.githubusercontent.com/aruljohn/Bible-kjv/master"

# aruljohn/Bible-kjv uses full book names with underscores as filenames, e.g. Genesis.json
def source_filename(name_en: str) -> str:
    return name_en.replace(" ", "") + ".json"


def get_book_id_map():
    resp = supabase.table("books").select("id, osis_code, name_en").execute()
    return {row["name_en"]: row["id"] for row in resp.data}, {
        row["osis_code"]: row["id"] for row in resp.data
    }


def run():
    name_to_id, _ = get_book_id_map()
    if not name_to_id:
        raise RuntimeError("books table is empty — run seed_books.py first.")

    for order, testament, osis_code, name_en, chapter_count in tqdm(BOOKS, desc="Books"):
        book_id = name_to_id.get(name_en)
        if not book_id:
            print(f"  SKIP {name_en} — not found in books table")
            continue

        url = f"{RAW_BASE}/{source_filename(name_en)}"
        resp = requests.get(url, timeout=30)
        if resp.status_code != 200:
            print(f"  WARN could not fetch {name_en} ({resp.status_code}) — check filename format")
            continue

        data = resp.json()
        verse_rows = []
        for chapter in data.get("chapters", []):
            ch_num = int(chapter["chapter"])
            for verse in chapter.get("verses", []):
                v_num = int(verse["verse"])
                canonical_ref = f"{osis_code.upper()}.{ch_num}.{v_num}"
                verse_rows.append(
                    {
                        "book_id": book_id,
                        "chapter": ch_num,
                        "verse": v_num,
                        "canonical_ref": canonical_ref,
                        "_text": verse["text"],  # stripped before insert, used below
                    }
                )

        # 1. Upsert verses (without _text) to get IDs
        verse_insert_rows = [
            {k: v for k, v in row.items() if k != "_text"} for row in verse_rows
        ]
        batch_upsert("verses", verse_insert_rows, on_conflict="canonical_ref")

        # 2. Fetch back verse IDs for this book
        vresp = (
            supabase.table("verses")
            .select("id, canonical_ref")
            .eq("book_id", book_id)
            .execute()
        )
        ref_to_id = {row["canonical_ref"]: row["id"] for row in vresp.data}

        # 3. Upsert manuscript_texts (kjv)
        text_rows = []
        for row in verse_rows:
            vid = ref_to_id.get(row["canonical_ref"])
            if not vid:
                continue
            text_rows.append(
                {
                    "verse_id": vid,
                    "source": "kjv",
                    "text_content": row["_text"],
                    "source_edition": "KJV 1769 (Blayney) — public domain",
                }
            )
        batch_upsert("manuscript_texts", text_rows, on_conflict="verse_id,source")

    print("KJV seeding complete.")


if __name__ == "__main__":
    run()
