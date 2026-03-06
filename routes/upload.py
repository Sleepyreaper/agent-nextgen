"""Upload routes — file upload page and chunked upload API."""

import base64
import hashlib
import json
import logging
import os
import uuid

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from extensions import (
    csrf, limiter, run_async,
    get_belle, get_mirabel, get_orchestrator,
    _make_ocr_callback, refresh_foundry_dataset_async,
    start_application_processing, start_training_processing,
    extract_student_name, extract_student_email,
    _split_name_parts, _build_identity_key, _summarize_filenames,
    _aggregate_documents, _collect_documents_from_storage,
    find_high_probability_match, _merge_uploaded_text,
)
from src.config import config
from src.database import db
from src.storage import storage
from src.document_processor import DocumentProcessor

logger = logging.getLogger(__name__)

upload_bp = Blueprint('upload', __name__)


@upload_bp.route('/upload', methods=['GET', 'POST'])
def upload():
    """
    Upload new application file.
    Smee extracts student info automatically.
    """
    if request.method == 'POST':
        try:
            # Check for files from either direct upload OR chunked blob upload
            has_direct_files = (
                'file' in request.files
                and any(f.filename for f in request.files.getlist('file'))
            )
            has_chunked_blobs = bool(
                (request.form.get('chunked_blob_info') or '').strip()
                or (request.form.get('video_blob_info') or '').strip()
            )
            # Also accept base64-encoded blob info for WAF compatibility
            _raw_blob_check = (
                (request.form.get('chunked_blob_info') or '').strip()
                or (request.form.get('video_blob_info') or '').strip()
            )
            if _raw_blob_check:
                import base64 as _b64_check
                try:
                    _decoded_check = _b64_check.b64decode(_raw_blob_check).decode('utf-8')
                    has_chunked_blobs = _decoded_check.strip() not in ('', '[]')
                except Exception:
                    has_chunked_blobs = _raw_blob_check.strip() not in ('', '[]')

            if not has_direct_files and not has_chunked_blobs:
                flash('No file uploaded', 'error')
                return redirect(request.url)
            
            # Determine application type from radio buttons
            app_type = request.form.get('app_type', '2026')  # Default to 2026
            is_training = (app_type == 'training')
            is_test = (app_type == 'test')
            
            # Get selection status for training data
            was_selected = None
            if is_training:
                was_selected_value = (request.form.get('was_selected') or '').strip().lower()
                was_selected = was_selected_value in {'on', 'yes', 'true', '1'}
            
            belle = get_belle()
            grouped_uploads: Dict[str, Dict[str, Any]] = {}
            valid_files = 0

            files = request.files.getlist('file') if 'file' in request.files else []
            for file in files:
                if not file.filename:
                    continue

                if not DocumentProcessor.validate_file_type(file.filename):
                    flash(f"Invalid file type: {file.filename}. Please upload PDF, DOCX, TXT, or MP4 files.", 'error')
                    continue

                valid_files += 1
                filename = secure_filename(file.filename)
                temp_id = uuid.uuid4().hex
                temp_path = os.path.join(app.config['UPLOAD_FOLDER'], f"temp_{temp_id}_{filename}")
                file.save(temp_path)

                # ── Route: Video files → Mirabel, Documents → Belle ──
                is_video = DocumentProcessor.is_video_file(filename)

                if is_video:
                    # Video file: use Mirabel Video Analyzer
                    with open(temp_path, 'rb') as handle:
                        file_content = handle.read()

                    try:
                        mirabel = get_mirabel()
                        doc_analysis = mirabel.analyze_video(temp_path, filename)
                        application_text = doc_analysis.get('agent_fields', {}).get('application_text', '')
                        file_type = 'mp4'
                    except Exception as e:
                        logger.warning(f"Mirabel video analysis failed: {e}")
                        doc_analysis = {
                            "document_type": "video_submission",
                            "confidence": 0,
                            "student_info": {},
                            "extracted_data": {},
                            "agent_fields": {}
                        }
                        application_text = ""
                        file_type = 'mp4'
                    finally:
                        try:
                            os.remove(temp_path)
                        except Exception:
                            pass
                else:
                    # Document file: use Belle Document Analyzer
                    ocr_callback = _make_ocr_callback()
                    application_text, file_type = DocumentProcessor.process_document(
                        temp_path, ocr_callback=ocr_callback
                    )

                    with open(temp_path, 'rb') as handle:
                        file_content = handle.read()

                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass

                    try:
                        doc_analysis = belle.analyze_document(application_text, filename)
                    except Exception as e:
                        logger.warning(f"Belle analysis failed: {e}")
                        doc_analysis = {
                            "document_type": "unknown",
                            "confidence": 0,
                            "student_info": {},
                            "extracted_data": {},
                            "agent_fields": {}
                        }

                belle_student_info = doc_analysis.get('student_info', {})
                extracted_name = belle_student_info.get('name') or extract_student_name(application_text)
                first_name = belle_student_info.get('first_name')
                last_name = belle_student_info.get('last_name')
                if extracted_name and not (first_name and last_name):
                    first_name, last_name = _split_name_parts(extracted_name)

                student_email = belle_student_info.get('email') or extract_student_email(application_text) or ""
                school_name = (doc_analysis.get('agent_fields') or {}).get('school_name') or belle_student_info.get('school_name')

                identity_key = _build_identity_key(
                    first_name=first_name,
                    last_name=last_name,
                    school_name=school_name,
                    email=student_email,
                    full_name=extracted_name,
                    filename=filename
                )

                if identity_key not in grouped_uploads:
                    grouped_uploads[identity_key] = {
                        'first_name': first_name,
                        'last_name': last_name,
                        'student_name': extracted_name,
                        'student_email': student_email,
                        'school_name': school_name,
                        'files': []
                    }

                group = grouped_uploads[identity_key]
                if first_name and not group.get('first_name'):
                    group['first_name'] = first_name
                if last_name and not group.get('last_name'):
                    group['last_name'] = last_name
                if extracted_name and not group.get('student_name'):
                    group['student_name'] = extracted_name
                if student_email and not group.get('student_email'):
                    group['student_email'] = student_email
                if school_name and not group.get('school_name'):
                    group['school_name'] = school_name

                group['files'].append({
                    'filename': filename,
                    'text': application_text,
                    'file_type': file_type,
                    'file_content': file_content,
                    'document_type': doc_analysis.get('document_type', 'unknown'),
                    'student_info': belle_student_info,
                    'agent_fields': doc_analysis.get('agent_fields', {})
                })

            # ── Process pre-uploaded blobs (chunked upload for all file types) ─
            blob_info_raw = (
                request.form.get('chunked_blob_info', '').strip()
                or request.form.get('video_blob_info', '').strip()   # backward compat
            )
            if blob_info_raw:
                import json as _json
                import base64 as _b64
                # The JS client Base64-encodes the JSON to avoid WAF
                # false positives on JSON patterns in form data.
                try:
                    decoded = _b64.b64decode(blob_info_raw).decode('utf-8')
                except Exception:
                    decoded = blob_info_raw  # fallback: raw JSON
                try:
                    chunked_blobs = _json.loads(decoded)
                except Exception:
                    chunked_blobs = []

                for cblob in chunked_blobs:
                    blob_path = cblob.get('blob_path')
                    cfilename = secure_filename(cblob.get('filename', 'file.bin'))
                    if not blob_path:
                        continue

                    temp_id = uuid.uuid4().hex
                    temp_path = os.path.join(
                        app.config['UPLOAD_FOLDER'],
                        f"temp_{temp_id}_{cfilename}"
                    )

                    try:
                        ok = storage.download_blob_to_file(
                            blob_path=blob_path,
                            local_path=temp_path,
                            application_type=app_type,
                        )
                        if not ok:
                            flash(f"Could not retrieve {cfilename} from storage", 'error')
                            continue

                        valid_files += 1

                        # Read file content for later storage.upload_file()
                        with open(temp_path, 'rb') as handle:
                            file_content = handle.read()

                        is_video = DocumentProcessor.is_video_file(cfilename)

                        if is_video:
                            # Video → Mirabel
                            try:
                                mirabel = get_mirabel()
                                doc_analysis = mirabel.analyze_video(temp_path, cfilename)
                                application_text = doc_analysis.get('agent_fields', {}).get('application_text', '')
                                file_type = 'mp4'
                            except Exception as e:
                                logger.warning("Mirabel video analysis (blob) failed: %s", e)
                                doc_analysis = {
                                    "document_type": "video_submission",
                                    "confidence": 0,
                                    "student_info": {},
                                    "extracted_data": {},
                                    "agent_fields": {}
                                }
                                application_text = ""
                                file_type = 'mp4'
                        else:
                            # Document → Belle
                            ocr_callback = _make_ocr_callback()
                            application_text, file_type = DocumentProcessor.process_document(
                                temp_path, ocr_callback=ocr_callback
                            )
                            try:
                                doc_analysis = belle.analyze_document(application_text, cfilename)
                            except Exception as e:
                                logger.warning("Belle analysis failed for chunked blob %s: %s", cfilename, e)
                                doc_analysis = {
                                    "document_type": "unknown",
                                    "confidence": 0,
                                    "student_info": {},
                                    "extracted_data": {}
                                }
                    finally:
                        try:
                            os.remove(temp_path)
                        except Exception:
                            pass

                    belle_student_info = doc_analysis.get('student_info', {})
                    extracted_name = belle_student_info.get('name') or extract_student_name(application_text)
                    first_name = belle_student_info.get('first_name')
                    last_name = belle_student_info.get('last_name')
                    if extracted_name and not (first_name and last_name):
                        first_name, last_name = _split_name_parts(extracted_name)

                    student_email = belle_student_info.get('email') or extract_student_email(application_text) or ""
                    school_name = (doc_analysis.get('agent_fields') or {}).get('school_name') or belle_student_info.get('school_name')

                    identity_key = _build_identity_key(
                        first_name=first_name,
                        last_name=last_name,
                        school_name=school_name,
                        email=student_email,
                        full_name=extracted_name,
                        filename=cfilename
                    )

                    if identity_key not in grouped_uploads:
                        grouped_uploads[identity_key] = {
                            'first_name': first_name,
                            'last_name': last_name,
                            'student_name': extracted_name,
                            'student_email': student_email,
                            'school_name': school_name,
                            'files': []
                        }

                    group = grouped_uploads[identity_key]
                    if first_name and not group.get('first_name'):
                        group['first_name'] = first_name
                    if last_name and not group.get('last_name'):
                        group['last_name'] = last_name
                    if extracted_name and not group.get('student_name'):
                        group['student_name'] = extracted_name
                    if student_email and not group.get('student_email'):
                        group['student_email'] = student_email
                    if school_name and not group.get('school_name'):
                        group['school_name'] = school_name

                    group['files'].append({
                        'filename': cfilename,
                        'text': application_text,
                        'file_type': file_type,
                        'file_content': file_content,
                        'document_type': doc_analysis.get('document_type', 'unknown'),
                        'student_info': belle_student_info,
                        'agent_fields': doc_analysis.get('agent_fields', {})
                    })

            if valid_files == 0:
                flash('No valid files uploaded.', 'error')
                return redirect(request.url)

            results = []
            for group in grouped_uploads.values():
                group_first = group.get('first_name')
                group_last = group.get('last_name')
                group_name = group.get('student_name')
                if group_first and group_last:
                    group_name = f"{group_first} {group_last}".strip()

                group_email = group.get('student_email')
                group_school = group.get('school_name')

                aggregated = _aggregate_documents(group['files'])
                match = find_high_probability_match(
                    student_name=group_name,
                    student_first_name=group_first,
                    student_last_name=group_last,
                    student_email=group_email,
                    school_name=group_school,
                    transcript_text=aggregated.get('transcript_text'),
                    is_training=is_training,
                    is_test=is_test
                )

                if match and match.get('application_id'):
                    application_id = match['application_id']
                    application_record = db.get_application(application_id) or {}
                    student_id = (
                        application_record.get('student_id')
                        or match.get('student_id')
                        or storage.generate_student_id()
                    )

                    if not application_record.get('student_id') and student_id:
                        db.update_application_fields(application_id, {'student_id': student_id})

                    for file_entry in group['files']:
                        storage_result = storage.upload_file(
                            file_content=file_entry['file_content'],
                            filename=file_entry['filename'],
                            student_id=student_id,
                            application_type=app_type
                        )
                        if not storage_result.get('success'):
                            flash(
                                f"Error uploading {file_entry['filename']} to storage: "
                                f"{storage_result.get('error')}",
                                'error'
                            )

                    documents = _collect_documents_from_storage(student_id, app_type, belle)
                    if not documents:
                        documents = group['files']

                    aggregated = _aggregate_documents(documents)
                    updates = {}
                    for field in ['application_text', 'transcript_text', 'recommendation_text']:
                        new_value = aggregated.get(field)
                        if new_value:
                            updates[field] = new_value
                        elif application_record.get(field):
                            updates[field] = application_record.get(field)

                    db.update_application_fields(application_id, updates)

                    missing_fields = []
                    if not updates.get('transcript_text'):
                        missing_fields.append('transcript')
                    if not updates.get('recommendation_text'):
                        missing_fields.append('letters_of_recommendation')
                    db.set_missing_fields(application_id, missing_fields)

                    reprocess_note = _summarize_filenames([f['filename'] for f in group['files']])
                    try:
                        db.save_agent_audit(
                            application_id,
                            'System',
                            f"reprocess:new_upload:{reprocess_note}"
                        )
                    except Exception:
                        pass

                    start_application_processing(application_id)

                    if is_training:
                        refresh_foundry_dataset_async("training_match_update")

                    results.append({
                        'application_id': application_id,
                        'action': 'matched',
                        'applicant_name': match.get('applicant_name') or group_name,
                        'match_score': match.get('match_score')
                    })
                    continue

                # ── Duplicate file detection (SHA-256 content hash) ──
                hash_obj = hashlib.sha256()
                for fe in group['files']:
                    hash_obj.update(fe.get('file_content') or b'')
                file_content_hash = hash_obj.hexdigest()

                dup = db.check_duplicate_file(
                    file_content_hash, is_training=(is_training or is_test)
                )
                if dup:
                    dup_name = dup.get('applicant_name', 'Unknown')
                    dup_file = dup.get('original_file_name', '')
                    dup_id = dup.get('application_id')
                    flash(
                        f"Duplicate file skipped — this file was already uploaded "
                        f"for {dup_name} (application #{dup_id}, file: {dup_file}).",
                        'warning'
                    )
                    results.append({
                        'application_id': dup_id,
                        'action': 'duplicate_skipped',
                        'applicant_name': dup_name,
                    })
                    continue

                student_id = storage.generate_student_id()
                for file_entry in group['files']:
                    storage_result = storage.upload_file(
                        file_content=file_entry['file_content'],
                        filename=file_entry['filename'],
                        student_id=student_id,
                        application_type=app_type
                    )
                    if not storage_result.get('success'):
                        flash(
                            f"Error uploading {file_entry['filename']} to storage: {storage_result.get('error')}",
                            'error'
                        )

                application_text = aggregated.get('application_text') or group['files'][0]['text']
                file_type = group['files'][0].get('file_type')
                filename = group['files'][0].get('filename')
                student_name = group_name or f"Student {student_id}"

                application_id = db.create_application(
                    applicant_name=student_name,
                    email=group_email or "",
                    application_text=application_text,
                    file_name=filename,
                    file_type=file_type,
                    is_training=(is_training or is_test),
                    is_test_data=is_test,
                    was_selected=was_selected,
                    student_id=student_id,
                    file_content_hash=file_content_hash,
                    first_name=group_first,
                    last_name=group_last,
                    high_school=group_school
                )

                additional_fields = {}
                if aggregated.get('transcript_text'):
                    additional_fields['transcript_text'] = aggregated.get('transcript_text')
                if aggregated.get('recommendation_text'):
                    additional_fields['recommendation_text'] = aggregated.get('recommendation_text')
                if additional_fields:
                    db.update_application_fields(application_id, additional_fields)

                missing_fields = []
                if not additional_fields.get('transcript_text'):
                    missing_fields.append('transcript')
                if not additional_fields.get('recommendation_text'):
                    missing_fields.append('letters_of_recommendation')
                if missing_fields:
                    db.set_missing_fields(application_id, missing_fields)

                if is_training:
                    application_record = db.get_application(application_id) or {}
                    placeholder_fields = {}

                    if not application_record.get('application_text'):
                        placeholder_fields['application_text'] = 'No application essay provided for this training run.'
                    if not application_record.get('transcript_text'):
                        placeholder_fields['transcript_text'] = 'No transcript provided for this training run.'
                    if not application_record.get('recommendation_text'):
                        placeholder_fields['recommendation_text'] = 'No recommendation letter provided for this training run.'

                    if placeholder_fields:
                        db.update_application_fields(application_id, placeholder_fields)

                    # Auto-link historical scoring data by name match
                    # Propagate was_selected so Milo can distinguish selected vs not-selected
                    try:
                        historical = db.get_historical_score_by_name(student_name)
                        if historical:
                            db.link_historical_score_to_application(
                                historical['score_id'], application_id,
                                was_selected=was_selected
                            )
                            logger.info(
                                f"✓ Linked historical score {historical['score_id']} "
                                f"({historical.get('applicant_name')}) to application {application_id}"
                                f" [was_selected={was_selected}]"
                            )
                    except Exception as hist_err:
                        logger.warning(f"Historical score matching failed for '{student_name}': {hist_err}")

                    db.set_missing_fields(application_id, [])
                    start_training_processing(application_id)

                if is_test:
                    application_record = db.get_application(application_id) or {}
                    placeholder_fields = {}

                    if not application_record.get('application_text'):
                        placeholder_fields['application_text'] = 'No application essay provided for this test run.'
                    if not application_record.get('transcript_text'):
                        placeholder_fields['transcript_text'] = 'No transcript provided for this test run.'
                    if not application_record.get('recommendation_text'):
                        placeholder_fields['recommendation_text'] = 'No recommendation letter provided for this test run.'

                    if placeholder_fields:
                        db.update_application_fields(application_id, placeholder_fields)

                    db.set_missing_fields(application_id, [])
                    start_application_processing(application_id)

                results.append({
                    'application_id': application_id,
                    'action': 'created',
                    'applicant_name': student_name
                })

            if not results:
                flash('No valid uploads were processed.', 'error')
                return redirect(request.url)

            matched_count = len([r for r in results if r.get('action') == 'matched'])
            created_count = len([r for r in results if r.get('action') == 'created'])

            if is_training:
                flash(
                    f"✅ Uploaded {len(results)} student group(s). "
                    f"Matched {matched_count}, created {created_count}.",
                    'success'
                )
                refresh_foundry_dataset_async("training_upload")
                return redirect(url_for('training.training'))

            if is_test:
                flash(
                    f"✅ Uploaded {len(results)} test student group(s). "
                    f"Matched {matched_count}, created {created_count}.",
                    'success'
                )
                return redirect(url_for('testing.test'))

            if len(results) == 1:
                result = results[0]
                if result.get('action') == 'matched':
                    flash(
                        f"✅ Matched upload to {result.get('applicant_name', 'existing student')}. "
                        "Re-running agents with all documents.",
                        'success'
                    )
                    return redirect(url_for('applications.student_detail', application_id=result['application_id']))

                flash(
                    f"✅ Application uploaded for {result.get('applicant_name', 'student')}. "
                    "Information needed before processing.",
                    'success'
                )
                return redirect(url_for('applications.process_student', application_id=result['application_id']))

            flash(
                f"✅ Uploaded {len(results)} student group(s). "
                f"Matched {matched_count}, created {created_count}.",
                'success'
            )
            return redirect(url_for('applications.students'))
            
        except Exception as e:
            logger.error('File upload failed: %s', e, exc_info=True); flash('An error occurred while uploading the file', 'error')
            import traceback
            traceback.print_exc()
            return redirect(request.url)
    
    # if query parameter provided, pass along to template so JS can preselect
    app_type = request.args.get('app_type')
    was_selected = request.args.get('was_selected')
    if app_type:
        logger.info(f"Upload page requested with preselect app_type={app_type}")
    return render_template('upload.html', preselect_type=app_type, preselect_selected=was_selected)



