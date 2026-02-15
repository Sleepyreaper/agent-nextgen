"""Flask web application for application evaluation system."""

import os
import asyncio
import time
import uuid
import json
from typing import Optional
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response
from werkzeug.utils import secure_filename
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

from src.config import config
from src.database import db
from src.document_processor import DocumentProcessor
from src.storage import storage
from src.test_data_generator import test_data_generator
from src.agents import (
    GastonEvaluator,
    SmeeOrchestrator,
    RapunzelGradeReader,
    MoanaSchoolContext,
    TianaApplicationReader,
    MulanRecommendationReader,
    MerlinStudentEvaluator,
    AuroraAgent,
    BelleDocumentAnalyzer
)

# Initialize Flask app
app = Flask(__name__, template_folder='web/templates', static_folder='web/static')
app.secret_key = config.flask_secret_key or 'dev-secret-key-change-in-production'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['UPLOAD_FOLDER'] = 'uploads'

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize Azure OpenAI client
def get_ai_client():
    """Get Azure OpenAI client."""
    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(),
        "https://cognitiveservices.azure.com/.default"
    )
    return AzureOpenAI(
        azure_ad_token_provider=token_provider,
        api_version=config.api_version,
        azure_endpoint=config.azure_openai_endpoint
    )

# Initialize evaluator agent
evaluator_agent = None
orchestrator_agent = None
belle_analyzer = None

def get_evaluator():
    """Get or create Gaston evaluator agent."""
    global evaluator_agent
    if not evaluator_agent:
        client = get_ai_client()
        training_examples = db.get_training_examples()
        evaluator_agent = GastonEvaluator(
            name="GastonEvaluator",
            client=client,
            model=config.deployment_name,
            training_examples=training_examples
        )
    return evaluator_agent


def get_belle():
    """Get or create Belle document analyzer."""
    global belle_analyzer
    if not belle_analyzer:
        client = get_ai_client()
        belle_analyzer = BelleDocumentAnalyzer(
            client=client,
            model=config.deployment_name
        )
    return belle_analyzer


def get_orchestrator():
    """Get or create Smee orchestrator with registered agents."""
    global orchestrator_agent
    if not orchestrator_agent:
        client = get_ai_client()
        orchestrator_agent = SmeeOrchestrator(
            name="Smee",
            client=client,
            model=config.deployment_name,
            db_connection=db
        )

        # Register specialist agents with DB connections where supported
        orchestrator_agent.register_agent(
            "application_reader",
            TianaApplicationReader(
                name="Tiana Application Reader",
                client=client,
                model=config.deployment_name,
                db_connection=db
            )
        )
        orchestrator_agent.register_agent(
            "grade_reader",
            RapunzelGradeReader(
                name="Rapunzel Grade Reader",
                client=client,
                model=config.deployment_name
            )
        )
        orchestrator_agent.register_agent(
            "school_context",
            MoanaSchoolContext(
                name="Moana School Context",
                client=client,
                model=config.deployment_name,
                db_connection=db
            )
        )
        orchestrator_agent.register_agent(
            "recommendation_reader",
            MulanRecommendationReader(
                name="Mulan Recommendation Reader",
                client=client,
                model=config.deployment_name,
                db_connection=db
            )
        )
        orchestrator_agent.register_agent(
            "student_evaluator",
            MerlinStudentEvaluator(
                name="Merlin Student Evaluator",
                client=client,
                model=config.deployment_name,
                db_connection=db
            )
        )

    return orchestrator_agent


@app.route('/')
def index():
    """Home page - Dashboard."""
    try:
        applications = db.get_applications_with_evaluations()
        pending_count = len([a for a in applications if a.get('status') == 'Pending'])
        evaluated_count = len([a for a in applications if a.get('status') == 'Evaluated'])
        
        # Get recent applications (limit 10)
        recent_apps = applications[:10] if applications else []
        
        return render_template('index.html', 
                             applications=recent_apps,
                             pending_count=pending_count,
                             evaluated_count=evaluated_count,
                             total_count=len(applications))
    except Exception as e:
        flash(f'Error loading applications: {str(e)}', 'error')
        return render_template('index.html', applications=[], pending_count=0, evaluated_count=0, total_count=0)


