#!/usr/bin/env python3
"""Biotech VC Daily Digest — bilingual (EN/KO) with LLM-rewritten summaries."""

import argparse
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
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

WATCHLIST = {
    # "Moderna": ["moderna", "mrna"],
}

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

# GitHub Models — free, OpenAI-compatible, auth via GITHUB_TOKEN in Actions
LLM_ENDPOINT = "https://models.github.ai/inference/chat/completions"
LLM_MODEL = "openai/gpt-4o-mini"
LLM_BATCH_SIZE = 6
LLM_TIMEOUT_S = 120


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def clean_text(raw: str, max_len: int = 1200) -> str:
    text = re.sub(r"<[^>]+>", "", raw or "")
    text = re.sub(r"\s+", " ", text).strip()
    if max_len and len(text) > max_len:
        text = text[:max_len].rstrip() + "..."
    return text


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


# ─── FETCH ───────────────────────────────────────────────────────────────────

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
        summary_raw = clean_text(e.get("summary", ""))
        full_text = title + " " + summary_raw

        out.append({
            "source": name,
            "title": title,
            "link": e.get("link", ""),
            "summary_raw": summary_raw,
            "summary_en": "",
            "summary_ko": "",
            "published": pub_dt,
            "deals": classify(full_text, DEAL_PATTERNS, "📰 General"),
            "modalities": classify(full_text, MODALITY_PATTERNS, "🔬 Other"),
            "watchlist": watchlist_hits(full_text),
        })
    return out


def collect_entries(hours: int) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    print(f"Fetching feeds since {since.strftime('%Y-%m-%d %H:%M UTC')}...\n")
    entries: list[dict] = []
    for name, url in FEEDS.items():
        try:
            new = fetch_feed(name, url, since)
            print(f"  ✓ {name:30s} {len(new):3d}")
            entries.extend(new)
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ {name:30s} ERROR: {exc}")
    entries.sort(key=lambda x: x["published"], reverse=True)
    seen, unique = set(), []
    for e in entries:
        key = e["title"].lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(e)
    return unique


# ─── LLM ENRICHMENT ──────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are a biotech VC news editor. For each news item, produce two summaries:\n"
    "- 'en': 2-3 informative sentences in English. Mention concrete facts: company "
    "name, deal value (if any), drug/target/modality, trial phase, indication, key "
    "numbers. No fluff or marketing language. Do not just restate the title.\n"
    "- 'ko': natural Korean translation of the same content. Use industry terminology "
    "(e.g., 임상 2상, FDA 승인, 시리즈 B). Keep company and drug names in English.\n"
    'Return strictly valid JSON: {"items":[{"i":1,"en":"...","ko":"..."}, ...]}.'
)


