import re

def _normalize_school_candidate(raw: str) -> str:
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip()
    s = re.sub(r'^["\']+|["\']+$', '', s)
    s = re.sub(r'^(in|at|from|attended|attending)\b[:\s,-]*', '', s, flags=re.IGNORECASE).strip()
    s = re.sub(r'[\.,;:\-\|]+$', '', s).strip()
    s = re.sub(r'\s{2,}', ' ', s)
    if not s:
        return None
    if len(s.split()) == 1 and not any(k in s.lower() for k in ['school', 'high', 'hs', 'academy', 'charter', 'magnet']):
        return None
    return s

def _is_valid_school_name(name: str) -> bool:
    if not name or not isinstance(name, str):
        return False
    s = name.strip()
    if len(s) < 3 or len(s) > 200:
        return False
    lowered = s.lower()
    if re.search(r'\b20\d{2}\b', s):
        return False
    negative_keywords = ['internship', 'intern', 'resume', 'experience', 'position', 'interns', 'internships']
    if any(k in lowered for k in negative_keywords):
        return False
    keywords = ['high school', ' hs', 'school', 'academy', 'charter', 'magnet', 'secondary']
    if any(k in lowered for k in keywords):
        return True
    if any(x in lowered for x in ['university', 'college', 'community college']):
        return False
    if 'institute' in lowered and 'high' not in lowered and 'school' not in lowered:
        return False
    parts = [p for p in re.split(r"\s+", s) if p]
    alpha_parts = [p for p in parts if re.search(r'[A-Za-z]', p)]
    if len(alpha_parts) >= 2 and all(p[0].isupper() for p in alpha_parts if p[0].isalpha()):
        if all(len(re.sub(r'[^A-Za-z]', '', p)) >= 2 for p in alpha_parts):
            return True
    return False

examples = [
    "in Atlanta",
    "Kennedy Technical Institute",
    "Kennedy Technical Institute High School",
    "Wheeler High School",
    "Columbus",
    "Central Catholic",
    "12345",
    '"Kennedy Technical Institute"',
    "Attended Kennedy Technical Institute",
    "I attended Wheeler High School in Columbus, GA",
    "High School: Wheeler High School",
    "High School - Wheeler High School",
    "HS: Wheeler High School",
]

for t in examples:
    norm = _normalize_school_candidate(t)
    valid = _is_valid_school_name(norm)
    print(f"INPUT: {t!r} -> NORMALIZED: {norm!r} | VALID: {valid}")
