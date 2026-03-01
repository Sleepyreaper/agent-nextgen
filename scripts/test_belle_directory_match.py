import json
import os
import re
import difflib

def fetch_state_school_list(state_code: str):
    code = state_code.strip().lower()
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
    json_path = os.path.join(data_dir, f'{code}_high_schools.json')
    if not os.path.isfile(json_path):
        print(f'No local data file found: {json_path}')
        return []
    with open(json_path, 'r', encoding='utf-8') as f:
        entries = json.load(f)
    schools = []
    for entry in entries:
        name = entry.get('school_name', '').strip() if isinstance(entry, dict) else str(entry).strip()
        if name and name not in schools:
            schools.append(name)
    return schools


def normalize_for_matching(s: str):
    s2 = s.lower()
    s2 = re.sub(r"[^a-z0-9\s]", ' ', s2)
    s2 = re.sub(r"\s{2,}", ' ', s2).strip()
    return s2


def match_against_state_schools(candidate: str, state_code: str):
    if not candidate or not state_code:
        return None
    schools = fetch_state_school_list(state_code)
    if not schools:
        return None
    cand_norm = normalize_for_matching(candidate)
    norm_map = {}
    norm_list = []
    for s in schools:
        n = normalize_for_matching(s)
        if n and n not in norm_map:
            norm_map[n] = s
            norm_list.append(n)
    matches = difflib.get_close_matches(cand_norm, norm_list, n=3, cutoff=0.72)
    if matches:
        return norm_map[matches[0]]
    for n, orig in norm_map.items():
        if cand_norm in n or n in cand_norm:
            return orig
    return None

if __name__ == '__main__':
    state = 'ga'
    print('Loading schools for', state)
    schools = fetch_state_school_list(state)
    print(f'Found {len(schools)} schools (showing first 20):')
    for s in schools[:20]:
        print('-', s)

    tests = [
        'Wheeler High School',
        'Kennedy Technical Institute',
        'Central Catholic',
        'in Atlanta',
        'Columbus',
        'McEachern High School'
    ]
    for t in tests:
        m = match_against_state_schools(t, state)
        print(f"{t!r} -> {m!r}")