def call_llm(messages: list[dict]) -> str | None:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return None
    body = json.dumps({
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    req = urllib.request.Request(
        LLM_ENDPOINT,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        print(f"  ✗ LLM HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:300]}")
    except Exception as e:  # noqa: BLE001
        print(f"  ✗ LLM error: {e}")
    return None


def enrich_batch(entries: list[dict]) -> bool:
    items_text = "\n\n".join(
        f"{i+1}. TITLE: {e['title']}\n   CONTENT: {e['summary_raw']}"
        for i, e in enumerate(entries)
    )
    raw = call_llm([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Items:\n{items_text}"},
    ])
    if not raw:
        return False
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as ex:
        print(f"  ✗ JSON parse failed: {ex}")
        return False
    for item in parsed.get("items", []):
        idx = item.get("i", 0) - 1
        if 0 <= idx < len(entries):
            entries[idx]["summary_en"] = item.get("en", "").strip()
            entries[idx]["summary_ko"] = item.get("ko", "").strip()
    return True


def enrich_with_llm(entries: list[dict]) -> None:
    if not entries:
        return
    if not os.environ.get("GITHUB_TOKEN"):
        print("\n  (no GITHUB_TOKEN — skipping LLM, using raw RSS summaries)")
        return
    print(f"\nEnriching {len(entries)} entries via GitHub Models ({LLM_MODEL})...")
    for start in range(0, len(entries), LLM_BATCH_SIZE):
        batch = entries[start:start + LLM_BATCH_SIZE]
        ok = enrich_batch(batch)
        n = start // LLM_BATCH_SIZE + 1
        print(f"  {'✓' if ok else '✗'} batch {n} ({len(batch)} items)")


# ─── RENDERING ───────────────────────────────────────────────────────────────

LABELS = {
    "en": {
        "title_prefix": "🧬 Biotech Daily Digest",
        "meta": lambda h, n, s: f"*Last {h}h · {n} unique entries · {s} sources*",
        "at_a_glance": "📊 At a Glance",
        "modality_col": "Modality",
        "total_col": "Total",
        "watchlist": "🎯 Watchlist Hits",
    },
    "ko": {
        "title_prefix": "🧬 바이오테크 데일리 다이제스트",
        "meta": lambda h, n, s: f"*최근 {h}시간 · 고유 기사 {n}건 · 소스 {s}개*",
        "at_a_glance": "📊 한눈에 보기",
        "modality_col": "모달리티",
        "total_col": "합계",
        "watchlist": "🎯 워치리스트 매치",
    },
}


def build_summary_table(entries: list[dict], lang: str) -> str:
    L = LABELS[lang]
    counts: dict[str, dict[str, int]] = {}
    for e in entries:
        for m in e["modalities"]:
            counts.setdefault(m, {})
            for d in e["deals"]:
                counts[m][d] = counts[m].get(d, 0) + 1
    if not counts:
        return ""
    deal_cols = [d for d in DEAL_ORDER if any(d in row for row in counts.values())]
    header = f"| {L['modality_col']} | {L['total_col']} | " + " | ".join(deal_cols) + " |"
    sep = "|" + "---|" * (len(deal_cols) + 2)
    rows = []
    for m in MODALITY_ORDER:
        if m not in counts:
            continue
        row = counts[m]
        total = sum(row.values())
        cells = [str(row.get(d, 0)) if row.get(d, 0) else "·" for d in deal_cols]
        rows.append(f"| {m} | **{total}** | " + " | ".join(cells) + " |")
    return "\n".join([f"## {L['at_a_glance']}", "", header, sep, *rows, ""])


def render_digest(entries: list[dict], lang: str, hours: int) -> str:
    L = LABELS[lang]
    today = datetime.now().strftime("%Y-%m-%d (%A)")
    sum_field = "summary_en" if lang == "en" else "summary_ko"

    def get_summary(e: dict) -> str:
        return e.get(sum_field) or e.get("summary_raw") or ""

    lines = [
        f"# {L['title_prefix']} — {today}",
        "",
        L["meta"](hours, len(entries), len(FEEDS)),
        "",
        build_summary_table(entries, lang),
    ]

    wl = [e for e in entries if e["watchlist"]]
    if wl:
        lines += [f"## {L['watchlist']}", ""]
        for e in wl:
            tags = ", ".join(f"**{c}**" for c in e["watchlist"])
            deal_tags = " ".join(f"`{d}`" for d in e["deals"])
            lines += [
                f"- {tags} {deal_tags} — [{e['title']}]({e['link']}) *— {e['source']}*",
                f"  > {get_summary(e)}",
                "",
            ]

    by_mod: dict[str, list[dict]] = {}
    for e in entries:
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
                f"  {get_summary(e)}",
                "",
            ]
    return "\n".join(lines)


# ─── MAIN ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--out", type=Path, default=Path("digests"))
    args = parser.parse_args()

    entries = collect_entries(args.hours)
    enrich_with_llm(entries)

    args.out.mkdir(exist_ok=True)
    today_str = datetime.now().strftime("%Y%m%d")
    for lang in ("en", "ko"):
        digest = render_digest(entries, lang, args.hours)
        out_path = args.out / f"digest_{today_str}_{lang}.md"
        out_path.write_text(digest, encoding="utf-8")
        print(f"\n✓ {lang.upper()} digest → {out_path} ({len(digest):,} chars)")


if __name__ == "__main__":
    main()
