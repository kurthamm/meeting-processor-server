"""
Entity Template Generator for Meeting Processor
Handles creation of rich, AI-enhanced templates for people, companies, and technologies
"""

import re
from typing import Dict, Optional, TYPE_CHECKING
from utils.logger import LoggerMixin, log_success, log_error
from .ai_context import AIContextExtractor

if TYPE_CHECKING:
    from core.file_manager import FileManager


class EntityTemplateGenerator(LoggerMixin):
    """Generates intelligent templates for entity notes using AI context"""
    
    def __init__(self, file_manager: 'FileManager', anthropic_client):
        self.file_manager = file_manager
        self.ai_context = AIContextExtractor(anthropic_client, file_manager)
    
    def generate_person_template(self, person_name: str, meeting_filename: str, meeting_date: str) -> str:
        """Generate an AI-enhanced person note template"""
        safe_name = self._sanitize_filename(person_name)
        
        # Get AI context for the person
        ai_analysis = self.ai_context.analyze_person_context(person_name, meeting_filename)
        
        # Extract context fields
        role = ai_analysis.get('role', 'Team Member')
        department = ai_analysis.get('department', 'Unknown')
        company = ai_analysis.get('company', 'Unknown')
        expertise = ai_analysis.get('expertise', [])
        communication_style = ai_analysis.get('communication_style', 'Unknown')
        key_responsibilities = ai_analysis.get('key_responsibilities', [])
        relationships = ai_analysis.get('relationships', [])
        
        # Build dynamic dataview queries
        dataview_assigned_tasks = self._build_dataview_assigned_tasks(person_name)
        dataview_mentioned_tasks = self._build_dataview_mentioned_tasks(person_name)
        dataview_meetings = self._build_dataview_meetings(safe_name, person_name)
        dataview_technologies = self._build_dataview_technologies(person_name)
        dataview_companies = self._build_dataview_companies(person_name)
        
        # Generate template with AI insights
        content = f"""---
type: person
name: {person_name}
role: {role}
department: {department}
company: {company}
communication-style: {communication_style}
first-mentioned: {meeting_date}
last-updated: {self._get_current_timestamp()}
tags:
  - person
  - {department.lower().replace(' ', '-')}
  - {role.lower().replace(' ', '-')}
---

# {person_name}

**Role:** {role}  
**Department:** {department}  
**Company:** {company}  
**Communication Style:** {communication_style}  
**First Mentioned:** {meeting_date}

## Key Insights
{self._format_ai_insights(ai_analysis)}

## Expertise & Skills
{self._format_list(expertise, 'No specific expertise mentioned yet')}

## Key Responsibilities
{self._format_list(key_responsibilities, 'No specific responsibilities mentioned yet')}

## Professional Relationships
{self._format_relationships(relationships)}

## Current Tasks Assigned
{dataview_assigned_tasks}

## Tasks Mentioned In
{dataview_mentioned_tasks}

## Meeting History
{dataview_meetings}

## Technology Experience
{dataview_technologies}

## Company Connections
{dataview_companies}

## Meeting References
- [[{meeting_filename}]] - {meeting_date}

## Notes
<!-- Add personal observations and context here -->

---
**Last Updated:** {self._get_current_timestamp()}  
**Auto-generated:** Yes, enhanced with AI context analysis
"""
        return content
    
    def generate_company_template(self, company_name: str, meeting_filename: str, meeting_date: str) -> str:
        """Generate an AI-enhanced company note template"""
        safe_name = self._sanitize_filename(company_name)
        
        # Get AI context for the company
        ai_analysis = self.ai_context.analyze_company_context(company_name, meeting_filename)
        
        # Extract context fields
        industry = ai_analysis.get('industry', 'Unknown')
        company_type = ai_analysis.get('type', 'Unknown')  # Client, Partner, Vendor, etc.
        size = ai_analysis.get('size', 'Unknown')
        technologies = ai_analysis.get('technologies', [])
        services = ai_analysis.get('services', [])
        key_people = ai_analysis.get('key_people', [])
        relationship_status = ai_analysis.get('relationship_status', 'Unknown')
        
        # Build dynamic dataview queries
        dataview_people = self._build_dataview_company_people(company_name)
        dataview_meetings = self._build_dataview_company_meetings(safe_name, company_name)
        dataview_technologies = self._build_dataview_company_technologies(company_name)
        dataview_tasks = self._build_dataview_company_tasks(company_name)
        
        content = f"""---
type: company
name: {company_name}
industry: {industry}
company-type: {company_type}
size: {size}
relationship-status: {relationship_status}
first-mentioned: {meeting_date}
last-updated: {self._get_current_timestamp()}
tags:
  - company
  - {industry.lower().replace(' ', '-')}
  - {company_type.lower().replace(' ', '-')}
---

# {company_name}

**Industry:** {industry}  
**Type:** {company_type}  
**Size:** {size}  
**Relationship:** {relationship_status}  
**First Mentioned:** {meeting_date}

## Company Overview
{self._format_ai_insights(ai_analysis)}

## Services & Products
{self._format_list(services, 'No specific services mentioned yet')}

## Technologies Used
{self._format_list(technologies, 'No specific technologies mentioned yet')}

## Key Contacts
{dataview_people}

## Meeting History
{dataview_meetings}

## Technology Stack
{dataview_technologies}

## Related Tasks
{dataview_tasks}

## Partnership Details
<!-- Add partnership terms, contracts, SLAs, etc. -->

## Meeting References
- [[{meeting_filename}]] - {meeting_date}

## Notes
<!-- Add company-specific observations and context here -->

---
**Last Updated:** {self._get_current_timestamp()}  
**Auto-generated:** Yes, enhanced with AI context analysis
"""
        return content
    
    def generate_technology_template(self, tech_name: str, meeting_filename: str, meeting_date: str) -> str:
        """Generate an AI-enhanced technology note template"""
        safe_name = self._sanitize_filename(tech_name)
        
        # Get AI context for the technology
        ai_analysis = self.ai_context.analyze_technology_context(tech_name, meeting_filename)
        
        # Extract context fields
        category = ai_analysis.get('category', 'Unknown')
        implementation_status = ai_analysis.get('status', 'Under Discussion')
        use_cases = ai_analysis.get('use_cases', [])
        benefits = ai_analysis.get('benefits', [])
        challenges = ai_analysis.get('challenges', [])
        alternatives = ai_analysis.get('alternatives', [])
        
        # Build dynamic dataview queries
        dataview_meetings = self._build_dataview_technology_meetings(safe_name, tech_name)
        dataview_people = self._build_dataview_technology_people(tech_name)
        dataview_companies = self._build_dataview_technology_companies(tech_name)
        dataview_tasks = self._build_dataview_technology_tasks(tech_name)
        
        content = f"""---
type: technology
name: {tech_name}
category: {category}
status: {implementation_status}
first-mentioned: {meeting_date}
last-updated: {self._get_current_timestamp()}
tags:
  - technology
  - {category.lower().replace(' ', '-')}
  - {implementation_status.lower().replace(' ', '-')}
---

# {tech_name}

**Category:** {category}  
**Status:** {implementation_status}  
**First Mentioned:** {meeting_date}

## Technology Overview
{self._format_ai_insights(ai_analysis)}

## Use Cases
{self._format_list(use_cases, 'No specific use cases mentioned yet')}

## Benefits
{self._format_list(benefits, 'No specific benefits mentioned yet')}

## Challenges & Considerations
{self._format_list(challenges, 'No specific challenges mentioned yet')}

## Alternatives Considered
{self._format_list(alternatives, 'No alternatives mentioned yet')}

## People Involved
{dataview_people}

## Company Usage
{dataview_companies}

## Meeting History
{dataview_meetings}

## Related Tasks
{dataview_tasks}

## Implementation Notes
<!-- Add technical details, architecture decisions, etc. -->

## Meeting References
- [[{meeting_filename}]] - {meeting_date}

## Notes
<!-- Add technology-specific observations and context here -->

---
**Last Updated:** {self._get_current_timestamp()}  
**Auto-generated:** Yes, enhanced with AI context analysis
"""
        return content
    
    # Helper methods for building dataview queries
    def _build_dataview_assigned_tasks(self, person_name: str) -> str:
        """Build dataview query for assigned tasks"""
        return f'''```dataview
task
from "Tasks"
where contains(file.text, "Assigned To: {person_name}")
where !completed
sort priority desc
```'''
    
    def _build_dataview_mentioned_tasks(self, person_name: str) -> str:
        """Build dataview query for mentioned tasks"""
        return f'''```dataview
list
from "Tasks"
where contains(file.text, "{person_name}") 
where !contains(file.text, "Assigned To: {person_name}")
sort file.ctime desc
```'''
    
    def _build_dataview_meetings(self, safe_name: str, person_name: str) -> str:
        """Build dataview query for person's meetings"""
        return f'''```dataview
table without id 
  file.link as "Meeting",
  date as "Date",
  meeting-type as "Type"
from "Meetings"
where contains(people-mentioned, "[[People/{safe_name}|{person_name}]]")
sort date desc
```'''
    
    def _build_dataview_technologies(self, person_name: str) -> str:
        """Build dataview query for person's technologies"""
        return f'''```dataview
list
from "Technologies"
where contains(file.text, "{person_name}")
sort file.mtime desc
```'''
    
    def _build_dataview_companies(self, person_name: str) -> str:
        """Build dataview query for person's companies"""
        return f'''```dataview
list
from "Companies"
where contains(file.text, "{person_name}")
sort file.mtime desc
```'''
    
    def _build_dataview_company_people(self, company_name: str) -> str:
        """Build dataview query for company people"""
        return f'''```dataview
table without id
  file.link as "Person",
  role as "Role",
  department as "Department"
from "People"
where contains(company, "{company_name}")
sort role asc
```'''
    
    def _build_dataview_company_meetings(self, safe_name: str, company_name: str) -> str:
        """Build dataview query for company meetings"""
        return f'''```dataview
table without id
  file.link as "Meeting",
  date as "Date",
  meeting-type as "Type"
from "Meetings"
where contains(companies-discussed, "[[Companies/{safe_name}|{company_name}]]")
sort date desc
```'''
    
    def _build_dataview_company_technologies(self, company_name: str) -> str:
        """Build dataview query for company technologies"""
        return f'''```dataview
list
from "Technologies"
where contains(file.text, "{company_name}")
sort file.mtime desc
```'''
    
    def _build_dataview_company_tasks(self, company_name: str) -> str:
        """Build dataview query for company tasks"""
        return f'''```dataview
list
from "Tasks"
where contains(file.text, "{company_name}")
sort priority desc
```'''
    
    def _build_dataview_technology_meetings(self, safe_name: str, tech_name: str) -> str:
        """Build dataview query for technology meetings"""
        return f'''```dataview
table without id
  file.link as "Meeting",
  date as "Date",
  meeting-type as "Type"
from "Meetings"
where contains(technologies-referenced, "[[Technologies/{safe_name}|{tech_name}]]")
sort date desc
```'''
    
    def _build_dataview_technology_people(self, tech_name: str) -> str:
        """Build dataview query for technology people"""
        return f'''```dataview
list
from "People"
where contains(file.text, "{tech_name}")
sort file.mtime desc
```'''
    
    def _build_dataview_technology_companies(self, tech_name: str) -> str:
        """Build dataview query for technology companies"""
        return f'''```dataview
list
from "Companies"
where contains(file.text, "{tech_name}")
sort file.mtime desc
```'''
    
    def _build_dataview_technology_tasks(self, tech_name: str) -> str:
        """Build dataview query for technology tasks"""
        return f'''```dataview
list
from "Tasks"
where contains(file.text, "{tech_name}")
sort priority desc
```'''
    
    # Utility methods
    def _sanitize_filename(self, name: str) -> str:
        """Sanitize a name for use as a filename"""
        # Remove special characters, replace spaces with hyphens
        safe_name = re.sub(r'[^\w\s-]', '', name)
        safe_name = re.sub(r'\s+', '-', safe_name)
        return safe_name.strip('-')
    
    def _format_ai_insights(self, ai_analysis: Dict) -> str:
        """Format AI insights into readable text"""
        insights = ai_analysis.get('insights', '')
        if insights:
            return f"{insights}\n"
        return "<!-- AI context analysis will be added here -->\n"
    
    def _format_list(self, items: list, fallback: str) -> str:
        """Format a list of items into markdown"""
        if not items:
            return f"<!-- {fallback} -->\n"
        
        formatted_items = []
        for item in items:
            if isinstance(item, str):
                formatted_items.append(f"- {item}")
            elif isinstance(item, dict):
                formatted_items.append(f"- **{item.get('name', 'Unknown')}**: {item.get('description', '')}")
        
        return "\n".join(formatted_items) + "\n"
    
    def _format_relationships(self, relationships: list) -> str:
        """Format professional relationships"""
        if not relationships:
            return "<!-- Professional relationships will be identified here -->\n"
        
        formatted = []
        for rel in relationships:
            if isinstance(rel, dict):
                person = rel.get('person', 'Unknown')
                relation = rel.get('relation', 'colleague')
                formatted.append(f"- **{person}** - {relation}")
            else:
                formatted.append(f"- {rel}")
        
        return "\n".join(formatted) + "\n"
    
    def _get_current_timestamp(self) -> str:
        """Get current timestamp for metadata"""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")