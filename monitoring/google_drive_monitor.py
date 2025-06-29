"""
Google Drive file monitoring for Meeting Processor
Replaces local file system monitoring with Google Drive API polling
"""

import time
import tempfile
from pathlib import Path
from typing import Set, Dict, TYPE_CHECKING
from datetime import datetime

from core.google_drive_service import GoogleDriveService
from utils.logger import LoggerMixin, log_file_processing, log_warning

if TYPE_CHECKING:
    from main import MeetingProcessor


class GoogleDriveFileMonitor(LoggerMixin):
    """Google Drive file monitor that replaces local file system watching"""
    
    def __init__(self, processor: 'MeetingProcessor', drive_service: GoogleDriveService):
        self.processor = processor
        self.drive_service = drive_service
        self.processing_files: Set[str] = set()
        self.poll_interval = 30  # seconds between polls
        self.temp_dir = Path(tempfile.gettempdir()) / "meeting_processor"
        self.temp_dir.mkdir(exist_ok=True)
        
        self.logger.info(f"📁 Google Drive monitor initialized")
        self.logger.info(f"📂 Temp directory: {self.temp_dir}")
        self.logger.info(f"⏱️ Poll interval: {self.poll_interval} seconds")
    
    def start_monitoring(self):
        """Start monitoring Google Drive for new MP4 files"""
        self.logger.info("🔍 Starting Google Drive monitoring...")
        
        while True:
            try:
                self._check_for_new_files()
                time.sleep(self.poll_interval)
            except KeyboardInterrupt:
                self.logger.info("🛑 Google Drive monitoring stopped")
                break
            except Exception as e:
                self.logger.error(f"Error in Google Drive monitoring: {e}")
                time.sleep(self.poll_interval)
    
    def _check_for_new_files(self):
        """Check Google Drive for new MP4 files and process them"""
        try:
            new_files = self.drive_service.check_for_new_files()
            
            for file_info in new_files:
                file_id = file_info['id']
                file_name = file_info['name']
                
                # Skip if already processing or processed
                if (file_id in self.processing_files or 
                    self.drive_service.is_file_processed(file_id) or
                    self.processor.file_manager.is_file_processed(file_name)):
                    continue
                
                log_file_processing(self.logger, file_name, 'detect', "Google Drive")
                
                # Validate file before processing
                if not self._validate_file_for_processing(file_info):
                    continue
                
                # Mark as processing and handle
                self.processing_files.add(file_id)
                
                try:
                    self._process_drive_file(file_info)
                except Exception as e:
                    log_file_processing(self.logger, file_name, 'error', str(e))
                finally:
                    self.processing_files.discard(file_id)
                    
        except Exception as e:
            self.logger.error(f"Error checking for new files: {e}")
    
    def _validate_file_for_processing(self, file_info: Dict) -> bool:
        """Validate that file is ready for processing"""
        try:
            file_name = file_info['name']
            file_size = int(file_info.get('size', 0))
            
            # Check file size (should be > 0)
            if file_size == 0:
                log_warning(self.logger, f"File is empty: {file_name}")
                return False
            
            # Check if it's actually an MP4 file
            if not file_name.lower().endswith('.mp4'):
                log_warning(self.logger, f"File is not MP4: {file_name}")
                return False
            
            # Log file info
            file_size_mb = file_size / (1024 * 1024)
            self.logger.info(f"📊 File validated: {file_name} ({file_size_mb:.1f}MB)")
            
            return True
            
        except Exception as e:
            log_warning(self.logger, f"File validation failed for {file_info.get('name', 'unknown')}: {e}")
            return False
    
    def _process_drive_file(self, file_info: Dict):
        """Download and process a file from Google Drive"""
        file_id = file_info['id']
        file_name = file_info['name']
        
        log_file_processing(self.logger, file_name, 'start')
        
        # Create temporary local file path
        temp_file_path = self.temp_dir / file_name
        
        try:
            # Download file from Google Drive
            if not self.drive_service.download_file(file_id, file_name, temp_file_path):
                log_file_processing(self.logger, file_name, 'error', "Download failed")
                return
            
            # Process the file using existing processor
            self.processor.process_meeting_file(temp_file_path, drive_file_info=file_info)
            
            # Mark as processed in Google Drive service
            self.drive_service.mark_file_processed(file_id)
            
            # Clean up temporary file
            if temp_file_path.exists():
                temp_file_path.unlink()
                self.logger.debug(f"🗑️ Cleaned up temp file: {file_name}")
            
            log_file_processing(self.logger, file_name, 'complete')
            
        except Exception as e:
            log_file_processing(self.logger, file_name, 'error', str(e))
            # Clean up temp file on error
            if temp_file_path.exists():
                temp_file_path.unlink()
            raise
    
    def get_monitoring_status(self) -> Dict:
        """Get current monitoring status"""
        return {
            'currently_processing': len(self.processing_files),
            'processing_files': list(self.processing_files),
            'temp_directory': str(self.temp_dir),
            'poll_interval': self.poll_interval,
            'drive_service_info': self.drive_service.get_service_info()
        }
    
    def is_processing_file(self, file_id: str) -> bool:
        """Check if a specific file is currently being processed"""
        return file_id in self.processing_files


class GoogleDriveBackupMonitor(LoggerMixin):
    """Backup monitoring to catch any files missed by regular polling"""
    
    def __init__(self, processor: 'MeetingProcessor', drive_service: GoogleDriveService):
        self.processor = processor
        self.drive_service = drive_service
        self.processed_files_in_session: Set[str] = set()
        self.scan_interval = 300  # 5 minutes between backup scans
    
    def backup_scan(self):
        """Backup scan for files that might have been missed"""
        try:
            self.logger.debug("🔍 Running backup scan on Google Drive...")
            
            # Get all MP4 files in the input folder
            files = self.drive_service.list_files_in_folder(
                self.drive_service.input_folder_id,
                mime_type='video/mp4'
            )
            
            for file_info in files:
                file_id = file_info['id']
                file_name = file_info['name']
                
                # Skip if already processed in this session or previously
                if (file_id in self.processed_files_in_session or 
                    self.drive_service.is_file_processed(file_id) or
                    self.processor.file_manager.is_file_processed(file_name)):
                    continue
                
                log_file_processing(self.logger, file_name, 'detect', "Backup scan")
                self.processed_files_in_session.add(file_id)
                
                # Process through main monitor logic would go here
                # For now, just log that we found it
                self.logger.info(f"📁 Backup scan found unprocessed file: {file_name}")
                
        except Exception as e:
            self.logger.debug(f"Error in backup scan: {e}")
    
    def get_scan_statistics(self) -> Dict:
        """Get monitoring statistics"""
        try:
            input_files = self.drive_service.list_files_in_folder(
                self.drive_service.input_folder_id
            )
            mp4_files = [f for f in input_files if f['name'].lower().endswith('.mp4')]
            
            return {
                'total_files_in_input': len(input_files),
                'mp4_files_in_input': len(mp4_files),
                'processed_in_session': len(self.processed_files_in_session),
                'total_processed_ever': len(self.drive_service.processed_files)
            }
        except Exception as e:
            self.logger.debug(f"Error getting scan statistics: {e}")
            return {}