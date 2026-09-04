"""
Seed `lexicon_entries` (source='bdb') from openscriptures/HebrewLexicon.

VERIFIED STRUCTURE (checked 2026-09-03, confirmed from real raw XML excerpts
quoted in the project's own mailing list, crosswire.org/pipermail/sword-devel):

LexicalIndex.xml is the bridge file — each entry links a headword to BOTH a BDB
entry id and (when available) a Strong's number, in one place:

    <entry id="bep">
      <w xlit="ʾereṣ">אֶ֫רֶץ</w>
      <pos>N</pos>
      <def>earth</def>
      <xref bdb="a.fx.aa" strong="776" twot="167"/>
      <etym root="ארץ" type="main"/>
    </entry>

BrownDriverBriggs.xml holds the actual BDB entry content, keyed by the same id
referenced in `xref/@bdb`:

    <entry id="a.fx.aa" type="root">
      <w>...</w>, <def>...</def>, ... full BDB article text ...
      <status p="...">done</status>
    </entry>

So the join is: LexicalIndex entries with BOTH `xref/@strong` and `xref/@bdb`
give us strong_number -> bdb_entry_id; then look up that id's full text in
BrownDriverBriggs.xml. This is simpler than parsing BDB independently by root,
because the project already built exactly the bridge we need.

Not every Strong's number has a completed BDB entry yet — the project's own
docs note BDB "remains a work in progress." Expect partial coverage.

License: CC BY 4.0 — attribution to OpenScriptures required. Underlying BDB
text is public domain (1900s).

Requires lexicon_entries to already have Strong's Hebrew rows (run
seed_strongs.py first) so upserts land on existing strong_number rows rather
than creating orphaned ones — though this script can run standalone too, since
it upserts by (strong_number, source) and 'bdb' is a separate source row from
'strongs' for the same strong_number.

Run: python seed_bdb.py
"""
import re
import requests
from lxml import etree
from tqdm import tqdm
from _client import batch_upsert

LEXICAL_INDEX_URL = (
    "https://raw.githubusercontent.com/openscriptures/HebrewLexicon/master/"
    "LexicalIndex.xml"
)
BDB_URL = (
    "https://raw.githubusercontent.com/openscriptures/HebrewLexicon/master/"
    "BrownDriverBriggs.xml"
)


def build_strong_to_bdbid(xml_bytes):
    """Parse LexicalIndex.xml, return ({strong_number: bdb_entry_id}, {strong_number: headword})."""
    root = etree.fromstring(xml_bytes)
    bdbid_map = {}
    headword_map = {}
    for entry in root.findall(".//entry"):
        xref = entry.find("xref")
        if xref is None:
            continue
        strong_num = xref.get("strong")
        bdb_id = xref.get("bdb")
        if not (strong_num and bdb_id and strong_num.isdigit()):
            continue
        key = f"H{int(strong_num):04d}"
        bdbid_map[key] = bdb_id
        w = entry.find("w")
        if w is not None and w.text:
            headword_map[key] = w.text
    return bdbid_map, headword_map


def build_bdb_entries(xml_bytes):
    """Parse BrownDriverBriggs.xml, return {bdb_entry_id: (headword, full_text)}."""
    root = etree.fromstring(xml_bytes)
    entries = {}
    for entry in root.findall(".//entry"):
        bdb_id = entry.get("id")
        if not bdb_id:
            continue

        first_w = entry.find("w")
        headword = first_w.text if first_w is not None and first_w.text else None

        text_parts = []
        for el in entry.iter():
            tag = etree.QName(el).localname if isinstance(el.tag, str) else None
            if tag == "status":
                continue
            if el.text:
                text_parts.append(el.text)
            if el.tail:
                text_parts.append(el.tail)
        full_text = re.sub(r"\s+", " ", "".join(text_parts)).strip()
        if full_text:
            entries[bdb_id] = (headword, full_text)
    return entries


def run():
    print("Fetching LexicalIndex.xml (Strong's <-> BDB bridge)...")
    li_resp = requests.get(LEXICAL_INDEX_URL, timeout=60)
    li_resp.raise_for_status()
    strong_to_bdbid, strong_to_headword = build_strong_to_bdbid(li_resp.content)
    print(f"  found {len(strong_to_bdbid)} Strong's-number-to-BDB-id links")

    print("Fetching BrownDriverBriggs.xml (full BDB content)...")
    bdb_resp = requests.get(BDB_URL, timeout=60)
    bdb_resp.raise_for_status()
    bdb_entries = build_bdb_entries(bdb_resp.content)
    print(f"  parsed {len(bdb_entries)} BDB entries")

    rows = []
    missing = 0
    skipped_no_headword = 0
    for strong_number, bdb_id in strong_to_bdbid.items():
        entry = bdb_entries.get(bdb_id)
        if not entry:
            missing += 1
            continue
        headword, full_text = entry
        if not headword:
            # lexicon_entries.headword is NOT NULL in the schema — LexicalIndex's
            # own <w> for this strong number is a safe fallback source for it.
            li_headword = strong_to_headword.get(strong_number)
            headword = li_headword
        if not headword:
            skipped_no_headword += 1
            continue
        rows.append(
            {
                "strong_number": strong_number,
                "source": "bdb",
                "headword": headword,
                "transliteration": None,
                "part_of_speech": None,
                "short_definition": full_text[:255],
                "full_definition": full_text,
            }
        )

    print(f"  {missing} Strong's numbers had a BDB link but no completed entry text "
          f"(expected — BDB coverage is partial per the project's own notes)")
    print(f"  {skipped_no_headword} skipped: no headword available from either BDB or LexicalIndex "
          f"(lexicon_entries.headword is NOT NULL in the schema)")
    batch_upsert("lexicon_entries", rows, on_conflict="strong_number,source")
    print(f"BDB seeding complete: {len(rows)} entries.")


if __name__ == "__main__":
    run()