@app.route('/health')
def health():
    """Health check endpoint for Azure App Service."""
    return jsonify({
        'status': 'healthy',
        'app': 'NextGen Agent System',
        'version': '1.0'
    }), 200


@app.route('/upload', methods=['GET', 'POST'])
def upload():
    """
    Upload new application file.
    Smee extracts student info automatically.
    """
    if request.method == 'POST':
        try:
            # Get uploaded file
            if 'file' not in request.files:
                flash('No file uploaded', 'error')
                return redirect(request.url)
            
            file = request.files['file']
            if file.filename == '':
                flash('No file selected', 'error')
                return redirect(request.url)
            
            if not DocumentProcessor.validate_file_type(file.filename):
                flash('Invalid file type. Please upload PDF, DOCX, or TXT files.', 'error')
                return redirect(request.url)
            
            # Determine application type
            is_training = request.form.get('is_training') == 'on'
            app_type = "training" if is_training else "2026"
            
            # Get selection status for training data
            was_selected = None
            if is_training:
                was_selected = request.form.get('was_selected') == 'on'
            
            # Generate unique student ID
            student_id = storage.generate_student_id()
            
            # Save file temporarily to extract text
            filename = secure_filename(file.filename)
            temp_path = os.path.join(app.config['UPLOAD_FOLDER'], f"temp_{student_id}_{filename}")
            file.save(temp_path)
            
            # Extract text from file
            application_text, file_type = DocumentProcessor.process_document(temp_path)
            
            # Read file content for Azure Storage
            with open(temp_path, 'rb') as f:
                file_content = f.read()
            
            # Upload to Azure Storage
            storage_result = storage.upload_file(
                file_content=file_content,
                filename=filename,
                student_id=student_id,
                application_type=app_type
            )
            
            # Clean up temporary file
            try:
                os.remove(temp_path)
            except:
                pass
            
            if not storage_result.get('success'):
                flash(f"Error uploading to storage: {storage_result.get('error')}", 'error')
                return redirect(request.url)
            
            # Use Belle to analyze the document and extract structured data
            try:
                belle = get_belle()
                doc_analysis = belle.analyze_document(application_text, filename)
            except Exception as e:
                print(f"Warning: Belle analysis failed: {e}")
                doc_analysis = {
                    "document_type": "unknown",
                    "confidence": 0,
                    "extracted_data": {}
                }
            
            # Extract student info from text
            student_name = extract_student_name(application_text)
            student_email = extract_student_email(application_text)
            
            # Save to database with extracted info and storage path
            application_id = db.create_application(
                applicant_name=student_name or f"Student {student_id}",
                email=student_email or "",
                application_text=application_text,
                file_name=filename,
                file_type=file_type,
                is_training=is_training,
                was_selected=was_selected
            )
            
            # Flash success message with student ID and Belle's analysis
            if is_training:
                flash(f'✅ Training data uploaded! Student ID: {student_id}', 'success')
                if doc_analysis.get('document_type') != 'unknown':
                    flash(f"📖 Belle identified: {doc_analysis['document_type'].replace('_', ' ').title()}", 'info')
                return redirect(url_for('training'))
            else:
                flash(f'✅ Application uploaded! Student ID: {student_id}. Processing with Smee...', 'success')
                if doc_analysis.get('document_type') != 'unknown':
                    flash(f"📖 Belle identified: {doc_analysis['document_type'].replace('_', ' ').title()}", 'info')
                return redirect(url_for('process_student', application_id=application_id))
            
        except Exception as e:
            flash(f'Error uploading file: {str(e)}', 'error')
            import traceback
            traceback.print_exc()
            return redirect(request.url)
    
    return render_template('upload.html')


