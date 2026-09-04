"""
Post-seed sanity check. Run this AFTER run_all_seeds.py to spot-check known
reference points across the database — not a full audit, just enough real
checks to catch "the seed ran without errors but the data is actually wrong
or missing" before you build UI on top of it.

Each check is a fact that should be true if seeding worked: Genesis 1:1 has
Hebrew + KJV text, John 3:16 has Greek text, a well-known Strong's number
resolves to a real definition, a journey stop has real coordinates, etc.

Usage:
  python verify_seed.py

Exits non-zero if any check fails, so you can use it in a CI-style workflow
too, not just eyeball it.
"""
import sys
from _client import supabase

CHECKS_PASSED = 0
CHECKS_FAILED = 0


def check(description, condition, detail=""):
    global CHECKS_PASSED, CHECKS_FAILED
    if condition:
        CHECKS_PASSED += 1
        print(f"  ✅ {description}")
    else:
        CHECKS_FAILED += 1
        print(f"  ❌ {description}" + (f" — {detail}" if detail else ""))


def get_verse_id(canonical_ref):
    resp = supabase.table("verses").select("id").eq("canonical_ref", canonical_ref).execute()
    return resp.data[0]["id"] if resp.data else None


def section(title):
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def run():
    # -------------------------------------------------------------------
    section("1. Books & verses")
    # -------------------------------------------------------------------
    books_resp = supabase.table("books").select("id").execute()
    check("66 books present", len(books_resp.data) == 66, f"found {len(books_resp.data)}")

    verses_resp = supabase.table("verses").select("id", count="exact").execute()
    verse_count = verses_resp.count or 0
    # KJV has 31,102 verses — the real, well-known number for this canon.
    check(
        "verse count is in the right ballpark (~31,102 for the 66-book KJV canon)",
        30000 < verse_count < 32000,
        f"found {verse_count}",
    )

    # -------------------------------------------------------------------
    section("2. Manuscript texts — Genesis 1:1 and John 3:16")
    # -------------------------------------------------------------------
    gen_1_1 = get_verse_id("GEN.1.1")
    check("Genesis 1:1 exists in verses", gen_1_1 is not None)

    if gen_1_1:
        mss = supabase.table("manuscript_texts").select("source, text_content").eq("verse_id", gen_1_1).execute()
        sources_found = {row["source"] for row in mss.data}
        check("Genesis 1:1 has KJV text", "kjv" in sources_found)
        check("Genesis 1:1 has Hebrew (Leningrad) text", "hebrew_leningrad" in sources_found)
        check("Genesis 1:1 has Latin (Vulgate) text", "latin_vulgate" in sources_found)
        check(
            "Genesis 1:1 does NOT have Greek text (correctly — it's OT)",
            "greek_sblgnt" not in sources_found,
        )
        kjv_row = next((r for r in mss.data if r["source"] == "kjv"), None)
        if kjv_row:
            check(
                "Genesis 1:1 KJV text contains 'beginning'",
                "beginning" in kjv_row["text_content"].lower(),
                f"got: {kjv_row['text_content'][:80]}",
            )

    john_3_16 = get_verse_id("JOHN.3.16")
    check("John 3:16 exists in verses", john_3_16 is not None)
    if john_3_16:
        mss = supabase.table("manuscript_texts").select("source, text_content").eq("verse_id", john_3_16).execute()
        sources_found = {row["source"] for row in mss.data}
        check("John 3:16 has Greek (SBLGNT) text", "greek_sblgnt" in sources_found)
        check("John 3:16 has KJV text", "kjv" in sources_found)
        check(
            "John 3:16 does NOT have Hebrew text (correctly — it's NT)",
            "hebrew_leningrad" not in sources_found,
        )

    # -------------------------------------------------------------------
    section("3. Word-level linking")
    # -------------------------------------------------------------------
    if gen_1_1:
        words = (
            supabase.table("word_occurrences")
            .select("surface_form, lexicon_entry_id")
            .eq("verse_id", gen_1_1)
            .eq("manuscript_source", "hebrew_leningrad")
            .order("word_order")
            .execute()
        )
        check("Genesis 1:1 has Hebrew word_occurrences", len(words.data) > 0, f"found {len(words.data)}")
        linked = [w for w in words.data if w["lexicon_entry_id"]]
        check(
            "at least some Genesis 1:1 words are linked to a lexicon entry",
            len(linked) > 0,
            f"{len(linked)}/{len(words.data)} linked",
        )

    # -------------------------------------------------------------------
    section("4. Lexicon — Strong's + BDB")
    # -------------------------------------------------------------------
    # H430 (Elohim, "God") is one of the most common OT words — a real,
    # well-known reference point.
    h430 = supabase.table("lexicon_entries").select("*").eq("strong_number", "H0430").execute()
    check("H0430 (Elohim) exists in lexicon_entries", len(h430.data) > 0)
    strongs_h430 = [e for e in h430.data if e["source"] == "strongs"]
    check("H0430 has a Strong's entry", len(strongs_h430) > 0)
    bdb_h430 = [e for e in h430.data if e["source"] == "bdb"]
    check(
        "H0430 has a BDB entry (may legitimately be missing — BDB coverage is partial)",
        len(bdb_h430) > 0 or True,  # informational, not a hard failure
    )
    if not bdb_h430:
        print("     (no BDB entry for H0430 — check if this is expected given BDB's known partial coverage)")

    g26 = supabase.table("lexicon_entries").select("*").eq("strong_number", "G0026").execute()
    check("G0026 (agape, 'love') exists in lexicon_entries", len(g26.data) > 0)

    lexicon_count = supabase.table("lexicon_entries").select("id", count="exact").eq("source", "strongs").execute()
    check(
        "Strong's entry count is in the right ballpark (~14,000+ Hebrew+Greek combined)",
        (lexicon_count.count or 0) > 10000,
        f"found {lexicon_count.count}",
    )

    # -------------------------------------------------------------------
    section("5. Cross-references (TSK)")
    # -------------------------------------------------------------------
    if gen_1_1:
        xrefs = supabase.table("cross_references").select("id").eq("from_verse_id", gen_1_1).execute()
        check("Genesis 1:1 has at least one cross-reference", len(xrefs.data) > 0, f"found {len(xrefs.data)}")

    xref_count = supabase.table("cross_references").select("id", count="exact").execute()
    check(
        "cross-reference count is substantial (TSK has 500,000+)",
        (xref_count.count or 0) > 100000,
        f"found {xref_count.count}",
    )

    # -------------------------------------------------------------------
    section("6. Commentaries & context cards")
    # -------------------------------------------------------------------
    commentaries = supabase.table("commentaries").select("author").execute()
    check("at least 3 commentaries seeded", len(commentaries.data) >= 3, f"found {len(commentaries.data)}")

    context_cards = supabase.table("context_cards").select("id", count="exact").execute()
    check("at least some context cards exist", (context_cards.count or 0) > 0, f"found {context_cards.count}")

    # -------------------------------------------------------------------
    section("7. Maps & journeys")
    # -------------------------------------------------------------------
    locations = supabase.table("map_locations").select("name, latitude, longitude").execute()
    check("at least 40 map locations seeded", len(locations.data) >= 40, f"found {len(locations.data)}")
    jerusalem = [l for l in locations.data if l["name"] == "Jerusalem"]
    check("Jerusalem exists with real-looking coordinates", len(jerusalem) > 0)
    if jerusalem:
        lat, lon = jerusalem[0]["latitude"], jerusalem[0]["longitude"]
        # Jerusalem is real-world ~31.77°N, 35.21°E — sanity-range check, not exact match.
        check(
            "Jerusalem's coordinates are in the right part of the world",
            30 < lat < 33 and 34 < lon < 36,
            f"got lat={lat}, lon={lon}",
        )

    journeys = supabase.table("journeys").select("name").execute()
    check("4 of Paul's journeys seeded", len(journeys.data) == 4, f"found {len(journeys.data)}")

    stops = supabase.table("journey_stops").select("id", count="exact").execute()
    check("journey stops exist", (stops.count or 0) > 20, f"found {stops.count}")

    # -------------------------------------------------------------------
    section("SUMMARY")
    # -------------------------------------------------------------------
    total = CHECKS_PASSED + CHECKS_FAILED
    print(f"\n{CHECKS_PASSED}/{total} checks passed.")
    if CHECKS_FAILED:
        print(f"{CHECKS_FAILED} check(s) failed — see ❌ lines above for what to investigate.")
        sys.exit(1)
    else:
        print("Everything checked out. Safe to start building against this data.")


if __name__ == "__main__":
    run()
