"""
File management for Meeting Processor
Handles file operations, directory setup, and processing tracking
"""

import shutil
import time
import threading
from pathlib import Path
from typing import Set, Optional, TYPE_CHECKING
from utils.logger import LoggerMixin, log_success, log_error, log_warning

if TYPE_CHECKING:
    from core.google_drive_service import GoogleDriveService


class FileManager(LoggerMixin):
    """Handles file operations and tracking"""
    
    def __init__(self, settings, google_drive_service: Optional['GoogleDriveService'] = None):
        self.settings = settings
        self.google_drive_service = google_drive_service
        self.input_dir = Path(settings.input_dir)
        self.output_dir = Path(settings.output_dir)
        self.processed_dir = Path(settings.processed_dir)
        self.obsidian_vault_path = settings.obsidian_vault_path
        self.obsidian_folder_path = settings.obsidian_folder_path
        
        self.processed_files_log = self.output_dir / 'processed_files.txt'
        self.processed_files: Set[str] = set()
        self._processed_files_lock = threading.RLock()  # Reentrant lock for file operations
        
        # For Google Drive mode, we use the vault folder ID for direct uploads
        self.use_google_drive_vault = (
            settings.storage_mode == 'google_drive' and 
            hasattr(settings, 'google_drive_vault_folder_id') and
            settings.google_drive_vault_folder_id and
            google_drive_service is not None
        )
        
        self._setup_directories()
        self._load_processed_files()
    
    def _setup_directories(self):
        """Create necessary directories"""
        directories = [
            self.input_dir,
            self.output_dir,
            self.processed_dir
        ]
        
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            self.logger.debug(f"📁 Ensured directory exists: {directory}")
        
        # Create Obsidian vault structure
        obsidian_meetings_path = Path(self.obsidian_vault_path) / self.obsidian_folder_path
        obsidian_meetings_path.mkdir(parents=True, exist_ok=True)
        
        # Create entity folders
        for folder in self.settings.entity_folders:
            entity_path = Path(self.obsidian_vault_path) / folder
            entity_path.mkdir(parents=True, exist_ok=True)
            self.logger.debug(f"📁 Created entity folder: {folder}")
        
        log_success(self.logger, "Directory structure initialized")
    
    def _load_processed_files(self):
        """Load list of already processed files (thread-safe)"""
        try:
            # Clear processed files in testing mode
            if self.settings.testing_mode:
                self.logger.info("🔄 TESTING MODE: Clearing processed files list")
                with self._processed_files_lock:
                    self.processed_files = set()
                    if self.processed_files_log.exists():
                        self.processed_files_log.unlink()
                return
            
            with self._processed_files_lock:
                if self.processed_files_log.exists():
                    with open(self.processed_files_log, 'r', encoding='utf-8') as f:
                        self.processed_files = set(line.strip() for line in f if line.strip())
                    self.logger.info(f"📋 Loaded {len(self.processed_files)} processed files")
        except Exception as e:
            log_error(self.logger, "Error loading processed files list", e)
    
    def is_file_processed(self, filename: str) -> bool:
        """Check if file has already been processed (thread-safe)"""
        with self._processed_files_lock:
            return filename in self.processed_files
    
    def mark_file_processed(self, filename: str):
        """Mark file as processed (thread-safe)"""
        with self._processed_files_lock:
            if filename not in self.processed_files:
                self.processed_files.add(filename)
                try:
                    with open(self.processed_files_log, 'a', encoding='utf-8') as f:
                        f.write(f"{filename}\n")
                except Exception as e:
                    log_error(self.logger, f"Error writing to processed files log: {e}")
                    # Remove from memory set if we couldn't persist it
                    self.processed_files.discard(filename)
                else:
                    self.logger.debug(f"✓ Marked as processed: {filename}")
    
    def move_processed_file(self, source_path: Path) -> bool:
        """Move processed file to processed directory"""
        try:
            if not source_path.exists():
                log_warning(self.logger, f"Source file not found: {source_path}")
                return False
            
            dest_path = self.processed_dir / source_path.name
            
            # Handle existing files
            if dest_path.exists():
                timestamp = int(time.time())
                base_name = dest_path.stem
                extension = dest_path.suffix
                dest_path = self.processed_dir / f"{base_name}_{timestamp}{extension}"
            
            shutil.move(str(source_path), str(dest_path))
            log_success(self.logger, f"Moved to processed: {source_path.name}")
            return True
            
        except Exception as e:
            log_error(self.logger, f"Error moving file {source_path}", e)
            return False
    
    def save_to_obsidian_vault(self, filename: str, content: str) -> bool:
        """Save content to Obsidian vault (local or Google Drive)"""
        try:
            if self.use_google_drive_vault:
                # Save to Google Drive vault
                return self._save_to_google_drive_vault(filename, content)
            else:
                # Save to local vault
                return self._save_to_local_vault(filename, content)
                
        except Exception as e:
            log_error(self.logger, f"Error saving to vault: {filename}", e)
            return False
    
    def _save_to_local_vault(self, filename: str, content: str) -> bool:
        """Save content to local Obsidian vault"""
        vault_path = Path(self.obsidian_vault_path) / self.obsidian_folder_path / filename
        vault_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(vault_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        log_success(self.logger, f"Saved to local vault: {vault_path}")
        return True
    
    def _save_to_google_drive_vault(self, filename: str, content: str) -> bool:
        """Save content to Google Drive vault"""
        # Create temporary file
        temp_path = self.output_dir / f"temp_{filename}"
        
        try:
            # Write content to temporary file
            with open(temp_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            # Determine the folder structure in Google Drive
            drive_filename = f"{self.obsidian_folder_path}/{filename}".replace('\\', '/')
            
            # Upload to Google Drive vault folder
            file_id = self.google_drive_service.upload_file(
                temp_path, 
                drive_filename, 
                self.settings.google_drive_vault_folder_id
            )
            
            if file_id:
                log_success(self.logger, f"Saved to Google Drive vault: {drive_filename}")
                return True
            else:
                log_error(self.logger, f"Failed to upload to Google Drive vault: {filename}")
                return False
                
        finally:
            # Clean up temporary file
            if temp_path.exists():
                temp_path.unlink()
    
    def create_vault_folder_structure(self) -> bool:
        """Create folder structure in Google Drive vault if needed"""
        if not self.use_google_drive_vault:
            return True
            
        try:
            # Create main folders in Google Drive vault
            folders_to_create = [
                self.obsidian_folder_path,
                *self.settings.entity_folders
            ]
            
            for folder_name in folders_to_create:
                # Check if folder exists, create if not
                existing_folders = self.google_drive_service.list_files_in_folder(
                    self.settings.google_drive_vault_folder_id
                )
                
                folder_exists = any(
                    f['name'] == folder_name and f.get('mimeType') == 'application/vnd.google-apps.folder'
                    for f in existing_folders
                )
                
                if not folder_exists:
                    folder_id = self.google_drive_service.create_folder(
                        folder_name, 
                        self.settings.google_drive_vault_folder_id
                    )
                    if folder_id:
                        self.logger.info(f"📁 Created vault folder in Google Drive: {folder_name}")
            
            return True
            
        except Exception as e:
            log_error(self.logger, "Error creating vault folder structure", e)
            return False
    
    def get_output_path(self, filename: str) -> Path:
        """Get full output path for a file"""
        return self.output_dir / filename
    
    def get_vault_path(self, filename: str) -> Path:
        """Get full vault path for a file"""
        return Path(self.obsidian_vault_path) / self.obsidian_folder_path / filename
    
    def cleanup_old_files(self, days: int = 30):
        """Clean up old processed files"""
        try:
            cutoff_time = time.time() - (days * 24 * 60 * 60)
            cleaned_count = 0
            
            for file_path in self.processed_dir.iterdir():
                if file_path.is_file() and file_path.stat().st_mtime < cutoff_time:
                    file_path.unlink()
                    cleaned_count += 1
            
            if cleaned_count > 0:
                log_success(self.logger, f"Cleaned up {cleaned_count} old files")
                
        except Exception as e:
            log_error(self.logger, "Error during cleanup", e)