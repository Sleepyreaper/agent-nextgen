"""Mirabel Video Analyzer - Extracts applicant information from video submissions.

Like Mirabel from Encanto who sees the extraordinary in what others overlook,
this agent analyzes video submissions to extract structured data about applicants
using GPT-4o vision (frame analysis) and audio transcription.

Architecture:
    1. Extract key frames from video using OpenCV (every N seconds)
    2. Extract audio track and transcribe via Whisper / Azure Speech
    3. Send frames + transcript to GPT-4o for structured extraction
    4. Output same agent_fields format as Belle for seamless pipeline integration
"""

import base64
import io
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple

from src.agents.base_agent import BaseAgent
from src.agents.system_prompts import MIRABEL_VIDEO_PROMPT
from src.agents.telemetry_helpers import agent_run, tool_call
from src.config import config
from src.utils import safe_load_json

logger = logging.getLogger(__name__)

# Maximum number of frames to extract (to stay within token limits)
MAX_FRAMES = 20
# Default interval between frame captures (seconds)
DEFAULT_FRAME_INTERVAL = 3.0
# Maximum video duration to process (seconds) - 10 minutes
MAX_VIDEO_DURATION = 600
# Supported video extensions
VIDEO_EXTENSIONS = {'mp4'}


def _check_opencv() -> bool:
    """Check if OpenCV is available."""
    try:
        import cv2  # noqa: F401
        return True
    except ImportError:
        return False


def _check_ffmpeg() -> bool:
    """Check if ffmpeg is available on the system."""
    return shutil.which('ffmpeg') is not None


