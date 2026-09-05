"""
Seed `lexicon_entries` (source='strongs') for Hebrew and Greek.

This version fails LOUDLY if Hebrew parsing returns too few rows, printing
the actual raw XML content so the real structure is visible in one shot
instead of another guess-and-check round.

Run: python seed_strongs.py
"""
import requests
from lxml import etree
from tqdm import tqdm
from _client import batch_upsert

LEXICAL_INDEX_URL = (
    "https://raw.githubusercontent.com/openscriptures/HebrewLexicon/master/"
    "LexicalIndex.xml"
)
GREEK_URL = (
    "https://raw.githubusercontent.com/openscriptures/strongs/master/greek/"
    "StrongsGreekDictionaryXML_1.4/strongsgreek.xml"
)


def parse_hebrew_from_lexical_index(xml_bytes):
    root = etree.fromstring(xml_bytes)
    rows = []
    seen_strong_numbers = set()

    for entry in root.findall(".//entry"):
        xref = entry.find("xref")
        if xref is None:
            continue
        strong_raw = xref.get("strong")
        if not strong_raw or not strong_raw.isdigit():
            continue
        strong_number = f"H{int(strong_raw):04d}"
        if strong_number in seen_strong_numbers:
            continue

        w = entry.find("w")
        headword = w.text if w is not None else None
        translit = w.get("xlit") if w is not None else None
        gloss = entry.findtext("def") or ""

        if not headword:
            continue

        seen_strong_numbers.add(strong_number)
        rows.append(
            {
                "strong_number": strong_number,
                "source": "strongs",
                "headword": headword,
                "transliteration": translit,
                "part_of_speech": entry.findtext("pos"),
                "short_definition": gloss[:255] if gloss else None,
                "full_definition": gloss or "See BDB entry for full definition (linked via TWOT/xref).",
            }
        )
    return rows


def parse_greek(xml_bytes):
    root = etree.fromstring(xml_bytes)
    rows = []
    for entry in root.iter("entry"):
        strongs_attr = entry.get("strongs")
        if not strongs_attr or not strongs_attr.isdigit():
            continue
        strong_number = f"G{int(strongs_attr):04d}"

        greek = entry.find("greek")
        headword = greek.get("unicode") if greek is not None else None
        translit = greek.get("translit") if greek is not None else None

        strongs_def = (entry.findtext("strongs_def") or "").strip()
        kjv_def = (entry.findtext("kjv_def") or "").strip()
        full_def = "\n".join(filter(None, [strongs_def, kjv_def]))

        if not headword:
            continue

        rows.append(
            {
                "strong_number": strong_number,
                "source": "strongs",
                "headword": headword,
                "transliteration": translit,
                "part_of_speech": None,
                "short_definition": strongs_def[:255] if strongs_def else None,
                "full_definition": full_def or "See KJV usage notes.",
            }
        )
    return rows


def run():
    print("Fetching Hebrew Strong's data (openscriptures/HebrewLexicon, LexicalIndex.xml)...")
    hresp = requests.get(LEXICAL_INDEX_URL, timeout=60)
    hresp.raise_for_status()
    print(f"  downloaded {len(hresp.content) / 1e6:.2f} MB")
    hebrew_rows = parse_hebrew_from_lexical_index(hresp.content)
    print(f"  parsed {len(hebrew_rows)} Hebrew entries")
    if len(hebrew_rows) < 1000:
        print("  RAW XML SNIPPET (first 3000 chars) for diagnosis:")
        print(hresp.content[:3000].decode("utf-8", errors="replace"))
        raise RuntimeError(
            f"Only {len(hebrew_rows)} Hebrew entries parsed (expected 7000+). "
            f"The XML structure printed above does not match what this parser "
            f"expects -- fix parse_hebrew_from_lexical_index() to match it."
        )

    print("Fetching Greek Strong's (openscriptures/strongs)...")
    gresp = requests.get(GREEK_URL, timeout=60)
    gresp.raise_for_status()
    greek_rows = parse_greek(gresp.content)
    print(f"  parsed {len(greek_rows)} Greek entries")
    if len(greek_rows) < 5000:
        print("  WARN expected ~5600+ Greek Strong's entries -- got fewer.")

    all_rows = [r for r in (hebrew_rows + greek_rows) if r["strong_number"] and r["headword"]]
    batch_upsert("lexicon_entries", all_rows, on_conflict="strong_number,source")
    print(f"Strong's seeding complete: {len(all_rows)} entries.")


if __name__ == "__main__":
    run()
