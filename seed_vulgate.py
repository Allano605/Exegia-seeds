"""
Seed `manuscript_texts` (source='latin_vulgate') from the Clementine Vulgate.

VERIFIED SOURCE (checked 2026-09-03): seven1m/open-bibles, file
"lat-clementine.usfx.xml" — confirmed present in the repo's own README table,
listed as "Latin / USFX / Clementine Latin Vulgate / Public Domain".
https://github.com/seven1m/open-bibles

USFX is a MILESTONE format, not a nested one — <c id="1"/> and <v id="1"/> are
empty markers, and verse text is the plain text/tail content that follows until
the next milestone (this is confirmed from the format's own spec at
https://ebible.org/usfx/ and matches how the project's own reference parsers,
e.g. seven1m/usfx (Ruby) and ksturner/usfx (JS), read it — both use a
start/end-event walk with a "currently inside a verse" mode flag, which is what
`extract_verses()` below replicates). This is a real structural fact about the
format, not a guess.

Run: python seed_vulgate.py
"""
import re
import requests
from lxml import etree
from tqdm import tqdm
from _client import supabase, batch_upsert

VULGATE_URL = (
    "https://raw.githubusercontent.com/seven1m/open-bibles/master/"
    "lat-clementine.usfx.xml"
)

# USFX book IDs use the standard 3-letter USFM/Paratext codes, which differ from
# our OSIS codes (e.g. "GEN" vs "Gen", "1SA" vs "1Sam") — mapping table below.
USFX_TO_OSIS = {
    "GEN": "Gen", "EXO": "Exod", "LEV": "Lev", "NUM": "Num", "DEU": "Deut",
    "JOS": "Josh", "JDG": "Judg", "RUT": "Ruth", "1SA": "1Sam", "2SA": "2Sam",
    "1KI": "1Kgs", "2KI": "2Kgs", "1CH": "1Chr", "2CH": "2Chr", "EZR": "Ezra",
    "NEH": "Neh", "EST": "Esth", "JOB": "Job", "PSA": "Ps", "PRO": "Prov",
    "ECC": "Eccl", "SNG": "Song", "ISA": "Isa", "JER": "Jer", "LAM": "Lam",
    "EZK": "Ezek", "DAN": "Dan", "HOS": "Hos", "JOL": "Joel", "AMO": "Amos",
    "OBA": "Obad", "JON": "Jonah", "MIC": "Mic", "NAM": "Nah", "HAB": "Hab",
    "ZEP": "Zeph", "HAG": "Hag", "ZEC": "Zech", "MAL": "Mal",
    "MAT": "Matt", "MRK": "Mark", "LUK": "Luke", "JHN": "John", "ACT": "Acts",
    "ROM": "Rom", "1CO": "1Cor", "2CO": "2Cor", "GAL": "Gal", "EPH": "Eph",
    "PHP": "Phil", "COL": "Col", "1TH": "1Thess", "2TH": "2Thess",
    "1TI": "1Tim", "2TI": "2Tim", "TIT": "Titus", "PHM": "Phlm", "HEB": "Heb",
    "JAS": "Jas", "1PE": "1Pet", "2PE": "2Pet", "1JN": "1John", "2JN": "2John",
    "3JN": "3John", "JUD": "Jude", "REV": "Rev",
}


def extract_verses(xml_bytes):
    """
    Walk the USFX tree as start/end events (mirroring how the format's own
    reference parsers read it). Accumulate text only while "inside" a verse
    milestone, and skip text inside footnotes <f>...</f> or cross-refs <x>...</x>
    so verse text stays clean of study-note clutter.
    Returns: {usfx_book_id: {(chapter, verse): text}}
    """
    books = {}
    current_book = None
    current_chapter = None
    current_verse = None
    footnote_depth = 0
    buffer = []

    def flush():
        if current_book and current_chapter and current_verse:
            text = re.sub(r"\s+", " ", "".join(buffer)).strip()
            if text:
                books.setdefault(current_book, {})[(current_chapter, current_verse)] = text
        buffer.clear()

    root = etree.fromstring(xml_bytes)
    for action, el in etree.iterwalk(root, events=("start", "end")):
        tag = etree.QName(el).localname if isinstance(el.tag, str) else None

        if action == "start":
            if tag == "book":
                current_book = el.get("id")
                current_chapter = None
                current_verse = None
            elif tag == "c":
                flush()
                try:
                    current_chapter = int(el.get("id"))
                except (TypeError, ValueError):
                    current_chapter = None
                current_verse = None
            elif tag == "v":
                flush()
                try:
                    current_verse = int(el.get("id"))
                except (TypeError, ValueError):
                    current_verse = None
            elif tag == "ve":
                flush()
                current_verse = None
            elif tag in ("f", "x"):
                footnote_depth += 1

            if footnote_depth == 0 and current_verse and el.text:
                buffer.append(el.text)
        else:  # end event
            if tag in ("f", "x"):
                footnote_depth = max(0, footnote_depth - 1)
            if footnote_depth == 0 and current_verse and el.tail:
                buffer.append(el.tail)

    flush()
    return books


def run():
    print("Fetching Clementine Vulgate (seven1m/open-bibles, USFX)...")
    resp = requests.get(VULGATE_URL, timeout=60)
    resp.raise_for_status()
    books_data = extract_verses(resp.content)
    print(f"  parsed {len(books_data)} books")
    if len(books_data) < 60:
        print("  WARN expected 66 books — got fewer. Inspect the XML before trusting this run.")

    books_resp = supabase.table("books").select("id, osis_code").execute()
    osis_to_id = {row["osis_code"]: row["id"] for row in books_resp.data}

    for usfx_id, verses in tqdm(books_data.items(), desc="Books"):
        osis_code = USFX_TO_OSIS.get(usfx_id)
        book_id = osis_to_id.get(osis_code) if osis_code else None
        if not book_id:
            print(f"  SKIP unmapped USFX book id: {usfx_id}")
            continue

        vresp = (
            supabase.table("verses")
            .select("id, chapter, verse")
            .eq("book_id", book_id)
            .execute()
        )
        ref_lookup = {(row["chapter"], row["verse"]): row["id"] for row in vresp.data}

        text_rows = []
        for (chapter, verse), text in verses.items():
            vid = ref_lookup.get((chapter, verse))
            if not vid:
                continue
            text_rows.append(
                {
                    "verse_id": vid,
                    "source": "latin_vulgate",
                    "text_content": text,
                    "source_edition": "Clementine Vulgate (seven1m/open-bibles, USFX) — public domain",
                }
            )
        batch_upsert("manuscript_texts", text_rows, on_conflict="verse_id,source")

    print("Vulgate seeding complete.")


if __name__ == "__main__":
    run()
