"""
Entity detection and management modules for Meeting Processor

This module provides a complete entity management system with:
- AI-powered entity detection from meeting transcripts
- Smart template generation for people, companies, and technologies
- Obsidian vault integration with dynamic dataview queries
- Resource management and error handling
"""

from .detector import EntityDetector
from .manager import ObsidianEntityManager
from .note_manager import EntityNoteManager
from .template_generator import EntityTemplateGenerator
from .ai_context import AIContextExtractor

__all__ = [
    'EntityDetector',
    'ObsidianEntityManager', 
    'EntityNoteManager',
    'EntityTemplateGenerator',
    'AIContextExtractor',
    'EntityProcessingFacade'
]


class EntityProcessingFacade:
    """
    Simplified facade for entity processing that combines all components
    
    This provides a single interface for the most common entity operations,
    hiding the complexity of the underlying modular architecture.
    """
    
    def __init__(self, file_manager, anthropic_client):
        """Initialize the facade with required dependencies"""
        self.file_manager = file_manager
        self.anthropic_client = anthropic_client
        
        # Initialize all components
        self.detector = EntityDetector(anthropic_client)
        self.note_manager = EntityNoteManager(file_manager, anthropic_client)
        self.template_generator = EntityTemplateGenerator(file_manager, anthropic_client)
        self.ai_context = AIContextExtractor(anthropic_client, file_manager)
        
        # Legacy compatibility - ObsidianEntityManager for existing code
        self.obsidian_manager = ObsidianEntityManager(file_manager, anthropic_client)
    
    def process_meeting_entities(self, transcript_content: str, meeting_filename: str, meeting_date: str):
        """
        Complete end-to-end entity processing for a meeting
        
        Args:
            transcript_content: Full meeting transcript
            meeting_filename: Base filename for the meeting
            meeting_date: Meeting date in YYYY-MM-DD format
            
        Returns:
            Dict containing entity links for updating meeting notes
        """
        # Step 1: Detect entities from transcript
        entities = self.detector.detect_entities(transcript_content)
        
        # Step 2: Create entity notes with smart templates
        entity_links = self.note_manager.create_entity_notes(
            entities, meeting_filename, meeting_date
        )
        
        return entity_links
    
    def create_entity_from_template(self, entity_type: str, entity_name: str, 
                                  meeting_filename: str, meeting_date: str) -> str:
        """
        Create a single entity note using smart templates
        
        Args:
            entity_type: 'people', 'companies', or 'technologies'
            entity_name: Name of the entity
            meeting_filename: Source meeting filename
            meeting_date: Meeting date
            
        Returns:
            Wiki link string for the created entity
        """
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
            raise ValueError(f"Unsupported entity type: {entity_type}")
        
        # Save the note using note manager
        safe_name = self.note_manager._sanitize_filename(entity_name)
        folder_map = {
            'people': 'People',
            'companies': 'Companies', 
            'technologies': 'Technologies'
        }
        
        folder = folder_map[entity_type]
        filename = f"{safe_name}.md"
        
        self.note_manager._save_entity_note(folder, filename, content)
        
        return f"[[{folder}/{safe_name}|{entity_name}]]"
    
    def get_entity_context(self, entity_name: str, entity_type: str, meeting_filename: str) -> dict:
        """
        Get AI-enhanced context for an entity
        
        Args:
            entity_name: Name of the entity
            entity_type: Type of entity
            meeting_filename: Source meeting filename
            
        Returns:
            Dictionary containing context information
        """
        return self.ai_context.extract_entity_context(
            entity_name, entity_type, meeting_filename
        )
    
    def get_entity_statistics(self) -> dict:
        """Get statistics about all entity notes"""
        return self.note_manager.get_entity_summary()
    
    def cleanup_orphaned_entities(self) -> int:
        """Find and report orphaned entity notes"""
        return self.note_manager.cleanup_orphaned_entities()
    
    # Legacy compatibility methods
    def create_entity_notes(self, entities: dict, meeting_filename: str, meeting_date: str) -> dict:
        """Legacy compatibility method"""
        return self.obsidian_manager.create_entity_notes(entities, meeting_filename, meeting_date)
    
    def update_meeting_note_with_entities(self, meeting_note_path, entity_links: dict):
        """Legacy compatibility method"""
        return self.obsidian_manager.update_meeting_note_with_entities(meeting_note_path, entity_links)