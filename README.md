# Exegia — Seeding Scripts

These scripts populate the Supabase schema (`exegia_schema.sql`) with **real, publicly
available texts**. No AI-generated content is inserted by any script here — that's
intentional, matching the Tier 1 "pure scholarly" principle.

⚠️ **This sandbox has no internet access**, so these scripts are written but untested
against live sources. Run them from your own machine, Render job, or Colab notebook
where network access is available. Inspect the first ~20 rows of each source file
before a full run — source projects occasionally change their file format.

## Quickest way to run everything

```bash
python run_all_seeds.py              # runs all 11 steps in order, doesn't stop on failure
python run_all_seeds.py --list       # see step ids
python run_all_seeds.py --only bdb   # re-run just one step
python run_all_seeds.py --skip vulgate  # run everything except one step
python verify_seed.py                # run AFTER seeding — spot-checks known reference points
```

Prints a pass/fail summary at the end and gives you the exact re-run command
for anything that failed — built for a "kick it off from your phone and check
back later" workflow. It does NOT stop at the first failure: independent steps
(e.g. `strongs`) still run even if an unrelated one (e.g. `vulgate`) fails,
since there's no reason one blocking issue should hide whether everything
else worked.

`verify_seed.py` is a separate, second step — run it after `run_all_seeds.py`
finishes. It doesn't check "did every table get some rows," it checks specific
known facts: does Genesis 1:1 actually have Hebrew+KJV+Vulgate text (and
correctly NOT Greek, since it's Old Testament); does John 3:16 have Greek
(and correctly NOT Hebrew); does H0430 (Elohim) resolve to a real Strong's
entry; are Jerusalem's seeded coordinates actually in the right part of the
world; and so on — roughly 25 checks total, each tied to something that's
true in reality, not just "the row count is nonzero." Exits non-zero on any
failure so it's usable as `run_all_seeds.py && verify_seed.py` in one command.


## Run order (dependencies matter)

1. `seed_books.py` — hardcoded 66-book canon, no external source needed. Run first.
2. `seed_kjv.py` — populates `verses` (canonical structure) AND `manuscript_texts`
   (source='kjv'). Run before Hebrew/Greek/Vulgate seeds since they attach to
   existing `verses` rows.
3. `seed_hebrew_leningrad.py` — Old Testament Hebrew text + word-level Strong's tags.
4. `seed_greek_sblgnt.py` — New Testament Greek text + word-level Strong's/lemma tags.
5. `seed_vulgate.py` — Latin Vulgate text.
6. `seed_strongs.py` — Strong's Hebrew + Greek dictionary entries (run before or after
   4/5, but before you rely on `word_occurrences.lexicon_entry_id` lookups working).
7. `seed_bdb.py` — Brown-Driver-Briggs Hebrew lexicon, linked to Strong's numbers.
   Run after `seed_strongs.py` (both write to `lexicon_entries`, just different
   `source` values for the same `strong_number`).
8. `seed_tsk_crossrefs.py` — Treasury of Scripture Knowledge cross-references.

## Verification status (updated 2026-09-03)

Every source below was checked directly (fetched real file contents / repo trees),
not assumed. Status per source:

