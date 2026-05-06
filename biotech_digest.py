#!/usr/bin/env python3
"""
Biotech VC Daily Digest
========================
Pulls latest news from major biotech/pharma RSS feeds, classifies each entry
by deal type AND therapeutic modality, and outputs a structured markdown digest.

Usage:
    python biotech_digest.py              # last 24 hours
    python biotech_digest.py --hours 48   # last 48 hours
"""

import argparse
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

import feedparser


# ─── CONFIG ──────────────────────────────────────────────────────────────────

FEEDS = {
    "Fierce Biotech":         "https://www.fiercebiotech.com/rss/xml",
    "Fierce Pharma":          "https://www.fiercepharma.com/rss/xml",
    "Endpoints News":         "https://endpts.com/feed/",
    "BioPharma Dive":         "https://www.biopharmadive.com/feeds/news/",
    "STAT — Pharmalot":       "https://www.statnews.com/category/pharmalot/feed/",
    "STAT — Biotech":         "https://www.statnews.com/category/biotech/feed/",
    "FierceBiotech Research": "https://www.fiercebiotech.com/biotech-research/rss/xml",
}

# Optional. Companies you're actively tracking — appear at top if any hits.
WATCHLIST = {
    # "Moderna": ["moderna", "mrna"],
    # "Vertex":  ["vertex pharm", "vrtx"],
}

# Deal type classification (regex, case-insensitive)
DEAL_PATTERNS = {
    "💰 Financing": [
        r"\bseries [a-z]\b", r"\braises? \$", r"\bsecures? \$",
        r"\bcloses? \$", r"\bipo\b", r"\bventure\b",
        r"\bfunding round\b", r"\bcrossover\b", r"\bpre-ipo\b",
        r"\bseed round\b",
    ],
    "🤝 M&A": [
        r"\bacquires?\b", r"\bacquisition\b", r"\bmerger\b",
        r"\bto buy\b", r"\btakeover\b",
    ],
    "🧪 Clinical": [
        r"\bphase [123]\b", r"\bclinical trial\b", r"\btopline\b",
        r"\bprimary endpoint\b", r"\breadout\b", r"\binterim data\b",
        r"\bmet endpoint\b", r"\bfailed to meet\b", r"\bdosing\b",
    ],
    "📋 Regulatory": [
        r"\bfda\b", r"\bapprov\w+\b", r"\bind\b", r"\bbla\b",
        r"\bnda\b", r"\bema\b", r"\bcrl\b", r"\bbreakthrough\b",
        r"\bfast track\b", r"\borphan\b", r"\baccelerated approval\b",
    ],
    "🔗 Partnership / Licensing": [
        r"\bpartnership\b", r"\bcollaboration\b", r"\blicens\w+\b",
        r"\bdeal worth\b", r"\bmilestone payment\b", r"\bupfront\b",
    ],
    "👥 People / Strategy": [
        r"\bappoints?\b", r"\bnames? new\b", r"\bsteps? down\b",
        r"\blays? off\b", r"\brestructur\w+",
    ],
}

# Therapeutic modality / area classification
MODALITY_PATTERNS = {
    "🎯 Oncology":           [r"\bcancer\b", r"\boncolog\w+", r"\btumor\b", r"\bleukemia\b",
                              r"\blymphoma\b", r"\bmelanoma\b", r"\bcarcinoma\b", r"\bsolid tumor\b"],
    "💊 GLP-1 / Metabolic":  [r"\bglp-?1\b", r"\bobesity\b", r"\bweight loss\b", r"\bdiabet\w+",
                              r"\bsemaglutide\b", r"\btirzepatide\b", r"\bmetabolic\b"],
    "💉 ADC":                [r"\badc\b", r"\bantibody-?drug conjugate\b", r"\bdrug conjugate\b"],
    "🧬 Cell & Gene Therapy":[r"\bcell therapy\b", r"\bcar-?t\b", r"\bgene therapy\b",
                              r"\baav\b", r"\blentivirus\b", r"\bipsc\b", r"\bstem cell\b"],
    "🧪 RNA Therapeutics":   [r"\bmrna\b", r"\bsirna\b", r"\boligonucleotide\b",
                              r"\bantisense\b", r"\baso\b"],
    "✂️ Gene Editing":       [r"\bcrispr\b", r"\bgene editing\b", r"\bbase editing\b",
                              r"\bprime editing\b"],
    "🧠 Neurology / CNS":    [r"\balzheimer", r"\bparkinson", r"\bneurolog\w+",
                              r"\bmultiple sclerosis\b", r"\bals\b", r"\bcns\b", r"\bdementia\b"],
    "🛡️ Immunology":         [r"\bautoimmune\b", r"\bimmunolog\w+", r"\blupus\b",
                              r"\bpsoriasis\b", r"\binflammator\w+"],
    "🦠 Rare Disease":       [r"\brare disease\b", r"\bultra-rare\b"],
    "🤖 AI Drug Discovery":  [r"\bai-?driven\b", r"\bmachine learning\b", r"\bartificial intelligence\b",
                              r"\bai platform\b", r"\bai drug discovery\b"],
}

DEAL_ORDER = list(DEAL_PATTERNS.keys()) + ["📰 General"]
MODALITY_ORDER = list(MODALITY_PATTERNS.keys()) + ["🔬 Other"]


