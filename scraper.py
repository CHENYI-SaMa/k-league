#!/usr/bin/env python3
"""
韩职联（K League）赛事分析数据爬虫
数据来源: 500彩票网 https://trade.500.com/jczq/
用法: python scraper.py
输出: data.json
"""

import requests
import re
import json
import time
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
}

JCZQ_URL = 'https://trade.500.com/jczq/'
ANALYSIS_URL = 'https://odds.500.com/fenxi/shuju-{}.shtml'


def fetch_html(url, encoding='gb2312', retries=2):
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.encoding = encoding
            return r.text
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(2)


def parse_main_page(html):
    """Parse JCZQ main page for all matches"""
    matches = []
    parts = html.split('data-fixtureid="')
    parts = parts[1:]
    
    for part in parts:
        fixture_id = part.split('"')[0]
        context = part[:3000]
        
        def get_attr(name):
            m = re.search(rf'data-{name}="([^"]*)"', context)
            return m.group(1) if m else ''
        
        league = get_attr('simpleleague')
        # Normalize long league names for display
        league_display = {
            '芬兰超级联赛': '芬超',
            '韩国职业联赛': '韩职',
        }.get(league, league)
        
        home = get_attr('homesxname')
        away = get_attr('awaysxname')
        match_date = get_attr('matchdate')
        match_time = get_attr('matchtime')
        match_num = get_attr('matchnum')
        rangqiu = get_attr('rangqiu')
        
        rank_patterns = re.findall(r'排名第(\d+)', context)
        home_rank = rank_patterns[0] if len(rank_patterns) >= 1 else ''
        away_rank = rank_patterns[1] if len(rank_patterns) >= 2 else ''
        
        nspf_spans = re.findall(r'data-type="nspf"[^>]*data-sp="([^"]*)"', context)
        spf_spans = re.findall(r'data-type="spf"[^>]*data-sp="([^"]*)"', context)
        
        matches.append({
            'fixture_id': fixture_id,
            'match_num': match_num,
            'league': league_display,
            'home_team': home,
            'away_team': away,
            'home_rank': home_rank,
            'away_rank': away_rank,
            'match_date': match_date,
            'match_time': match_time,
            'rangqiu': rangqiu,
            'odds_nspf': nspf_spans[:3],
            'odds_spf': spf_spans[:3],
        })
    
    return matches


def parse_score_text(raw):
    """Parse '光州FC1:1金泉尚武' or '光州FC 1:1 金泉尚武' into teams and score"""
    # Strip ranking prefix like '[12]光州FC1:1金泉尚武[11]'
    raw = re.sub(r'\[\d+\]', '', raw).strip()
    
    # Match TeamName X:Y TeamName
    m = re.search(r'(.+?)\s*(\d+)[：:]\s*(\d+)\s*(.+)', raw)
    if m:
        return m.group(1).strip(), m.group(4).strip(), f'{m.group(2)}:{m.group(3)}'
    return '', '', ''


def parse_match_row(row):
    """Parse a match row: cells = [league, date, teams+score, half_score, result, ...]"""
    cells = row.find_all('td')
    if len(cells) < 5:
        return None
    
    # Cell 1: date - handle YYYY-MM-DD, YY-MM-DD, or just MM-DD
    date_text = cells[1].get_text(strip=True)
    date_m = re.search(r'((?:\d{2}|\d{4})-\d{2}-\d{2})', date_text)
    if not date_m:
        return None
    date = date_m.group(1)
    # Normalize: YYYY-MM-DD → YY-MM-DD
    if date.count('-') == 2 and len(date) >= 10:
        date = date[2:]
    # If only 5 chars (M-DD), prepend current year
    if len(date) == 5:
        date = '26-' + date
    
    # Cell 2: teams + score
    teams_text = cells[2].get_text(strip=True)
    home, away, score = parse_score_text(teams_text)
    if not score:
        return None
    
    # Result: find 胜/平/负 cell
    result = ''
    for cell in cells:
        ct = cell.get_text(strip=True)
        if ct in ('胜', '平', '负'):
            result = ct
            break
    
    return {
        'date': date,
        'home': home,
        'away': away,
        'score': score,
        'result': result,
    }


