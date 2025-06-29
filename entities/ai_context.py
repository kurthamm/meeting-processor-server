"""
AI Context Extraction for Entity Management
Extracts intelligent context about entities from meeting transcripts
"""

import os
from pathlib import Path
from typing import Dict, Optional, TYPE_CHECKING
from utils.logger import LoggerMixin

if TYPE_CHECKING:
    from core.file_manager import FileManager


class AIContextExtractor(LoggerMixin):
    """Extracts AI-powered context for entities"""
    
    def __init__(self, anthropic_client, file_manager: 'FileManager'):
        self.anthropic_client = anthropic_client
        self.file_manager = file_manager
        self.model = "claude-3-5-sonnet-20241022"
        self.employer = self._find_employer_context()
    
    def _find_employer_context(self) -> str:
        """Find the user's current employer from environment or Obsidian vault"""
        try:
            # First check environment variable
            company_from_env = os.getenv('OBSIDIAN_COMPANY_NAME', '')
            if company_from_env:
                self.logger.info(f"🏢 Using employer from environment: {company_from_env}")
                return company_from_env
            
            # Fallback to searching vault
            companies_path = Path(self.file_manager.obsidian_vault_path) / "Companies"
            if not companies_path.exists():
                return ""
            
            # Look for company marked as current employer
            for company_file in companies_path.glob("*.md"):
                try:
                    with open(company_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                        if "**Current Employer:** Yes" in content:
                            company_name = company_file.stem.replace('-', ' ')
                            self.logger.info(f"🏢 Found employer context: {company_name}")
                            return company_name
                except Exception as e:
                    self.logger.debug(f"Error reading company file {company_file}: {e}")
                    continue
            
            return ""
            
        except Exception as e:
            self.logger.error(f"Error finding employer context: {e}")
            return ""
    
    def extract_entity_context(self, entity_name: str, entity_type: str, meeting_filename: str) -> Dict[str, any]:
        """Extract context for an entity from meeting content"""
        if entity_type == 'people':
            return self.get_person_context(entity_name, meeting_filename)
        elif entity_type == 'companies':
            return self.get_company_context(entity_name, meeting_filename)
        elif entity_type == 'technologies':
            return self.get_technology_context(entity_name, meeting_filename)
        else:
            return self._get_default_context(entity_type)
    
    def get_person_context(self, person_name: str, meeting_filename: str) -> Dict[str, str]:
        """Extract AI context about a person"""
        if not self.anthropic_client:
            return self._get_default_person_context()
        
        try:
            # Read the transcript from the meeting file
            meeting_path = Path(self.file_manager.output_dir) / f"{meeting_filename}.md"
            transcript_snippet = ""
            
            if meeting_path.exists():
                with open(meeting_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # Extract a snippet around person's name
                    name_index = content.lower().find(person_name.lower())
                    if name_index > 0:
                        start = max(0, name_index - 500)
                        end = min(len(content), name_index + 500)
                        transcript_snippet = content[start:end]
            
            prompt = f"""Based on this meeting transcript snippet, extract context about {person_name}.
Focus on their role, company affiliation, and relationship to {self.employer if self.employer else 'the organization'}.

Transcript snippet:
{transcript_snippet}

Provide brief, factual responses for:
1. Role/Title
2. Company/Organization
3. Relationship to {self.employer if self.employer else 'us'}
4. Authority level
5. Department
6. Key projects mentioned
7. Any additional relevant notes

Format as JSON."""

            response = self.anthropic_client.messages.create(
                model=self.model,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}]
            )
            
            # Parse response and extract relevant fields
            context = self._parse_context_response(response.content[0].text)
            context['employer'] = self.employer
            context['summary'] = f"{person_name} is {context.get('role', 'a contact')} at {context.get('company', 'an organization')}."
            
            return context
            
        except Exception as e:
            self.logger.error(f"Error getting AI context for person {person_name}: {e}")
            return self._get_default_person_context()
    
    def get_company_context(self, company_name: str, meeting_filename: str) -> Dict[str, str]:
        """Extract AI context about a company"""
        if not self.anthropic_client:
            return self._get_default_company_context()
        
        try:
            # Similar logic to person context
            meeting_path = Path(self.file_manager.output_dir) / f"{meeting_filename}.md"
            transcript_snippet = ""
            
            if meeting_path.exists():
                with open(meeting_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    name_index = content.lower().find(company_name.lower())
                    if name_index > 0:
                        start = max(0, name_index - 500)
                        end = min(len(content), name_index + 500)
                        transcript_snippet = content[start:end]
            
            prompt = f"""Based on this meeting transcript snippet, extract context about {company_name}.
Focus on their business relationship to {self.employer if self.employer else 'our organization'}.

Transcript snippet:
{transcript_snippet}

Provide brief responses for:
1. Industry/Sector
2. Company size
3. Relationship to {self.employer if self.employer else 'us'} (client/vendor/partner/prospect)
4. Business needs discussed
5. Key contacts mentioned
6. Technologies they use
7. Active projects
8. Additional notes

Format as JSON."""

            response = self.anthropic_client.messages.create(
                model=self.model,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}]
            )
            
            context = self._parse_context_response(response.content[0].text)
            context['employer'] = self.employer
            context['relationship_to_employer'] = context.get('relationship', 'Unknown')
            context['summary'] = f"{company_name} is a {context.get('relationship', 'company')} in the {context.get('industry', 'business')} industry."
            
            # Extract technologies as list
            tech_string = context.get('technologies', '')
            context['technologies_used'] = [t.strip() for t in tech_string.split(',') if t.strip()] if tech_string else []
            
            return context
            
        except Exception as e:
            self.logger.error(f"Error getting AI context for company {company_name}: {e}")
            return self._get_default_company_context()
    
    def get_technology_context(self, tech_name: str, meeting_filename: str) -> Dict[str, str]:
        """Extract AI context about a technology"""
        if not self.anthropic_client:
            return self._get_default_technology_context()
        
        try:
            meeting_path = Path(self.file_manager.output_dir) / f"{meeting_filename}.md"
            transcript_snippet = ""
            
            if meeting_path.exists():
                with open(meeting_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    name_index = content.lower().find(tech_name.lower())
                    if name_index > 0:
                        start = max(0, name_index - 500)
                        end = min(len(content), name_index + 500)
                        transcript_snippet = content[start:end]
            
            prompt = f"""Based on this meeting transcript snippet, extract context about {tech_name} technology.

Transcript snippet:
{transcript_snippet}

Provide brief responses for:
1. Category (database/framework/service/tool/etc)
2. Current status (evaluating/implementing/in use)
3. How it's being used
4. Use cases mentioned
5. Integration points
6. Business value
7. Challenges mentioned
8. Future plans
9. Owner/responsible party

Format as JSON."""

            response = self.anthropic_client.messages.create(
                model=self.model,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}]
            )
            
            context = self._parse_context_response(response.content[0].text)
            context['summary'] = f"{tech_name} is a {context.get('category', 'technology')} that is {context.get('current_status', 'being used')}."
            
            # Extract use cases as list
            use_cases_string = context.get('use_cases', '')
            context['use_cases'] = [u.strip() for u in use_cases_string.split(',') if u.strip()] if use_cases_string else []
            
            return context
            
        except Exception as e:
            self.logger.error(f"Error getting AI context for technology {tech_name}: {e}")
            return self._get_default_technology_context()
    
    def _parse_context_response(self, response_text: str) -> Dict[str, str]:
        """Parse AI response into context dictionary"""
        import json
        
        try:
            # Try to parse as JSON first
            if '{' in response_text and '}' in response_text:
                json_start = response_text.find('{')
                json_end = response_text.rfind('}') + 1
                json_str = response_text[json_start:json_end]
                
                context = json.loads(json_str)
                # Convert all values to strings
                return {k: str(v) if v else '' for k, v in context.items()}
        except:
            pass
        
        # Fallback to parsing key-value pairs
        context = {}
        lines = response_text.split('\n')
        
        for line in lines:
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip().lower().replace(' ', '_').replace('/', '_')
                context[key] = value.strip()
        
        return context
    
    def _get_default_person_context(self) -> Dict[str, str]:
        """Default context for a person"""
        return {
            'role': '',
            'company': '',
            'relationship': '',
            'authority': '',
            'department': '',
            'projects': '',
            'notes': '',
            'email': '',
            'phone': '',
            'employer': self.employer,
            'summary': 'Person mentioned in meeting.'
        }
    
    def _get_default_company_context(self) -> Dict[str, str]:
        """Default context for a company"""
        return {
            'industry': '',
            'size': '',
            'location': '',
            'relationship': '',
            'relationship_to_employer': 'Unknown',
            'business_needs': '',
            'key_contacts': '',
            'technologies': '',
            'technologies_used': [],
            'projects': '',
            'notes': '',
            'employer': self.employer,
            'summary': 'Company discussed in meeting.'
        }
    
    def _get_default_technology_context(self) -> Dict[str, str]:
        """Default context for a technology"""
        return {
            'category': 'tool',
            'current_status': 'in use',
            'usage': '',
            'use_cases': [],
            'integrations': '',
            'business_value': '',
            'challenges': '',
            'future_plans': '',
            'owner': '',
            'summary': 'Technology referenced in meeting.'
        }
    
    def analyze_person_context(self, person_name: str, meeting_filename: str) -> Dict[str, any]:
        """Analyze person context for template generation"""
        context = self.get_person_context(person_name, meeting_filename)
        
        return {
            'role': context.get('role', 'Team Member'),
            'department': context.get('department', 'Unknown'),
            'company': context.get('company', 'Unknown'),
            'expertise': context.get('skills', '').split(',') if context.get('skills') else [],
            'communication_style': context.get('communication_style', 'Professional'),
            'key_responsibilities': context.get('responsibilities', '').split(',') if context.get('responsibilities') else [],
            'relationships': [],
            'insights': context.get('summary', '')
        }
    
    def analyze_company_context(self, company_name: str, meeting_filename: str) -> Dict[str, any]:
        """Analyze company context for template generation"""
        context = self.get_company_context(company_name, meeting_filename)
        
        return {
            'industry': context.get('industry', 'Unknown'),
            'type': context.get('relationship_to_employer', 'Partner'),
            'size': context.get('size', 'Unknown'),
            'technologies': context.get('technologies_used', []),
            'services': context.get('business_needs', '').split(',') if context.get('business_needs') else [],
            'key_people': context.get('key_contacts', '').split(',') if context.get('key_contacts') else [],
            'relationship_status': context.get('relationship', 'Active'),
            'insights': context.get('summary', '')
        }
    
    def analyze_technology_context(self, tech_name: str, meeting_filename: str) -> Dict[str, any]:
        """Analyze technology context for template generation"""
        context = self.get_technology_context(tech_name, meeting_filename)
        
        return {
            'category': context.get('category', 'Tool'),
            'status': context.get('current_status', 'In Use'),
            'use_cases': context.get('use_cases', []),
            'benefits': context.get('business_value', '').split(',') if context.get('business_value') else [],
            'challenges': context.get('challenges', '').split(',') if context.get('challenges') else [],
            'alternatives': [],
            'insights': context.get('summary', '')
        }

    def _get_default_context(self, entity_type: str) -> Dict[str, str]:
        """Default context for unknown entity types"""
        return {
            'type': entity_type,
            'summary': f'{entity_type.title()} entity mentioned in meeting.',
            'notes': ''
        }