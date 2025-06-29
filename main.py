#!/usr/bin/env python3
"""
Meeting Processor - Main Entry Point
Clean, modular architecture with focused responsibilities
"""

import sys
import time
import json
import queue
import threading
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

from watchdog.observers import Observer

from config.settings import Settings, ConfigurationError
from core.audio_processor import AudioProcessor
from core.transcription import TranscriptionService
from core.claude_analyzer import ClaudeAnalyzer
from core.file_manager import FileManager
from core.task_extractor import TaskExtractor
from core.dashboard_orchestrator import DashboardOrchestrator
from core.google_drive_service import GoogleDriveService
from core.vault_initializer import VaultInitializer
from entities.detector import EntityDetector
from entities.manager import ObsidianEntityManager
from obsidian.formatter import ObsidianFormatter
from monitoring.file_watcher import MeetingFileHandler
from monitoring.google_drive_monitor import GoogleDriveFileMonitor, GoogleDriveBackupMonitor
from utils.logger import Logger
from utils.resource_manager import get_resource_manager, get_memory_monitor, cleanup_resources
from utils.progress_tracker import get_progress_tracker
from utils.exceptions import (
    MeetingProcessorError, AudioProcessingError, TranscriptionError, 
    AnalysisError, StorageError, ResourceError, handle_error_with_report
)
from utils.file_naming import generate_smart_filename
from utils.intelligent_cache import get_intelligent_cache


