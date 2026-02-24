#!/usr/bin/env python
"""Test the student_detail route directly."""

from app import app as flask_app
from src.database import Database

db = Database()

# Test the database return value
application = db.get_application(8)
print(f"Database result: {application is not None}")

if application:
    print(f"ApplicationID: {application.get('ApplicationID')}")
print("Keys in application:", list(application.keys()) if application else [])

# Create a temporary record with a student_summary so we can validate the
# template renders it.  We'll delete it at the end so the database stays clean.
temp_id = None
try:
    temp_id = db.create_application(applicant_name='Route Test', email='routetest@example.com')
    # directly update the row to include a summary
    ss = {
        'status': 'completed',
        'overall_score': 73,
        'recommendation': 'Approve',
        'rationale': 'Test route summary',
        'confidence': 0.81
    }
    db.execute_non_query(
        "UPDATE applications SET student_summary = %s WHERE application_id = %s",
        (json.dumps(ss), temp_id)
    )

    # Now test the Flask route for this new record
    with flask_app.test_client() as client:
        response = client.get(f'/application/{temp_id}', follow_redirects=False)
        print(f"\nFlask route test for temp record:")
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            data = response.data.decode('utf-8')
            if 'Test route summary' in data or 'Overall Score' in data:
                print("✅ Summary text rendered in page")
            else:
                print("⚠️ Summary not present in HTML output")
            # new elements
            if 'NextGen Align' in data:
                print("✅ Alignment card present")
            else:
                print("⚠️ Alignment card missing")
            if 'Match Score' in data:
                print("✅ Match Score card present")
            else:
                print("⚠️ Match Score card missing")
            if 'Milo Training Insights' in data:
                print("✅ Milo insights section present")
            else:
                print("⚠️ Milo insights section missing")
            if 'AI Alignment Analysis' in data:
                print("✅ AI alignment section present")
            else:
                print("⚠️ AI alignment section missing")

    # Additional feedback route tests
    print("\nTesting feedback routes...")
    with flask_app.test_client() as client:
        get_resp = client.get('/feedback')
        print(f"GET /feedback status: {get_resp.status_code}")
        if get_resp.status_code == 200:
            html = get_resp.data.decode('utf-8')
            if 'id="feedbackForm"' in html:
                print("✅ Feedback form rendered")
            else:
                print("⚠️ Feedback form missing")

        post_resp = client.post('/feedback', json={})
        print(f"POST /feedback empty body status: {post_resp.status_code}")
        if post_resp.status_code == 400:
            print("✅ Bad request validated")
        else:
            print("⚠️ Unexpected response for empty feedback")

        # now submit a minimal valid payload, but skip GitHub invocation by
        # clearing token in config if present (the tests don't need real API)
        from src.config import config as _cfg
        old_token = _cfg.github_token
        old_repo = _cfg.github_repo
        _cfg.github_token = None
        _cfg.github_repo = None
        valid_resp = client.post('/feedback', json={'type':'issue','message':'test'})
        print(f"POST /feedback valid payload status: {valid_resp.status_code}")
        if valid_resp.status_code in (201, 503):
            print("✅ Feedback endpoint accepted input")
            try:
                print("Response JSON:", valid_resp.get_json())
            except Exception:
                pass
        else:
            print("⚠️ Feedback endpoint failed", valid_resp.get_data(as_text=True))
        # restore config
        _cfg.github_token = old_token
        _cfg.github_repo = old_repo

        # exercise new debug endpoint returning raw agent_results
        debug_resp = client.get(f'/student/{temp_id}/agent-results')
        print(f"Debug endpoint status: {debug_resp.status_code}")
        if debug_resp.status_code == 200:
            try:
                j = debug_resp.get_json()
                print("Debug JSON keys:", list(j.keys()))
                # should at least be dict, even if empty
                assert isinstance(j, dict)
            except Exception as ex:
                print("⚠ Error parsing debug JSON:", ex)
        else:
            print("⚠ Debug endpoint failed")
except Exception as e:
    print(f"Exception while setting up temporary record: {e}")
    import traceback
    traceback.print_exc()
finally:
    if temp_id:
        try:
            db.execute_non_query("DELETE FROM applications WHERE application_id = %s", (temp_id,))
            print(f"Cleaned up temporary record {temp_id}")
        except Exception:
            pass