# ── Chunked Video Upload API ─────────────────────────────────────────
@upload_bp.route('/api/file/upload-chunk', methods=['POST'])
@upload_bp.route('/api/video/upload-chunk', methods=['POST'])  # backward compat
@limiter.limit("300 per minute")
def file_upload_chunk():
    """Accept a chunk of file data and stage it in Azure Blob Storage.

    ALL file types (PDF, DOCX, TXT, MP4, etc.) are uploaded in chunks
    (default 4 MB on the client). Configure Azure Front Door WAF to
    exclude /api/file/upload-chunk from body inspection, or set the
    request body size limit to at least 8 MB for this route.

    The client sends:
      - chunk      : the binary chunk (file part)
      - upload_id  : UUID generated client-side (same for all chunks)
      - chunk_index: 0-based index of this chunk
      - total_chunks: total number of chunks
      - filename   : original file name
      - app_type   : "2026" | "training" | "test"

    On the final chunk the staged blocks are committed and the response
    includes ``blob_path`` and ``container`` for use in the form POST.
    """
    chunk = request.files.get('chunk')
    if not chunk:
        return jsonify({'error': 'No chunk data'}), 400

    upload_id = request.form.get('upload_id', '')
    chunk_index = int(request.form.get('chunk_index', 0))
    total_chunks = int(request.form.get('total_chunks', 1))
    filename = secure_filename(request.form.get('filename', 'file.bin'))
    app_type = request.form.get('app_type', '2026')

    if not upload_id:
        return jsonify({'error': 'upload_id is required'}), 400

    # Guard against unbounded chunked uploads (max 500 chunks × 4 MB ≈ 2 GB)
    if total_chunks > 500:
        return jsonify({'error': 'File too large (exceeds chunk limit)'}), 400
    if chunk_index < 0 or chunk_index >= total_chunks:
        return jsonify({'error': 'Invalid chunk_index'}), 400

    try:
        ok = storage.stage_chunked_upload(
            upload_id=upload_id,
            filename=filename,
            chunk_index=chunk_index,
            chunk_data=chunk.read(),
            application_type=app_type,
        )
        if not ok:
            return jsonify({'error': 'Storage not available – could not stage chunk'}), 500
    except Exception as e:
        logger.error("File chunk %d upload failed: %s", chunk_index, e)
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'error': 'An internal error occurred'}), 500

    result = {
        'upload_id': upload_id,
        'chunk_index': chunk_index,
        'total_chunks': total_chunks,
        'progress': round((chunk_index + 1) / total_chunks * 100, 1),
    }

    # Last chunk → commit all blocks
    if chunk_index == total_chunks - 1:
        try:
            commit = storage.commit_chunked_upload(
                upload_id=upload_id,
                filename=filename,
                total_chunks=total_chunks,
                application_type=app_type,
            )
            if commit.get('success'):
                result['complete'] = True
                result['blob_path'] = commit['blob_path']
                result['container'] = commit['container']
            else:
                return jsonify({'error': 'Failed to commit file upload'}), 500
        except Exception as e:
            logger.error("File commit failed for %s: %s", upload_id, e)
            logger.error('Request failed: %s', e, exc_info=True)
            return jsonify({'error': 'An internal error occurred'}), 500

    return jsonify(result)