| Source | File(s) | Status |
|---|---|---|
| KJV — aruljohn/Bible-kjv | `{BookName}.json` | ✅ **Verified.** Fetched Joel.json directly, confirmed exact JSON shape and filenames. `seed_kjv.py` matches reality. |
| Hebrew — openscriptures/morphhb (Leningrad Codex / OSHB) | `wlc/{OsisCode}.xml` | ✅ **Verified.** Fetched Obad.xml directly — namespace, `<verse osisID>`, `<w lemma morph id>` structure, and lemma format (e.g. `c/6965 b`) all confirmed. `seed_hebrew_leningrad.py` parsing logic matches reality, including correctly excluding qere/ketiv variant duplicates. |
| Strong's Hebrew — **openscriptures/HebrewLexicon** (`HebrewStrong.xml`) | switched from an earlier, less complete source | ✅ **Verified structure** via the project's own XSLT converter — real entry format is `<div type="entry" n="8141"><w lemma xlit POS/><note type="exegesis/explanation/translation">`. `seed_strongs.py` rewritten to match. This repo **also has a real BDB file** (`BrownDriverBriggs.xml`) cross-referenced to Strong's — better than a generic "BDB mirror." BDB parser not yet written (see Known Gaps). |
| Strong's Greek — openscriptures/strongs | `greek/StrongsGreekDictionaryXML_1.4/strongsgreek.xml` | ✅ **Verified — and corrected.** The original path I guessed (`greek/StrongsGreek.xml`) does not exist; real path has a nested version-numbered folder. `seed_strongs.py` fixed. Confirmed CC0/public domain from the file's own release notes. |
| Greek NT — MorphGNT/SBLGNT | `{n}-{Abbr}-morphgnt.txt` | ✅ **Verified — citation format decoded from a real GitHub issue thread quoting actual file lines** (`morphgnt/sblgnt` issue #44): 7 space-delimited columns confirmed, and the `citation` field's digit structure confirmed by cross-checking two real sample citations against their actual verse content (`160220` → 2 Tim 2:20, which does mention "vessels of gold"; `270920` → Rev 9:20, which mentions gold idols — both check out). `seed_greek_sblgnt.py` rewritten to parse chapter/verse from the last 4 digits of the citation rather than guessing a `chapter:verse` sub-format that doesn't actually exist in this file. License confirmed: SBLGNT text is **not** public domain — free to distribute, but selling/bundling >25% of a larger work needs SBL's written permission. |
| Latin Vulgate | `lat-clementine.usfx.xml` (seven1m/open-bibles) | ✅ **Verified.** Confirmed present in the repo's own README table as "Latin / USFX / Clementine Latin Vulgate / Public Domain." USFX's milestone-based structure (verses aren't nested containers, they're `<v id>` markers followed by plain text) confirmed against the format's own spec and two independent reference parsers (Ruby, JS). `seed_vulgate.py` rewritten with a real event-based parser matching how those reference implementations read it, including skipping footnote/cross-ref text. |
| Treasury of Scripture Knowledge | scrollmapper/bible_databases `cross_reference` table | ✅ **Verified — schema confirmed from multiple independent forks' matching README tables, and the seed script now parses the confirmed real file (`cross_references-mysql.sql`, 2024 branch) directly via regex rather than an unconfirmed CSV path.** The script prints a match count before mapping, so a 0-match run is immediately visible rather than silently wrong. |
| BDB (Brown-Driver-Briggs) — openscriptures/HebrewLexicon | `LexicalIndex.xml` + `BrownDriverBriggs.xml` | ✅ **Verified from real raw XML excerpts** quoted in the project's own mailing list (crosswire.org sword-devel). `LexicalIndex.xml` is a genuine bridge file — each entry links a headword to both a BDB entry id and a Strong's number via `<xref bdb="..." strong="..."/>`, which is exactly the join `seed_bdb.py` uses. BDB coverage is confirmed partial ("remains a work in progress" per the project's own docs) — expect gaps, not a bug. |

## Licenses (confirmed)

| Source | License |
|---|---|
| KJV text | Public domain |
| OSHB Hebrew text (Leningrad Codex) | Public domain; morphology/markup is CC BY 4.0 — **attribution to OpenScriptures required** |
| HebrewLexicon (Strong's Hebrew + BDB) | CC BY 4.0 — **attribution required** |
| Strong's Greek (openscriptures/strongs) | CC0 / public domain, confirmed from the file's own release notes |
| SBLGNT text | **Not public domain.** Free to distribute; cannot be sold standalone; if it's >25% of a paid work you need written permission from SBL. Confirm your use case at https://sblgnt.com/license/ before commercial launch — this is the one real legal gate in this list. |
| Latin Vulgate (Clementine) | Public domain (once you pick a verified source) |
| Treasury of Scripture Knowledge | CC BY — attribution to openbible.info required |

## Known gaps — do not run blind

1. **`seed_tsk_crossrefs.py`** targets the `2024` branch of scrollmapper/bible_databases specifically, because that's the branch whose schema is confirmed above — the `2025`+ branch has a documented breaking schema change that was not re-verified this session. If you want the newer branch, check its schema fresh first.
2. **Thayer's — confirmed real and public domain, but NOT available as a fetchable file.** Confirmed via the maintainer's own reply on GitHub (eliranwong/OpenGNT issue #2): the unabridged Thayer's lexicon is distributed only through the UniqueBible.app desktop application's in-app downloader, which pulls a SQLite file from the maintainer's personal Google Drive at runtime. There is no stable public URL for it. Options: (a) run UniqueBible.app once, download it via Resources → Install Marvel.bible Datasets → Lexicons, then host that file yourself and write a script against your own copy; (b) OCR the public-domain Internet Archive scan (archive.org/details/thayersgreekengl0000jose) — higher effort, OCR-error risk in Greek text; (c) ship without it — Strong's + BDB is already a real, legitimate two-source lexicon layer. No `seed_thayers.py` exists in this folder for this reason — writing one against a URL would mean faking a source.
3. **BDB coverage will be partial** by the project's own admission — not every Strong's-linked word has a completed BDB article yet. `seed_bdb.py` reports exactly how many are missing so you know the real number rather than assuming 100% coverage.
4. **`seed_commentaries.py`'s context-card extraction logic is unverified against the live API response shape.** The HelloAO API's exact JSON structure for a commentary chapter response wasn't directly fetched this session (only its endpoint URLs and licensing were confirmed via docs and third-party usage). The script tries a few plausible field names (`content`, `text`, `commentary`, `html`) and prints the real response keys if none match, so a shape mismatch is visible immediately rather than silently producing empty cards.
5. **Pronunciation audio (Strong's-number-level) — confirmed there is NO bulk, scriptable, open-license dataset for this**, and this is worth understanding rather than working around with a fake source. Real, legitimate recordings exist (Dr. Randall Buth's reconstructed-Koine and Hebrew recordings at biblicalulpan.org / available via Logos; Benjamin Kantor's historical-Koine recordings at KoineGreek.com), but they're individually hosted by their creators, not published as a bulk-downloadable per-word dataset, and several are commercial (Logos) or partial (Kantor's site covers only some chapters, gated for full access). The one bulk, genuinely downloadable option is **Faith Comes By Hearing's "Greek-Koine" 1904 audio** (per-chapter, not per-word, zip downloads) — real and freely downloadable, but that's *chapter-level spoken audio*, not the per-Strong's-number pronunciation clips the `pronunciation_audio` table's schema (`lexicon_entry_id` foreign key) was designed around. Two honest paths forward: (a) redesign this feature around chapter-level audio instead of word-level (matches what's actually available), or (b) treat word-level pronunciation as something you manually license/commission rather than script — don't fake either.

## What's now real and seedable that wasn't before

- **`seed_commentaries.py`** — 5 public-domain commentaries (Matthew Henry, JFB, Adam Clarke, John Gill, Keil-Delitzsch) via the verified HelloAO Free Use Bible API, plus overview context cards using Matthew Henry's chapter-1 remarks per book. Tyndale's notes are deliberately excluded from this "pure" set since they're CC BY-SA, not public domain — add them separately with honest attribution if you want them.
- **`seed_map_locations.py`** — real coordinates for ~65 biblical place names from the Pleiades ancient-places gazetteer (CC BY 3.0), confirmed via its own live data-dump index and README schema.
- **`seed_journeys.py`** — Paul's four journeys (three missionary journeys + the voyage to Rome) with real Acts chapter:verse references per stop, encoded directly from the text of Acts rather than a third-party dataset (the itinerary order isn't a contested scholarly question, just a reading of the narrative).

## A note on the Yoruba/Igbo/Hausa word-level lexicon problem

The `bcv-data/strongs` dataset on Hugging Face (found while verifying Strong's
sources) covers 12 languages: `arb, asm, ben, cmn-Hans, cmn-Hant, eng, fra, hau,
hin, por, rus, spa`. **Hausa (`hau`) is included — Yoruba and Igbo are not.**
So this is a real, provenance-tagged source for the Hausa word-lookup layer
(better than AI translation for that language specifically), but doesn't solve
Yoruba/Igbo.

Two more things worth knowing before using it:
- Its own provenance tags show many entries are `method: llm` (i.e., AI-generated) mixed in with `lexicon`-sourced ones, each row tagged individually — so it's not a "pure scholarly" source either, just an honestly-labeled mixed one. Same spirit as your own Tier 1/Tier 2 split, applied at the row level.
- License is **CC BY-SA 4.0** — share-alike. Unlike the CC BY sources elsewhere in this list, share-alike can require deriving works to use a compatible license. Worth a quick read of the actual terms before building on it commercially.

https://huggingface.co/datasets/bcv-data/strongs

## Environment variables (all scripts)

```
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=xxxx   # service role, not anon — needed to bypass RLS for seeding
```

## Install

```bash
pip install supabase requests lxml tqdm python-dotenv
```

## Notes on word-level linking

Both OSHB (Hebrew) and MorphGNT (Greek) embed Strong's numbers per word in their
morphology data, but in different formats — OSHB uses XML with `@lemma` attributes,
MorphGNT uses whitespace-delimited columns. The seed scripts extract these into
`word_occurrences.surface_form` + look up `lexicon_entry_id` by matching the Strong's
number. **Always run `seed_strongs.py` first if you want `lexicon_entry_id` populated
on insert** — otherwise re-run a backfill pass afterward (see `backfill_lexicon_links.py`).
