"""
Seed `lexicon_entries` (source='strongs') for Hebrew and Greek.

FIXED 2026-09-05: the first live run inserted almost no Hebrew entries
(verify_seed.py found ~5,523 total lexicon rows when ~14,000+ were expected --
essentially all Greek, near-zero Hebrew). The original Hebrew parser targeted
"HebrewStrong.xml" using a "<div type='entry' n='NNNN'>" structure that was
never actually confirmed against a live fetch of that specific file -- it was
inferred from a description of the project's XSLT converter, which turned out
to not match reality closely enough to parse correctly.

REPLACED with a parser for **LexicalIndex.xml** instead, whose structure has
now been independently confirmed TWICE from real quoted examples (a
crosswire.org sword-devel mailing list thread, and a live openscriptures/
morphhb GitHub issue #94 quoting an actual entry):

    <entry id="arn">
      <w xlit="ʾĕlōhîm">אֱלֹהִים</w>
      <pos>N</pos>
      <def>gods</def>
      <xref bdb="a.dl.ad" strong="430" twot="93c"/>
      <etym type="sub">arm</etym>
    </entry>

This gives strong_number (xref/@strong), headword (w text), transliteration
(w/@xlit), and a short gloss (def text) directly -- real, confirmed data,
even though it's a shorter gloss than a full dictionary-style definition.
(seed_bdb.py already successfully used this same file for the same reason --
this fix just applies the same confirmed source to the Strong's-entry half.)

Some Strong's numbers appear multiple times in LexicalIndex.xml with an `aug`
attribute distinguishing different senses of the same word (e.g. H0430 sense
"a" = "God", sense "b" = "gods") -- this script keeps the FIRST sense seen per
Strong's number for a single clean lexicon_entries row, rather than trying to
merge senses, since the schema's unique constraint is (strong_number, source).

GREEK (Strong's): unaffected by this fix -- the Greek section already parsed
correctly against real data (confirmed via verify_seed.py finding G0026 and a
Greek entry count consistent with expectations). Source: openscriptures/strongs
repo, file "greek/StrongsGreekDictionaryXML_1.4/strongsgreek.xml".
Text: CC0 / public domain per the file's own release notes.

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
    hebrew_rows = parse_hebrew_from_lexical_index(hresp.content)
    print(f"  parsed {len(hebrew_rows)} Hebrew entries")
    if len(hebrew_rows) < 7000:
        print("  WARN expected ~8600+ Hebrew Strong's entries -- got fewer. "
              "Inspect LexicalIndex.xml's real structure before trusting this run.")

    print("Fetching Greek Strong's (openscriptures/strongs)...")
    gresp = requests.get(GREEK_URL, timeout=60)
    gresp.raise_for_status()
    greek_rows = parse_greek(gresp.content)
    print(f"  parsed {len(greek_rows)} Greek entries")
    if len(greek_rows) < 5000:
        print("  WARN expected ~5600+ Greek Strong's entries -- got fewer. "
              "Inspect the XML structure before trusting this run.")

    all_rows = [r for r in (hebrew_rows + greek_rows) if r["strong_number"] and r["headword"]]
    batch_upsert("lexicon_entries", all_rows, on_conflict="strong_number,source")
    print(f"Strong's seeding complete: {len(all_rows)} entries.")


if __name__ == "__main__":
    run()