class MirabelVideoAnalyzer(BaseAgent):
    """Mirabel - Analyzes video submissions to extract applicant information.
    
    Capabilities:
    - Extract key frames from MP4 video files
    - Transcribe audio from video using Whisper/Azure Speech
    - Analyze frames with GPT-4o vision to extract visual content
    - Combine audio + visual analysis into structured applicant data
    - Output agent_fields compatible with downstream agents (Tiana, Rapunzel, Mulan, etc.)
    """

    def __init__(
        self,
        name: str = "Mirabel Video Analyzer",
        client=None,
        model: Optional[str] = None,
        db_connection=None,
    ):
        """
        Initialize Mirabel Video Analyzer.

        Args:
            name: Agent name
            client: Azure AI client (OpenAI or Foundry)
            model: Model deployment name (defaults to vision model)
            db_connection: Database connection (optional)
        """
        super().__init__(name=name, client=client)
        # Use vision model for frame analysis (GPT-4o)
        self.vision_model = model or config.foundry_vision_model_name or "gpt-4o"
        # Use whisper model for audio transcription if available
        self.whisper_model = getattr(config, 'foundry_whisper_model_name', None)
        self.db_connection = db_connection
        self.emoji = "🔮"
        self.description = "Analyzes video submissions and extracts applicant information"
        # Frame extraction settings
        self.frame_interval = float(
            os.getenv("MIRABEL_FRAME_INTERVAL", str(DEFAULT_FRAME_INTERVAL))
        )
        self.max_frames = int(os.getenv("MIRABEL_MAX_FRAMES", str(MAX_FRAMES)))
        self.has_opencv = _check_opencv()
        self.has_ffmpeg = _check_ffmpeg()

        if not self.has_opencv:
            logger.warning(
                "⚠️ MIRABEL: opencv-python-headless not installed. "
                "Video frame extraction will be unavailable. "
                "Install with: pip install opencv-python-headless"
            )

    async def process(self, message: str) -> str:
        """Process a message (required by BaseAgent ABC)."""
        return f"Mirabel Video Analyzer received: {message[:100]}..."

    def analyze_video(
        self,
        video_path: str,
        original_filename: str,
        application_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Analyze a video file and extract structured applicant information.

        Args:
            video_path: Path to the video file on disk
            original_filename: Original filename of the upload
            application_id: Optional application ID for logging

        Returns:
            Dict matching Belle's output format:
            - document_type: "video_submission"
            - confidence: float 0-1
            - student_info: extracted student details
            - extracted_data: structured content
            - agent_fields: downstream agent routing fields
            - summary: high-level summary
            - video_metadata: duration, frame_count, has_audio, etc.
        """
        with agent_run(self.name, "analyze_video", {"filename": original_filename}):
            start = time.time()
            result: Dict[str, Any] = {
                "document_type": "video_submission",
                "confidence": 0.0,
                "student_info": {},
                "extracted_data": {},
                "agent_fields": {},
                "summary": "",
                "video_metadata": {},
                "raw_extraction": None,
            }

            # ── Step 1: Extract frames ──────────────────────────────────
            frames, video_meta = self._extract_frames(video_path)
            result["video_metadata"] = video_meta

            if not frames:
                logger.error("❌ MIRABEL: No frames extracted from %s", original_filename)
                result["summary"] = "Failed to extract frames from video file."
                return result

            logger.info(
                "🔮 MIRABEL: Extracted %d frames from %s (%.1fs duration)",
                len(frames),
                original_filename,
                video_meta.get("duration_seconds", 0),
            )

            # ── Step 2: Extract and transcribe audio ────────────────────
            audio_transcript = self._extract_and_transcribe_audio(video_path)
            if audio_transcript:
                result["video_metadata"]["has_audio_transcript"] = True
                result["video_metadata"]["transcript_length"] = len(audio_transcript)
                logger.info(
                    "🔮 MIRABEL: Transcribed %d chars of audio from %s",
                    len(audio_transcript),
                    original_filename,
                )
            else:
                result["video_metadata"]["has_audio_transcript"] = False
                logger.info("🔮 MIRABEL: No audio transcript available for %s", original_filename)

            # ── Step 3: Analyze with GPT-4o vision ──────────────────────
            analysis = self._analyze_with_vision(frames, audio_transcript, original_filename)
            if analysis:
                result["confidence"] = analysis.get("confidence", 0.7)
                result["student_info"] = analysis.get("student_info", {})
                result["extracted_data"] = analysis.get("extracted_data", {})
                result["summary"] = analysis.get("summary", "")
                result["raw_extraction"] = analysis
                
                # Build agent_fields for downstream routing
                result["agent_fields"] = self._build_agent_fields(analysis, audio_transcript)
            else:
                logger.warning("⚠️ MIRABEL: GPT-4o analysis returned no results")
                # Fallback: use raw transcript as application text
                if audio_transcript:
                    result["agent_fields"]["application_text"] = audio_transcript
                    result["summary"] = "Video analysis failed; audio transcript available."

            elapsed = time.time() - start
            result["video_metadata"]["processing_time_seconds"] = round(elapsed, 2)
            logger.info(
                "✅ MIRABEL: Video analysis complete for %s in %.1fs",
                original_filename,
                elapsed,
            )
            return result

    # ─── Frame Extraction ───────────────────────────────────────────────

    def _extract_frames(self, video_path: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Extract key frames from a video file using OpenCV.

        Returns:
            Tuple of (frames_list, video_metadata)
            Each frame: {"image_bytes": bytes, "timestamp": float, "index": int}
        """
        meta: Dict[str, Any] = {
            "duration_seconds": 0,
            "total_frames": 0,
            "fps": 0,
            "width": 0,
            "height": 0,
            "extracted_frame_count": 0,
        }
        frames: List[Dict[str, Any]] = []

        if not self.has_opencv:
            logger.error("❌ MIRABEL: OpenCV not available for frame extraction")
            return frames, meta

        try:
            import cv2

            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                logger.error("❌ MIRABEL: Cannot open video file: %s", video_path)
                return frames, meta

            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            duration = total_frames / fps if fps > 0 else 0

            meta.update({
                "duration_seconds": round(duration, 2),
                "total_frames": total_frames,
                "fps": round(fps, 2),
                "width": width,
                "height": height,
            })

            # Enforce max duration
            if duration > MAX_VIDEO_DURATION:
                logger.warning(
                    "⚠️ MIRABEL: Video is %.0fs, exceeds %ds limit. Processing first %ds only.",
                    duration, MAX_VIDEO_DURATION, MAX_VIDEO_DURATION,
                )
                duration = MAX_VIDEO_DURATION

            # Calculate frame indices to extract
            interval_frames = int(fps * self.frame_interval)
            max_frame_idx = int(min(duration, MAX_VIDEO_DURATION) * fps)
            frame_indices = list(range(0, max_frame_idx, max(interval_frames, 1)))

            # Limit total frames
            if len(frame_indices) > self.max_frames:
                # Evenly sample from available indices
                step = len(frame_indices) / self.max_frames
                frame_indices = [frame_indices[int(i * step)] for i in range(self.max_frames)]

            for idx in frame_indices:
                cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                ret, frame = cap.read()
                if not ret:
                    continue

                # Resize if very large (keep aspect ratio, max 1280px width)
                if width > 1280:
                    scale = 1280 / width
                    new_w = 1280
                    new_h = int(height * scale)
                    frame = cv2.resize(frame, (new_w, new_h))

                # Encode as JPEG (smaller than PNG for transmission)
                success, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if success:
                    frames.append({
                        "image_bytes": buf.tobytes(),
                        "timestamp": round(idx / fps, 2),
                        "index": len(frames),
                    })

            cap.release()
            meta["extracted_frame_count"] = len(frames)
            return frames, meta

        except Exception as e:
            logger.error("❌ MIRABEL: Frame extraction failed: %s", e, exc_info=True)
            return frames, meta

    # ─── Audio Extraction & Transcription ───────────────────────────────

    def _extract_and_transcribe_audio(self, video_path: str) -> Optional[str]:
        """
        Extract audio from video and transcribe it.

        Uses ffmpeg to extract audio track, then transcribes via
        OpenAI Whisper API (if available) or returns None.
        """
        if not self.has_ffmpeg:
            logger.info("MIRABEL: ffmpeg not available, skipping audio transcription")
            return None

        audio_path = None
        try:
            # Extract audio to temporary WAV file
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                audio_path = tmp.name

            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-vn",                     # no video
                "-acodec", "pcm_s16le",    # PCM 16-bit
                "-ar", "16000",            # 16kHz sample rate (Whisper optimal)
                "-ac", "1",                # mono
                audio_path,
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=120,
            )

            if result.returncode != 0:
                stderr = result.stderr.decode("utf-8", errors="replace")
                if "does not contain any stream" in stderr or "no audio" in stderr.lower():
                    logger.info("MIRABEL: Video has no audio track")
                    return None
                logger.warning("MIRABEL: ffmpeg audio extraction failed: %s", stderr[:500])
                return None

            # Check if audio file has content
            if not os.path.exists(audio_path) or os.path.getsize(audio_path) < 1000:
                logger.info("MIRABEL: Audio file too small or empty, skipping transcription")
                return None

            # Transcribe using available method
            transcript = self._transcribe_audio(audio_path)
            return transcript

        except subprocess.TimeoutExpired:
            logger.warning("MIRABEL: Audio extraction timed out")
            return None
        except Exception as e:
            logger.error("MIRABEL: Audio extraction failed: %s", e)
            return None
        finally:
            if audio_path and os.path.exists(audio_path):
                try:
                    os.remove(audio_path)
                except Exception:
                    pass

    def _transcribe_audio(self, audio_path: str) -> Optional[str]:
        """
        Transcribe an audio file using the best available method.

        Priority:
        1. OpenAI Whisper API via Azure (if whisper model deployed)
        2. GPT-4o audio analysis (send audio description to vision model)
        3. Return None (frames-only analysis)
        """
        # Method 1: OpenAI Whisper API
        if self.whisper_model and self.client:
            try:
                with open(audio_path, "rb") as audio_file:
                    with tool_call(self.name, "whisper_transcription"):
                        # The Azure OpenAI / Foundry client supports audio.transcriptions
                        response = self.client.audio.transcriptions.create(
                            model=self.whisper_model,
                            file=audio_file,
                            response_format="text",
                            language="en",
                        )
                        transcript = str(response).strip()
                        if transcript:
                            logger.info("MIRABEL: Whisper transcribed %d chars", len(transcript))
                            return transcript
            except Exception as e:
                logger.warning("MIRABEL: Whisper transcription failed: %s", e)

        # Method 2: Use GPT-4o to describe audio content from video context
        # (Falls through to vision analysis which will note "no transcript available")
        logger.info("MIRABEL: No Whisper model available, proceeding with frames-only analysis")
        return None

    # ─── GPT-4o Vision Analysis ─────────────────────────────────────────

    def _analyze_with_vision(
        self,
        frames: List[Dict[str, Any]],
        audio_transcript: Optional[str],
        filename: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Send video frames + audio transcript to GPT-4o for structured extraction.

        Builds a multimodal message with:
        - System prompt (MIRABEL_VIDEO_PROMPT)
        - Audio transcript (if available)
        - Key frames as base64 images
        - Extraction instructions

        Returns parsed JSON with student_info, extracted_data, summary, confidence.
        """
        if not self.client:
            logger.error("❌ MIRABEL: No AI client available")
            return None

        with tool_call(self.name, "gpt4o_video_analysis"):
            try:
                # Build the multimodal user message
                user_content: List[Dict[str, Any]] = []

                # Text context
                context_parts = [
                    f"Analyze this video submission: '{filename}'",
                    f"Total frames sampled: {len(frames)}",
                ]
                if audio_transcript:
                    context_parts.append(
                        f"\n--- AUDIO TRANSCRIPT ---\n{audio_transcript}\n--- END TRANSCRIPT ---"
                    )
                else:
                    context_parts.append(
                        "\n[No audio transcript available. Analyze visual content only.]"
                    )

                context_parts.append(self._get_extraction_instructions())

                user_content.append({
                    "type": "text",
                    "text": "\n".join(context_parts),
                })

                # Add frames as images (limit to manage token budget)
                # Select a representative subset if we have many frames
                selected_frames = self._select_representative_frames(frames)
                for frame in selected_frames:
                    b64 = base64.b64encode(frame["image_bytes"]).decode("utf-8")
                    timestamp = frame["timestamp"]
                    user_content.append({
                        "type": "text",
                        "text": f"[Frame at {timestamp:.1f}s]",
                    })
                    user_content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64}",
                            "detail": "high",
                        },
                    })

                messages = [
                    {"role": "system", "content": MIRABEL_VIDEO_PROMPT},
                    {"role": "user", "content": user_content},
                ]

                # Call GPT-4o
                response = self.client.chat.completions.create(
                    model=self.vision_model,
                    messages=messages,
                    max_tokens=4000,
                    temperature=0.1,
                )

                raw_text = response.choices[0].message.content or ""
                logger.info("MIRABEL: GPT-4o returned %d chars", len(raw_text))

                # Parse the structured JSON response
                parsed = self._parse_analysis_response(raw_text)
                return parsed

            except Exception as e:
                logger.error("❌ MIRABEL: GPT-4o analysis failed: %s", e, exc_info=True)
                return None

    def _select_representative_frames(
        self, frames: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Select a representative subset of frames for GPT-4o analysis.

        Strategy:
        - Always include first and last frame
        - Evenly distribute remaining frames across the video duration
        - Cap at 10 frames to manage token costs (each high-detail image ~765 tokens)
        """
        max_vision_frames = min(10, len(frames))
        if len(frames) <= max_vision_frames:
            return frames

        selected = [frames[0]]  # First frame
        if len(frames) > 1:
            # Evenly spaced middle frames
            remaining = max_vision_frames - 2  # Reserve slots for first and last
            step = (len(frames) - 2) / (remaining + 1)
            for i in range(1, remaining + 1):
                idx = int(i * step)
                if idx < len(frames) - 1:
                    selected.append(frames[idx])
            selected.append(frames[-1])  # Last frame

        return selected

    def _get_extraction_instructions(self) -> str:
        """Return the JSON extraction instructions for GPT-4o."""
        return """
Please analyze all the video frames and the audio transcript (if provided) and respond with a JSON object containing:

{
    "confidence": 0.0-1.0,
    "student_info": {
        "name": "Full name if identified",
        "first_name": "First name",
        "last_name": "Last name",
        "email": "Email if mentioned",
        "school_name": "High school name if mentioned",
        "state_code": "Two-letter state code if identifiable",
        "grade_level": "Grade level if mentioned",
        "gpa": "GPA if mentioned"
    },
    "extracted_data": {
        "video_type": "essay_presentation | portfolio_showcase | introduction | interview | other",
        "key_themes": ["list of main themes/topics discussed"],
        "achievements": ["specific achievements, awards, or accomplishments mentioned"],
        "activities": ["extracurricular activities mentioned"],
        "interests": ["academic or career interests expressed"],
        "stem_interest": "description of STEM interest if expressed",
        "essay_content": "The substantive content/narrative of the video - what the student is communicating",
        "visual_content_notes": "Notable visual elements (slides, documents shown, setting)",
        "presentation_quality": {
            "communication_skills": "assessment of verbal communication",
            "preparation_level": "how well-prepared the presentation appears",
            "authenticity": "assessment of genuineness and personal voice",
            "overall_quality": "poor | fair | good | very_good | excellent"
        },
        "documents_shown": ["any documents, certificates, or materials visible in the video"],
        "quotes": ["notable direct quotes from the student with approximate timestamps"]
    },
    "summary": "A comprehensive 3-5 sentence summary of the video content and the student's presentation"
}

IMPORTANT: 
- Return ONLY valid JSON, no markdown code fences.
- If information is not available, use null or empty strings/arrays.
- Be thorough - this data feeds into the full evaluation pipeline.
"""

    def _parse_analysis_response(self, raw_text: str) -> Optional[Dict[str, Any]]:
        """Parse the GPT-4o response into structured data."""
        # Try direct JSON parse
        parsed = safe_load_json(raw_text)
        if parsed:
            return parsed

        # Try extracting JSON from markdown code fences
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', raw_text, re.DOTALL)
        if json_match:
            parsed = safe_load_json(json_match.group(1))
            if parsed:
                return parsed

        # Try finding JSON object in the text
        brace_start = raw_text.find('{')
        brace_end = raw_text.rfind('}')
        if brace_start >= 0 and brace_end > brace_start:
            parsed = safe_load_json(raw_text[brace_start:brace_end + 1])
            if parsed:
                return parsed

        logger.warning("MIRABEL: Could not parse GPT-4o response as JSON")
        # Return a minimal structure with the raw text as summary
        return {
            "confidence": 0.5,
            "student_info": {},
            "extracted_data": {"essay_content": raw_text},
            "summary": raw_text[:500],
        }

    # ─── Agent Fields Builder ───────────────────────────────────────────

    def _build_agent_fields(
        self,
        analysis: Dict[str, Any],
        audio_transcript: Optional[str],
    ) -> Dict[str, Any]:
        """
        Build agent_fields dict matching Belle's output format for downstream routing.

        Maps video-extracted content to the fields expected by:
        - Tiana (application_text) — essay/presentation content
        - Rapunzel (transcript_text) — academic records if shown
        - Mulan (recommendation_text) — recommendations if mentioned
        - Milo (essay_video) — video presentation quality
        """
        agent_fields: Dict[str, Any] = {}
        extracted = analysis.get("extracted_data", {})
        student_info = analysis.get("student_info", {})

        # ── Application text for Tiana ──
        # Combine essay content, themes, achievements into a cohesive narrative
        app_parts: List[str] = []
        
        # Add the essay/narrative content
        essay_content = extracted.get("essay_content")
        if essay_content:
            app_parts.append(f"VIDEO ESSAY/PRESENTATION CONTENT:\n{essay_content}")

        # Add key themes
        themes = extracted.get("key_themes", [])
        if themes:
            app_parts.append(f"\nKEY THEMES: {', '.join(themes)}")

        # Add achievements
        achievements = extracted.get("achievements", [])
        if achievements:
            app_parts.append(f"\nACHIEVEMENTS MENTIONED: {', '.join(achievements)}")

        # Add interests
        interests = extracted.get("interests", [])
        if interests:
            app_parts.append(f"\nINTERESTS: {', '.join(interests)}")

        # Add activities
        activities = extracted.get("activities", [])
        if activities:
            app_parts.append(f"\nACTIVITIES: {', '.join(activities)}")

        # STEM interest for Milo
        stem = extracted.get("stem_interest")
        if stem:
            app_parts.append(f"\nSTEM INTEREST: {stem}")
            agent_fields["interest"] = stem

        # Include notable quotes
        quotes = extracted.get("quotes", [])
        if quotes:
            app_parts.append("\nNOTABLE QUOTES:")
            for q in quotes:
                app_parts.append(f"  - \"{q}\"")

        # Include full audio transcript as appendix
        if audio_transcript:
            app_parts.append(f"\n--- FULL AUDIO TRANSCRIPT ---\n{audio_transcript}")

        if app_parts:
            agent_fields["application_text"] = "\n".join(app_parts)
        elif audio_transcript:
            # Fallback: use raw transcript
            agent_fields["application_text"] = audio_transcript

        # ── Transcript text for Rapunzel ──
        # Include if GPA or academic records were shown/mentioned
        docs_shown = extracted.get("documents_shown", [])
        if student_info.get("gpa") or any("transcript" in d.lower() for d in docs_shown if d):
            transcript_parts = []
            if student_info.get("gpa"):
                transcript_parts.append(f"GPA: {student_info['gpa']}")
                agent_fields["gpa"] = student_info["gpa"]
            visual_notes = extracted.get("visual_content_notes")
            if visual_notes:
                transcript_parts.append(f"Visual notes: {visual_notes}")
            if transcript_parts:
                agent_fields["transcript_text"] = "\n".join(transcript_parts)

        # ── School info ──
        if student_info.get("school_name"):
            agent_fields["school_name"] = student_info["school_name"]
        if student_info.get("state_code"):
            agent_fields["state_code"] = student_info["state_code"]

        # ── Activities ──
        if activities:
            agent_fields["activities"] = activities

        # ── Video presentation quality metadata ──
        pres_quality = extracted.get("presentation_quality", {})
        if pres_quality:
            agent_fields["video_presentation_quality"] = pres_quality

        # ── Source marker ──
        agent_fields["_source"] = "mirabel_video"
        agent_fields["_video_type"] = extracted.get("video_type", "unknown")

        return agent_fields