def extract_student_name(text: str) -> Optional[str]:
    """Extract student name from application text."""
    try:
        # Look for common patterns like "My name is..." or "I am..."
        import re
        
        # Pattern 1: "My name is [Name]"
        match = re.search(r"(?:my name is|i am|i\'m)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)", text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        
        # Pattern 2: First capitalized words at start of text
        words = text.split()
        if len(words) >= 2:
            for i in range(len(words) - 1):
                if words[i][0].isupper() and words[i+1][0].isupper():
                    name = f"{words[i]} {words[i+1]}"
                    if len(name) < 50:  # Sanity check
                        return name
        
        return None
    except:
        return None


def extract_student_email(text: str) -> Optional[str]:
    """Extract email address from application text."""
    import re
    
    matches = re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', text)
    return matches[0] if matches else None



@app.route('/evaluate/<int:application_id>', methods=['POST'])
def evaluate(application_id):
    """Evaluate a single application."""
    try:
        # Get application
        application = db.get_application(application_id)
        if not application:
            return jsonify({'error': 'Application not found'}), 404
        
        # Get evaluator and run evaluation
        evaluator = get_evaluator()
        evaluation = asyncio.run(evaluator.evaluate_application(application))
        
        # Save evaluation to database
        db.save_evaluation(
            application_id=application_id,
            agent_name=evaluation['agent_name'],
            overall_score=evaluation['overall_score'],
            technical_score=evaluation['technical_skills_score'],
            communication_score=evaluation['communication_score'],
            experience_score=evaluation['experience_score'],
            cultural_fit_score=evaluation['cultural_fit_score'],
            strengths=evaluation['strengths'],
            weaknesses=evaluation['weaknesses'],
            recommendation=evaluation['recommendation'],
            detailed_analysis=evaluation['detailed_analysis'],
            comparison=evaluation['comparison_to_excellence'],
            model_used=evaluation['model_used'],
            processing_time_ms=evaluation['processing_time_ms']
        )
        
        # Update application status
        db.execute_non_query(
            "UPDATE Applications SET Status = 'Evaluated' WHERE ApplicationID = %s",
            (application_id,)
        )
        
        return jsonify(evaluation)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/evaluate_all', methods=['POST'])
def evaluate_all():
    """Evaluate all pending applications."""
    try:
        pending = db.get_pending_applications()
        evaluator = get_evaluator()
        
        results = []
        for application in pending:
            evaluation = asyncio.run(evaluator.evaluate_application(application))
            
            # Save to database
            db.save_evaluation(
                application_id=application['ApplicationID'],
                agent_name=evaluation['agent_name'],
                overall_score=evaluation['overall_score'],
                technical_score=evaluation['technical_skills_score'],
                communication_score=evaluation['communication_score'],
                experience_score=evaluation['experience_score'],
                cultural_fit_score=evaluation['cultural_fit_score'],
                strengths=evaluation['strengths'],
                weaknesses=evaluation['weaknesses'],
                recommendation=evaluation['recommendation'],
                detailed_analysis=evaluation['detailed_analysis'],
                comparison=evaluation['comparison_to_excellence'],
                model_used=evaluation['model_used'],
                processing_time_ms=evaluation['processing_time_ms']
            )
            
            # Update status
            db.execute_non_query(
                "UPDATE Applications SET Status = 'Evaluated' WHERE ApplicationID = %s",
                (application['ApplicationID'],)
            )
            
            results.append({
                'application_id': application['ApplicationID'],
                'applicant_name': application['ApplicantName'],
                'recommendation': evaluation['recommendation'],
                'overall_score': evaluation['overall_score']
            })
        
        return jsonify({'success': True, 'evaluations': results})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/students')
def students():
    """View all students."""
    try:
        search_query = request.args.get('search', '').strip()
        
        if search_query:
            # Search by name or email
            query = """
                SELECT * FROM Applications 
                WHERE IsTrainingExample = FALSE 
                AND (ApplicantName ILIKE %s OR Email ILIKE %s)
                ORDER BY UploadedDate DESC
            """
            applications = db.execute_query(query, (f'%{search_query}%', f'%{search_query}%'))
        else:
            # Get all real students (not training examples)
            query = """
                SELECT * FROM Applications 
                WHERE IsTrainingExample = FALSE 
                ORDER BY UploadedDate DESC
            """
            applications = db.execute_query(query)
        
        return render_template('students.html', 
                             applications=applications,
                             search_query=search_query)
    except Exception as e:
        flash(f'Error loading students: {str(e)}', 'error')
        return render_template('students.html', applications=[], search_query='')


@app.route('/training')
def training():
    """Training data management page - historical applications for agent learning."""
    try:
        search_query = request.args.get('search', '').strip()
        filter_selected = request.args.get('filter', '')
        
        if search_query:
            # Search by name or email in training data
            query = """
                SELECT * FROM Applications 
                WHERE IsTrainingExample = TRUE
                AND (ApplicantName ILIKE %s OR Email ILIKE %s)
                ORDER BY UploadedDate DESC
            """
            training_data = db.execute_query(query, (f'%{search_query}%', f'%{search_query}%'))
        else:
            # Get all training examples
            query = """
                SELECT * FROM Applications 
                WHERE IsTrainingExample = TRUE
                ORDER BY UploadedDate DESC
            """
            training_data = db.execute_query(query)
        
        # Apply filter if specified
        if filter_selected == 'selected':
            training_data = [t for t in training_data if t.get('wasselected')]
        elif filter_selected == 'not_selected':
            training_data = [t for t in training_data if not t.get('wasselected')]
        
        # Calculate statistics
        total_count = len(training_data)
        selected_count = len([t for t in training_data if t.get('wasselected')])
        not_selected_count = total_count - selected_count
        
        return render_template('training.html',
                             training_data=training_data,
                             search_query=search_query,
                             filter_selected=filter_selected,
                             total_count=total_count,
                             selected_count=selected_count,
                             not_selected_count=not_selected_count)
    except Exception as e:
        flash(f'Error loading training data: {str(e)}', 'error')
        return render_template('training.html', 
                             training_data=[], 
                             search_query='',
                             filter_selected='',
                             total_count=0,
                             selected_count=0,
                             not_selected_count=0)


@app.route('/test')
def test():
    """Test system with sample students list."""
    try:
        return render_template('test.html')
    except Exception as e:
        flash(f'Error loading test page: {str(e)}', 'error')
        return render_template('test.html')


def cleanup_test_data():
    """
    Delete all old test data (applications marked with IsTrainingExample = TRUE).
    Called at the start of each new test run to ensure clean slate.
    """
    try:
        # Delete all related evaluation data first (foreign key constraints)
        test_app_ids = db.execute_query(
            "SELECT ApplicationID FROM Applications WHERE IsTrainingExample = TRUE"
        )
        
        for app_record in test_app_ids:
            app_id = app_record.get('applicationid')
            
            # Delete from specialized agent tables
            try:
                db.execute_non_query("DELETE FROM TianaApplications WHERE ApplicationID = %s", (app_id,))
            except:
                pass
            
            try:
                db.execute_non_query("DELETE FROM MulanRecommendations WHERE ApplicationID = %s", (app_id,))
            except:
                pass
            
            try:
                db.execute_non_query("DELETE FROM MerlinEvaluations WHERE ApplicationID = %s", (app_id,))
            except:
                pass
            
            try:
                db.execute_non_query("DELETE FROM StudentSchoolContext WHERE ApplicationID = %s", (app_id,))
            except:
                pass
            
            try:
                db.execute_non_query("DELETE FROM Grades WHERE ApplicationID = %s", (app_id,))
            except:
                pass
            
            try:
                db.execute_non_query("DELETE FROM AIEvaluations WHERE ApplicationID = %s", (app_id,))
            except:
                pass
            
            try:
                db.execute_non_query("DELETE FROM AgentAuditLogs WHERE ApplicationID = %s", (app_id,))
            except:
                pass
        
        # Now delete the applications themselves
        db.execute_non_query("DELETE FROM Applications WHERE IsTrainingExample = TRUE")
        
        print(f"✓ Cleaned up {len(test_app_ids)} old test applications and their related data")
        
    except Exception as e:
        print(f"⚠ Warning during test data cleanup: {str(e)}")
        # Don't fail the test if cleanup has issues - just log and continue


@app.route('/process/<int:application_id>')
def process_student(application_id):
    """Process student through Smee orchestrator."""
    try:
        application = db.get_application(application_id)
        if not application:
            flash('Student not found', 'error')
            return redirect(url_for('students'))
        
        # Show processing page with progress
        return render_template('process_student.html', 
                             application=application,
                             application_id=application_id)
        
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('students'))


