"""
Transcription service for Meeting Processor
Handles OpenAI Whisper transcription with chunking support
"""

import signal
from pathlib import Path
from typing import Optional, TYPE_CHECKING
from utils.logger import LoggerMixin, log_success, log_error, log_warning
from utils.retry_handler import (
    api_retry, 
    handle_api_errors, 
    OPENAI_RETRYABLE_EXCEPTIONS,
    APIRetryableError
)

if TYPE_CHECKING:
    import openai
    from core.audio_processor import AudioProcessor


class TranscriptionService(LoggerMixin):
    """Handles OpenAI Whisper transcription"""
    
    def __init__(self, openai_client: Optional['openai.OpenAI'], audio_processor: 'AudioProcessor'):
        self.openai_client = openai_client
        self.audio_processor = audio_processor
        self.max_file_size_mb = 25  # Whisper API limit
        self.timeout_seconds = 120  # Timeout for API calls
    
    def transcribe_audio(self, audio_path: Path) -> Optional[str]:
        """Transcribe audio using OpenAI Whisper"""
        if not self.openai_client:
            log_warning(self.logger, "OpenAI client not available - skipping transcription")
            return None
        
        file_size_mb = audio_path.stat().st_size / (1024 * 1024)
        
        self.logger.info(f"🎤 Starting transcription: {audio_path.name} ({file_size_mb:.1f}MB)")
        
        # Handle large files by chunking
        if file_size_mb > self.max_file_size_mb:
            return self._transcribe_large_file(audio_path, file_size_mb)
        else:
            return self._transcribe_single_file(audio_path, file_size_mb)
    
    def _transcribe_large_file(self, audio_path: Path, file_size_mb: float) -> Optional[str]:
        """Transcribe large files by chunking"""
        self.logger.info(f"📊 File size {file_size_mb:.1f}MB exceeds limit, creating chunks...")
        
        chunks = self.audio_processor.chunk_audio_file(audio_path)
        if not chunks:
            log_error(self.logger, "Failed to create audio chunks")
            return None
        
        full_transcript = []
        successful_chunks = 0
        
        for i, chunk_path in enumerate(chunks, 1):
            self.logger.info(f"🎤 Transcribing chunk {i}/{len(chunks)}: {chunk_path.name}")
            
            chunk_text = self._transcribe_chunk(chunk_path, i)
            if chunk_text and not chunk_text.startswith('[Audio section'):
                successful_chunks += 1
            
            full_transcript.append(chunk_text)
            
            # Clean up chunk file immediately after processing
            self._cleanup_chunk(chunk_path)
        
        if successful_chunks == 0:
            log_error(self.logger, "No chunks were successfully transcribed")
            return None
        
        combined_transcript = " ".join(full_transcript)
        
        log_success(self.logger, 
                   f"Completed chunked transcription: {successful_chunks}/{len(chunks)} chunks successful")
        
        return combined_transcript
    
    def _transcribe_single_file(self, audio_path: Path, file_size_mb: float) -> Optional[str]:
        """Transcribe a single file with retry logic"""
        try:
            return self._call_whisper_api(audio_path)
        except Exception as e:
            log_error(self.logger, f"Failed to transcribe {audio_path.name}: {e}")
            return None
    
    @handle_api_errors
    @api_retry.retry(
        retryable_exceptions=OPENAI_RETRYABLE_EXCEPTIONS,
        context="OpenAI Whisper transcription"
    )
    def _call_whisper_api(self, audio_path: Path) -> str:
        """Make the actual API call to OpenAI Whisper with error handling"""
        try:
            with open(audio_path, 'rb') as audio_file:
                transcript = self.openai_client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="verbose_json",
                    timeout=self.timeout_seconds
                )
            
            result_text = transcript.text if hasattr(transcript, 'text') else str(transcript)
            
            log_success(self.logger, 
                       f"Transcribed {audio_path.name}: {len(result_text)} characters")
            
            return result_text
        
        except Exception as e:
            # Convert to retryable error if appropriate
            error_msg = str(e).lower()
            if any(term in error_msg for term in ['rate limit', 'timeout', 'connection', 'server error']):
                raise APIRetryableError(f"OpenAI API error: {e}")
            else:
                # Non-retryable error
                raise
    
    def _transcribe_chunk(self, chunk_path: Path, chunk_number: int) -> str:
        """Transcribe a single chunk with timeout handling"""
        try:
            with open(chunk_path, 'rb') as audio_file:
                # Set up timeout handler
                def timeout_handler(signum, frame):
                    raise TimeoutError("Whisper API call timed out")
                
                signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(self.timeout_seconds)
                
                try:
                    transcript = self.openai_client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file,
                        response_format="verbose_json",
                        timeout=self.timeout_seconds
                    )
                    
                    chunk_text = transcript.text.strip() if hasattr(transcript, 'text') else str(transcript).strip()
                    
                    self.logger.debug(f"✓ Chunk {chunk_number} transcribed: {len(chunk_text)} characters")
                    return chunk_text
                    
                finally:
                    signal.alarm(0)  # Cancel the alarm
                    
        except TimeoutError:
            log_error(self.logger, f"Timeout transcribing chunk {chunk_number}")
            return f"[Audio section {chunk_number} could not be transcribed - timeout]"
        except Exception as e:
            log_error(self.logger, f"Error transcribing chunk {chunk_number}", e)
            return f"[Audio section {chunk_number} could not be transcribed: {str(e)}]"
    
    def _cleanup_chunk(self, chunk_path: Path):
        """Clean up temporary chunk file"""
        try:
            if chunk_path.exists():
                chunk_path.unlink()
                self.logger.debug(f"🗑️  Cleaned up chunk: {chunk_path.name}")
        except Exception as e:
            log_warning(self.logger, f"Could not clean up chunk {chunk_path.name}: {e}")
    
    def estimate_transcription_time(self, audio_duration_seconds: float) -> int:
        """Estimate transcription time based on audio duration"""
        # Rough estimate: Whisper processes about 1 minute of audio per 10-15 seconds
        return max(30, int(audio_duration_seconds / 4))  # Minimum 30 seconds
    
    def validate_audio_file(self, audio_path: Path) -> bool:
        """Validate that audio file is suitable for transcription"""
        try:
            if not audio_path.exists():
                log_error(self.logger, f"Audio file does not exist: {audio_path}")
                return False
            
            if not audio_path.is_file():
                log_error(self.logger, f"Path is not a file: {audio_path}")
                return False
            
            file_size = audio_path.stat().st_size
            if file_size == 0:
                log_error(self.logger, f"Audio file is empty: {audio_path}")
                return False
            
            # Check if file is readable
            with open(audio_path, 'rb') as f:
                f.read(1024)  # Try to read first 1KB
            
            self.logger.debug(f"✓ Audio file validation passed: {audio_path.name}")
            return True
            
        except Exception as e:
            log_error(self.logger, f"Audio file validation failed for {audio_path.name}", e)
            return False