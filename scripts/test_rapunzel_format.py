#!/usr/bin/env python3
"""Quick test to check Rapunzel's raw output format."""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI
from src.agents.rapunzel_grade_reader import RapunzelGradeReader

token_provider = get_bearer_token_provider(
    DefaultAzureCredential(), 'https://cognitiveservices.azure.com/.default')
azure_endpoint = os.environ.get('AZURE_OPENAI_ENDPOINT', '')
if not azure_endpoint:
    raise ValueError('AZURE_OPENAI_ENDPOINT environment variable must be set')
client = AzureOpenAI(
    azure_ad_token_provider=token_provider,
    api_version='2024-12-01-preview',
    azure_endpoint=azure_endpoint)

rapunzel = RapunzelGradeReader('Rapunzel', client, model='gpt-4.1')

test_text = """--- PAGE 8 of 11 ---
Central Gwinnett High School
STUDENT: Abdalla, Yusra  DOB: 10/10/2007  Grade: 10
Weighted GPA: 3.833  Unweighted GPA: 3.5
Total Credits: 14.000

Grade 9:
English 9 - A (95)  Biology - B+ (88)  Math 9 - B (84)  World History - A (93)
Health - A (97)  Spanish I - B+ (87)

Grade 10:
AP World History - B+ (88)  Honors English 10 - A- (91)  Chemistry - B (85)
AP Human Geography - A (94)  Math 10 - B+ (87)  Spanish II - B (84)
"""

result = asyncio.run(rapunzel.parse_grades(test_text, 'Yusra Abdalla'))
print('GPA:', result.get('gpa'))
print('Rigor:', result.get('course_rigor_index'))
print('Quality:', result.get('transcript_quality'))
print('Confidence:', result.get('confidence_level'))
print('Courses:', len(result.get('grade_table_rows', [])))
print('---RAW ANALYSIS (first 3000 chars)---')
analysis = result.get('full_analysis', '')
print(analysis[:3000])