@app.route('/api/process/<int:application_id>', methods=['POST'])
def api_process_student(application_id):
    """API endpoint to process student with Smee orchestrator."""
    try:
        application = db.get_application(application_id)
        if not application:
            return jsonify({'error': 'Student not found'}), 404
        
        # Get orchestrator
        orchestrator = get_orchestrator()
        
        # Run full agent pipeline
        result = asyncio.run(
            orchestrator.coordinate_evaluation(
                application=application,
                evaluation_steps=['application_reader', 'grade_reader', 'recommendation_reader', 'school_context', 'student_evaluator']
            )
        )
        
        # Update status
        db.execute_non_query(
            "UPDATE Applications SET Status = 'Evaluated' WHERE ApplicationID = %s",
            (application_id,)
        )
        
        return jsonify({
            'success': True,
            'application_id': application_id,
            'result': result
        })
        
    except Exception as e:
        import traceback
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@app.route('/api/status/<int:application_id>')
def api_get_status(application_id):
    """API endpoint to get application requirements and agent status."""
    try:
        application = db.get_application(application_id)
        if not application:
            return jsonify({'error': 'Student not found'}), 404
        
        # Get orchestrator and check requirements
        orchestrator = get_orchestrator()
        status = orchestrator.check_application_requirements(application)
        
        return jsonify({
            'success': True,
            'application_id': application_id,
            'status': status
        })
        
    except Exception as e:
        import traceback
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@app.route('/application/<int:application_id>')
def view_application(application_id):
    """Legacy view - redirect to new student detail page."""
    return redirect(url_for('student_detail', application_id=application_id))


