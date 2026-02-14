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
from src.agents import (
    EvaluatorAgent,
    SmeeOrchestrator,
    RapunzelGradeReader,
    MoanaSchoolContext,
    TianaApplicationReader,
    MulanRecommendationReader,
    MerlinStudentEvaluator,
    PresenterAgent
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

def get_evaluator():
    """Get or create evaluator agent."""
    global evaluator_agent
    if not evaluator_agent:
        client = get_ai_client()
        training_examples = db.get_training_examples()
        evaluator_agent = EvaluatorAgent(
            name="ApplicationEvaluator",
            client=client,
            model=config.deployment_name,
            training_examples=training_examples
        )
    return evaluator_agent


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
            
            # Flash success message with student ID
            if is_training:
                flash(f'✅ Training data uploaded! Student ID: {student_id}', 'success')
                return redirect(url_for('training'))
            else:
                flash(f'✅ Application uploaded! Student ID: {student_id}. Processing with Smee...', 'success')
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


@app.route('/test/<student_id>')
def test_detail(student_id):
    """Detailed test results for a specific student."""
    try:
        # Define test students with detailed data anchored in what they provided
        test_students = {
            'alex': {
                'name': 'Alex Johnson',
                'email': 'alex.johnson@example.com',
                'status': 'COMPLETE',
                'application_text': "I am Alex Johnson from Lincoln High School. My passion for STEM has driven me throughout my academic career. I have maintained a 3.85 GPA while taking 5 AP courses including AP Biology, AP Chemistry, and Calculus. In my junior year, I founded the Science Club which now has 40+ members. I served as President of the Student Government Council and led multiple community service projects. I believe education is transformative and I am committed to pursuing engineering in college.",
                'merlin_summary': {
                    'score': 88,
                    'recommendation': 'STRONGLY RECOMMEND',
                    'overall': "Alex Johnson presents a compelling candidacy with exceptional academic achievement and demonstrated leadership. With a 3.85 GPA and completion of five AP courses, Alex has consistently demonstrated mastery of advanced coursework. Most notably, the founding and leadership of the Science Club (growing to 40+ members) shows genuine initiative and community impact. The personal statement reveals a thoughtful student with clear calling toward engineering and a genuine passion for STEM. Teacher recommendations emphasize Alex's work ethic, intellectual curiosity, and ability to inspire peers. The combination of rigorous academics, proven leadership, and authentic passion makes Alex an excellent candidate who will likely thrive at the university level and contribute meaningfully to campus intellectual life.",
                    'key_strengths': ['3.85 GPA with rigorous curriculum', 'Founded and expanded Science Club to 40+ members', 'Clear career direction (engineering)', 'Strong teacher endorsements', 'Demonstrated leadership as Student Government President', 'Community service commitment'],
                    'considerations': ['Out-of-state applicant (requires no sponsorship)', 'Well-prepared for advanced coursework']
                },
                'agents': {
                    'tiana': {
                        'name': '👸 Tiana - Application Reader',
                        'status': '✅ Complete',
                        'score': 85,
                        'analysis': "Alex's personal statement is well-written and demonstrates clear self-awareness. The writing is organized, articulate, and provides specific examples of leadership and passion. The applicant effectively communicates their journey from discovering STEM interest to founding the Science Club. The essay shows maturity and purpose.",
                        'key_qualities': ['Clear writing style', 'Specific examples and stories', 'Demonstrates reflection and self-awareness', 'Authentic voice', 'Well-organized narrative'],
                        'strengths_found': 'Alex communicates strong motivation for STEM with concrete evidence through club founding and leadership.'
                    },
                    'rapunzel': {
                        'name': '💇 Rapunzel - Grade Reader',
                        'status': '✅ Complete',
                        'gpa': 3.85,
                        'academic_score': 92,
                        'courses_analyzed': 'AP Biology (A), AP Chemistry (A-), Calculus (A), AP US History (A), Regular English (A-)',
                        'grade_trends': 'Consistent high grades throughout; slight upward trend from freshman to junior year',
                        'key_findings': ['Rigorous curriculum selection', 'Consistent excellence across STEM and humanities', 'Balanced course load shows versatility', '5 AP courses completed', 'No grade decline detected']
                    },
                    'moana': {
                        'name': '🌊 Moana - School Context',
                        'status': '✅ Complete',
                        'school_name': 'Lincoln High School',
                        'location': 'Lincoln, Nebraska',
                        'school_ranking': 'Top 15% in state',
                        'school_info': 'Lincoln High School is a well-funded public school in an affluent district with strong STEM program. Known for rigorous academics and high college placement rates.',
                        'key_context': ['School offers 12+ AP courses', 'Science curriculum is well-developed with lab facilities', 'Strong teacher network and mentorship available', 'High college acceptance rate indicates good college prep']
                    },
                    'mulan': {
                        'name': '🗡️ Mulan - Recommendation Reader',
                        'status': '✅ Complete',
                        'recommendation_count': 2,
                        'endorsement_strength': 95,
                        'rec1': 'AP Biology teacher emphasizes Alex\'s intellectual curiosity, exceptional work ethic, and ability to synthesize complex concepts.',
                        'rec2': 'Science Club member testimonial praises Alex\'s genuine passion and inclusive leadership style that made the club welcoming to all.',
                        'key_endorsements': ['Exceptional scientific thinking', 'Inspires peers through authentic passion', 'Collaborative and inclusive leader', 'Reliable and committed', 'Demonstrates maturity beyond grade level']
                    }
                }
            },
            'jordan': {
                'name': 'Jordan Smith',
                'email': 'jordan.smith@example.com',
                'status': 'PARTIAL',
                'application_text': "I am Jordan Smith. I go to a public school without many advanced opportunities. I have worked hard to maintain good grades with a 3.45 GPA. I haven't taken many AP courses but I am interested in environmental science and plan to study that in college.",
                'merlin_summary': {
                    'score': 65,
                    'recommendation': 'CONSIDER - Recommend gathering more information',
                    'overall': "Jordan Smith demonstrates solid academic fundamentals with a 3.45 GPA and commitment to learning despite limited advanced offerings at school. The interest in environmental science is clear and genuine. However, the application is incomplete - we lack critical information about teacher endorsements which would help assess Jordan's potential for college-level work. The limited enrollment in AP-level courses makes academic comparison more difficult. To make a full evaluation, we recommend requesting teacher recommendation letters and potentially additional documentation about advanced work undertaken within available constraints.",
                    'key_strengths': ['Good GPA given school resources', 'Clear field of interest (environmental science)', 'Honest and straightforward communication'],
                    'missing_context': ['No teacher recommendations provided', 'Limited AP/advanced coursework documented', 'School context unclear (affects grade interpretation)', 'Insufficient evidence of leadership or initiative']
                },
                'agents': {
                    'tiana': {
                        'name': '👸 Tiana - Application Reader',
                        'status': '✅ Complete',
                        'score': 72,
                        'analysis': "Jordan's statement is brief and lacks detailed examples or personal narrative. While the interest in environmental science is stated, there is limited evidence of how this passion developed or what specific actions demonstrate commitment. The writing is clear but lacks the depth and reflection seen in more compelling applications.",
                        'observations': ['Brief statement', 'Some personal voice present', 'Lacks specific examples', 'Interest stated but not demonstrated', 'Could benefit from more detail']
                    },
                    'rapunzel': {
                        'name': '💇 Rapunzel - Grade Reader',
                        'status': '✅ Complete',
                        'gpa': 3.45,
                        'academic_score': 78,
                        'courses_analyzed': '2 AP courses total (AP Environmental Science, AP World History)',
                        'grade_pattern': 'Solid B+/A- grades consistently',
                        'key_findings': ['Respectable GPA given limited AP availability', 'Limited advanced coursework limits assessment', 'No grade decline shown', 'Could have taken more challenging courses']
                    },
                    'moana': {
                        'name': '🌊 Moana - School Context',
                        'status': '⚠️ Insufficient data',
                        'school_info': 'School not specified in application',
                        'limitation': 'Without school name and context, difficult to assess how rigorous the GPA is relative to available opportunities.',
                        'needed': 'School name, location, and available AP courses would help contextualize grades'
                    },
                    'mulan': {
                        'name': '🗡️ Mulan - Recommendation Reader',
                        'status': '⚠️ Missing',
                        'recommendation_count': 0,
                        'missing': 'No recommendation letters provided',
                        'critical': 'Recommendations from teachers would be essential to assess Jordan\'s potential, work ethic, and character.'
                    }
                }
            }
        }
        
        if student_id not in test_students:
            flash('Student not found', 'error')
            return redirect(url_for('test'))
        
        student = test_students[student_id]
        
        return render_template('test_detail.html', student=student)
    except Exception as e:
        flash(f'Error loading test details: {str(e)}', 'error')
        return redirect(url_for('test'))


@app.route('/student/<int:application_id>')
def student_detail(application_id):
    """View comprehensive student summary built by Merlin."""
    try:
        # Get main application record
        application = db.get_application(application_id)
        if not application:
            flash('Student not found', 'error')
            return redirect(url_for('students'))
        
        # Get all agent outputs
        tiana_data = db.execute_query(
            "SELECT * FROM TianaApplications WHERE ApplicationID = %s ORDER BY CreatedAt DESC LIMIT 1",
            (application_id,)
        )
        
        rapunzel_data = db.execute_query(
            "SELECT * FROM AIEvaluations WHERE ApplicationID = %s AND AgentName = 'Rapunzel' ORDER BY EvaluationDate DESC LIMIT 1",
            (application_id,)
        )
        
        moana_data = db.get_student_school_context(application_id)
        
        mulan_data = db.execute_query(
            "SELECT * FROM MulanRecommendations WHERE ApplicationID = %s ORDER BY CreatedAt DESC",
            (application_id,)
        )
        
        merlin_data = db.execute_query(
            "SELECT * FROM MerlinEvaluations WHERE ApplicationID = %s ORDER BY CreatedAt DESC LIMIT 1",
            (application_id,)
        )
        
        # Get agent processing status
        audit_logs = db.execute_query(
            "SELECT * FROM AgentAuditLogs WHERE ApplicationID = %s ORDER BY CreatedAt DESC",
            (application_id,)
        )
        
        return render_template('student_detail.html',
                             application=application,
                             tiana=tiana_data[0] if tiana_data else None,
                             rapunzel=rapunzel_data[0] if rapunzel_data else None,
                             moana=moana_data,
                             mulan=mulan_data,
                             merlin=merlin_data[0] if merlin_data else None,
                             audit_logs=audit_logs)
        
    except Exception as e:
        flash(f'Error loading student: {str(e)}', 'error')
        return redirect(url_for('students'))


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
presenter = PresenterAgent()


def generate_session_updates(session_id):
    """
    Generator function for SSE updates during test processing.
    Yields status updates as agents process students.
    """
    submission = test_submissions.get(session_id)
    if not submission:
        yield f"data: {json.dumps({'error': 'Session not found'})}\n\n"
        return
    
    # Send initial connected message
    yield f"data: {json.dumps({'type': 'connected', 'message': 'Connected to test stream'})}\n\n"
    time.sleep(0.1)
    
    # Simulate agent pipeline with status updates
    students = submission['students']
    
    for idx, student in enumerate(students):
        student_id = f"student_{idx}"
        
        # Student submitted
        yield f"data: {json.dumps({'type': 'student_submitted', 'student': student, 'student_id': student_id})}\n\n"
        time.sleep(1)
        
        # Tiana starts
        yield f"data: {json.dumps({'type': 'agent_start', 'agent': 'tiana', 'student_id': student_id, 'emoji': '👸'})}\n\n"
        time.sleep(1.5)
        
        # Tiana completes
        yield f"data: {json.dumps({'type': 'agent_complete', 'agent': 'tiana', 'student_id': student_id, 'status': 'complete'})}\n\n"
        time.sleep(0.5)
        
        # Rapunzel starts
        yield f"data: {json.dumps({'type': 'agent_start', 'agent': 'rapunzel', 'student_id': student_id, 'emoji': '💇'})}\n\n"
        time.sleep(1.5)
        yield f"data: {json.dumps({'type': 'agent_complete', 'agent': 'rapunzel', 'student_id': student_id, 'status': 'complete'})}\n\n"
        time.sleep(0.5)
        
        # Moana starts
        yield f"data: {json.dumps({'type': 'agent_start', 'agent': 'moana', 'student_id': student_id, 'emoji': '🌊'})}\n\n"
        time.sleep(1.5)
        yield f"data: {json.dumps({'type': 'agent_complete', 'agent': 'moana', 'student_id': student_id, 'status': 'complete'})}\n\n"
        time.sleep(0.5)
        
        # Mulan starts
        yield f"data: {json.dumps({'type': 'agent_start', 'agent': 'mulan', 'student_id': student_id, 'emoji': '🗡️'})}\n\n"
        time.sleep(1.5)
        yield f"data: {json.dumps({'type': 'agent_complete', 'agent': 'mulan', 'student_id': student_id, 'status': 'complete'})}\n\n"
        time.sleep(0.5)
        
        # Merlin starts
        yield f"data: {json.dumps({'type': 'agent_start', 'agent': 'merlin', 'student_id': student_id, 'emoji': '🧙'})}\n\n"
        time.sleep(2)
        yield f"data: {json.dumps({'type': 'agent_complete', 'agent': 'merlin', 'student_id': student_id, 'status': 'complete'})}\n\n"
        time.sleep(0.5)
        
        # Smee verifies
        yield f"data: {json.dumps({'type': 'agent_start', 'agent': 'smee', 'student_id': student_id, 'emoji': '🎩'})}\n\n"
        time.sleep(1)
        yield f"data: {json.dumps({'type': 'agent_complete', 'agent': 'smee', 'student_id': student_id, 'status': 'complete', 'verified': True})}\n\n"
        time.sleep(0.5)
        
        # Presenter formats results
        yield f"data: {json.dumps({'type': 'agent_start', 'agent': 'presenter', 'student_id': student_id, 'emoji': '🎨'})}\n\n"
        time.sleep(1)
        yield f"data: {json.dumps({'type': 'agent_complete', 'agent': 'presenter', 'student_id': student_id, 'status': 'complete'})}\n\n"
        time.sleep(0.5)
        
        # Results ready
        yield f"data: {json.dumps({'type': 'results_ready', 'student_id': student_id, 'results_url': url_for('test_detail', student_id=student_id)})}\n\n"
        time.sleep(0.2)


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
    Accept test student submissions and start processing pipeline.
    Returns a session ID to stream updates from.
    """
    try:
        data = request.json
        students = data.get('students', [])
        
        if not students:
            return jsonify({'error': 'No students provided'}), 400
        
        # Generate session ID
        session_id = str(uuid.uuid4())
        
        # Track submission
        test_submissions[session_id] = {
            'students': students,
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


if __name__ == '__main__':
    # Only use debug mode for local development
    debug_mode = os.getenv('FLASK_ENV') != 'production'
    app.run(debug=debug_mode, host='0.0.0.0', port=int(os.getenv('PORT', 5001)))
