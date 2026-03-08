"""One-time script: seed school aliases via the API.

Run with: python3 scripts/seed_school_aliases.py <base_url> <csrf_token> <session_cookie>
Or deploy as an API endpoint.
"""

# Known alias mappings: student input → correct DB school name
ALIAS_MAP = [
    ("Grayson Highschool", "Grayson High School"),
    ("Parkview Highschool", "Parkview High School"),
    ("Campbell Highschool", "Campbell High School"),
    ("Chamblee High", "Chamblee High School"),
    ("Chamblee Highschool", "Chamblee High School"),
    ("Chattahoochee HS", "Chattahoochee High School"),
    ("Cristo Rey Atlanta Jesuit Highschool", "Cristo Rey Atlanta Jesuit High School"),
    ("Cross Keys Highschool", "Cross Keys High School"),
    ("Dacula Highschool", "Dacula High School"),
    ("Mountain View Highschool", "Mountain View High School"),
    ("South Cobb Highschool", "South Cobb High School"),
    ("Brookwood Highschool", "Brookwood High School"),
    ("Berkmar Highschool", "Berkmar High School"),
    ("Stone Mtn Highschool", "Stone Mountain High School"),
    ("Westlake higschool", "Westlake High School"),
    ("Osborne Hghschool", "Osborne High School"),
    ("Paul Duke STEM HIghschool", "Paul Duke STEM High School"),
    ("Peachtree Ridge High", "Peachtree Ridge High School"),
    ("Peachtree Ridge Highschool", "Peachtree Ridge High School"),
    ("McClure Health Sciene Highschool", "McClure Health Science High School"),
    ("McEachin High School", "McEachern High School"),
    ("John McEachern High School", "McEachern High School"),
    ("The Gwinnett School of Mathematics", "Gwinnett School of Mathematics, Science and Technology"),
    ("Gwinnett School of Mathematics", "Gwinnett School of Mathematics, Science and Technology"),
    ("Gwinnett School of Mathematics Science and Technology", "Gwinnett School of Mathematics, Science and Technology"),
    ("Gwinnett online campus", "Gwinnett Online Campus"),
    ("Benjamin E Mays High School", "Benjamin E. Mays High School"),
    ("Baldwin County High school", "Baldwin County High School"),
    ("PHILLIPS EXETER ACADEMY", "Phillips Exeter Academy"),
    ("Arabia Mountain High School", "Arabia Mountain High School"),
    ("Rockdale Magnet High School for Science and Technology", "Rockdale Magnet School for Science and Technology"),
]

# Schools that should be created if they don't exist in the DB.
# These are real schools that students attend but aren't in our NCES/GOSA data.
CREATE_IF_MISSING = [
    {"school_name": "Chamblee Charter High School", "state_code": "GA"},
    {"school_name": "Chamblee High School", "state_code": "GA"},
    {"school_name": "Gwinnett School of Mathematics, Science and Technology", "state_code": "GA"},
    {"school_name": "Gwinnett Online Campus", "state_code": "GA"},
    {"school_name": "Baldwin County High School", "state_code": "GA"},
    {"school_name": "Phillips Exeter Academy", "state_code": "NH"},
    {"school_name": "Rockdale Magnet School for Science and Technology", "state_code": "GA"},
    {"school_name": "McClure Health Science High School", "state_code": "GA"},
    {"school_name": "Cate School", "state_code": "CA"},
    {"school_name": "Dillard High School", "state_code": "FL"},
    {"school_name": "Edina High School", "state_code": "MN"},
    {"school_name": "Laurel Springs School", "state_code": "CA"},
    {"school_name": "St. Croix Educational Complex High School", "state_code": "VI"},
    {"school_name": "Elite Scholars Academy", "state_code": "GA"},
    {"school_name": "Fulton Science Academy Private School", "state_code": "GA"},
    {"school_name": "Newton College and Career Academy", "state_code": "GA"},
]
