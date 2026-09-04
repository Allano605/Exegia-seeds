"""
Seed `lexicon_entries` from VERIFIED real sources (checked against actual repo
contents on 2026-09-03, not guessed):

HEBREW (Strong's): openscriptures/HebrewLexicon, file "HebrewStrong.xml"
  https://github.com/openscriptures/HebrewLexicon
  CC BY 4.0 (attribution: OpenScriptures / Daniel Owens et al.)
  Real structure (confirmed from source): OSIS-style
    <div type="entry" n="8141">
      <w lemma="שָׁנֶה" xlit="shâneh" POS="shaw-neh'" .../>   <!-- POS attr actually
           holds the *pronunciation* string in this file, per the project's own
           StrongJson.xslt converter — a quirk of their schema, not a typo here -->
      <note type="exegesis">...derivation...</note>
      <note type="explanation">...strongs_def...</note>
      <note type="translation">...kjv_def...</note>
    </div>

HEBREW (BDB): same repo, file "BrownDriverBriggs.xml" — full Brown-Driver-Briggs
  lexicon, cross-referenced to Strong's numbers via LexicalIndex.xml. BDB is
  organized by Hebrew root, not 1:1 by Strong's number, so it needs its own
  parser — see seed_bdb.py, run after this script.

GREEK (Strong's): openscriptures/strongs repo, file
  "greek/StrongsGreekDictionaryXML_1.4/strongsgreek.xml" — NOTE the nested
  folder name, confirmed from the repo's own build scripts. A flat
  "greek/StrongsGreek.xml" path (an earlier guess in a prior draft of this
  script) does NOT exist in the repo.
  Text: CC0 / public domain per the file's own release notes (Ulrik
  Sandborg-Petersen explicitly waived rights under CC0).
  Real structure: <entry strongs="26"><greek unicode="ἀγαπάω" translit="agapao"
  .../><strongs_def>...</strongs_def><kjv_def>...</kjv_def></entry>

Run: python seed_strongs.py
"""
import requests
from lxml import etree
from tqdm import tqdm
from _client import batch_upsert

HEBREW_URL = (
    "https://raw.githubusercontent.com/openscriptures/HebrewLexicon/master/"
    "HebrewStrong.xml"
)
GREEK_URL = (
    "https://raw.githubusercontent.com/openscriptures/strongs/master/greek/"
    "StrongsGreekDictionaryXML_1.4/strongsgreek.xml"
)

OSIS_NS = "http://www.bibletechnologies.net/2003/OSIS/namespace"


def parse_hebrew(xml_bytes):
    root = etree.fromstring(xml_bytes)
    entries = root.findall(".//div[@type='entry']")
    if not entries:
        entries = root.findall(f".//{{{OSIS_NS}}}div[@type='entry']")

    rows = []
    for entry in entries:
        num = entry.get("n")
        if not num:
            continue
        strong_number = f"H{int(num):04d}"

        w = entry.find("w")
        if w is None:
            w = entry.find(f"{{{OSIS_NS}}}w")
        headword = w.get("lemma") if w is not None else None
        translit = w.get("xlit") if w is not None else None

        def note_text(note_type):
            n = entry.find(f"note[@type='{note_type}']")
            if n is None:
                n = entry.find(f"{{{OSIS_NS}}}note[@type='{note_type}']")
            return "".join(n.itertext()).strip() if n is not None else ""

        derivation = note_text("exegesis")
        strongs_def = note_text("explanation")
        kjv_def = note_text("translation")
        full_def = "\n".join(filter(None, [derivation, strongs_def, kjv_def]))

        rows.append(
            {
                "strong_number": strong_number,
                "source": "strongs",
                "headword": headword,
                "transliteration": translit,
                "part_of_speech": None,
                "short_definition": strongs_def[:255] if strongs_def else None,
                "full_definition": full_def or "See derivation notes.",
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
    print("Fetching Hebrew Strong's (openscriptures/HebrewLexicon)...")
    hresp = requests.get(HEBREW_URL, timeout=60)
    hresp.raise_for_status()
    hebrew_rows = parse_hebrew(hresp.content)
    print(f"  parsed {len(hebrew_rows)} Hebrew entries")
    if len(hebrew_rows) < 8000:
        print("  WARN expected ~8600+ Hebrew Strong's entries — got fewer. "
              "Inspect the XML structure before trusting this run.")

    print("Fetching Greek Strong's (openscriptures/strongs)...")
    gresp = requests.get(GREEK_URL, timeout=60)
    gresp.raise_for_status()
    greek_rows = parse_greek(gresp.content)
    print(f"  parsed {len(greek_rows)} Greek entries")
    if len(greek_rows) < 5000:
        print("  WARN expected ~5600+ Greek Strong's entries — got fewer. "
              "Inspect the XML structure before trusting this run.")

    all_rows = [r for r in (hebrew_rows + greek_rows) if r["strong_number"] and r["headword"]]
    batch_upsert("lexicon_entries", all_rows, on_conflict="strong_number,source")
    print(f"Strong's seeding complete: {len(all_rows)} entries.")


if __name__ == "__main__":
    run()
