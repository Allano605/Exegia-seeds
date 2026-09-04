"""
Seed `manuscript_texts` (source='hebrew_leningrad') and `word_occurrences` from the
OpenScriptures Hebrew Bible (OSHB), which digitizes the Leningrad Codex (BHS).
https://github.com/openscriptures/morphhb

License: CC BY 4.0 — attribution to OpenScriptures required in-app (e.g. an
"About this text" screen), per README.md.

OSHB ships one XML file per book (e.g. morphhb/wlc/Gen.xml) in OSIS format with
morphology per word, including Strong's numbers in `@lemma` attributes like
"b/7225" (b = prefix, 7225 = Strong's number without the H).

Requires `verses` to already be populated (run seed_kjv.py first) since Hebrew
verses attach to the same canonical_ref backbone.

Run: python seed_hebrew_leningrad.py
"""
import requests
from lxml import etree
from tqdm import tqdm
from _client import supabase, batch_upsert
from books_data import BOOKS

RAW_BASE = "https://raw.githubusercontent.com/openscriptures/morphhb/master/wlc"
NS = {"osis": "http://www.bibletechnologies.net/2003/OSIS/namespace"}


def get_verse_id_map(book_id):
    resp = (
        supabase.table("verses")
        .select("id, canonical_ref")
        .eq("book_id", book_id)
        .execute()
    )
    return {row["canonical_ref"]: row["id"] for row in resp.data}


def run():
    books_resp = supabase.table("books").select("id, osis_code").eq("testament", "old").execute()
    osis_to_id = {row["osis_code"]: row["id"] for row in books_resp.data}
    if not osis_to_id:
        raise RuntimeError("books table is empty or has no OT books — run seed_books.py first.")

    for order, testament, osis_code, name_en, chapter_count in tqdm(BOOKS, desc="OT Books"):
        if testament != "old":
            continue
        book_id = osis_to_id.get(osis_code)
        if not book_id:
            continue

        url = f"{RAW_BASE}/{osis_code}.xml"
        resp = requests.get(url, timeout=30)
        if resp.status_code != 200:
            print(f"  WARN could not fetch {osis_code} ({resp.status_code})")
            continue

        root = etree.fromstring(resp.content)
        ref_to_id = get_verse_id_map(book_id)

        text_rows = []
        word_rows = []

        for verse_el in root.iter("{http://www.bibletechnologies.net/2003/OSIS/namespace}verse"):
            osis_id = verse_el.get("osisID")  # e.g. "Gen.1.1"
            if not osis_id:
                continue
            canonical_ref = osis_id.upper()
            vid = ref_to_id.get(canonical_ref)
            if not vid:
                continue

            words = verse_el.findall("{http://www.bibletechnologies.net/2003/OSIS/namespace}w")
            full_text = " ".join(w.text for w in words if w.text)
            text_rows.append(
                {
                    "verse_id": vid,
                    "source": "hebrew_leningrad",
                    "text_content": full_text,
                    "source_edition": "OSHB / Leningrad Codex (BHS) — CC BY 4.0, attribution: OpenScriptures.org",
                }
            )

            for order_idx, w in enumerate(words, start=1):
                lemma = w.get("lemma", "")
                # lemma format examples: "7225", "b/7225", "7225 a" — take first numeric token
                strong_num = None
                for token in lemma.replace("/", " ").split():
                    if token.isdigit():
                        strong_num = f"H{int(token):04d}"
                        break
                word_rows.append(
                    {
                        "verse_id": vid,
                        "manuscript_source": "hebrew_leningrad",
                        "word_order": order_idx,
                        "surface_form": w.text or "",
                        "_strong_number": strong_num,  # resolved to lexicon_entry_id below
                    }
                )

        batch_upsert("manuscript_texts", text_rows, on_conflict="verse_id,source")

        # Resolve strong numbers -> lexicon_entry_id
        strong_nums = {r["_strong_number"] for r in word_rows if r["_strong_number"]}
        if strong_nums:
            lex_resp = (
                supabase.table("lexicon_entries")
                .select("id, strong_number")
                .eq("source", "strongs")
                .in_("strong_number", list(strong_nums))
                .execute()
            )
            strong_to_lexid = {row["strong_number"]: row["id"] for row in lex_resp.data}
        else:
            strong_to_lexid = {}

        final_word_rows = [
            {
                "verse_id": r["verse_id"],
                "manuscript_source": r["manuscript_source"],
                "word_order": r["word_order"],
                "surface_form": r["surface_form"],
                "lexicon_entry_id": strong_to_lexid.get(r["_strong_number"]),
            }
            for r in word_rows
        ]
        # word_occurrences has no natural unique key across re-runs other than
        # (verse_id, manuscript_source, word_order). Consider adding that as a unique
        # constraint in the schema for idempotent upserts; for now, clear this book's
        # Hebrew word rows before reinserting so re-runs don't duplicate.
        book_verse_ids = list(ref_to_id.values())
        if book_verse_ids:
            supabase.table("word_occurrences").delete().in_("verse_id", book_verse_ids).eq(
                "manuscript_source", "hebrew_leningrad"
            ).execute()
        for i in range(0, len(final_word_rows), 500):
            supabase.table("word_occurrences").insert(final_word_rows[i : i + 500]).execute()

    print("Hebrew (Leningrad/OSHB) seeding complete.")


if __name__ == "__main__":
    run()
