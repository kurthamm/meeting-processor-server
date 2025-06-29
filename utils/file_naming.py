"""
Smart File Naming for Meeting Processor
Generates human-readable filenames with extracted metadata
"""

import re
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from utils.logger import LoggerMixin


@dataclass
class MeetingMetadata:
    """Extracted metadata from meeting content"""
    topic: str = ""
    participants: List[str] = field(default_factory=list)
    meeting_type: str = ""
    duration_minutes: int = 0
    technologies: List[str] = field(default_factory=list)
    companies: List[str] = field(default_factory=list)
    urgency: str = "normal"  # critical, high, normal, low
    has_decisions: bool = False
    has_action_items: bool = False
    estimated_importance: str = "medium"  # high, medium, low


class SmartFileNamer(LoggerMixin):
    """Generates intelligent filenames based on meeting content"""
    
    def __init__(self, settings):
        self.settings = settings
        self.naming_template = getattr(settings, 'FILE_NAMING_TEMPLATE', 
                                     '{topic}_{date}_{time}_{metadata}')
        
        # Patterns for detecting meeting types
        self.meeting_type_patterns = {
            'standup': [
                r'\b(daily\s+)?standup\b', r'\bdaily\s+scrum\b', r'\bstandup\s+meeting\b',
                r'\bscrum\s+daily\b', r'\bmorning\s+sync\b', r'\bdaily\s+sync\b'
            ],
            'retrospective': [
                r'\bretro\b', r'\bretrospective\b', r'\bsprint\s+retro\b',
                r'\bpostmortem\b', r'\bpost.mortem\b', r'\blessons\s+learned\b'
            ],
            'planning': [
                r'\bplanning\b', r'\bsprint\s+planning\b', r'\bquarterly\s+planning\b',
                r'\bproject\s+planning\b', r'\brelease\s+planning\b'
            ],
            'client_call': [
                r'\bclient\b', r'\bcustomer\b', r'\bexternal\b', r'\bvendor\b',
                r'\bpartner\s+call\b', r'\bclient\s+meeting\b'
            ],
            'interview': [
                r'\binterview\b', r'\bcandidate\b', r'\bhiring\b', r'\brecruiting\b',
                r'\bphone\s+screen\b', r'\btechnical\s+interview\b'
            ],
            'demo': [
                r'\bdemo\b', r'\bdemonstration\b', r'\bshowcase\b', r'\bpresentation\b',
                r'\bshow\s+and\s+tell\b', r'\bproduct\s+demo\b'
            ],
            'review': [
                r'\breview\b', r'\bcode\s+review\b', r'\bdesign\s+review\b',
                r'\barchitecture\s+review\b', r'\bpeer\s+review\b'
            ],
            'brainstorm': [
                r'\bbrainstorm\b', r'\bidea\s+session\b', r'\bcreative\s+session\b',
                r'\bideation\b', r'\bthinking\s+session\b'
            ],
            'onboarding': [
                r'\bonboarding\b', r'\bonboard\b', r'\borientation\b', r'\bwelcome\b',
                r'\bnew\s+hire\b', r'\bintroduction\b'
            ],
            'training': [
                r'\btraining\b', r'\bworkshop\b', r'\btutorial\b', r'\blearning\b',
                r'\beducation\b', r'\bknowledge\s+transfer\b'
            ]
        }
        
        # Patterns for detecting urgency/importance
        self.urgency_patterns = {
            'critical': [
                r'\burgent\b', r'\bcritical\b', r'\bemergency\b', r'\bhotfix\b',
                r'\basap\b', r'\bimmediate\b', r'\bcrisis\b'
            ],
            'high': [
                r'\bhigh\s+priority\b', r'\bimportant\b', r'\bescalation\b',
                r'\bblocking\b', r'\btime\s+sensitive\b'
            ],
            'low': [
                r'\bfyi\b', r'\binformational\b', r'\boptional\b', r'\bnice\s+to\s+have\b',
                r'\blow\s+priority\b'
            ]
        }
    
    def generate_filename(self, analysis: Dict[str, Any], original_name: str, 
                         transcript: str = "") -> str:
        """Generate smart filename from meeting analysis"""
        try:
            # Extract metadata from content
            metadata = self._extract_metadata(analysis, transcript, original_name)
            
            # Generate components for filename
            components = self._build_filename_components(metadata, original_name)
            
            # Apply naming strategy based on meeting type and importance
            filename = self._apply_naming_strategy(components, metadata)
            
            # Ensure filename is valid and unique
            filename = self._sanitize_and_validate_filename(filename)
            
            self.logger.debug(f"Generated filename: {original_name} → {filename}")
            return filename
            
        except Exception as e:
            self.logger.warning(f"Error generating smart filename: {e}")
            return self._fallback_filename(original_name)
    
    def _extract_metadata(self, analysis: Dict[str, Any], transcript: str, 
                         original_name: str) -> MeetingMetadata:
        """Extract metadata from meeting analysis and transcript"""
        metadata = MeetingMetadata()
        
        # Extract topic from analysis or infer from filename
        metadata.topic = self._extract_topic(analysis, original_name)
        
        # Extract participants
        metadata.participants = self._extract_participants(analysis)
        
        # Detect meeting type
        metadata.meeting_type = self._detect_meeting_type(analysis, transcript, original_name)
        
        # Estimate duration from transcript length
        metadata.duration_minutes = self._estimate_duration(transcript)
        
        # Extract technologies and companies from entities
        entities = analysis.get('entities', {})
        metadata.technologies = entities.get('technologies', [])[:3]  # Limit to top 3
        metadata.companies = entities.get('companies', [])[:2]  # Limit to top 2
        
        # Detect urgency and importance
        metadata.urgency = self._detect_urgency(analysis, transcript)
        metadata.estimated_importance = self._estimate_importance(metadata, analysis)
        
        # Check for key content types
        metadata.has_decisions = self._has_decisions(analysis)
        metadata.has_action_items = self._has_action_items(analysis)
        
        return metadata
    
    def _extract_topic(self, analysis: Dict[str, Any], original_name: str) -> str:
        """Extract main topic from analysis or filename"""
        # Try to extract from analysis summary
        analysis_text = analysis.get('analysis', '')
        if analysis_text:
            # Look for topic indicators
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
                        return self._clean_topic(topic)
        
        # Fallback to filename-based extraction
        return self._extract_topic_from_filename(original_name)
    
    def _extract_topic_from_filename(self, filename: str) -> str:
        """Extract topic from original filename"""
        # Remove extension and common prefixes
        name = Path(filename).stem
        name = re.sub(r'^(meeting|call|session|zoom|teams)[-_\s]*', '', name, flags=re.IGNORECASE)
        name = re.sub(r'[-_\s]*(recording|rec|audio|video)$', '', name, flags=re.IGNORECASE)
        
        # Clean up and format
        name = re.sub(r'[_-]+', ' ', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        # Capitalize words appropriately
        words = name.split()
        if len(words) > 0:
            # Keep first word capitalized, be smart about others
            formatted_words = [words[0].capitalize()]
            for word in words[1:]:
                if word.lower() in ['api', 'ui', 'db', 'sql', 'ai', 'ml', 'ci', 'cd']:
                    formatted_words.append(word.upper())
                elif len(word) > 3:
                    formatted_words.append(word.capitalize())
                else:
                    formatted_words.append(word.lower())
            return ' '.join(formatted_words)
        
        return name or "Meeting"
    
    def _clean_topic(self, topic: str) -> str:
        """Clean and format topic string"""
        # Remove markdown formatting
        topic = re.sub(r'\*\*([^*]+)\*\*', r'\1', topic)
        topic = re.sub(r'\*([^*]+)\*', r'\1', topic)
        
        # Remove excess whitespace and punctuation
        topic = re.sub(r'[.,:;]+$', '', topic)
        topic = re.sub(r'\s+', ' ', topic).strip()
        
        # Limit length
        if len(topic) > 60:
            topic = topic[:57] + "..."
        
        return topic or "Meeting"
    
    def _extract_participants(self, analysis: Dict[str, Any]) -> List[str]:
        """Extract participant names from analysis"""
        participants = []
        
        # From entities
        entities = analysis.get('entities', {})
        people = entities.get('people', [])
        participants.extend(people[:5])  # Limit to 5 people
        
        return participants
    
    def _detect_meeting_type(self, analysis: Dict[str, Any], transcript: str, 
                           filename: str) -> str:
        """Detect meeting type from content"""
        # Combine text sources for analysis
        search_text = ' '.join([
            analysis.get('analysis', ''),
            transcript[:1000],  # First 1000 chars of transcript
            filename
        ]).lower()
        
        # Check patterns for each meeting type
        for meeting_type, patterns in self.meeting_type_patterns.items():
            for pattern in patterns:
                if re.search(pattern, search_text, re.IGNORECASE):
                    return meeting_type
        
        # Default classification based on participant count
        participant_count = len(self._extract_participants(analysis))
        if participant_count == 2:
            return "one_on_one"
        elif participant_count > 8:
            return "team_meeting"
        else:
            return "meeting"
    
    def _estimate_duration(self, transcript: str) -> int:
        """Estimate meeting duration from transcript length"""
        if not transcript:
            return 0
        
        # Rough estimation: ~150 words per minute of speech
        word_count = len(transcript.split())
        return max(1, round(word_count / 150))
    
    def _detect_urgency(self, analysis: Dict[str, Any], transcript: str) -> str:
        """Detect urgency level from content"""
        search_text = f"{analysis.get('analysis', '')} {transcript[:500]}".lower()
        
        for urgency, patterns in self.urgency_patterns.items():
            for pattern in patterns:
                if re.search(pattern, search_text, re.IGNORECASE):
                    return urgency
        
        return "normal"
    
    def _estimate_importance(self, metadata: MeetingMetadata, analysis: Dict[str, Any]) -> str:
        """Estimate overall meeting importance"""
        score = 0
        
        # Urgency contributes to importance
        urgency_scores = {'critical': 3, 'high': 2, 'normal': 0, 'low': -1}
        score += urgency_scores.get(metadata.urgency, 0)
        
        # Meeting type importance
        important_types = ['client_call', 'demo', 'planning', 'retrospective', 'interview']
        if metadata.meeting_type in important_types:
            score += 2
        
        # Content indicators
        if metadata.has_decisions:
            score += 2
        if metadata.has_action_items:
            score += 1
        
        # Participant count (more people = potentially more important)
        if len(metadata.participants) >= 5:
            score += 1
        elif len(metadata.participants) >= 8:
            score += 2
        
        # Duration (longer meetings might be more important)
        if metadata.duration_minutes >= 60:
            score += 1
        elif metadata.duration_minutes >= 120:
            score += 2
        
        # Convert score to importance level
        if score >= 4:
            return "high"
        elif score <= -1:
            return "low"
        else:
            return "medium"
    
    def _has_decisions(self, analysis: Dict[str, Any]) -> bool:
        """Check if meeting contains decisions"""
        text = analysis.get('analysis', '').lower()
        decision_indicators = [
            'decided', 'decision', 'agreed', 'concluded', 'resolved',
            'approved', 'selected', 'chosen', 'finalized'
        ]
        return any(indicator in text for indicator in decision_indicators)
    
    def _has_action_items(self, analysis: Dict[str, Any]) -> bool:
        """Check if meeting contains action items"""
        text = analysis.get('analysis', '').lower()
        action_indicators = [
            'action item', 'todo', 'to do', 'follow up', 'next step',
            'assigned', 'responsible', 'will do', 'task', 'homework'
        ]
        return any(indicator in text for indicator in action_indicators)
    
    def _build_filename_components(self, metadata: MeetingMetadata, 
                                 original_name: str) -> Dict[str, str]:
        """Build filename components from metadata"""
        now = datetime.now()
        
        components = {
            'topic': self._sanitize_filename_part(metadata.topic),
            'date': now.strftime("%Y-%m-%d"),
            'time': now.strftime("%H%M"),
            'type': metadata.meeting_type,
            'duration': f"{metadata.duration_minutes}min" if metadata.duration_minutes > 0 else "",
            'participants': f"{len(metadata.participants)}p" if metadata.participants else "",
            'urgency': metadata.urgency if metadata.urgency != 'normal' else "",
            'importance': metadata.estimated_importance if metadata.estimated_importance != 'medium' else "",
            'original': Path(original_name).stem
        }
        
        # Build metadata suffix
        metadata_parts = []
        if metadata.has_decisions:
            metadata_parts.append("decisions")
        if metadata.has_action_items:
            metadata_parts.append("actions")
        if metadata.urgency in ['critical', 'high']:
            metadata_parts.append(metadata.urgency)
        if metadata.participants and len(metadata.participants) > 5:
            metadata_parts.append(f"{len(metadata.participants)}people")
        
        components['metadata'] = '_'.join(metadata_parts) if metadata_parts else ""
        
        return components
    
    def _apply_naming_strategy(self, components: Dict[str, str], 
                             metadata: MeetingMetadata) -> str:
        """Apply naming strategy based on meeting type and context"""
        topic = components['topic']
        date = components['date']
        time = components['time']
        
        # Strategy based on meeting type
        if metadata.meeting_type == 'standup':
            return f"Standup_{date}_{time}"
        
        elif metadata.meeting_type == 'client_call':
            client = metadata.companies[0] if metadata.companies else "Client"
            return f"{topic}_{client}Call_{date}_{components['duration']}"
        
        elif metadata.meeting_type == 'interview':
            candidate = metadata.participants[0] if metadata.participants else "Candidate"
            return f"Interview_{candidate}_{date}_{time}"
        
        elif metadata.meeting_type == 'demo':
            return f"Demo_{topic}_{date}_{components['participants']}"
        
        elif metadata.meeting_type == 'retrospective':
            return f"Retro_{topic}_{date}"
        
        elif metadata.meeting_type == 'planning':
            return f"Planning_{topic}_{date}_{components['duration']}"
        
        elif metadata.urgency == 'critical':
            return f"URGENT_{topic}_{date}_{time}"
        
        elif metadata.estimated_importance == 'high':
            metadata_suffix = f"_{components['metadata']}" if components['metadata'] else ""
            return f"{topic}_Important_{date}{metadata_suffix}"
        
        elif len(metadata.participants) >= 8:
            return f"{topic}_TeamMeeting_{date}_{components['participants']}"
        
        else:
            # Default strategy
            parts = [topic, date, time]
            if components['duration'] and metadata.duration_minutes >= 60:
                parts.append(components['duration'])
            if components['metadata']:
                parts.append(components['metadata'])
            
            return '_'.join(filter(None, parts))
    
    def _sanitize_filename_part(self, text: str) -> str:
        """Sanitize a part of the filename"""
        if not text:
            return ""
        
        # Remove/replace invalid characters
        text = re.sub(r'[<>:"/\\|?*]', '', text)
        text = re.sub(r'[^\w\s-]', '', text)
        text = re.sub(r'\s+', '_', text)
        text = re.sub(r'_{2,}', '_', text)
        text = text.strip('_')
        
        # Limit length
        if len(text) > 40:
            text = text[:37] + "..."
        
        return text
    
    def _sanitize_and_validate_filename(self, filename: str) -> str:
        """Final sanitization and validation of filename"""
        # Ensure .md extension
        if not filename.endswith('.md'):
            filename += '.md'
        
        # Remove invalid characters
        filename = re.sub(r'[<>:"/\\|?*]', '', filename)
        filename = re.sub(r'\.{2,}', '.', filename)  # Multiple dots
        filename = re.sub(r'_{2,}', '_', filename)   # Multiple underscores
        
        # Ensure reasonable length
        if len(filename) > 100:
            name_part = filename[:-3]  # Remove .md
            filename = name_part[:97] + '.md'
        
        # Ensure it doesn't start with special characters
        filename = re.sub(r'^[._-]+', '', filename)
        
        return filename or "Meeting.md"
    
    def _fallback_filename(self, original_name: str) -> str:
        """Generate fallback filename if smart naming fails"""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        safe_name = self._sanitize_filename_part(Path(original_name).stem)
        return f"{safe_name}_{timestamp}.md"


# Global file namer instance
_global_file_namer = None


def get_file_namer(settings) -> SmartFileNamer:
    """Get the global file namer instance"""
    global _global_file_namer
    if _global_file_namer is None:
        _global_file_namer = SmartFileNamer(settings)
    return _global_file_namer


def generate_smart_filename(analysis: Dict[str, Any], original_name: str, 
                          transcript: str, settings) -> str:
    """Convenience function to generate smart filename"""
    namer = get_file_namer(settings)
    return namer.generate_filename(analysis, original_name, transcript)