@app.route('/training/<int:application_id>')
def view_training_detail(application_id):
    """View details of a training example."""
    try:
        application = db.get_application(application_id)
        if not application or not application.get('istrainingexample'):
            flash('Training example not found', 'error')
            return redirect(url_for('training'))
        
        return render_template('application.html', 
                             application=application,
                             is_training=True)
        
    except Exception as e:
        flash(f'Error loading training example: {str(e)}', 'error')
        return redirect(url_for('training'))


@app.route('/training/<int:application_id>/delete', methods=['POST'])
def delete_training(application_id):
    """Delete a training example."""
    try:
        application = db.get_application(application_id)
        if not application or not application.get('istrainingexample'):
            flash('Training example not found', 'error')
            return redirect(url_for('training'))
        
        # Delete the training example
        db.execute_non_query(
            "DELETE FROM Applications WHERE ApplicationID = %s AND IsTrainingExample = TRUE",
            (application_id,)
        )
        
        flash(f'Training example deleted successfully', 'success')
        
        # Reset evaluator to reload training data
        global evaluator_agent
        evaluator_agent = None
        
        return redirect(url_for('training'))
        
    except Exception as e:
        flash(f'Error deleting training example: {str(e)}', 'error')
        return redirect(url_for('training'))


# ============================================================================
# REAL-TIME TEST SYSTEM WITH SERVER-SENT EVENTS (SSE)
# ============================================================================

# In-memory tracking of test submissions and processing status
test_submissions = {}  # {session_id: {student_list, status_updates}}
aurora = AuroraAgent()


