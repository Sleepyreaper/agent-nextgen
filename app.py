"""Flask web application for application evaluation system."""

import os
import asyncio
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from werkzeug.utils import secure_filename
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

from src.config import config
from src.database import db
from src.document_processor import DocumentProcessor
from src.agents import EvaluatorAgent

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


@app.route('/')
def index():
    """Home page."""
    try:
        applications = db.get_applications_with_evaluations()
        pending_count = len([a for a in applications if a['Status'] == 'Pending'])
        evaluated_count = len([a for a in applications if a['Status'] == 'Evaluated'])
        
        return render_template('index.html', 
                             applications=applications,
                             pending_count=pending_count,
                             evaluated_count=evaluated_count)
    except Exception as e:
        flash(f'Error loading applications: {str(e)}', 'error')
        return render_template('index.html', applications=[], pending_count=0, evaluated_count=0)


@app.route('/upload', methods=['GET', 'POST'])
def upload():
    """Upload new application."""
    if request.method == 'POST':
        try:
            # Get form data
            applicant_name = request.form.get('applicant_name')
            email = request.form.get('email')
            position = request.form.get('position')
            is_training = request.form.get('is_training') == 'on'
            was_selected = request.form.get('was_selected') == 'on' if is_training else None
            
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
            
            # Save file
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            
            # Extract text
            application_text, file_type = DocumentProcessor.process_document(file_path)
            
            # Save to database
            application_id = db.create_application(
                applicant_name=applicant_name,
                email=email,
                application_text=application_text,
                file_name=filename,
                file_type=file_type,
                is_training=is_training,
                was_selected=was_selected
            )
            
            if is_training:
                flash(f'Training example uploaded successfully!', 'success')
                # Refresh evaluator with new training data
                global evaluator_agent
                evaluator_agent = None  # Reset to reload training examples
            else:
                flash(f'Application uploaded successfully! ID: {application_id}', 'success')
            
            return redirect(url_for('index'))
            
        except Exception as e:
            flash(f'Error uploading application: {str(e)}', 'error')
            return redirect(request.url)
    
    return render_template('upload.html')


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
            "UPDATE Applications SET Status = 'Evaluated' WHERE ApplicationID = ?",
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
                "UPDATE Applications SET Status = 'Evaluated' WHERE ApplicationID = ?",
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


@app.route('/application/<int:application_id>')
def view_application(application_id):
    """View application details and evaluation."""
    try:
        application = db.get_application(application_id)
        if not application:
            flash('Application not found', 'error')
            return redirect(url_for('index'))
        
        # Get evaluation if it exists
        evaluations = db.execute_query(
            "SELECT * FROM AIEvaluations WHERE ApplicationID = ? ORDER BY EvaluationDate DESC",
            (application_id,)
        )
        evaluation = evaluations[0] if evaluations else None
        
        return render_template('application.html', application=application, evaluation=evaluation)
        
    except Exception as e:
        flash(f'Error loading application: {str(e)}', 'error')
        return redirect(url_for('index'))


if __name__ == '__main__':
    # Only use debug mode for local development
    debug_mode = os.getenv('FLASK_ENV') != 'production'
    app.run(debug=debug_mode, host='0.0.0.0', port=int(os.getenv('PORT', 5001)))
