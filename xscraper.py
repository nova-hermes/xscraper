#!/usr/bin/env python3
"""
xscraper - Automated Twitter/X scraper using the syndication API.
No API keys needed. No paid plans. Just works.

Usage:
  python3 xscraper.py add <username>      # Add account to watch
  python3 xscraper.py remove <username>   # Remove account
  python3 xscraper.py list                # List watched accounts
  python3 xscraper.py scrape              # Scrape all watched accounts
  python3 xscraper.py scrape <username>   # Scrape one account
  python3 xscraper.py search "query"      # Search scraped tweets
  python3 xscraper.py digest              # Get today's top tweets
  python3 xscraper.py stats               # Database stats
"""

import urllib.request
import json
import re
import sqlite3
import sys
import os
import time
import hashlib
from datetime import datetime, timedelta

# ─── Config ───────────────────────────────────────────────────────────────

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xscraper.db")
WATCHLIST_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchlist.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

SCRAPE_DELAY = 20  # seconds between accounts (syndication API is rate-limited)

# ─── Database ─────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS tweets (
            hash TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            text TEXT,
            created_at TEXT,
            likes INTEGER DEFAULT 0,
            retweets INTEGER DEFAULT 0,
            scraped_at TEXT
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_username ON tweets(username)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_likes ON tweets(likes)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_created ON tweets(created_at)")
    conn.commit()
    return conn

# ─── Watchlist ────────────────────────────────────────────────────────────

def load_watchlist():
    if os.path.exists(WATCHLIST_PATH):
        with open(WATCHLIST_PATH, 'r') as f:
            return json.load(f)
    return {"accounts": []}

def save_watchlist(watchlist):
    with open(WATCHLIST_PATH, 'w') as f:
        json.dump(watchlist, f, indent=2)

# ─── Core Scraper ─────────────────────────────────────────────────────────

def make_hash(username, text, created_at):
    raw = f"{username}|{text}|{created_at}"
    return hashlib.md5(raw.encode()).hexdigest()

def scrape_account(username, conn, max_retries=3):
    username = username.strip().lstrip('@')
    url = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{username}"
    
    print(f"  @{username}...", end=" ", flush=True)
    
    html = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as resp:
                html = resp.read().decode('utf-8', errors='replace')
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < max_retries - 1:
                wait = 20 * (attempt + 1)
                print(f"⏳ waiting {wait}s...", end=" ", flush=True)
                time.sleep(wait)
                continue
            elif e.code == 429:
                print("❌ rate limited")
                return 0, 0
            else:
                print(f"❌ HTTP {e.code}")
                return 0, 0
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(10)
                continue
            print(f"❌ {str(e)[:50]}")
            return 0, 0
    
    if not html:
        print("❌ no data")
        return 0, 0
    
    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
    if not match:
        print("❌ parse error")
        return 0, 0
    
    data = json.loads(match.group(1))
    entries = data.get('props', {}).get('pageProps', {}).get('timeline', {}).get('entries', [])
    
    c = conn.cursor()
    new_count = 0
    total = 0
    
    for entry in entries:
        if entry.get('type') != 'tweet':
            continue
        tweet = entry.get('content', {}).get('tweet', {})
        if not tweet:
            continue
        
        total += 1
        text = tweet.get('full_text', '')
        created = tweet.get('created_at', '')
        likes = tweet.get('favorite_count', 0) or 0
        rts = tweet.get('retweet_count', 0) or 0
        tweet_hash = make_hash(username, text, created)
        
        try:
            c.execute(
                "INSERT INTO tweets (hash, username, text, created_at, likes, retweets, scraped_at) VALUES (?,?,?,?,?,?,?)",
                (tweet_hash, username, text, created, likes, rts, datetime.utcnow().isoformat())
            )
            new_count += 1
        except sqlite3.IntegrityError:
            pass
    
    conn.commit()
    print(f"✓ {total} tweets, {new_count} new")
    return total, new_count

# ─── Search & Digest ──────────────────────────────────────────────────────

