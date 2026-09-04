"""
Seed the `books` table. No external source needed — this is the fixed 66-book
Protestant canon (matches KJV/SBLGNT/OSHB scope; add Apocrypha later as a separate
optional pass if you want Catholic/Orthodox canon support).

Run: python seed_books.py
"""
from _client import supabase
from books_data import BOOKS

def run():
    rows = [
        {
            "book_order": order,
            "testament": testament,
            "osis_code": osis_code,
            "name_en": name_en,
            "chapter_count": chapter_count,
        }
        for order, testament, osis_code, name_en, chapter_count in BOOKS
    ]
    supabase.table("books").upsert(rows, on_conflict="osis_code").execute()
    print(f"Seeded {len(rows)} books.")

if __name__ == "__main__":
    run()
