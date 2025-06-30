"""
Claude AI analysis for Meeting Processor
Handles transcript analysis, speaker identification, and topic extraction
"""

import re
from datetime import datetime
from typing import Dict, Any, Optional, List
from utils.logger import LoggerMixin, log_success, log_error, log_warning
from utils.retry_handler import (
    api_retry, 
    handle_api_errors, 
    ANTHROPIC_RETRYABLE_EXCEPTIONS,
    APIRetryableError
)


class ClaudeAnalyzer(LoggerMixin):
    """Handles Claude AI analysis and speaker identification"""
    
    def __init__(self, anthropic_client):
        self.anthropic_client = anthropic_client
        self.model = "claude-3-5-sonnet-20241022"
        self.max_analysis_tokens = 4000
        self.max_speaker_tokens = 8000
    
    @handle_api_errors
    @api_retry.retry(
        retryable_exceptions=ANTHROPIC_RETRYABLE_EXCEPTIONS,
        context="Anthropic Claude API"
    )
    def _call_claude_api(self, prompt: str, max_tokens: int = 4000) -> str:
        """Make a Claude API call with retry logic and error handling"""
        try:
            response = self.anthropic_client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}]
            )
            
            # Safely extract text from Anthropic response
            try:
                if hasattr(response, 'content') and response.content:
                    content = response.content[0] if isinstance(response.content, list) else response.content
                    if hasattr(content, 'text'):
                        result = content.text
                    elif isinstance(content, dict):
                        result = content.get('text', str(content))
                    else:
                        result = str(content)
                else:
                    result = str(response)
                
                # Ensure it's a string and strip
                if not isinstance(result, str):
                    result = str(result)
                return result.strip()
            except Exception as e:
                self.logger.warning(f"Error extracting text from Claude response: {e}")
                return ""
        
        except Exception as e:
            # Convert to retryable error if appropriate
            error_msg = str(e).lower()
            if any(term in error_msg for term in ['rate limit', 'timeout', 'connection', 'server error', 'overloaded']):
                raise APIRetryableError(f"Anthropic API error: {e}")
            else:
                # Non-retryable error
                raise
    
    def extract_meeting_topic(self, transcript: str) -> str:
        """Extract meeting topic using Claude AI for filename generation"""
        try:
            self.logger.info("🏷️  Extracting meeting topic for filename...")
            
            topic_prompt = f"""Please analyze this meeting transcript and extract a concise meeting topic suitable for a filename. 

Requirements:
- Maximum 4-6 words
- Use title case 
- Replace spaces with hyphens
- Remove special characters that aren't suitable for filenames
- Focus on the main subject/purpose of the meeting

Examples of good topics:
- "DEAL-Payroll-Implementation"
- "Q3-Sales-Review"
- "Project-Kickoff-Meeting"
- "Budget-Planning-Session"

Transcript excerpt (first 1000 characters):
{transcript[:1000]}

Please respond with just the topic in the format specified above, nothing else."""

            topic = self._call_claude_api(topic_prompt, max_tokens=100)
            
            # Clean up the topic to ensure it's filename-safe
            topic = re.sub(r'[^\w\-]', '', topic)
            topic = re.sub(r'-+', '-', topic)  # Remove multiple consecutive hyphens
            topic = topic.strip('-')  # Remove leading/trailing hyphens
            
            if not topic:  # Fallback if cleaning removed everything
                topic = "Meeting-Recording"
            
            log_success(self.logger, f"Extracted meeting topic: {topic}")
            return topic
            
        except Exception as e:
            log_error(self.logger, "Error extracting meeting topic", e)
            return "Meeting-Recording"  # Fallback topic
    
    def analyze_transcript(self, transcript: str, audio_filename: str) -> Optional[Dict[str, Any]]:
        """Analyze transcript with Claude AI"""
        try:
            self.logger.info("🧠 Analyzing transcript with Claude AI...")
            
            prompt = f"""Please analyze this meeting transcript and provide a comprehensive analysis:

**Audio File:** {audio_filename}
**Transcript:**
{transcript}

Please provide:

1. **Meeting Summary**: Brief overview of the meeting purpose and key topics
2. **Major Decisions**: List all decisions made during the meeting
3. **Action Items/Tasks**: Extract all tasks assigned, including who is responsible and deadlines if mentioned
4. **Key Discussion Points**: Important topics discussed in detail
5. **Participants**: List of people who spoke (if identifiable from the transcript)
6. **Next Steps**: Any follow-up actions or future meetings mentioned
7. **Important Quotes**: Any significant statements or commitments made

Format the response as a well-structured document that can be easily reviewed and shared.

IMPORTANT: Ensure the analysis captures ALL content from the transcript without summarization or omission of details."""

            analysis = self._call_claude_api(prompt, max_tokens=self.max_analysis_tokens)
            
            result = {
                "timestamp": datetime.now().isoformat(),
                "source_file": audio_filename,
                "transcript": transcript,
                "analysis": analysis
            }
            
            log_success(self.logger, "Completed transcript analysis")
            return result
            
        except Exception as e:
            log_error(self.logger, "Error analyzing transcript with Claude AI", e)
            return None
    
    def identify_speakers(self, transcript: str) -> str:
        """Use Claude to identify and format speakers in the transcript"""
        try:
            transcript_length = len(transcript)
            self.logger.info(f"🎭 Identifying speakers in transcript ({transcript_length} chars)")
            
            if transcript_length > 10000:
                return self._identify_speakers_chunked(transcript)
            else:
                return self._identify_speakers_single(transcript)
            
        except Exception as e:
            log_error(self.logger, "Error identifying speakers", e)
            return transcript
    
    def _identify_speakers_single(self, transcript: str) -> str:
        """Identify speakers in a single transcript"""
        try:
            speaker_prompt = f"""Please analyze this meeting transcript and identify different speakers. Add speaker labels that preserve ALL the original content.

CRITICAL REQUIREMENTS:
1. Keep 100% of the original transcript content - do not summarize, omit, or paraphrase ANY spoken words
2. Only add speaker labels like "Speaker A:", "Speaker B:", etc. at the beginning of speaker turns
3. Preserve all conversation details, technical terms, names, and complete sentences
4. Do not replace any content with summaries like "[Continues with technical instructions]"
5. If you cannot complete the full formatting due to length, return the original transcript unchanged

Try to identify natural speaker changes based on:
- Changes in topic or perspective  
- Conversational patterns (questions/answers)
- Different speaking styles or vocabulary
- Context clues about roles

Original transcript:
{transcript}

Please return the COMPLETE transcript with only speaker labels added, maintaining every single word from the original."""

            formatted_transcript = self._call_claude_api(speaker_prompt, max_tokens=self.max_speaker_tokens)
            
            # Verify that the formatted transcript is not significantly shorter than original
            if len(formatted_transcript) < len(transcript) * 0.85:
                log_warning(self.logger, "Formatted transcript seems truncated, using original")
                return transcript
            
            log_success(self.logger, "Successfully formatted transcript with speakers")
            return formatted_transcript
            
        except Exception as e:
            log_error(self.logger, "Error in single speaker identification", e)
            return transcript
    
    def _identify_speakers_chunked(self, transcript: str) -> str:
        """Process very long transcripts in chunks for speaker identification"""
        try:
            chunks = self._split_transcript_into_chunks(transcript)
            self.logger.info(f"🔪 Split transcript into {len(chunks)} chunks for speaker identification")
            
            formatted_chunks = []
            
            for i, chunk in enumerate(chunks):
                self.logger.debug(f"Processing speaker ID for chunk {i+1}/{len(chunks)} ({len(chunk)} chars)")
                formatted_chunk = self._process_speaker_chunk(chunk, i, len(chunks))
                formatted_chunks.append(formatted_chunk)
            
            result = "\n\n".join(formatted_chunks)
            
            # Final verification
            if len(result) < len(transcript) * 0.7:
                log_warning(self.logger, "Chunked result seems too short, using original")
                return transcript
            
            log_success(self.logger, "Successfully completed chunked speaker identification")
            return result
            
        except Exception as e:
            log_error(self.logger, "Error in chunked speaker identification", e)
            return transcript
    
    def _split_transcript_into_chunks(self, transcript: str, chunk_size: int = 5000, overlap: int = 200) -> List[str]:
        """Split transcript into manageable chunks"""
        sentences = transcript.split('. ')
        chunks = []
        current_chunk = ""
        
        for sentence in sentences:
            if len(current_chunk) + len(sentence) < chunk_size:
                current_chunk += sentence + ". "
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                
                # Add overlap for context
                if len(current_chunk) > overlap:
                    overlap_text = current_chunk[-overlap:]
                    current_chunk = overlap_text + sentence + ". "
                else:
                    current_chunk = sentence + ". "
        
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        return chunks
    
    def _process_speaker_chunk(self, chunk: str, chunk_index: int, total_chunks: int) -> str:
        """Process a single chunk for speaker identification"""
        chunk_prompt = f"""Add speaker labels to this transcript chunk. Keep ALL original content exactly as is.

This is chunk {chunk_index + 1} of {total_chunks} from a longer meeting transcript.

CRITICAL REQUIREMENTS:
1. Add ONLY speaker labels like "Speaker A:", "Speaker B:" at the beginning of speaker turns
2. Keep 100% of the original words - no changes, no summarization, no corrections
3. Maintain all technical terms, numbers, and conversation flow exactly
4. Do not reorganize or clean up the text
5. Do NOT add any commentary, explanations, or chunk references
6. Return ONLY the transcript content with speaker labels added
7. If you cannot complete the full formatting, return the original chunk unchanged

Original chunk:
{chunk}

RETURN ONLY THE TRANSCRIPT WITH SPEAKER LABELS - NO OTHER TEXT:"""

        try:
            formatted_chunk = self._call_claude_api(chunk_prompt, max_tokens=self.max_speaker_tokens)
            
            # Verify chunk wasn't significantly altered
            if len(formatted_chunk) < len(chunk) * 0.75:
                log_warning(self.logger, f"Chunk {chunk_index + 1} seems heavily modified, using original")
                return chunk
            
            self.logger.debug(f"✓ Successfully processed chunk {chunk_index + 1}")
            return formatted_chunk
            
        except Exception as e:
            log_error(self.logger, f"Error processing chunk {chunk_index + 1}", e)
            return chunk