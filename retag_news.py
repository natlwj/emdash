"""
EMDASH :: retag_news.py   (one-time maintenance utility)

Re-applies the CURRENT tagging engine (news_ingest.tag_countries) to every row
already in the `news` table, and refreshes the stored `iso3_tags` column.

WHY THIS EXISTS
  Tagging runs at INGEST time. Re-pulling uses INSERT OR IGNORE on (ts,url),
  so rows already in the DB keep their OLD stored tags forever -- even after you
  improve the alias tables or add the acronym patch. The News Feed re-derives
  tags at display time, so it already looks right; but anything that reads the
  STORED column (core.news_coverage(), the SQLite Store coverage tiles, exports)
  stays stale until you run this once.

SAFE BY DESIGN -- ADD ONLY
  * Existing tags are NEVER removed. New tags found by the current engine are
    APPENDED. This preserves GDELT rows tagged by their query-country even when
    the headline text names no country (e.g. a THA flood story stays THA).
  * FEED_ORIGIN_ISO fallback is applied only to rows that end up with no tag.
  * Only rows whose tag string actually changes are written.

USAGE
  python retag_news.py            # DRY RUN -- shows counts + samples, writes nothing
  python retag_news.py --commit   # actually writes the changes

Run it from the EMDASH folder (same place as app.py). Delete afterwards if you
prefer, or keep it -- it's the canonical "re-tag after an engine change" tool.
"""
from __future__ import annotations

import argparse

import config
import core
import news_ingest


def _merge(old: str, source_id: str, headline: str, origin: dict) -> str:
    """Add-only merge: keep old tags, append new finds, origin fallback last."""
    have = [t for t in (old or "").split(",") if t]
    for t in news_ingest.tag_countries(headline).split(","):
        if t and t not in have:
            have.append(t)
    if not have:
        fb = origin.get(source_id, "")
        if fb:
            have.append(fb)
    return ",".join(have)


def main(commit: bool) -> None:
    origin = getattr(config, "FEED_ORIGIN_ISO", {})
    conn = core.get_conn()
    rows = conn.execute(
        "SELECT rowid, source_id, iso3_tags, headline FROM news"
    ).fetchall()

    updates = []           # (new_tags, rowid)
    newly_tagged = 0       # rows that went from empty -> tagged
    samples = []
    for rid, source_id, old, headline in rows:
        merged = _merge(old, source_id, headline, origin)
        if merged != (old or ""):
            updates.append((merged, rid))
            if not (old or "") and merged:
                newly_tagged += 1
            if len(samples) < 15:
                samples.append((old or "(none)", merged, headline))

    total = len(rows)
    still_empty = sum(
        1 for rid, s, old, h in rows
        if not _merge(old, s, h, origin)
    )

    print("=" * 74)
    print(f"  rows in table          : {total}")
    print(f"  rows that would change : {len(updates)}")
    print(f"  ...of which newly tagged (empty -> tagged): {newly_tagged}")
    print(f"  rows still country-less after re-tag       : {still_empty}"
          f"  ({still_empty/total:.1%})")
    print("=" * 74)
    print("  SAMPLE CHANGES (old -> new) :")
    for old, new, h in samples:
        print(f"    {old:12} -> {new:14} {h[:44]}")
    print("=" * 74)

    if not commit:
        print("  DRY RUN -- nothing written. Re-run with --commit to apply.")
        conn.close()
        return

    conn.executemany("UPDATE news SET iso3_tags=? WHERE rowid=?", updates)
    conn.commit()
    conn.close()
    print(f"  COMMITTED: {len(updates)} rows updated.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true",
                    help="write changes (default is dry run)")
    main(ap.parse_args().commit)
