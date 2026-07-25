#!/usr/bin/env python3
"""Push files to GitHub via API (bypasses proxy authentication issues)"""
import requests, json, os, base64, urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load credentials from .env file
def load_env():
    env = {}
    env_path = os.path.join(BASE_DIR, '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    env[k.strip()] = v.strip()
    return env

env = load_env()
TOKEN = env.get('GITHUB_TOKEN', os.environ.get('GITHUB_TOKEN', ''))
OWNER = env.get('GITHUB_OWNER', os.environ.get('GITHUB_OWNER', ''))
REPO = env.get('GITHUB_REPO', os.environ.get('GITHUB_REPO', ''))

if not TOKEN or not OWNER or not REPO:
    print('ERROR: Missing GITHUB_TOKEN, GITHUB_OWNER, or GITHUB_REPO in .env')
    exit(1)

HEADERS = {'Authorization': f'token {TOKEN}', 'Accept': 'application/vnd.github+json'}
API = 'https://api.github.com'

def api(path, method='GET', data=None, max_retries=3):
    import time
    for attempt in range(max_retries):
        try:
            r = requests.request(method, API+path, headers=HEADERS, json=data, verify=False)
            if r.status_code >= 400:
                print(f'Error {r.status_code}: {r.text[:300]}')
                return None
            return r.json()
        except Exception as e:
            if attempt == max_retries - 1:
                print(f'Request failed after {max_retries} attempts: {e}')
                return None
            print(f'  Retry {attempt+1}/{max_retries} after error: {e}')
            time.sleep(3)

# Get default branch ref
ref_data = api(f'/repos/{OWNER}/{REPO}/git/ref/heads/main')
if not ref_data or 'object' not in ref_data:
    ref_data = api(f'/repos/{OWNER}/{REPO}/git/ref/heads/master')

files_to_push = ['index.html', 'data.json', 'scraper.py', '.gitignore', 'push_to_github.py', 'daily_update.py']

# Create blobs
tree_items = []
for fname in files_to_push:
    fpath = os.path.join(BASE_DIR, fname)
    if not os.path.exists(fpath):
        continue
    try:
        with open(fpath, 'r', encoding='utf-8') as f:
            content = f.read()
        encoding = 'utf-8'
    except UnicodeDecodeError:
        with open(fpath, 'rb') as f:
            content = base64.b64encode(f.read()).decode()
        encoding = 'base64'
    
    blob_data = {'content': content, 'encoding': encoding}
    blob = api(f'/repos/{OWNER}/{REPO}/git/blobs', 'POST', blob_data)
    if blob:
        tree_items.append({'path': fname, 'mode': '100644', 'type': 'blob', 'sha': blob['sha']})
        print(f'  Blob: {fname} ({blob["sha"][:8]})')

if not tree_items:
    print('No files to push')
    exit(1)

if ref_data and 'object' in ref_data:
    base_sha = ref_data['object']['sha']
    base_commit = api(f'/repos/{OWNER}/{REPO}/git/commits/{base_sha}')
    base_tree_sha = base_commit['tree']['sha']
    
    tree = api(f'/repos/{OWNER}/{REPO}/git/trees', 'POST', {
        'base_tree': base_tree_sha,
        'tree': tree_items
    })
    print(f'Tree: {tree["sha"][:8]}')
    
    commit = api(f'/repos/{OWNER}/{REPO}/git/commits', 'POST', {
        'message': 'Daily data refresh',
        'tree': tree['sha'],
        'parents': [base_sha]
    })
    print(f'Commit: {commit["sha"][:8]}')
    
    api(f'/repos/{OWNER}/{REPO}/git/refs/heads/main', 'PATCH', {
        'sha': commit['sha'],
        'force': False
    })
    print('Branch updated!')
else:
    tree = api(f'/repos/{OWNER}/{REPO}/git/trees', 'POST', {'tree': tree_items})
    commit = api(f'/repos/{OWNER}/{REPO}/git/commits', 'POST', {
        'message': 'Initial commit: K League analysis',
        'tree': tree['sha']
    })
    api(f'/repos/{OWNER}/{REPO}/git/refs', 'POST', {
        'ref': 'refs/heads/main',
        'sha': commit['sha']
    })
    print('Branch created!')

print(f'\n✅ Pushed! https://{OWNER.lower()}.github.io/{REPO}/')
