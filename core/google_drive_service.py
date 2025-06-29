"""
Google Drive integration for Meeting Processor
Handles file monitoring, download, and upload operations
"""

import io
import os
import time
from pathlib import Path
from typing import List, Dict, Optional, Set
from datetime import datetime, timedelta

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

from utils.logger import LoggerMixin


class GoogleDriveService(LoggerMixin):
    """Google Drive API service for file operations"""
    
    SCOPES = ['https://www.googleapis.com/auth/drive']
    
    def __init__(self, credentials_path: str, token_path: str, 
                 input_folder_id: str, output_folder_id: str):
        """
        Initialize Google Drive service
        
        Args:
            credentials_path: Path to credentials.json file
            token_path: Path to store token.json file
            input_folder_id: Google Drive folder ID for input MP4 files
            output_folder_id: Google Drive folder ID for output files
        """
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.input_folder_id = input_folder_id
        self.output_folder_id = output_folder_id
        self.service = None
        self.processed_files: Set[str] = set()
        self.last_check_time = datetime.now() - timedelta(hours=1)
        
        self._authenticate()
    
    def _authenticate(self):
        """Authenticate and create Google Drive service"""
        creds = None
        
        # Load existing token
        if os.path.exists(self.token_path):
            creds = Credentials.from_authorized_user_file(self.token_path, self.SCOPES)
        
        # If there are no valid credentials, authenticate
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(self.credentials_path):
                    raise FileNotFoundError(
                        f"Google Drive credentials file not found at {self.credentials_path}. "
                        "Please download credentials.json from Google Cloud Console."
                    )
                
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path, self.SCOPES
                )
                creds = flow.run_local_server(port=0)
            
            # Save credentials for next run
            with open(self.token_path, 'w') as token:
                token.write(creds.to_json())
        
        self.service = build('drive', 'v3', credentials=creds)
        self.logger.info("✅ Google Drive service authenticated")
    
    def check_for_new_files(self) -> List[Dict]:
        """
        Check for new MP4 files in the input folder
        
        Returns:
            List of file metadata dictionaries
        """
        try:
            # Query for MP4 files in the input folder modified since last check
            query = (
                f"'{self.input_folder_id}' in parents "
                f"and mimeType contains 'video/mp4' "
                f"and trashed = false "
                f"and modifiedTime > '{self.last_check_time.isoformat()}Z'"
            )
            
            results = self.service.files().list(
                q=query,
                pageSize=100,
                fields="nextPageToken, files(id, name, size, modifiedTime, mimeType)"
            ).execute()
            
            files = results.get('files', [])
            new_files = []
            
            for file_info in files:
                file_id = file_info['id']
                if file_id not in self.processed_files:
                    new_files.append(file_info)
                    self.logger.info(f"📁 New MP4 found: {file_info['name']}")
            
            self.last_check_time = datetime.now()
            return new_files
            
        except HttpError as error:
            self.logger.error(f"Error checking for new files: {error}")
            return []
    
    def download_file(self, file_id: str, file_name: str, local_path: Path) -> bool:
        """
        Download a file from Google Drive
        
        Args:
            file_id: Google Drive file ID
            file_name: Name of the file
            local_path: Local path to save the file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            self.logger.info(f"⬇️ Downloading {file_name} from Google Drive...")
            
            # Get file metadata to check size
            file_metadata = self.service.files().get(fileId=file_id).execute()
            file_size = int(file_metadata.get('size', 0))
            file_size_mb = file_size / (1024 * 1024)
            
            self.logger.info(f"📊 File size: {file_size_mb:.1f}MB")
            
            # Request file content
            request = self.service.files().get_media(fileId=file_id)
            
            # Create local directory if it doesn't exist
            local_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Download file
            with io.BytesIO() as fh:
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while done is False:
                    status, done = downloader.next_chunk()
                    if status:
                        progress = int(status.progress() * 100)
                        self.logger.debug(f"⬇️ Download progress: {progress}%")
                
                # Write to local file
                with open(local_path, 'wb') as f:
                    f.write(fh.getvalue())
            
            self.logger.info(f"✅ Downloaded: {file_name}")
            return True
            
        except HttpError as error:
            self.logger.error(f"Error downloading {file_name}: {error}")
            return False
        except Exception as error:
            self.logger.error(f"Unexpected error downloading {file_name}: {error}")
            return False
    
    def upload_file(self, local_path: Path, drive_filename: str, 
                   parent_folder_id: Optional[str] = None) -> Optional[str]:
        """
        Upload a file to Google Drive
        
        Args:
            local_path: Local file path
            drive_filename: Name for the file in Google Drive
            parent_folder_id: Parent folder ID (uses output folder if not specified)
            
        Returns:
            File ID if successful, None otherwise
        """
        try:
            folder_id = parent_folder_id or self.output_folder_id
            
            self.logger.info(f"⬆️ Uploading {drive_filename} to Google Drive...")
            
            # Determine MIME type based on file extension
            suffix = local_path.suffix.lower()
            mime_type_map = {
                '.json': 'application/json',
                '.md': 'text/markdown',
                '.txt': 'text/plain',
                '.mp4': 'video/mp4',
                '.flac': 'audio/flac'
            }
            mime_type = mime_type_map.get(suffix, 'application/octet-stream')
            
            # File metadata
            file_metadata = {
                'name': drive_filename,
                'parents': [folder_id]
            }
            
            # Upload file
            media = MediaFileUpload(str(local_path), mimetype=mime_type)
            file = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()
            
            file_id = file.get('id')
            self.logger.info(f"✅ Uploaded: {drive_filename} (ID: {file_id})")
            return file_id
            
        except HttpError as error:
            self.logger.error(f"Error uploading {drive_filename}: {error}")
            return None
        except Exception as error:
            self.logger.error(f"Unexpected error uploading {drive_filename}: {error}")
            return None
    
    def move_file_to_processed(self, file_id: str, processed_folder_id: str) -> bool:
        """
        Move a file to the processed folder
        
        Args:
            file_id: Google Drive file ID
            processed_folder_id: Processed folder ID
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Get current parents
            file = self.service.files().get(fileId=file_id, fields='parents').execute()
            previous_parents = ",".join(file.get('parents'))
            
            # Move file
            file = self.service.files().update(
                fileId=file_id,
                addParents=processed_folder_id,
                removeParents=previous_parents,
                fields='id, parents'
            ).execute()
            
            self.logger.info(f"📦 Moved file to processed folder (ID: {file_id})")
            return True
            
        except HttpError as error:
            self.logger.error(f"Error moving file to processed folder: {error}")
            return False
    
    def mark_file_processed(self, file_id: str):
        """Mark a file as processed to avoid reprocessing"""
        self.processed_files.add(file_id)
    
    def is_file_processed(self, file_id: str) -> bool:
        """Check if a file has been processed"""
        return file_id in self.processed_files
    
    def create_folder(self, folder_name: str, parent_folder_id: str) -> Optional[str]:
        """
        Create a folder in Google Drive
        
        Args:
            folder_name: Name of the folder to create
            parent_folder_id: Parent folder ID
            
        Returns:
            Folder ID if successful, None otherwise
        """
        try:
            file_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [parent_folder_id]
            }
            
            folder = self.service.files().create(
                body=file_metadata,
                fields='id'
            ).execute()
            
            folder_id = folder.get('id')
            self.logger.info(f"📁 Created folder: {folder_name} (ID: {folder_id})")
            return folder_id
            
        except HttpError as error:
            self.logger.error(f"Error creating folder {folder_name}: {error}")
            return None
    
    def list_files_in_folder(self, folder_id: str, mime_type: Optional[str] = None) -> List[Dict]:
        """
        List files in a Google Drive folder
        
        Args:
            folder_id: Folder ID
            mime_type: Optional MIME type filter
            
        Returns:
            List of file metadata dictionaries
        """
        try:
            query = f"'{folder_id}' in parents and trashed = false"
            if mime_type:
                query += f" and mimeType = '{mime_type}'"
            
            results = self.service.files().list(
                q=query,
                pageSize=1000,
                fields="nextPageToken, files(id, name, size, modifiedTime, mimeType)"
            ).execute()
            
            return results.get('files', [])
            
        except HttpError as error:
            self.logger.error(f"Error listing files in folder: {error}")
            return []
    
    def get_service_info(self) -> Dict:
        """Get service information for logging"""
        return {
            'authenticated': self.service is not None,
            'input_folder_id': self.input_folder_id,
            'output_folder_id': self.output_folder_id,
            'processed_files_count': len(self.processed_files),
            'last_check_time': self.last_check_time.isoformat()
        }