"""Debug keyword matches for Augustus page 10."""
import sys
sys.path.insert(0, '.')
import fitz

doc = fitz.open("/Users/sleepy/Downloads/OneDrive_1_3-2-2026/Augustus, Chloe'.pdf")
p10 = doc[9].get_text().strip().lower()

app_medium = ['essay', 'reflection', 'experience', 'passion', 'motivation', 'goals', 'leadership', 'award',
    'scholarship', 'activities', 'involvement', 'challenge', 'growth', 'impact',
    'teacher', 'course', 'science', 'mathematics', 'english', 'subject', 'grade', 'inspired',
    'learned', 'developed', 'interested', 'opportunity', 'career', 'research', 'program', 'stem',
    'community', 'family', 'future', 'dream', 'hope', 'because', 'believe', 'understand']

rec_high = ['letter of recommendation', 'to whom it may concern', 'i am writing to recommend', 'i recommend',
    'it is my pleasure', 'sincerely', 'respectfully submitted', 'i have known',
    'i have had the pleasure', 'reference letter', 'to whom it may concern,',
    'i am writing this letter', 'pleasure of teaching', 'strongly recommend']

rec_medium = ['recommend', 'reference', 'endorsement', 'counselor', 'principal', 'dear', 'academic standing',
    'work ethic', 'my student', 'my class', 'strong candidate', 'exceptional student',
    'pleasure to teach', 'honor roll', 'academic excellence', 'department chair', 'school counselor',
    'years of teaching', 'year of teaching']

app_high = ['personal statement', 'statement of purpose', 'why i want', 'my goals', 'application essay',
    'extracurricular activities', 'community service', 'volunteer experience', 'i am passionate',
    'my dream', 'i aspire', 'in the future', 'my experience', 'application summary',
    'competition details', 'application information', 'personal details', 'i write to apply',
    'i am applying', 'extra_cur', 'essay_video']

print("APP HIGH matches (3pt each):")
for kw in app_high:
    if kw in p10:
        print(f"  +3: '{kw}'")

print("\nAPP MEDIUM matches (1pt each):")
for kw in app_medium:
    if kw in p10:
        print(f"  +1: '{kw}'")

print("\nREC HIGH matches (3pt each):")
for kw in rec_high:
    if kw in p10:
        print(f"  +3: '{kw}'")

print("\nREC MEDIUM matches (1pt each):")
for kw in rec_medium:
    if kw in p10:
        print(f"  +1: '{kw}'")

# Count structural heuristics
lines = doc[9].get_text().strip().split('\n')
non_empty = [ln for ln in lines if ln.strip()]
short = sum(1 for ln in non_empty if len(ln.strip()) < 60)
long = sum(1 for ln in non_empty if len(ln.strip()) >= 80)
avg_len = sum(len(ln.strip()) for ln in non_empty) / len(non_empty) if non_empty else 0
print(f"\nStructural: avg_line={avg_len:.0f}, short={short}, long={long}")

doc.close()
