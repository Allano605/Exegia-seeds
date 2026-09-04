"""
Seed `manuscript_texts` (source='greek_sblgnt') and `word_occurrences` from
MorphGNT/SBLGNT. https://github.com/morphgnt/sblgnt

VERIFIED FORMAT (checked 2026-09-03 against real sample lines quoted in the
project's own issue tracker, github.com/morphgnt/sblgnt/issues/44):

  160220 A- ----NPN- χρυσᾶ χρυσᾶ χρυσᾶ χρύσεος
  270920 A- ----APN- χρυσᾶ χρυσᾶ χρυσᾶ χρυσοῦς

7 space-delimited columns (confirmed against the project's own SQLite-conversion
docs): citation, part_of_speech_code, parsing_code, punctuated_text,
unpunctuated_text, normalized_word, lemma.

The `citation` field is BOOK+CHAPTER+VERSE digits with NO word index — multiple
consecutive rows share the same citation for words in the same verse, and word
order is simply the row order within the file. Confirmed from the two real
samples above: "160220" = book 16 (2 Timothy, in the NT-relative 1-27 numbering
used internally — Matt=1 ... Rev=27) + chapter 02 + verse 20 → 2 Tim 2:20, which
does mention "vessels of gold" (χρυσᾶ). "270920" = book 27 (Revelation) +
chapter 09 + verse 20 → Rev 9:20, which also mentions gold idols. Both check out
against the actual verse content, confirming the parse.

Because the book-number digit count isn't fixed-width in a way that's safe to
guess (and because we already know which book we're processing from the loop),
this script takes chapter/verse from the LAST 4 DIGITS of the citation
(chapter=2 digits, verse=2 digits) rather than trying to parse the book number
out of the string. No NT book has a chapter or verse count reaching 100, so this
is safe.

LICENSE FLAG: SBLGNT text itself is subject to the SBLGNT EULA (free to
distribute, cannot be sold standalone, and needs written permission from SBL if
it makes up >25% of a commercial work — see https://sblgnt.com/license/). The
morphological tagging/lemmatization from MorphGNT is CC-BY-SA.

Requires `verses` to already be populated (run seed_kjv.py first).

Run: python seed_greek_sblgnt.py
"""
import requests
from tqdm import tqdm
from _client import supabase, batch_upsert
from books_data import BOOKS

RAW_BASE = "https://raw.githubusercontent.com/morphgnt/sblgnt/master"

# MorphGNT filenames use a different numbering (61-Mt through 87-Re, apparently
# counting Apocrypha before the NT) than the internal citation field (1-27,
# Matt-Rev) — the filename mapping was independently confirmed against the
# repo's own file tree in a prior session.
MORPHGNT_FILES = {
    "Matt": "61-Mt", "Mark": "62-Mk", "Luke": "63-Lk", "John": "64-Jn",
    "Acts": "65-Ac", "Rom": "66-Ro", "1Cor": "67-1Co", "2Cor": "68-2Co",
    "Gal": "69-Ga", "Eph": "70-Eph", "Phil": "71-Php", "Col": "72-Col",
    "1Thess": "73-1Th", "2Thess": "74-2Th", "1Tim": "75-1Ti", "2Tim": "76-2Ti",
    "Titus": "77-Tit", "Phlm": "78-Phm", "Heb": "79-Heb", "Jas": "80-Jas",
    "1Pet": "81-1Pe", "2Pet": "82-2Pe", "1John": "83-1Jn", "2John": "84-2Jn",
    "3John": "85-3Jn", "Jude": "86-Jud", "Rev": "87-Re",
}


def get_verse_id_map(book_id):
    resp = (
        supabase.table("verses")
        .select("id, canonical_ref")
        .eq("book_id", book_id)
        .execute()
    )
    return {row["canonical_ref"]: row["id"] for row in resp.data}


def run():
    books_resp = supabase.table("books").select("id, osis_code").eq("testament", "new").execute()
    osis_to_id = {row["osis_code"]: row["id"] for row in books_resp.data}
    if not osis_to_id:
        raise RuntimeError("books table has no NT books — run seed_books.py first.")

    # Lemma-text-to-lexicon-id matching (MorphGNT gives lemma text, not a Strong's
    # number directly — first-pass match by headword text; expect some manual
    # cleanup for accented-form mismatches or homonyms).
    lex_resp = (
        supabase.table("lexicon_entries")
        .select("id, headword")
        .eq("source", "strongs")
        .execute()
    )
    headword_to_lexid = {row["headword"]: row["id"] for row in lex_resp.data if row["headword"]}

    for order, testament, osis_code, name_en, chapter_count in tqdm(BOOKS, desc="NT Books"):
        if testament != "new":
            continue
        book_id = osis_to_id.get(osis_code)
        file_prefix = MORPHGNT_FILES.get(osis_code)
        if not book_id or not file_prefix:
            continue

        url = f"{RAW_BASE}/{file_prefix}-morphgnt.txt"
        resp = requests.get(url, timeout=30)
        if resp.status_code != 200:
            print(f"  WARN could not fetch {osis_code} ({resp.status_code})")
            continue

        ref_to_id = get_verse_id_map(book_id)
        verse_words = {}  # canonical_ref -> list of (punctuated_text, lemma)

        bad_lines = 0
        for line in resp.text.splitlines():
            parts = line.split()
            if len(parts) != 7:
                bad_lines += 1
                continue
            citation, pos_code, parsing_code, punctuated, unpunctuated, normalized, lemma = parts
            if len(citation) < 4 or not citation.isdigit():
                bad_lines += 1
                continue
            chapter = int(citation[-4:-2])
            verse = int(citation[-2:])
            canonical_ref = f"{osis_code.upper()}.{chapter}.{verse}"
            verse_words.setdefault(canonical_ref, []).append((punctuated, lemma))

        if bad_lines:
            print(f"  {osis_code}: {bad_lines} lines did not match the expected "
                  f"7-column format — investigate before trusting this book's data.")

        text_rows = []
        word_rows = []
        for canonical_ref, words in verse_words.items():
            vid = ref_to_id.get(canonical_ref)
            if not vid:
                continue
            text_rows.append(
                {
                    "verse_id": vid,
                    "source": "greek_sblgnt",
                    "text_content": " ".join(w[0] for w in words),
                    "source_edition": "SBLGNT — free with attribution, commercial use needs SBL permission (sblgnt.com/license)",
                }
            )
            for order_idx, (surface_form, lemma) in enumerate(words, start=1):
                word_rows.append(
                    {
                        "verse_id": vid,
                        "manuscript_source": "greek_sblgnt",
                        "word_order": order_idx,
                        "surface_form": surface_form,
                        "lexicon_entry_id": headword_to_lexid.get(lemma),
                    }
                )

        batch_upsert("manuscript_texts", text_rows, on_conflict="verse_id,source")

        book_verse_ids = list(ref_to_id.values())
        if book_verse_ids:
            supabase.table("word_occurrences").delete().in_("verse_id", book_verse_ids).eq(
                "manuscript_source", "greek_sblgnt"
            ).execute()
        for i in range(0, len(word_rows), 500):
            supabase.table("word_occurrences").insert(word_rows[i : i + 500]).execute()

    print("Greek (SBLGNT) seeding complete.")


if __name__ == "__main__":
    run()