class MeetingProcessor:
    """Main orchestrator that coordinates all components"""

    def __init__(self):
        self.logger = Logger.setup()

        # Load and validate settings
        self.settings = Settings()

        # Storage service (Google Drive or local) - initialize early
        self.google_drive_service = None
        if self.settings.storage_mode == 'google_drive':
            self.google_drive_service = GoogleDriveService(
                credentials_path=self.settings.google_drive_credentials_path,
                token_path=self.settings.google_drive_token_path,
                input_folder_id=self.settings.google_drive_input_folder_id,
                output_folder_id=self.settings.google_drive_output_folder_id
            )

        # Initialize vault before file management
        self.vault_initializer = VaultInitializer(self.settings, self.google_drive_service)
        vault_initialized = self.vault_initializer.initialize_vault()
        
        if not vault_initialized:
            raise ConfigurationError("Failed to initialize Obsidian vault")
        
        # Initialize file management - pass Google Drive service for vault operations
        self.file_manager = FileManager(self.settings, self.google_drive_service)

        # Core components
        self.audio_processor = AudioProcessor(self.file_manager.output_dir)
        self.transcription_service = TranscriptionService(
            self.settings.openai_client,
            self.audio_processor
        )
        self.claude_analyzer = ClaudeAnalyzer(self.settings.anthropic_client)

        # Entity & formatting
        self.entity_detector = EntityDetector(self.settings.anthropic_client)
        self.entity_manager = ObsidianEntityManager(
            self.file_manager,
            self.settings.anthropic_client
        )
        self.obsidian_formatter = ObsidianFormatter(self.claude_analyzer)
        self.task_extractor = TaskExtractor(self.settings.anthropic_client)
        self.dashboard_orchestrator = DashboardOrchestrator(
            self.file_manager,
            self.settings.anthropic_client
        )

        # Create vault folder structure if using Google Drive
        if self.file_manager.use_google_drive_vault:
            self.file_manager.create_vault_folder_structure()

        # File-processing queue & workers
        self.processing_queue = queue.Queue()
        self.shutdown_event = threading.Event()
        self.processed_files = set()   # store by filename
        self.processing_files = set()
        self.file_lock = threading.Lock()
        
        # Resource management
        self.resource_manager = get_resource_manager()
        self.memory_monitor = get_memory_monitor()
        self.progress_tracker = get_progress_tracker()
        
        # Intelligent caching
        cache_dir = self.file_manager.output_dir / ".cache"
        self.intelligent_cache = get_intelligent_cache(cache_dir)

        self.logger.info("Meeting Processor initialized successfully")
        self.logger.info(f"Storage mode: {self.settings.storage_mode}")
        
        if self.settings.storage_mode == 'local':
            self.logger.info(f"Input dir:  {self.file_manager.input_dir}")
            self.logger.info(f"Output dir: {self.file_manager.output_dir}")
        else:
            self.logger.info(f"Google Drive input folder:  {self.settings.google_drive_input_folder_id}")
            self.logger.info(f"Google Drive output folder: {self.settings.google_drive_output_folder_id}")
        
        if self.file_manager.use_google_drive_vault:
            self.logger.info(f"Vault: Google Drive folder {self.settings.google_drive_vault_folder_id}")
        else:
            self.logger.info(f"Vault: Local path {self.file_manager.obsidian_vault_path}")

    def start_processing_workers(self, num_workers: int = 2):
        """Kick off background threads to handle files"""
        for i in range(num_workers):
            t = threading.Thread(
                target=self._processing_worker,
                name=f"Worker-{i}",
                daemon=True
            )
            t.start()
            self.logger.info(f"Started {t.name}")
        

    def _processing_worker(self):
        while not self.shutdown_event.is_set():
            try:
                mp4_path = self.processing_queue.get(timeout=1)
                if mp4_path is None:
                    break  # shutdown signal
                try:
                    self._process_meeting_file(mp4_path)
                    
                    # Check memory usage periodically
                    self.memory_monitor.check_memory_usage()
                    
                finally:
                    self.processing_queue.task_done()
            except queue.Empty:
                continue

    def queue_file_for_processing(self, file_path: Path) -> bool:
        """Add a new MP4 to the work queue if it hasn't been seen"""
        name = file_path.name
        with self.file_lock:
            if (name in self.processed_files or
                name in self.processing_files or
                self.file_manager.is_file_processed(name)):
                return False
            self.processing_files.add(name)

        self.processing_queue.put(file_path)
        self.logger.info(f"Queued: {name}")
        return True

    def process_meeting_file(self, mp4_path: Path, drive_file_info: Optional[Dict] = None):
        """Public method to process a meeting file (called by monitors)"""
        self._process_meeting_file(mp4_path, drive_file_info)

    def _process_meeting_file(self, mp4_path: Path, drive_file_info: Optional[Dict] = None):
        name = mp4_path.name
        file_size_mb = 0.0
        
        try:
            # Calculate file size for progress estimation
            if mp4_path.exists():
                file_size_mb = mp4_path.stat().st_size / (1024 * 1024)
            elif drive_file_info and 'size' in drive_file_info:
                file_size_mb = int(drive_file_info['size']) / (1024 * 1024)
            
            # Start progress tracking
            progress = self.progress_tracker.start_processing(name, file_size_mb)
            
            # Check resource availability
            self.progress_tracker.update_stage(name, "validate", 0.1, "checking resources")
            
            # Memory check
            memory_ok = not self.memory_monitor.check_memory_usage()
            if not memory_ok:
                self.logger.warning(f"⚠️ High memory usage detected before processing {name}")
            
            # Disk space check
            disk_ok = self.memory_monitor.check_disk_space(str(self.file_manager.output_dir))
            if not disk_ok:
                raise ResourceError(
                    f"Insufficient disk space to process {name}",
                    resource_type="disk"
                )
            
            # Get resource status for logging
            resource_status = self.memory_monitor.get_resource_status()
            if resource_status.get('memory', {}).get('alerts', {}).get('system_high'):
                self.logger.warning(f"⚠️ System memory usage high: {resource_status['memory']['system_used_percent']:.1f}%")
            
            if resource_status.get('cpu', {}).get('alerts', {}).get('high_usage'):
                self.logger.warning(f"⚠️ High CPU usage: {resource_status['cpu']['usage_percent']:.1f}%")
            
            # Validate API configuration
            self.progress_tracker.update_stage(name, "validate", 0.5, "checking API keys")
            if not self.settings.openai_client and not self.settings.testing_mode:
                self._create_api_key_reminder(mp4_path)
                self.progress_tracker.complete_processing(name, success=False)
                return
            
            self.progress_tracker.complete_stage(name, "validate", "ready to process")

            # Audio conversion
            self.progress_tracker.update_stage(name, "convert", 0.0, "starting conversion")
            flac = self.audio_processor.convert_mp4_to_flac(mp4_path)
            if not flac:
                self.logger.error(f"Conversion failed: {name}")
                self.progress_tracker.complete_processing(name, success=False)
                return
            self.progress_tracker.complete_stage(name, "convert", f"created {flac.name}")

            # Transcription and analysis
            analysis = self._run_transcription_and_analysis_with_progress(flac, name)
            if not analysis:
                self.logger.error(f"Analysis failed: {flac.name}")
                self.progress_tracker.complete_processing(name, success=False)
                return

            # Entity detection
            self.progress_tracker.update_stage(name, "entities", 0.0, "detecting entities")
            if 'entities' not in analysis:
                entities = self.entity_detector.detect_entities(analysis.get('transcript', ''))
                analysis['entities'] = entities
            
            entity_links = self.entity_manager.create_entity_notes(
                analysis['entities'], 
                mp4_path.stem, 
                datetime.now().strftime("%Y-%m-%d")
            )
            analysis['entity_links'] = entity_links
            self.progress_tracker.complete_stage(name, "entities", f"found {sum(len(v) for v in entity_links.values())} entities")

            # Save results
            self.progress_tracker.update_stage(name, "save", 0.0, "saving to vault")
            self._save_analysis(analysis, name, drive_file_info)
            self.progress_tracker.update_stage(name, "save", 0.7, "moving files")
            
            # Handle file moving based on storage mode
            if self.settings.storage_mode == 'google_drive' and drive_file_info:
                # Move file to processed folder in Google Drive
                if self.google_drive_service:
                    self.google_drive_service.move_file_to_processed(
                        drive_file_info['id'],
                        self.settings.google_drive_processed_folder_id
                    )
            else:
                # Local file system move
                self.file_manager.move_processed_file(mp4_path)

            with self.file_lock:
                self.processed_files.add(name)
                self.processing_files.discard(name)
            self.file_manager.mark_file_processed(name)

            self.progress_tracker.complete_stage(name, "save", "files archived")
            self.progress_tracker.complete_processing(name, success=True)

        except AudioProcessingError as e:
            self.logger.error(e.get_user_friendly_message())
            self._create_error_report(mp4_path, e, {"file_size_mb": file_size_mb})
            self.progress_tracker.complete_processing(name, success=False)
            with self.file_lock:
                self.processing_files.discard(name)
        
        except TranscriptionError as e:
            self.logger.error(e.get_user_friendly_message())
            self._create_error_report(mp4_path, e, {"file_size_mb": file_size_mb})
            self.progress_tracker.complete_processing(name, success=False)
            with self.file_lock:
                self.processing_files.discard(name)
        
        except AnalysisError as e:
            self.logger.error(e.get_user_friendly_message())
            self._create_error_report(mp4_path, e, {"file_size_mb": file_size_mb})
            self.progress_tracker.complete_processing(name, success=False)
            with self.file_lock:
                self.processing_files.discard(name)
        
        except StorageError as e:
            self.logger.error(e.get_user_friendly_message())
            self._create_error_report(mp4_path, e, {"file_size_mb": file_size_mb})
            self.progress_tracker.complete_processing(name, success=False)
            with self.file_lock:
                self.processing_files.discard(name)
        
        except ResourceError as e:
            self.logger.error(e.get_user_friendly_message())
            self._create_error_report(mp4_path, e, {"file_size_mb": file_size_mb})
            self.progress_tracker.complete_processing(name, success=False)
            with self.file_lock:
                self.processing_files.discard(name)
        
        except Exception as e:
            # Convert unknown errors to MeetingProcessorError with context
            error = MeetingProcessorError(
                f"Unexpected error processing {name}: {str(e)}",
                details=f"Error type: {type(e).__name__}",
                solutions=[
                    "Check system resources (memory, disk space)",
                    "Verify all dependencies are installed correctly",
                    "Try processing a smaller file to test the system",
                    "Check the error report for more details"
                ]
            )
            self.logger.error(error.get_user_friendly_message())
            self._create_error_report(mp4_path, error, {
                "file_size_mb": file_size_mb,
                "error_type": type(e).__name__,
                "original_error": str(e)
            })
            self.progress_tracker.complete_processing(name, success=False)
            with self.file_lock:
                self.processing_files.discard(name)
    
    def _create_error_report(self, mp4_path: Path, error: MeetingProcessorError, context: dict):
        """Create detailed error report for user debugging"""
        try:
            report_path = handle_error_with_report(
                error, 
                mp4_path.name, 
                str(self.file_manager.output_dir),
                context
            )
            if report_path:
                self.logger.info(f"📄 Error report created: {Path(report_path).name}")
        except Exception as e:
            self.logger.warning(f"Could not create error report: {e}")

    def _create_api_key_reminder(self, mp4_path: Path):
        """Write a note reminding the user to set their API keys"""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"API-KEY-REQUIRED_{mp4_path.stem}_{ts}.md"
        content = f"""# API Key Required — {mp4_path.name}

Please configure your API keys in `.env` before retrying:

- **OPENAI_API_KEY** (for transcription)
- **ANTHROPIC_API_KEY** (for analysis)

Restart the processor after updating.
"""
        path = self.file_manager.output_dir / filename
        path.write_text(content, encoding="utf-8")
        self.logger.info(f"Reminder written: {filename}")

    def _run_transcription_and_analysis_with_progress(self, flac_path: Path, filename: str) -> Optional[Dict]:
        """Core: Whisper → Claude → Entities with progress tracking and intelligent caching"""
        try:
            # Transcription phase
            self.progress_tracker.update_stage(filename, "transcribe", 0.0, "preparing audio")
            transcript = self.transcription_service.transcribe_audio(flac_path)
            if not transcript:
                return None
            self.progress_tracker.complete_stage(filename, "transcribe", f"{len(transcript.split())} words transcribed")

            # Check cache for similar analysis
            self.progress_tracker.update_stage(filename, "analyze", 0.0, "checking cache")
            file_metadata = {
                "filename": filename,
                "file_size": flac_path.stat().st_size if flac_path.exists() else 0,
                "processing_date": datetime.now().isoformat()
            }
            
            cached_entry = self.intelligent_cache.get_cached_analysis(transcript, file_metadata)
            
            if cached_entry:
                # Use cached analysis
                self.progress_tracker.update_stage(filename, "analyze", 0.9, f"using cached analysis (similarity)")
                
                result = {
                    "timestamp": datetime.now().isoformat(),
                    "source_file": flac_path.name,
                    "transcript": transcript,
                    "analysis": cached_entry.analysis.get("analysis", ""),
                    "entities": cached_entry.entities,
                    "cache_info": {
                        "cached": True,
                        "cache_hash": cached_entry.transcript_hash,
                        "cache_created": cached_entry.created_at.isoformat(),
                        "access_count": cached_entry.access_count
                    }
                }
                self.progress_tracker.complete_stage(filename, "analyze", "used cached analysis")
                return result
            
            # No cache hit - perform full analysis
            result = {
                "timestamp": datetime.now().isoformat(),
                "source_file": flac_path.name,
                "transcript": transcript
            }

            # Analysis phase
            self.progress_tracker.update_stage(filename, "analyze", 0.1, "performing AI analysis")
            
            # Full analysis if Anthropic is configured
            if self.settings.anthropic_client:
                self.progress_tracker.update_stage(filename, "analyze", 0.3, "Claude analysis")
                analysis_text = self.claude_analyzer.analyze_transcript(
                    transcript, flac_path.name
                ) or self._basic_analysis(transcript)
                result["analysis"] = analysis_text
                
                self.progress_tracker.update_stage(filename, "analyze", 0.8, "detecting entities")
                result["entities"] = self.entity_detector.detect_all_entities(
                    transcript, flac_path.name
                )
            else:
                result["analysis"] = self._basic_analysis(transcript)
                result["entities"] = {"people": [], "companies": [], "technologies": []}
            
            # Cache the new analysis
            self.progress_tracker.update_stage(filename, "analyze", 0.95, "caching analysis")
            try:
                cache_hash = self.intelligent_cache.cache_analysis(
                    transcript, 
                    {"analysis": result["analysis"]}, 
                    result["entities"], 
                    file_metadata
                )
                result["cache_info"] = {
                    "cached": False,
                    "cache_hash": cache_hash,
                    "newly_cached": True
                }
                self.logger.debug(f"💾 Cached new analysis: {cache_hash[:8]}")
            except Exception as e:
                self.logger.warning(f"Could not cache analysis: {e}")
                result["cache_info"] = {"cached": False, "cache_error": str(e)}
            
            self.progress_tracker.complete_stage(filename, "analyze", "analysis complete")
            return result

        except Exception as e:
            self.logger.error(f"Transcription/analysis error: {e}")
            return None

    def _run_transcription_and_analysis(self, flac_path: Path) -> Optional[Dict]:
        """Legacy method for backward compatibility"""
        return self._run_transcription_and_analysis_with_progress(flac_path, flac_path.name)

    def _basic_analysis(self, transcript: str) -> str:
        """Fallback summary when Claude is unavailable"""
        wc = len(transcript.split())
        cc = len(transcript)
        return (
            f"# Basic Analysis\n\n"
            f"- Words: {wc}\n"
            f"- Characters: {cc}\n"
            f"- Estimated length: {wc//130} min\n"
        )

    def _extract_topic_from_analysis(self, analysis: Dict) -> Optional[str]:
        """Extract topic from analysis data"""
        analysis_text = analysis.get('analysis', '')
        if analysis_text:
            # Look for topic indicators in the analysis
            topic_patterns = [
                r'(?:topic|subject|regarding|about):\s*([^\n.]+)',
                r'(?:meeting\s+about|discussing)\s+([^\n.]+)',
                r'(?:^|\n)(?:topic|subject):\s*([^\n]+)',
                r'(?:^|\n)\*\*(?:topic|subject)\*\*:?\s*([^\n]+)'
            ]
            
            for pattern in topic_patterns:
                match = re.search(pattern, analysis_text, re.IGNORECASE)
                if match:
                    topic = match.group(1).strip()
                    if len(topic) > 5 and len(topic) < 100:  # Reasonable topic length
                        return topic.replace('*', '').strip()  # Remove markdown formatting
        return None

    def _save_analysis(self, analysis: Dict, original_name: str, drive_file_info: Optional[Dict] = None):
        """Persist JSON, Markdown, entity notes, tasks, and dashboards with smart naming"""
        # Generate smart filename based on content analysis
        smart_filename = generate_smart_filename(
            analysis, 
            original_name, 
            analysis.get("transcript", ""),
            self.settings
        )
        
        # Create base name without extension for related files
        base_name = smart_filename[:-3]  # Remove .md extension
        md_name = smart_filename
        json_name = f"{base_name}_analysis.json"
        
        # Extract topic from analysis or use base name
        topic = self._extract_topic_from_analysis(analysis) or base_name.replace('_', ' ')
        
        # Create date string and base variables for entity/task creation
        date = datetime.now().strftime("%Y-%m-%d")
        base = base_name  # Use base_name as the base identifier
        
        self.logger.info(f"💡 Smart filename generated: {original_name} → {smart_filename}")

        # 1) JSON
        json_path = self.file_manager.output_dir / json_name
        json_path.write_text(
            json.dumps(analysis, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        self.logger.info(f"Saved JSON: {json_name}")
        
        # Upload to Google Drive if in Google Drive mode
        if self.settings.storage_mode == 'google_drive' and self.google_drive_service:
            self.google_drive_service.upload_file(json_path, json_name)

        # 2) Markdown note
        md_content = self.obsidian_formatter.create_obsidian_note(
            analysis["analysis"],
            analysis["transcript"],
            original_name,
            topic
        )
        md_path = self.file_manager.output_dir / md_name
        md_path.write_text(md_content, encoding="utf-8")
        
        # Upload to Google Drive if in Google Drive mode
        if self.settings.storage_mode == 'google_drive' and self.google_drive_service:
            self.google_drive_service.upload_file(md_path, md_name)

        # 3) Entity notes - only create if entities were detected
        links = {}
        if analysis.get("entities") and self.settings.anthropic_client:
            # Only create entity notes if we have entities
            entity_count = sum(len(v) for v in analysis["entities"].values())
            if entity_count > 0:
                links = self.entity_manager.create_entity_notes(
                    analysis["entities"], base, date
                )
            else:
                self.logger.debug("No entities detected - skipping entity note creation")

        # 4) Task notes
        tasks = []
        if self.settings.anthropic_client:
            tasks = self.task_extractor.extract_all_tasks(
                analysis["transcript"], base, date
            )
            for task in tasks:
                self.task_extractor.create_task_note(task, self.file_manager)

        # 5) Inject task links
        if tasks:
            md_content = self._inject_task_links(md_content, tasks)
            (self.file_manager.obsidian_vault_path
             / self.file_manager.obsidian_folder_path
             / md_name).write_text(md_content, encoding="utf-8")

        # 6) Save to vault & update entities
        saved = self.file_manager.save_to_obsidian_vault(md_name, md_content)
        if saved and links:
            vault_path = (Path(self.file_manager.obsidian_vault_path)
                          / self.file_manager.obsidian_folder_path
                          / md_name)
            self.entity_manager.update_meeting_note_with_entities(vault_path, links)

        # 7) Dashboard updates
        self._maybe_update_dashboard(base, date, tasks, analysis.get("entities", {}))

    def _inject_task_links(self, content: str, tasks: List[Dict]) -> str:
        """Add a bullet list of task links under the Action Items header"""
        pattern = r'(#{2,}\s*Action\s*Items?\s*\n)'
        match = re.search(pattern, content, re.IGNORECASE)
        if not match:
            self.logger.warning("Action Items header not found")
            return content

        insert = match.end()
        # Fixed: Using 'task_id' to match task_extractor.py
        section = "\n".join(f"- [ ] [[Tasks/{t['task_id']}|{t['task']}]]" for t in tasks)
        return content[:insert] + section + "\n\n" + content[insert:]

    def _maybe_update_dashboard(
        self, base: str, date: str, tasks: List[Dict], entities: Dict
    ):
        """Conditionally update dashboards based on meeting importance"""
        data = {"filename": base, "date": date, "has_transcript": True}
        self.dashboard_orchestrator.maybe_refresh(data, tasks, entities)

    def process_existing_files(self):
        """Queue any MP4s already in the input folder or Google Drive"""
        if self.settings.storage_mode == 'local':
            found = list(self.file_manager.input_dir.glob("*.mp4"))
            self.logger.info(f"Found {len(found)} existing MP4(s)")
            for f in found:
                self.queue_file_for_processing(f)
        elif self.settings.storage_mode == 'google_drive' and self.google_drive_service:
            # For Google Drive, we'll rely on the monitor to handle existing files
            self.logger.info("Google Drive mode - existing files will be detected by monitor")

    def shutdown(self):
        """Graceful shutdown with resource cleanup"""
        self.logger.info("Shutting down...")
        self.shutdown_event.set()
        
        # Stop file watchers if they exist
        if hasattr(self, 'observer') and self.observer:
            self.observer.stop()
            self.observer.join()
        
        # Signal workers to stop
        for _ in range(self.processing_queue.maxsize or 2):
            self.processing_queue.put(None)
        self.processing_queue.join()
        
        # Clean up resources
        self.logger.info("🧹 Cleaning up resources...")
        cleanup_resources()
        
        self.logger.info("✅ Shutdown complete")


def main() -> int:
    logger = Logger.setup()
    try:
        logger.info("Starting Meeting Processor")
        proc = MeetingProcessor()
        proc.start_processing_workers()
        proc.process_existing_files()

        if proc.settings.storage_mode == 'local':
            # Use local file system monitoring
            handler = MeetingFileHandler(proc)
            obs = Observer()
            obs.schedule(handler, str(proc.file_manager.input_dir), recursive=False)
            obs.start()
            logger.info("Watching local directory for new files… (Ctrl+C to exit)")

            while True:
                time.sleep(5)
                
        elif proc.settings.storage_mode == 'google_drive':
            # Use Google Drive monitoring
            if proc.google_drive_service:
                drive_monitor = GoogleDriveFileMonitor(proc, proc.google_drive_service)
                logger.info("Starting Google Drive monitoring… (Ctrl+C to exit)")
                drive_monitor.start_monitoring()
            else:
                logger.error("Google Drive service not initialized")
                return 1
    except KeyboardInterrupt:
        logger.info("Interrupt received, exiting…")
    except ConfigurationError as e:
        logger.error(f"Config error: {e}")
        return 1
    except Exception:
        logger.exception("Fatal error")
        return 1
    finally:
        if 'obs' in locals():
            obs.stop()
            obs.join()
        if 'proc' in locals():
            proc.shutdown()
        logger.info("Processor stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())