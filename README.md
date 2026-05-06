# 🧬 Biotech VC Daily Digest

Daily-scraped, deal-type and modality-classified biotech news digest, with **English + Korean** summaries rewritten by an LLM (GitHub Models — free, no API key needed). Runs autonomously on GitHub Actions every day at 07:00 KST.

## Live archive
See [`digests/`](./digests) — two files per day (`_en.md` and `_ko.md`), committed automatically by GitHub Actions.

## Manual run

```bash
pip install -r requirements.txt
python biotech_digest.py             # last 24h
python biotech_digest.py --hours 48  # weekend catch-up
```

## Customize
Edit `biotech_digest.py`:
- `FEEDS` — add/remove RSS sources
- `WATCHLIST` — companies to flag at top of digest
- `DEAL_PATTERNS` / `MODALITY_PATTERNS` — adjust classification rules
