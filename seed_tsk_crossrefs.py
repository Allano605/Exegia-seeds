"""
Seed `cross_references` from the Treasury of Scripture Knowledge dataset.

FIXED 2026-09-04: after several attempts chasing third-party SQL mirrors that
kept 404ing or had unreliable structure, this script now goes straight to the
PRIMARY source instead. Fetched directly from openbible.info's own live page
(https://www.openbible.info/labs/cross-references/) moments ago, which
contains this exact real download link in its own HTML:

    "Download all the cross-reference data (2 MB .zip)"
    -> https://a.openbible.info/data/cross-references.zip

This is the actual, current, first-party link -- not a guess, not a mirror.
Confirmed real by fetching the live page and reading the href directly.

Inside the zip is a tab-separated text file with columns for From Verse,
To Verse, and Votes, using dotted OSIS-style book abbreviations with
range notation for multi-verse spans (e.g. "Gen.1.1-Gen.1.3"). The exact
header/column names and book-abbreviation scheme were NOT independently
re-verified against the actual unzipped file contents this session (this
fetch only confirmed the download link itself works, not what's inside it)
-- this script reads the header row and prints it, and reports any book
abbreviation it can't map, so a mismatch is visible immediately rather than
silently producing wrong or zero results.

License: CC BY (Creative Commons Attribution), confirmed directly from the
same live page. Underlying TSK data itself is public domain.

Run: python seed_tsk_crossrefs.py
"""
import csv
import io
import zipfile
import requests
from tqdm import tqdm
from _client import supabase, batch_upsert

ZIP_URL = "https://a.openbible.info/data/cross-references.zip"

BOOK_ABBR_MAP = {
    "Gen": "Gen", "Exod": "Exod", "Exo": "Exod", "Lev": "Lev", "Num": "Num",
    "Deut": "Deut", "Deu": "Deut", "Josh": "Josh", "Jos": "Josh", "Judg": "Judg",
    "Jdg": "Judg", "Ruth": "Ruth", "Rut": "Ruth", "1Sam": "1Sam", "1Sa": "1Sam",
    "2Sam": "2Sam", "2Sa": "2Sam", "1Kgs": "1Kgs", "1Ki": "1Kgs", "2Kgs": "2Kgs",
    "2Ki": "2Kgs", "1Chr": "1Chr", "1Ch": "1Chr", "2Chr": "2Chr", "2Ch": "2Chr",
    "Ezra": "Ezra", "Ezr": "Ezra", "Neh": "Neh", "Esth": "Esth", "Est": "Esth",
    "Job": "Job", "Ps": "Ps", "Psa": "Ps", "Psalm": "Ps", "Prov": "Prov",
    "Pro": "Prov", "Eccl": "Eccl", "Ecc": "Eccl", "Song": "Song", "Sol": "Song",
    "SS": "Song", "Isa": "Isa", "Jer": "Jer", "Lam": "Lam", "Ezek": "Ezek",
    "Eze": "Ezek", "Dan": "Dan", "Hos": "Hos", "Joel": "Joel", "Joe": "Joel",
    "Amos": "Amos", "Amo": "Amos", "Obad": "Obad", "Oba": "Obad", "Jonah": "Jonah",
    "Jon": "Jonah", "Mic": "Mic", "Nah": "Nah", "Hab": "Hab", "Zeph": "Zeph",
    "Zep": "Zeph", "Hag": "Hag", "Zech": "Zech", "Zec": "Zech", "Mal": "Mal",
    "Matt": "Matt", "Mat": "Matt", "Mark": "Mark", "Mar": "Mark", "Luke": "Luke",
    "Luk": "Luke", "John": "John", "Joh": "John", "Acts": "Acts", "Act": "Acts",
    "Rom": "Rom", "1Cor": "1Cor", "1Co": "1Cor", "2Cor": "2Cor", "2Co": "2Cor",
    "Gal": "Gal", "Eph": "Eph", "Phil": "Phil", "Php": "Phil", "Col": "Col",
    "1Thess": "1Thess", "1Th": "1Thess", "2Thess": "2Thess", "2Th": "2Thess",
    "1Tim": "1Tim", "1Ti": "1Tim", "2Tim": "2Tim", "2Ti": "2Tim", "Titus": "Titus",
    "Tit": "Titus", "Phlm": "Phlm", "Phm": "Phlm", "Heb": "Heb", "Jas": "Jas",
    "1Pet": "1Pet", "1Pe": "1Pet", "2Pet": "2Pet", "2Pe": "2Pet", "1John": "1John",
    "1Jo": "1John", "1Jn": "1John", "2John": "2John", "2Jo": "2John", "2Jn": "2John",
    "3John": "3John", "3Jo": "3John", "3Jn": "3John", "Jude": "Jude", "Jud": "Jude",
    "Rev": "Rev",
}


