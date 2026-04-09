# xscraper 🐦

Automated Twitter/X scraper. No API keys. No paid plans. Just works.

## What It Does

- Scrapes tweets from any public Twitter account using the syndication API
- Stores everything in a local SQLite database
- Searches, digests, and stats — all offline
- Auto-scrapes on a schedule (cron job)
- Zero dependencies — pure Python stdlib

## Usage

```bash
# Add accounts to watch
python3 xscraper.py add elonmusk
python3 xscraper.py add NousResearch

# List watched accounts
python3 xscraper.py list

# Scrape everything
python3 xscraper.py scrape

# Scrape one account
python3 xscraper.py scrape elonmusk

# Search tweets
python3 xscraper.py search "AI agents"

# Get today's digest
python3 xscraper.py digest

# Database stats
python3 xscraper.py stats
```

## How It Works

Uses Twitter's public syndication API (`syndication.twitter.com/srv/timeline-profile/screen-name/{username}`) which returns full tweet data without authentication. This is the same endpoint Twitter uses for embedded timelines on websites.

**No API keys. No developer account. No payment.**

## Rate Limits

The syndication API is rate-limited by IP. The scraper handles this with:
- 20 second delay between accounts
- Automatic retry with exponential backoff on 429 errors
- Recommended: scrape every 6 hours max

## Data Storage

SQLite database at `xscraper.db` with:
- Tweet text, username, timestamps
- Like/retweet counts
- Deduplication via content hashing
- Indexed for fast search

## Auto-Scrape

Set up a cron job to auto-scrape and send you digests:

```bash
# Every 6 hours
0 */6 * * * cd /path/to/xscraper && python3 xscraper.py scrape && python3 xscraper.py digest 6
```

## Requirements

- Python 3.8+
- That's it. No pip install needed.
