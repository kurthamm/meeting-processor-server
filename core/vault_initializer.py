"""
Vault Initializer for Meeting Processor
Handles automatic creation and syncing of Obsidian vaults with proper folder structure,
templates, and configuration files for both local and Google Drive storage modes.
"""

import json
import shutil
from pathlib import Path
from typing import Dict, List, Optional, TYPE_CHECKING
from utils.logger import LoggerMixin, log_success, log_error, log_warning
from utils.resource_manager import temp_file

if TYPE_CHECKING:
    from core.google_drive_service import GoogleDriveService


class VaultInitializer(LoggerMixin):
    """Handles automatic vault creation, validation, and syncing"""
    
    def __init__(self, settings, google_drive_service: Optional['GoogleDriveService'] = None):
        self.settings = settings
        self.google_drive_service = google_drive_service
        self.vault_path = Path(settings.obsidian_vault_path)
        self.vault_meta_path = Path(__file__).parent.parent / "obsidian-vault-meta"
        
        # Determine if we're using Google Drive vault
        self.use_google_drive_vault = (
            settings.storage_mode == 'google_drive' and 
            hasattr(settings, 'google_drive_vault_folder_id') and
            settings.google_drive_vault_folder_id and
            google_drive_service is not None
        )
        
        # Required vault structure
        self.required_folders = [
            'Meetings',
            'Tasks', 
            'People',
            'Companies',
            'Technologies',
            'Templates',
            'Meta',
            'Meta/dashboards',
            '.obsidian'
        ]
        
        # Required files with their source paths
        self.required_files = {
            'Templates/meeting-template.md': 'templates/meeting-template.md',
            'Templates/task-template.md': 'templates/task-template.md',
            'Templates/person-template.md': 'templates/person-template.md',
            'Templates/company-template.md': 'templates/company-template.md',
            'Templates/technology-template.md': 'templates/technology-template.md',
            'Templates/project-template.md': 'templates/project-template.md',
            'Templates/solution-template.md': 'templates/solution-template.md',
            'Templates/knowledge-template.md': 'templates/knowledge-template.md',
            'Meta/dashboards/🧠-Command-Center.md': 'dashboards/🧠-Command-Center.md',
            'Meta/dashboards/Task-Dashboard.md': 'dashboards/Task-Dashboard.md'
        }
        
        # Obsidian configuration files
        self.obsidian_config = {
            'app.json': self._get_app_config(),
            'appearance.json': self._get_appearance_config(),
            'core-plugins.json': self._get_core_plugins_config(),
            'community-plugins.json': self._get_community_plugins_config(),
            'workspace.json': self._get_workspace_config()
        }

    def initialize_vault(self) -> bool:
        """
        Initialize vault with proper structure and configuration.
        Returns True if successful, False otherwise.
        """
        try:
            self.logger.info("🏗️ Initializing Obsidian vault...")
            
            # Check vault completeness first
            vault_status = self._analyze_vault_completeness()
            
            if vault_status['is_complete']:
                log_success(f"✅ Vault at {self.vault_path} is already complete")
                return True
            
            # Create vault structure
            success = self._create_vault_structure(vault_status)
            
            if success:
                log_success(f"🎉 Vault successfully initialized at {self.vault_path}")
                self._log_vault_summary()
                return True
            else:
                log_error("❌ Failed to initialize vault")
                return False
                
        except Exception as e:
            log_error(f"💥 Error initializing vault: {str(e)}")
            return False

    def _analyze_vault_completeness(self) -> Dict:
        """Analyze current vault state and identify missing components"""
        status = {
            'exists': False,
            'is_complete': True,
            'missing_folders': [],
            'missing_files': [],
            'missing_config': [],
            'has_obsidian_config': False
        }
        
        if self.use_google_drive_vault:
            # For Google Drive vaults, we'll assume incomplete and create structure
            status['exists'] = True  # Google Drive folder exists
            status['is_complete'] = False
            status['missing_folders'] = self.required_folders.copy()
            status['missing_files'] = list(self.required_files.keys())
            status['missing_config'] = list(self.obsidian_config.keys())
            self.logger.info("🌐 Google Drive vault mode - will create complete structure")
        else:
            # Local vault analysis
            if not self.vault_path.exists():
                self.logger.info(f"📁 Vault directory {self.vault_path} does not exist")
                status['is_complete'] = False
                status['missing_folders'] = self.required_folders.copy()
                status['missing_files'] = list(self.required_files.keys())
                status['missing_config'] = list(self.obsidian_config.keys())
            else:
                status['exists'] = True
                self.logger.info(f"📁 Analyzing existing vault at {self.vault_path}")
                
                # Check folders
                for folder in self.required_folders:
                    folder_path = self.vault_path / folder
                    if not folder_path.exists():
                        status['missing_folders'].append(folder)
                        status['is_complete'] = False
                
                # Check files
                for vault_file in self.required_files.keys():
                    file_path = self.vault_path / vault_file
                    if not file_path.exists():
                        status['missing_files'].append(vault_file)
                        status['is_complete'] = False
                
                # Check Obsidian config
                obsidian_dir = self.vault_path / '.obsidian'
                if obsidian_dir.exists():
                    status['has_obsidian_config'] = True
                    for config_file in self.obsidian_config.keys():
                        config_path = obsidian_dir / config_file
                        if not config_path.exists():
                            status['missing_config'].append(config_file)
                            status['is_complete'] = False
                else:
                    status['missing_config'] = list(self.obsidian_config.keys())
                    status['is_complete'] = False
        
        # Log analysis results
        if status['missing_folders']:
            log_warning(f"📂 Missing folders: {', '.join(status['missing_folders'])}")
        if status['missing_files']:
            log_warning(f"📄 Missing files: {', '.join(status['missing_files'])}")
        if status['missing_config']:
            log_warning(f"⚙️ Missing config: {', '.join(status['missing_config'])}")
            
        return status

    def _create_vault_structure(self, vault_status: Dict) -> bool:
        """Create missing vault components based on analysis"""
        try:
            # Create base vault directory for local mode
            if not self.use_google_drive_vault and not self.vault_path.exists():
                self.vault_path.mkdir(parents=True, exist_ok=True)
                log_success(f"📁 Created vault directory: {self.vault_path}")
            
            # Create missing folders
            if vault_status['missing_folders']:
                self._create_folders(vault_status['missing_folders'])
            
            # Create missing files
            if vault_status['missing_files']:
                self._create_files(vault_status['missing_files'])
            
            # Create missing Obsidian configuration
            if vault_status['missing_config']:
                self._create_obsidian_config(vault_status['missing_config'])
            
            return True
            
        except Exception as e:
            log_error(f"💥 Error creating vault structure: {str(e)}")
            return False

    def _create_folders(self, missing_folders: List[str]) -> None:
        """Create missing folders in vault"""
        for folder in missing_folders:
            if self.use_google_drive_vault:
                # For Google Drive, create folder structure
                parent_id = self.settings.google_drive_vault_folder_id
                folder_parts = folder.split('/')
                
                current_parent = parent_id
                for part in folder_parts:
                    # Check if folder exists first
                    existing_folders = self.google_drive_service.list_files_in_folder(
                        current_parent, 'application/vnd.google-apps.folder'
                    )
                    
                    existing_folder = next(
                        (f for f in existing_folders if f['name'] == part), 
                        None
                    )
                    
                    if existing_folder:
                        current_parent = existing_folder['id']
                        self.logger.info(f"📁 Folder exists: {part}")
                    else:
                        # Create the folder
                        folder_id = self.google_drive_service.create_folder(part, current_parent)
                        if folder_id:
                            current_parent = folder_id
                            log_success(f"🌐 Created Google Drive folder: {part}")
                        else:
                            log_error(f"❌ Failed to create Google Drive folder: {part}")
                            break
            else:
                # Local folder creation
                folder_path = self.vault_path / folder
                folder_path.mkdir(parents=True, exist_ok=True)
                log_success(f"📂 Created folder: {folder}")

    def _create_files(self, missing_files: List[str]) -> None:
        """Create missing template and dashboard files"""
        for vault_file in missing_files:
            source_file = self.required_files[vault_file]
            source_path = self.vault_meta_path / source_file
            
            if not source_path.exists():
                log_warning(f"⚠️ Source template not found: {source_path}")
                continue
            
            # Read and process template content
            content = source_path.read_text(encoding='utf-8')
            processed_content = self._process_template_content(content, vault_file)
            
            if self.use_google_drive_vault:
                # For Google Drive, upload the file to the appropriate folder
                self._upload_file_to_google_drive(vault_file, processed_content)
            else:
                # Local file creation
                target_path = self.vault_path / vault_file
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_text(processed_content, encoding='utf-8')
                log_success(f"📄 Created file: {vault_file}")

    def _upload_file_to_google_drive(self, vault_file: str, content: str) -> None:
        """Upload a file to Google Drive vault with proper resource management"""
        try:
            # Use resource-managed temporary file
            with temp_file(suffix='.md', prefix='vault_upload_') as temp_file_path:
                # Write content to temporary file
                temp_file_path.write_text(content, encoding='utf-8')
                
                # Find the correct parent folder ID for this file
                parent_folder_id = self._get_google_drive_folder_id_for_file(vault_file)
                
                if parent_folder_id:
                    # Upload to Google Drive
                    file_name = Path(vault_file).name
                    file_id = self.google_drive_service.upload_file(
                        temp_file_path, parent_folder_id, file_name
                    )
                    
                    if file_id:
                        log_success(f"🌐 Uploaded to Google Drive: {vault_file}")
                    else:
                        log_error(f"❌ Failed to upload: {vault_file}")
                else:
                    log_error(f"❌ Could not find parent folder for: {vault_file}")
            
        except Exception as e:
            log_error(f"💥 Error uploading {vault_file} to Google Drive: {str(e)}")

    def _get_google_drive_folder_id_for_file(self, vault_file: str) -> Optional[str]:
        """Get the Google Drive folder ID for a specific vault file"""
        try:
            folder_path = str(Path(vault_file).parent)
            if folder_path == '.':
                return self.settings.google_drive_vault_folder_id
            
            # Navigate to the correct folder
            current_parent = self.settings.google_drive_vault_folder_id
            folder_parts = folder_path.split('/')
            
            for part in folder_parts:
                existing_folders = self.google_drive_service.list_files_in_folder(
                    current_parent, 'application/vnd.google-apps.folder'
                )
                
                existing_folder = next(
                    (f for f in existing_folders if f['name'] == part), 
                    None
                )
                
                if existing_folder:
                    current_parent = existing_folder['id']
                else:
                    log_error(f"❌ Folder not found: {part}")
                    return None
            
            return current_parent
            
        except Exception as e:
            log_error(f"💥 Error finding folder for {vault_file}: {str(e)}")
            return None

    def _create_obsidian_config(self, missing_config: List[str]) -> None:
        """Create missing Obsidian configuration files"""
        if self.use_google_drive_vault:
            # For Google Drive vaults, create .obsidian folder and upload config files
            self._create_obsidian_config_google_drive(missing_config)
            return
        
        obsidian_dir = self.vault_path / '.obsidian'
        obsidian_dir.mkdir(exist_ok=True)
        
        for config_file in missing_config:
            config_path = obsidian_dir / config_file
            config_content = self.obsidian_config[config_file]
            
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config_content, f, indent=2)
            
            log_success(f"⚙️ Created config: {config_file}")

    def _create_obsidian_config_google_drive(self, missing_config: List[str]) -> None:
        """Create Obsidian configuration files in Google Drive"""
        try:
            # First, ensure .obsidian folder exists
            vault_root_id = self.settings.google_drive_vault_folder_id
            existing_folders = self.google_drive_service.list_files_in_folder(
                vault_root_id, 'application/vnd.google-apps.folder'
            )
            
            obsidian_folder = next(
                (f for f in existing_folders if f['name'] == '.obsidian'), 
                None
            )
            
            if not obsidian_folder:
                obsidian_folder_id = self.google_drive_service.create_folder('.obsidian', vault_root_id)
                if not obsidian_folder_id:
                    log_error("❌ Failed to create .obsidian folder in Google Drive")
                    return
                log_success("📁 Created .obsidian folder in Google Drive")
            else:
                obsidian_folder_id = obsidian_folder['id']
                self.logger.info("📁 .obsidian folder exists in Google Drive")
            
            # Create each missing config file
            for config_file in missing_config:
                self._upload_obsidian_config_file(config_file, obsidian_folder_id)
                
        except Exception as e:
            log_error(f"💥 Error creating Obsidian config in Google Drive: {str(e)}")

    def _upload_obsidian_config_file(self, config_file: str, obsidian_folder_id: str) -> None:
        """Upload a single Obsidian config file to Google Drive with proper resource management"""
        try:
            config_content = self.obsidian_config[config_file]
            
            # Use resource-managed temporary file
            with temp_file(suffix='.json', prefix='obsidian_config_') as temp_file_path:
                # Write JSON content to temporary file
                with open(temp_file_path, 'w', encoding='utf-8') as f:
                    json.dump(config_content, f, indent=2)
                
                # Upload to Google Drive
                file_id = self.google_drive_service.upload_file(
                    temp_file_path, obsidian_folder_id, config_file
                )
                
                if file_id:
                    log_success(f"🌐 Uploaded Obsidian config: {config_file}")
                else:
                    log_error(f"❌ Failed to upload config: {config_file}")
            
        except Exception as e:
            log_error(f"💥 Error uploading config {config_file}: {str(e)}")

    def _process_template_content(self, content: str, file_path: str) -> str:
        """Process template content with user-specific variables"""
        # Replace template variables
        replacements = {
            '{{user}}': self.settings.obsidian_user_name,
            '{{company}}': self.settings.obsidian_company_name,
            '{{date}}': '{{date}}',  # Keep template syntax for Obsidian
            '{{time}}': '{{time}}'   # Keep template syntax for Obsidian
        }
        
        processed_content = content
        for placeholder, value in replacements.items():
            processed_content = processed_content.replace(placeholder, value)
        
        return processed_content

    def _log_vault_summary(self) -> None:
        """Log summary of vault structure"""
        self.logger.info("📋 Vault Structure Summary:")
        self.logger.info(f"   📍 Location: {self.vault_path}")
        self.logger.info(f"   🌐 Google Drive Mode: {self.use_google_drive_vault}")
        self.logger.info(f"   📂 Folders: {len(self.required_folders)}")
        self.logger.info(f"   📄 Template Files: {len(self.required_files)}")
        self.logger.info(f"   ⚙️ Config Files: {len(self.obsidian_config)}")

    # Obsidian Configuration Generators
    def _get_app_config(self) -> Dict:
        """Core Obsidian app configuration"""
        return {
            "legacyEditor": False,
            "livePreview": True,
            "defaultViewMode": "preview",
            "attachmentFolderPath": "./",
            "newLinkFormat": "relative",
            "useMarkdownLinks": True,
            "newFileLocation": "current",
            "promptDelete": True,
            "showLineNumber": True,
            "spellcheck": True,
            "strictLineBreaks": False,
            "foldHeading": True,
            "foldIndent": True,
            "showFrontmatter": True,
            "alwaysUpdateLinks": True
        }

    def _get_appearance_config(self) -> Dict:
        """Obsidian appearance configuration"""
        return {
            "theme": "moonstone",
            "cssTheme": "",
            "baseFontSize": 16,
            "interfaceFontFamily": "",
            "textFontFamily": "",
            "monospaceFontFamily": "",
            "showViewHeader": True,
            "showInlineTitle": True,
            "showUnsavedIndicator": True,
            "translucency": False
        }

    def _get_core_plugins_config(self) -> List[str]:
        """Essential Obsidian core plugins"""
        return [
            "file-explorer",
            "global-search", 
            "switcher",
            "graph",
            "backlink",
            "canvas",
            "outgoing-link",
            "tag-pane",
            "page-preview",
            "daily-notes",
            "templates",
            "note-composer",
            "command-palette",
            "slash-command",
            "editor-status",
            "starred",
            "markdown-importer",
            "zk-prefixer",
            "random-note",
            "outline",
            "word-count",
            "slides",
            "audio-recorder",
            "workspaces",
            "file-recovery",
            "publish",
            "sync"
        ]

    def _get_community_plugins_config(self) -> Dict:
        """Community plugins configuration (empty by default)"""
        return {
            "plugins": {
                "dataview": True
            },
            "enabledPlugins": [
                "dataview"
            ]
        }

    def _get_workspace_config(self) -> Dict:
        """Default workspace layout"""
        return {
            "main": {
                "id": "main-workspace",
                "type": "split",
                "children": [
                    {
                        "id": "sidebar-left",
                        "type": "split",
                        "children": [
                            {
                                "id": "file-explorer",
                                "type": "leaf",
                                "state": {
                                    "type": "file-explorer",
                                    "state": {}
                                }
                            }
                        ],
                        "direction": "vertical"
                    },
                    {
                        "id": "main-area",
                        "type": "split",
                        "children": [
                            {
                                "id": "welcome-tab",
                                "type": "leaf",
                                "state": {
                                    "type": "markdown",
                                    "state": {
                                        "file": "Meta/dashboards/🧠-Command-Center.md",
                                        "mode": "preview"
                                    }
                                }
                            }
                        ],
                        "direction": "vertical"
                    }
                ],
                "direction": "horizontal"
            },
            "left": {
                "id": "left-sidebar",
                "type": "split",
                "children": [],
                "direction": "vertical"
            },
            "right": {
                "id": "right-sidebar", 
                "type": "split",
                "children": [],
                "direction": "vertical"
            },
            "active": "welcome-tab",
            "lastOpenFiles": [
                "Meta/dashboards/🧠-Command-Center.md"
            ]
        }