# ─── CORE LOGIC ──────────────────────────────────────────────────────────────

def clean_summary(raw: str, max_len: int = 350) -> str:
    text = re.sub(r"<[^>]+>", "", raw)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len] + "..." if len(text) > max_len else text


def classify(text: str, patterns: dict, default: str) -> list[str]:
    text = text.lower()
    matches = [
        label for label, regexes in patterns.items()
        if any(re.search(r, text) for r in regexes)
    ]
    return matches or [default]


def watchlist_hits(text: str) -> list[str]:
    text = text.lower()
    return [name for name, aliases in WATCHLIST.items()
            if any(a.lower() in text for a in aliases)]


def fetch_feed(name: str, url: str, since: datetime) -> list[dict]:
    feed = feedparser.parse(url)
    out = []
    for e in feed.entries:
        struct = e.get("published_parsed") or e.get("updated_parsed")
        if not struct:
            continue
        pub_dt = datetime(*struct[:6], tzinfo=timezone.utc)
        if pub_dt < since:
            continue

        title = e.get("title", "").strip()
        summary = clean_summary(e.get("summary", ""))
        full_text = title + " " + summary

        out.append({
            "source": name,
            "title": title,
            "link": e.get("link", ""),
            "summary": summary,
            "published": pub_dt,
            "deals": classify(full_text, DEAL_PATTERNS, "📰 General"),
            "modalities": classify(full_text, MODALITY_PATTERNS, "🔬 Other"),
            "watchlist": watchlist_hits(full_text),
        })
    return out


def build_summary_table(entries: list[dict]) -> str:
    """Modality × Deal Type matrix at the top of the digest."""
    counts: dict[str, dict[str, int]] = {}
    for e in entries:
        for m in e["modalities"]:
            counts.setdefault(m, {})
            for d in e["deals"]:
                counts[m][d] = counts[m].get(d, 0) + 1

    if not counts:
        return ""

    deal_cols = [d for d in DEAL_ORDER if any(d in row for row in counts.values())]
    header = "| Modality | Total | " + " | ".join(deal_cols) + " |"
    sep = "|" + "---|" * (len(deal_cols) + 2)

    rows = []
    for m in MODALITY_ORDER:
        if m not in counts:
            continue
        row_counts = counts[m]
        total = sum(row_counts.values())
        cells = [str(row_counts.get(d, 0)) if row_counts.get(d, 0) else "·" for d in deal_cols]
        rows.append(f"| {m} | **{total}** | " + " | ".join(cells) + " |")

    return "\n".join(["## 📊 At a Glance", "", header, sep, *rows, ""])


def generate_digest(hours: int = 24) -> str:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    print(f"Fetching feeds since {since.strftime('%Y-%m-%d %H:%M UTC')}...\n")

    entries = []
    for name, url in FEEDS.items():
        try:
            new = fetch_feed(name, url, since)
            print(f"  ✓ {name:30s} {len(new):3d}")
            entries.extend(new)
        except Exception as exc:
            print(f"  ✗ {name:30s} ERROR: {exc}")

    entries.sort(key=lambda x: x["published"], reverse=True)

    # Dedupe by title
    seen, unique = set(), []
    for e in entries:
        key = e["title"].lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(e)

    today = datetime.now().strftime("%Y-%m-%d (%A)")
    lines = [
        f"# 🧬 Biotech Daily Digest — {today}",
        "",
        f"*Last {hours}h · {len(unique)} unique entries · {len(FEEDS)} sources*",
        "",
        build_summary_table(unique),
    ]

    # Watchlist hits
    wl = [e for e in unique if e["watchlist"]]
    if wl:
        lines += ["## 🎯 Watchlist Hits", ""]
        for e in wl:
            tags = ", ".join(f"**{c}**" for c in e["watchlist"])
            deal_tags = " ".join(f"`{d}`" for d in e["deals"])
            lines += [
                f"- {tags} {deal_tags} — [{e['title']}]({e['link']}) *— {e['source']}*",
                f"  > {e['summary']}",
                "",
            ]

    # Group by modality (primary view)
    by_mod: dict[str, list[dict]] = {}
    for e in unique:
        for m in e["modalities"]:
            by_mod.setdefault(m, []).append(e)

    for mod in MODALITY_ORDER:
        if mod not in by_mod:
            continue
        items = by_mod[mod]
        lines += [f"## {mod} ({len(items)})", ""]
        for e in items[:20]:
            deal_tags = " ".join(f"`{d}`" for d in e["deals"])
            lines += [
                f"- {deal_tags} [{e['title']}]({e['link']}) *— {e['source']}*",
                f"  {e['summary']}",
                "",
            ]

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--out", type=Path, default=Path("digests"))
    args = parser.parse_args()

    digest = generate_digest(hours=args.hours)
    args.out.mkdir(exist_ok=True)
    today_str = datetime.now().strftime("%Y%m%d")
    out_path = args.out / f"digest_{today_str}.md"
    out_path.write_text(digest, encoding="utf-8")
    print(f"\n✓ Digest saved → {out_path} ({len(digest):,} chars)")


if __name__ == "__main__":
    main()