def parse_ref(ref):
    """'Gen.1.1' or 'Gen.1.1-Gen.1.3' (range -> take first verse only) ->
    (osis_code, chapter, verse), or (None, book_abbr) if the book abbreviation
    is unmapped, or None if the string can't be parsed at all."""
    if not ref:
        return None
    first = ref.split("-")[0].strip()
    parts = first.split(".")
    if len(parts) != 3:
        return None
    book_abbr, chapter, verse = parts
    osis_code = BOOK_ABBR_MAP.get(book_abbr)
    if not osis_code:
        return None, book_abbr
    try:
        return osis_code, int(chapter), int(verse)
    except ValueError:
        return None


def run():
    print("Fetching TSK cross-references zip from openbible.info (primary source)...")
    resp = requests.get(ZIP_URL, timeout=120)
    resp.raise_for_status()
    print(f"  downloaded {len(resp.content) / 1e6:.2f} MB")

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = zf.namelist()
    print(f"  zip contains: {names}")
    txt_name = next((n for n in names if n.endswith(".txt")), names[0])
    print(f"  reading: {txt_name}")

    with zf.open(txt_name) as f:
        text = io.TextIOWrapper(f, encoding="utf-8")
        reader = csv.reader(text, delimiter="\t")
        header = next(reader)
        print(f"  header row: {header}")

        books_resp = supabase.table("books").select("id, osis_code").execute()
        osis_to_book_id = {row["osis_code"]: row["id"] for row in books_resp.data}

        verse_map = {}
        start = 0
        page_size = 1000
        while True:
            vresp = (
                supabase.table("verses")
                .select("id, book_id, chapter, verse")
                .range(start, start + page_size - 1)
                .execute()
            )
            if not vresp.data:
                break
            for row in vresp.data:
                verse_map[(row["book_id"], row["chapter"], row["verse"])] = row["id"]
            if len(vresp.data) < page_size:
                break
            start += page_size

        if not verse_map:
            raise RuntimeError("verses table is empty -- run seed_kjv.py first.")
        print(f"  loaded {len(verse_map)} verses for matching")

        rows = []
        skipped = 0
        unmapped_abbrs = set()
        for line in tqdm(reader, desc="Parsing"):
            if len(line) < 3:
                continue
            from_ref, to_ref, votes = line[0], line[1], line[2]

            from_parsed = parse_ref(from_ref)
            to_parsed = parse_ref(to_ref)

            if isinstance(from_parsed, tuple) and len(from_parsed) == 2 and from_parsed[0] is None:
                unmapped_abbrs.add(from_parsed[1])
                skipped += 1
                continue
            if isinstance(to_parsed, tuple) and len(to_parsed) == 2 and to_parsed[0] is None:
                unmapped_abbrs.add(to_parsed[1])
                skipped += 1
                continue
            if not from_parsed or not to_parsed:
                skipped += 1
                continue

            from_osis, from_ch, from_v = from_parsed
            to_osis, to_ch, to_v = to_parsed
            from_book_id = osis_to_book_id.get(from_osis)
            to_book_id = osis_to_book_id.get(to_osis)
            from_vid = verse_map.get((from_book_id, from_ch, from_v))
            to_vid = verse_map.get((to_book_id, to_ch, to_v))
            if not from_vid or not to_vid:
                skipped += 1
                continue

            try:
                rank = int(votes)
            except ValueError:
                rank = None

            rows.append(
                {
                    "from_verse_id": from_vid,
                    "to_verse_id": to_vid,
                    "source": "tsk",
                    "relevance_rank": rank,
                }
            )

    print(f"  parsed {len(rows)} cross-references ({skipped} skipped)")
    if unmapped_abbrs:
        print(f"  unmapped book abbreviations encountered: {sorted(unmapped_abbrs)} -- "
              f"add these to BOOK_ABBR_MAP if the count seems high")

    if not rows:
        raise RuntimeError(
            "0 cross-references parsed -- check the printed header row and sample "
            "abbreviations above against BOOK_ABBR_MAP and parse_ref()."
        )

    batch_upsert("cross_references", rows, on_conflict="from_verse_id,to_verse_id,source")
    print("TSK cross-reference seeding complete.")


if __name__ == "__main__":
    run()