def generate_session_updates(session_id):
    """
    Generator function for SSE updates during test processing.
    Creates real test applications in DB and runs full agent pipeline.
    Test data is marked with IsTrainingExample = TRUE.
    """
    submission = test_submissions.get(session_id)
    if not submission:
        yield f"data: {json.dumps({'error': 'Session not found'})}\n\n"
        return
    
    # Send initial connected message
    yield f"data: {json.dumps({'type': 'connected', 'message': 'Connected to test stream'})}\n\n"
    time.sleep(0.1)
    
    # Get generated test students
    students = submission['students']
    orchestrator = get_orchestrator()
    
    # Define agent processing order
    agent_display = [
        ('tiana', '👸'),
        ('rapunzel', '💇'),
        ('mulan', '🗡️'),
        ('moana', '🌊'),
        ('merlin', '🧙'),
        ('aurora', '👑')
    ]
    
    for idx, student in enumerate(students):
        name = student['name']
        email = student['email']
        application_text = student['application_text']
        
        # Create database record as TRAINING EXAMPLE
        application_id = db.create_application(
            applicant_name=name,
            email=email,
            application_text=application_text,
            file_name=f"test_{name.replace(' ', '_').lower()}.txt",
            file_type="txt",
            is_training=True,  # Mark as training/test data
            was_selected=None
        )
        
        submission['application_ids'].append(application_id)
        student_id = f"student_{idx}"
        
        # Student submitted
        yield f"data: {json.dumps({'type': 'student_submitted', 'student': {'name': name, 'email': email}, 'student_id': student_id})}\n\n"
        
        # Run REAL agent pipeline with real-time updates
        evaluation_steps = [
            ('application_reader', 'tiana', '👸'),
            ('grade_reader', 'rapunzel', '💇'),
            ('recommendation_reader', 'mulan', '🗡️'),
            ('school_context', 'moana', '🌊'),
            ('student_evaluator', 'merlin', '🧙')
        ]
        
        application_data = db.get_application(application_id)
        agent_results = {}
        overall_success = True
        
        for step_name, display_name, emoji in evaluation_steps:
            # Agent starts
            yield f"data: {json.dumps({'type': 'agent_start', 'agent': display_name, 'student_id': student_id, 'emoji': emoji})}\n\n"
            
            try:
                # Get the specific agent
                agent = orchestrator.agents.get(step_name)
                if not agent:
                    yield f"data: {json.dumps({'type': 'agent_error', 'agent': display_name, 'student_id': student_id, 'error': f'Agent {step_name} not found'})}\n\n"
                    overall_success = False
                    continue
                
                # Run this specific agent with timeout
                import asyncio
                import concurrent.futures
                
                async def run_agent_async():
                    if hasattr(agent, 'evaluate_student'):
                        # Merlin needs previous results
                        return await agent.evaluate_student(application_data, agent_results)
                    elif hasattr(agent, 'parse_application'):
                        return await agent.parse_application(application_data)
                    elif hasattr(agent, 'parse_grades'):
                        return await agent.parse_grades(
                            application_data.get('applicationtext', ''),
                            application_data.get('applicantname', '')
                        )
                    elif hasattr(agent, 'parse_recommendation'):
                        rec_text = application_data.get('recommendationtext') or application_data.get('applicationtext', '')
                        return await agent.parse_recommendation(
                            rec_text,
                            application_data.get('applicantname', ''),
                            application_id
                        )
                    elif hasattr(agent, 'analyze_student_school_context'):
                        rapunzel_data = agent_results.get('grade_reader')
                        return await agent.analyze_student_school_context(
                            application=application_data,
                            transcript_text=application_data.get('applicationtext', ''),
                            rapunzel_grades_data=rapunzel_data
                        )
                    else:
                        return await agent.process(f"Evaluate: {application_data.get('applicationtext', '')}")
                
                # Run with 10 minute timeout (deep thinking takes time)
                result = asyncio.run(
                    asyncio.wait_for(run_agent_async(), timeout=600.0)
                )
                
                agent_results[step_name] = result
                
                # Agent completed successfully
                yield f"data: {json.dumps({'type': 'agent_complete', 'agent': display_name, 'student_id': student_id, 'status': 'complete'})}\n\n"
                
            except asyncio.TimeoutError:
                error_msg = f'{display_name} timed out after 10 minutes (deep analysis in progress - this may indicate an issue)'
                yield f"data: {json.dumps({'type': 'agent_error', 'agent': display_name, 'student_id': student_id, 'error': error_msg})}\n\n"
                overall_success = False
            except Exception as e:
                error_msg = f'{display_name} error: {str(e)}'
                yield f"data: {json.dumps({'type': 'agent_error', 'agent': display_name, 'student_id': student_id, 'error': error_msg})}\n\n"
                overall_success = False
        
        # Update status
        try:
            if overall_success:
                db.execute_non_query(
                    "UPDATE Applications SET Status = 'Evaluated' WHERE ApplicationID = %s",
                    (application_id,)
                )
            else:
                db.execute_non_query(
                    "UPDATE Applications SET Status = 'Error' WHERE ApplicationID = %s",
                    (application_id,)
                )
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'student_id': student_id, 'error': f'Status update failed: {str(e)}'})}\n\n"
        
        # Aurora presentation - format results based on Merlin's assessment
        try:
            yield f"data: {json.dumps({'type': 'agent_start', 'agent': 'aurora', 'student_id': student_id, 'emoji': '👑'})}\n\n"
            
            # Get Aurora agent
            aurora_agent = orchestrator.agents.get('aurora')
            if aurora_agent and hasattr(aurora_agent, 'format_results') and overall_success:
                # Run Aurora to format results
                merlin_result = agent_results.get('student_evaluator', {})
                
                async def run_aurora_async():
                    return await aurora_agent.format_results(
                        application_data={
                            'name': application_data.get('applicantname'),
                            'email': application_data.get('email'),
                            'applicationtext': application_data.get('applicationtext')
                        },
                        agent_outputs={
                            'tiana': agent_results.get('application_reader'),
                            'rapunzel': agent_results.get('grade_reader'),
                            'moana': agent_results.get('school_context'),
                            'mulan': agent_results.get('recommendation_reader')
                        },
                        merlin_assessment=merlin_result
                    )
                
                aurora_summary = asyncio.run(
                    asyncio.wait_for(run_aurora_async(), timeout=60.0)
                )
                
                # Store Aurora's formatted summary in agent_results
                agent_results['aurora'] = aurora_summary
            
            yield f"data: {json.dumps({'type': 'agent_complete', 'agent': 'aurora', 'student_id': student_id, 'status': 'complete'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'agent_error', 'agent': 'aurora', 'student_id': student_id, 'error': f'Aurora formatting failed: {str(e)}'})}\n\n"
        
        # Results ready - link to REAL student detail page with DB data
        yield f"data: {json.dumps({'type': 'results_ready', 'student_id': student_id, 'results_url': f'/student/{application_id}', 'application_id': application_id, 'success': overall_success})}\n\n"
    
    # All complete
    yield f"data: {json.dumps({'type': 'all_complete', 'application_ids': submission['application_ids']})}\n\n"