def parse_analysis_page(html, match_data):
    """Parse match analysis page"""
    soup = BeautifulSoup(html, 'html.parser')
    # Get raw text with newlines preserved for regex
    raw_text = soup.get_text('\n', strip=True)
    text_flat = soup.get_text(' ', strip=True)
    tables = soup.find_all('table')
    
    home_team = match_data['home_team']
    away_team = match_data['away_team']
    
    data = {}
    
    # --- H2H summary (computed from match data later) ---
    
    # Find all odds tables (header has: 半场, 赛果, 盘路, 大小)
    odds_tables = []
    for table in tables:
        rows = table.find_all('tr')
        if len(rows) < 3:
            continue
        header_text = rows[0].get_text(strip=True)
        if all(k in header_text for k in ('半场', '赛果', '盘路', '大小')):
            matches_list = []
            for row in rows[2:]:  # Skip header + current match row
                cells = row.find_all('td')
                if len(cells) < 5:
                    continue
                teams_text = cells[2].get_text(strip=True) if len(cells) > 2 else ''
                if 'VS' in teams_text or 'vs' in teams_text.lower():
                    continue
                m = parse_match_row(row)
                if m:
                    matches_list.append(m)
            if matches_list:
                odds_tables.append(matches_list)
    
    # First odds table = H2H
    if odds_tables:
        data['h2h_matches'] = odds_tables[0][:6]
    
    # Remaining odds tables = recent form. Identify by team names
    home_recent = []
    away_recent = []
    
    for tbl in odds_tables[1:]:
        if not tbl:
            continue
        first_entry = tbl[0]
        teams_str = first_entry.get('home', '') + first_entry.get('away', '')
        
        if home_team in teams_str:
            if not home_recent:
                home_recent = tbl[:5]
        elif away_team in teams_str:
            if not away_recent:
                away_recent = tbl[:5]
    
    # Fallback: use table positions
    if not home_recent and len(odds_tables) > 1:
        home_recent = odds_tables[1][:5]
    if not away_recent and len(odds_tables) > 2:
        away_recent = odds_tables[2][:5]
    
    data['home_recent_5_matches'] = home_recent
    data['away_recent_5_matches'] = away_recent
    
    # --- Recent form stats from text ---
    # Use raw text (with newlines) for better matching
    all_recent = list(re.finditer(
        r'(\S+)\s*近(\d+)场战绩\s*(\d+)胜\s*(\d+)平\s*(\d+)负\s*进(\d+)球\s*失(\d+)球',
        raw_text
    ))
    
    seen_home = False
    seen_away = False
    for m in all_recent:
        team = m.group(1)
        entry = {
            'matches': m.group(2),
            'wins': m.group(3),
            'draws': m.group(4),
            'losses': m.group(5),
            'goals_for': m.group(6),
            'goals_against': m.group(7),
        }
        
        section_before = raw_text[max(0, m.start()-200):m.start()]
        
        if home_team in team:
            if '主场' in section_before:
                data['home_recent_home'] = entry
            elif not seen_home:
                data['home_recent_all'] = entry
                seen_home = True
        elif away_team in team:
            if '客场' in section_before:
                data['away_recent_away'] = entry
            elif not seen_away:
                data['away_recent_all'] = entry
                seen_away = True
    
    # --- Average stats ---
    avg_count = 0
    for table in tables:
        table_text = table.get_text(strip=True)
        if '总平均数' in table_text and '主场' in table_text and '客场' in table_text:
            avg_count += 1
            prefix = 'home' if avg_count == 1 else 'away'
            
            for row in table.find_all('tr')[1:]:
                cells = row.find_all('td')
                if len(cells) >= 4:
                    label = cells[0].get_text(strip=True)
                    vals = [c.get_text(strip=True).replace('球', '') for c in cells[1:4]]
                    
                    if '入球' in label:
                        data[f'{prefix}_avg_scored'] = vals[0]
                        data[f'{prefix}_avg_scored_home'] = vals[1]
                        data[f'{prefix}_avg_scored_away'] = vals[2]
                    elif '失球' in label:
                        data[f'{prefix}_avg_conceded'] = vals[0]
                        data[f'{prefix}_avg_conceded_home'] = vals[1]
                        data[f'{prefix}_avg_conceded_away'] = vals[2]
    
    return data


def scrape_all():
    print('正在获取竞彩足球主页...')
    main_html = fetch_html(JCZQ_URL)
    
    print('解析每日比赛列表...')
    matches = parse_main_page(main_html)
    
    print(f'找到 {len(matches)} 场比赛\n')
    
    for i, match in enumerate(matches):
        fixture_id = match['fixture_id']
        print(f'[{i+1}/{len(matches)}] {match["match_num"]} {match["home_team"]} vs {match["away_team"]}')
        
        try:
            analysis_html = fetch_html(ANALYSIS_URL.format(fixture_id))
            analysis_data = parse_analysis_page(analysis_html, match)
            match['analysis'] = analysis_data
            
            h2h = len(analysis_data.get('h2h_matches', []))
            h5 = len(analysis_data.get('home_recent_5_matches', []))
            a5 = len(analysis_data.get('away_recent_5_matches', []))
            print(f'  ✓ H2H:{h2h} 主:{h5} 客:{a5}')
        except Exception as e:
            print(f'  ✗ {e}')
            match['analysis'] = {}
        
        time.sleep(0.8)
    
    return matches


if __name__ == '__main__':
    data = scrape_all()
    
    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    leagues_count = len(set(m.get('league', '') for m in data))
    print(f'\n✅ 保存 data.json ({len(data)} 场，{leagues_count} 个联赛)')