def search_tweets(query, conn, limit=20):
    c = conn.cursor()
    c.execute(
        "SELECT username, text, created_at, likes, retweets, hash FROM tweets WHERE text LIKE ? ORDER BY likes DESC LIMIT ?",
        (f"%{query}%", limit)
    )
    results = c.fetchall()
    if not results:
        print(f"No tweets found matching '{query}'")
        return
    
    print(f"\n🔍 Results for '{query}' ({len(results)} found):\n")
    for username, text, created, likes, rt, h in results:
        preview = text[:150].replace('\n', ' ')
        print(f"  @{username} | ❤️{likes} 🔁{rt}")
        print(f"  {preview}")
        print()

def generate_digest(conn, hours=24):
    c = conn.cursor()
    since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    
    c.execute(
        "SELECT username, text, created_at, likes, retweets FROM tweets WHERE scraped_at >= ? ORDER BY likes DESC LIMIT 15",
        (since,)
    )
    tweets = c.fetchall()
    if not tweets:
        print("No tweets in the last 24h. Run 'scrape' first.")
        return None
    
    lines = [f"📰 Twitter Digest (last {hours}h)\n"]
    for i, (username, text, created, likes, rt) in enumerate(tweets, 1):
        short = text[:150].replace('\n', ' ')
        if len(text) > 150:
            short += "..."
        lines.append(f"{i}. @{username} | ❤️{likes} 🔁{rt}")
        lines.append(f"   {short}\n")
    
    digest = "\n".join(lines)
    print(digest)
    return digest

def show_stats(conn):
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM tweets")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(DISTINCT username) FROM tweets")
    accounts = c.fetchone()[0]
    c.execute("SELECT username, COUNT(*) FROM tweets GROUP BY username ORDER BY COUNT(*) DESC LIMIT 10")
    top = c.fetchall()
    
    print(f"\n📊 xscraper stats:")
    print(f"  Total tweets: {total}")
    print(f"  Accounts: {accounts}")
    print(f"\n  Top accounts:")
    for username, cnt in top:
        print(f"    @{username}: {cnt}")

# ─── CLI ──────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    
    cmd = sys.argv[1].lower()
    conn = init_db()
    
    if cmd == "add":
        if len(sys.argv) < 3:
            print("Usage: xscraper.py add <username>")
            return
        username = sys.argv[2].strip().lstrip('@')
        wl = load_watchlist()
        if username not in wl["accounts"]:
            wl["accounts"].append(username)
            save_watchlist(wl)
            print(f"✓ Added @{username}")
        else:
            print(f"@{username} already in watchlist")
    
    elif cmd == "remove":
        if len(sys.argv) < 3:
            print("Usage: xscraper.py remove <username>")
            return
        username = sys.argv[2].strip().lstrip('@')
        wl = load_watchlist()
        if username in wl["accounts"]:
            wl["accounts"].remove(username)
            save_watchlist(wl)
            print(f"✓ Removed @{username}")
        else:
            print(f"@{username} not in watchlist")
    
    elif cmd == "list":
        wl = load_watchlist()
        accounts = wl.get("accounts", [])
        if accounts:
            print(f"📋 Watchlist ({len(accounts)} accounts):")
            for a in accounts:
                print(f"  @{a}")
        else:
            print("Watchlist empty. Use 'add <username>' first.")
    
    elif cmd == "scrape":
        wl = load_watchlist()
        accounts = wl.get("accounts", [])
        
        if len(sys.argv) >= 3:
            scrape_account(sys.argv[2].strip().lstrip('@'), conn)
        elif accounts:
            print(f"🔄 Scraping {len(accounts)} accounts...\n")
            total_new = 0
            for i, username in enumerate(accounts):
                _, new = scrape_account(username, conn)
                total_new += new
                if i < len(accounts) - 1:
                    time.sleep(SCRAPE_DELAY)
            print(f"\n✅ Done! {total_new} new tweets.")
        else:
            print("No accounts to scrape. Use 'add <username>' first.")
    
    elif cmd == "search":
        if len(sys.argv) < 3:
            print("Usage: xscraper.py search <query>")
            return
        search_tweets(" ".join(sys.argv[2:]), conn)
    
    elif cmd == "digest":
        hours = int(sys.argv[2]) if len(sys.argv) >= 3 else 24
        generate_digest(conn, hours)
    
    elif cmd == "stats":
        show_stats(conn)
    
    else:
        print(f"Unknown: {cmd}")
        print(__doc__)
    
    conn.close()

if __name__ == "__main__":
    main()