@app.route('/api/test/stream/<session_id>')
def test_stream(session_id):
    """Server-Sent Events endpoint for real-time test status updates."""
    return Response(
        generate_session_updates(session_id),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'
        }
    )


@app.route('/api/test/submit', methods=['POST'])
def submit_test_data():
    """
    Generate synthetic test students and start processing pipeline.
    Cleans up old test data first, then creates new test students.
    Returns a session ID to stream updates from.
    """
    try:
        # CLEANUP: Delete old test data (all applications marked as training examples)
        cleanup_test_data()
        
        # Generate 3-8 random test students with realistic data
        students = test_data_generator.generate_batch()
        
        # Generate session ID
        session_id = str(uuid.uuid4())
        
        # Track submission
        test_submissions[session_id] = {
            'students': students,
            'application_ids': [],
            'created_at': time.time(),
            'status': 'processing'
        }
        
        return jsonify({
            'session_id': session_id,
            'student_count': len(students),
            'stream_url': url_for('test_stream', session_id=session_id)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/test/cleanup', methods=['POST'])
def cleanup_test_endpoint():
    """
    API endpoint to manually clear all test data from the database.
    Useful for starting fresh without running a full test.
    """
    try:
        cleanup_test_data()
        
        # Count remaining test data
        remaining = db.execute_query(
            "SELECT COUNT(*) as count FROM Applications WHERE IsTrainingExample = TRUE"
        )
        count = remaining[0].get('count', 0) if remaining else 0
        
        return jsonify({
            'status': 'success',
            'message': 'Test data cleaned up successfully',
            'remaining_test_apps': count
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/api/test/stats', methods=['GET'])
def test_stats():
    """
    Get statistics about test data currently in the database.
    """
    try:
        test_count = db.execute_query(
            "SELECT COUNT(*) as count FROM Applications WHERE IsTrainingExample = TRUE"
        )
        count = test_count[0].get('count', 0) if test_count else 0
        
        # Get list of test students
        test_apps = db.execute_query(
            "SELECT ApplicationID, ApplicantName, Status, UploadedDate FROM Applications WHERE IsTrainingExample = TRUE ORDER BY UploadedDate DESC"
        )
        
        return jsonify({
            'status': 'success',
            'test_count': count,
            'test_applications': test_apps
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


if __name__ == '__main__':
    # Only use debug mode for local development
    debug_mode = os.getenv('FLASK_ENV') != 'production'
    app.run(debug=debug_mode, host='0.0.0.0', port=int(os.getenv('PORT', 5001)))
