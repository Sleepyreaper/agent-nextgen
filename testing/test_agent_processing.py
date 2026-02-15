#!/usr/bin/env python3
"""Test script to verify agent processing and status display."""

import requests
import json
import time
import sys

BASE_URL = "http://localhost:5002"

def upload_test_student():
    """Upload a test student with an application."""
    print("\n📝 Uploading test student...")
    
    # Create sample application text
    application_text = """
    John Smith
    john.smith@email.com
    
    My name is John Smith and I am applying to your program.
    I graduated from Lincoln High School in 2024 with a 3.85 GPA.
    
    My academic strengths include:
    - Excellent grades in advanced mathematics and science
    - 4.0 GPA in AP courses
    - Strong analytical and problem-solving skills
    
    I am interested in engineering and plan to pursue a career in software development.
    """
    
    files = {
        'file': ('application.txt', application_text, 'text/plain')
    }
    data = {
        'is_test': 'true'  # Mark as test data
    }
    
    try:
        response = requests.post(
            f'{BASE_URL}/upload',
            files=files,
            data=data,
            timeout=30
        )
        
        if response.status_code == 302:  # Redirect
            # Extract application_id from redirect URL
            location = response.headers.get('Location', '')
            if '/student_detail/' in location:
                app_id = location.split('/student_detail/')[-1].split('/')[0]
                print(f"✓ Student uploaded successfully. ID: {app_id}")
                return int(app_id)
        elif response.status_code == 200:
            print(f"Response text: {response.text[:500]}")
            return None
        else:
            print(f"✗ Upload failed with status {response.status_code}")
            print(f"Response: {response.text[:500]}")
            return None
    except Exception as e:
        print(f"✗ Upload error: {e}")
        return None

def check_agent_questions(app_id):
    """Check what agents need from this student."""
    print(f"\n🤔 Checking agent questions for application {app_id}...")
    
    try:
        response = requests.get(
            f'{BASE_URL}/api/agent-questions/{app_id}',
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'success':
                print("✓ Retrieved agent questions:")
                questions = data.get('agent_questions', [])
                for q in questions:
                    print(f"  - {q.get('agent_name')}: {q.get('questions', [])[:1]}")
                return questions
            else:
                print(f"✗ Error: {data.get('error', 'Unknown error')}")
        else:
            print(f"✗ Failed with status {response.status_code}")
    except Exception as e:
        print(f"✗ Error checking questions: {e}")
    
    return []

def get_test_students():
    """Get all test students and their agent status."""
    print("\n📊 Retrieving test students and their processing status...")
    
    try:
        response = requests.get(
            f'{BASE_URL}/api/test/students',
            timeout=15
        )
        
        if response.status_code == 200:
            data = response.json()
            students = data.get('students', [])
            
            if students:
                print(f"✓ Found {len(students)} test student(s):\n")
                for student in students:
                    print(f"  Name: {student.get('name')}")
                    print(f"  ID: {student.get('application_id')}")
                    print(f"  Status: {student.get('status')}")
                    print(f"  Student ID: {student.get('student_id')}")
                    
                    progress = student.get('agent_progress', {})
                    if progress:
                        print(f"  Agent Progress:")
                        for agent, status in progress.items():
                            emoji = "✓" if status == "complete" else "⏳"
                            print(f"    {emoji} {agent}: {status}")
                    print()
                
                return students
            else:
                print("✗ No test students found")
        else:
            print(f"✗ Failed with status {response.status_code}")
            print(f"Response: {response.text}")
    except Exception as e:
        print(f"✗ Error retrieving students: {e}")
        import traceback
        traceback.print_exc()
    
    return []

def main():
    """Run the test workflow."""
    print("="*60)
    print("🧪 Agent Processing Test")
    print("="*60)
    
    # Step 1: Upload test student
    app_id = upload_test_student()
    if not app_id:
        print("\n✗ Failed to upload student. Exiting.")
        return False
    
    # Step 2: Check agent questions
    time.sleep(2)
    questions = check_agent_questions(app_id)
    
    # Step 3: Wait a few seconds for agents to process
    print("\n⏳ Waiting for agents to process (this may take 30-60 seconds)...")
    max_wait = 120  # Wait up to 2 minutes
    elapsed = 0
    while elapsed < max_wait:
        time.sleep(10)
        elapsed += 10
        print(f"   Elapsed: {elapsed}s...")
    
    # Step 4: Check student status
    time.sleep(2)
    students = get_test_students()
    
    if students:
        # Check if any agents have completed
        any_complete = False
        for student in students:
            progress = student.get('agent_progress', {})
            for agent, status in progress.items():
                if status == 'complete':
                    any_complete = True
                    break
        
        if any_complete:
            print("✅ SUCCESS: Agents are processing and storing results!")
            return True
        else:
            print("⚠️  ISSUE: Agents have not completed processing yet.")
            print("   This might be normal if agents are still running.")
            print("   Check back in a few minutes.")
            return False
    else:
        print("✗ FAILED: Could not retrieve student status")
        return False

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
