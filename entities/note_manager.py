"""
Entity Note Manager for Meeting Processor
Handles CRUD operations for entity notes with proper file management and validation
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Set, TYPE_CHECKING
from utils.logger import LoggerMixin, log_success, log_error, log_warning
from utils.resource_manager import get_resource_manager
from .template_generator import EntityTemplateGenerator

if TYPE_CHECKING:
    from core.file_manager import FileManager


class EntityNoteManager(LoggerMixin):
    """Manages entity note creation, updates, and file operations"""
    
    def __init__(self, file_manager: 'FileManager', anthropic_client):
        self.file_manager = file_manager
        self.template_generator = EntityTemplateGenerator(file_manager, anthropic_client)
        self.resource_manager = get_resource_manager()
        
        # Entity folders
        self.entity_folders = {
            'people': 'People',
            'companies': 'Companies', 
            'technologies': 'Technologies'
        }
    
    def create_entity_notes(self, entities: Dict[str, List[str]], 
                          meeting_filename: str, meeting_date: str) -> Dict[str, List[str]]:
        """
        Create entity notes and return link mapping
        
        Args:
            entities: Dict with keys 'people', 'companies', 'technologies'
            meeting_filename: Source meeting filename
            meeting_date: Meeting date
        
        Returns:
            Dict mapping entity types to lists of wiki links
        """
        try:
            entity_links = {
                'people': [],
                'companies': [],
                'technologies': []
            }
            
            # Process each entity type
            for entity_type, entity_list in entities.items():
                if entity_type in self.entity_folders and entity_list:
                    self.logger.info(f"🏷️ Processing {len(entity_list)} {entity_type}")
                    
                    for entity_name in entity_list:
                        if entity_name.strip():  # Skip empty names
                            link = self._create_entity_note(
                                entity_type, entity_name.strip(), 
                                meeting_filename, meeting_date
                            )
                            if link:
                                entity_links[entity_type].append(link)
            
            log_success(self.logger, f"Created entity notes: {sum(len(links) for links in entity_links.values())} total")
            return entity_links
            
        except Exception as e:
            log_error(self.logger, f"Error creating entity notes: {e}")
            return {'people': [], 'companies': [], 'technologies': []}
    
    def _create_entity_note(self, entity_type: str, entity_name: str, 
                          meeting_filename: str, meeting_date: str) -> Optional[str]:
        """Create or update a single entity note"""
        try:
            # Check if entity note already exists
            existing_note = self.find_existing_entity(entity_name, entity_type)
            
            if existing_note:
                # Update existing note with meeting reference
                self._append_meeting_reference(existing_note, meeting_filename, meeting_date)
                safe_name = self._sanitize_filename(entity_name)
                return f"[[{self.entity_folders[entity_type]}/{safe_name}|{entity_name}]]"
            else:
                # Create new note
                return self._create_new_entity_note(entity_type, entity_name, meeting_filename, meeting_date)
                
        except Exception as e:
            log_error(self.logger, f"Error creating {entity_type} note for '{entity_name}': {e}")
            return None
    
    def _create_new_entity_note(self, entity_type: str, entity_name: str, 
                              meeting_filename: str, meeting_date: str) -> Optional[str]:
        """Create a new entity note using appropriate template"""
        try:
            safe_name = self._sanitize_filename(entity_name)
            filename = f"{safe_name}.md"
            
            # Generate content using template generator
            if entity_type == 'people':
                content = self.template_generator.generate_person_template(
                    entity_name, meeting_filename, meeting_date
                )
            elif entity_type == 'companies':
                content = self.template_generator.generate_company_template(
                    entity_name, meeting_filename, meeting_date
                )
            elif entity_type == 'technologies':
                content = self.template_generator.generate_technology_template(
                    entity_name, meeting_filename, meeting_date
                )
            else:
                log_error(self.logger, f"Unknown entity type: {entity_type}")
                return None
            
            # Save the note
            self._save_entity_note(self.entity_folders[entity_type], filename, content)
            
            emoji_map = {'people': '👤', 'companies': '🏢', 'technologies': '💻'}
            self.logger.info(f"{emoji_map.get(entity_type, '📝')} Created new {entity_type[:-1]} note: {entity_name}")
            
            return f"[[{self.entity_folders[entity_type]}/{safe_name}|{entity_name}]]"
            
        except Exception as e:
            log_error(self.logger, f"Error creating new {entity_type} note for '{entity_name}': {e}")
            return None
    
    def _save_entity_note(self, folder: str, filename: str, content: str) -> bool:
        """Save entity note to Obsidian vault with proper error handling"""
        try:
            # Handle both local and Google Drive vaults
            if self.file_manager.use_google_drive_vault:
                return self._save_to_google_drive(folder, filename, content)
            else:
                return self._save_to_local_vault(folder, filename, content)
                
        except Exception as e:
            log_error(self.logger, f"Error saving entity note {folder}/{filename}: {e}")
            return False
    
    def _save_to_local_vault(self, folder: str, filename: str, content: str) -> bool:
        """Save entity note to local vault"""
        try:
            folder_path = Path(self.file_manager.obsidian_vault_path) / folder
            folder_path.mkdir(parents=True, exist_ok=True)
            
            file_path = folder_path / filename
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            log_success(self.logger, f"Created AI-enhanced entity note: {folder}/{filename}")
            return True
            
        except Exception as e:
            log_error(self.logger, f"Error saving to local vault {folder}/{filename}: {e}")
            return False
    
    def _save_to_google_drive(self, folder: str, filename: str, content: str) -> bool:
        """Save entity note to Google Drive vault"""
        try:
            # This would integrate with the vault initializer's Google Drive upload logic
            # For now, log the action
            log_success(self.logger, f"Would save to Google Drive: {folder}/{filename}")
            return True
            
        except Exception as e:
            log_error(self.logger, f"Error saving to Google Drive {folder}/{filename}: {e}")
            return False
    
    def _append_meeting_reference(self, note_path: Path, meeting_filename: str, meeting_date: str) -> bool:
        """Append meeting reference to existing entity note"""
        try:
            with open(note_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            meeting_ref = f"- [[{meeting_filename}]] - {meeting_date}"
            
            # Look for Meeting References section
            if "## Meeting References" in content:
                # Find the section and append
                lines = content.split('\n')
                ref_index = -1
                
                for i, line in enumerate(lines):
                    if line.strip() == "## Meeting References":
                        ref_index = i
                        break
                
                if ref_index != -1:
                    # Find where to insert (after the header, before next section or end)
                    insert_index = ref_index + 1
                    
                    # Skip to end of existing references
                    while (insert_index < len(lines) and 
                           lines[insert_index].strip() and 
                           not lines[insert_index].startswith('##')):
                        insert_index += 1
                    
                    # Check if this meeting is already referenced
                    existing_refs = '\n'.join(lines[ref_index:insert_index])
                    if meeting_filename not in existing_refs:
                        lines.insert(insert_index, meeting_ref)
                        
                        updated_content = '\n'.join(lines)
                        
                        with open(note_path, 'w', encoding='utf-8') as f:
                            f.write(updated_content)
                        
                        self.logger.debug(f"📝 Added meeting reference to {note_path.name}")
                        return True
                    else:
                        self.logger.debug(f"Meeting already referenced in {note_path.name}")
                        return True
            
            return False
            
        except Exception as e:
            log_error(self.logger, f"Error appending meeting reference to {note_path}: {e}")
            return False
    
    def find_existing_entity(self, entity_name: str, entity_type: str) -> Optional[Path]:
        """Find existing entity note by name and type"""
        try:
            if entity_type not in self.entity_folders:
                return None
            
            folder_name = self.entity_folders[entity_type]
            entity_dir = Path(self.file_manager.obsidian_vault_path) / folder_name
            
            if not entity_dir.exists():
                return None
            
            # Try exact filename match first
            safe_name = self._sanitize_filename(entity_name)
            exact_match = entity_dir / f"{safe_name}.md"
            if exact_match.exists():
                return exact_match
            
            # Try case-insensitive search
            entity_name_lower = entity_name.lower()
            for note_file in entity_dir.glob("*.md"):
                # Extract name from filename and compare
                note_name = note_file.stem.replace('-', ' ').lower()
                if note_name == entity_name_lower:
                    return note_file
            
            return None
            
        except Exception as e:
            log_error(self.logger, f"Error finding existing entity '{entity_name}': {e}")
            return None
    
    def bulk_update_entity_notes(self, updates: Dict[str, Dict[str, str]]) -> int:
        """
        Bulk update entity notes with new information
        
        Args:
            updates: Dict mapping entity paths to update data
            
        Returns:
            Number of successfully updated notes
        """
        try:
            updated_count = 0
            
            for entity_path_str, update_data in updates.items():
                entity_path = Path(entity_path_str)
                
                if self._update_entity_note(entity_path, update_data):
                    updated_count += 1
            
            if updated_count > 0:
                log_success(self.logger, f"Bulk updated {updated_count} entity notes")
            
            return updated_count
            
        except Exception as e:
            log_error(self.logger, f"Error in bulk update: {e}")
            return 0
    
    def _update_entity_note(self, entity_path: Path, update_data: Dict[str, str]) -> bool:
        """Update a single entity note with new data"""
        try:
            if not entity_path.exists():
                log_warning(self.logger, f"Entity note not found: {entity_path}")
                return False
            
            with open(entity_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Update frontmatter fields
            for field, value in update_data.items():
                if field in ['role', 'department', 'company', 'industry', 'status']:
                    content = self._update_frontmatter_field(content, field, value)
            
            # Update last-updated timestamp
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            content = self._update_frontmatter_field(content, 'last-updated', timestamp)
            
            with open(entity_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            self.logger.debug(f"📝 Updated entity note: {entity_path.name}")
            return True
            
        except Exception as e:
            log_error(self.logger, f"Error updating entity note {entity_path}: {e}")
            return False
    
    def _update_frontmatter_field(self, content: str, field: str, value: str) -> str:
        """Update a field in YAML frontmatter"""
        try:
            lines = content.split('\n')
            
            # Find frontmatter boundaries
            if not lines[0].strip() == '---':
                return content
            
            end_index = -1
            for i in range(1, len(lines)):
                if lines[i].strip() == '---':
                    end_index = i
                    break
            
            if end_index == -1:
                return content
            
            # Look for existing field
            field_pattern = f"{field}:"
            field_found = False
            
            for i in range(1, end_index):
                if lines[i].strip().startswith(field_pattern):
                    lines[i] = f"{field}: {value}"
                    field_found = True
                    break
            
            # Add field if not found
            if not field_found:
                lines.insert(end_index, f"{field}: {value}")
            
            return '\n'.join(lines)
            
        except Exception as e:
            log_error(self.logger, f"Error updating frontmatter field '{field}': {e}")
            return content
    
    def cleanup_orphaned_entities(self) -> int:
        """
        Find and remove entity notes that are no longer referenced
        
        Returns:
            Number of orphaned entities found
        """
        try:
            orphaned_count = 0
            
            for entity_type, folder_name in self.entity_folders.items():
                entity_dir = Path(self.file_manager.obsidian_vault_path) / folder_name
                
                if not entity_dir.exists():
                    continue
                
                # Get all entity files
                entity_files = list(entity_dir.glob("*.md"))
                
                # Check each entity for references
                for entity_file in entity_files:
                    if self._is_entity_orphaned(entity_file):
                        orphaned_count += 1
                        self.logger.info(f"🗑️ Found orphaned entity: {entity_file.name}")
                        # Note: Not actually deleting here, just counting
            
            return orphaned_count
            
        except Exception as e:
            log_error(self.logger, f"Error checking for orphaned entities: {e}")
            return 0
    
    def _is_entity_orphaned(self, entity_file: Path) -> bool:
        """Check if an entity note is orphaned (no references)"""
        try:
            # Simple check: if it has no meeting references, it might be orphaned
            with open(entity_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Look for meeting references section
            if "## Meeting References" not in content:
                return True
            
            # Check if there are actual references
            lines = content.split('\n')
            in_refs_section = False
            has_refs = False
            
            for line in lines:
                if line.strip() == "## Meeting References":
                    in_refs_section = True
                    continue
                elif line.startswith('##') and in_refs_section:
                    break
                elif in_refs_section and line.strip().startswith('- [['):
                    has_refs = True
                    break
            
            return not has_refs
            
        except Exception as e:
            log_error(self.logger, f"Error checking if entity is orphaned {entity_file}: {e}")
            return False
    
    def get_entity_summary(self) -> Dict[str, int]:
        """Get summary statistics for all entities"""
        try:
            summary = {}
            
            for entity_type, folder_name in self.entity_folders.items():
                entity_dir = Path(self.file_manager.obsidian_vault_path) / folder_name
                
                if entity_dir.exists():
                    entity_files = list(entity_dir.glob("*.md"))
                    summary[entity_type] = len(entity_files)
                else:
                    summary[entity_type] = 0
            
            return summary
            
        except Exception as e:
            log_error(self.logger, f"Error getting entity summary: {e}")
            return {entity_type: 0 for entity_type in self.entity_folders.keys()}
    
    def _sanitize_filename(self, name: str) -> str:
        """Sanitize a name for use as a filename"""
        # Remove special characters, replace spaces with hyphens
        safe_name = re.sub(r'[^\w\s-]', '', name)
        safe_name = re.sub(r'\s+', '-', safe_name)
        return safe_name.strip('-')