#!/usr/bin/env python3
"""
Daily update script: scrape data, push to GitHub.
Runs scraper.py then pushes all changed files to GitHub via API.
"""
import subprocess, sys, os

BASE = os.path.dirname(os.path.abspath(__file__))

# Step 1: Run scraper
print("=" * 50)
print("STEP 1: Scraping latest K League data...")
print("=" * 50)
result = subprocess.run(
    [sys.executable, os.path.join(BASE, 'scraper.py')],
    cwd=BASE, capture_output=False
)
if result.returncode != 0:
    print("ERROR: Scraper failed!")
    sys.exit(1)

# Step 2: Push to GitHub
print("\n" + "=" * 50)
print("STEP 2: Pushing to GitHub...")
print("=" * 50)
result = subprocess.run(
    [sys.executable, os.path.join(BASE, 'push_to_github.py')],
    cwd=BASE, capture_output=False
)
if result.returncode != 0:
    print("ERROR: GitHub push failed!")
    sys.exit(1)

print("\n✅ Daily update complete!")
