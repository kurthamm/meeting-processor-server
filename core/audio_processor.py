"""
Audio processing for Meeting Processor
Handles MP4 to FLAC conversion and audio chunking for large files
"""

import os
import subprocess
from pathlib import Path
from typing import List, Optional
from utils.logger import LoggerMixin, log_success, log_error, log_warning
from utils.exceptions import AudioProcessingError, ResourceError


class AudioProcessor(LoggerMixin):
    """Handles audio conversion and chunking operations"""
    
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.max_file_size_mb = 25  # Whisper API limit
    
    def convert_mp4_to_flac(self, mp4_path: Path) -> Optional[Path]:
        """Convert MP4 to FLAC using ffmpeg with enhanced error handling"""
        try:
            # Validate input file
            if not mp4_path.exists():
                raise AudioProcessingError(
                    f"Input file not found: {mp4_path.name}",
                    filename=mp4_path.name
                )
            
            # Check disk space
            if not self._check_disk_space(mp4_path):
                raise ResourceError(
                    f"Insufficient disk space for conversion: {mp4_path.name}",
                    resource_type="disk"
                )
            
            # Validate input file
            if not self._validate_input_file(mp4_path):
                raise AudioProcessingError(
                    f"Invalid or corrupted input file: {mp4_path.name}",
                    filename=mp4_path.name
                )
            
            flac_filename = mp4_path.stem + '.flac'
            flac_path = self.output_dir / flac_filename
            
            self.logger.info(f"🎵 Converting {mp4_path.name} to FLAC")
            
            cmd = [
                'ffmpeg', '-i', str(mp4_path),
                '-vn',  # No video
                '-ac', '1',  # Mono audio (reduces file size)
                '-ar', '16000',  # 16kHz sample rate (good for speech)
                '-acodec', 'flac',
                '-compression_level', '12',  # Maximum compression
                '-y',  # Overwrite output file
                str(flac_path)
            ]
            
            try:
                result = subprocess.run(
                    cmd, 
                    capture_output=True, 
                    text=True, 
                    timeout=300  # 5 minute timeout
                )
            except subprocess.TimeoutExpired:
                raise AudioProcessingError(
                    f"Conversion timeout exceeded for {mp4_path.name} (5 minutes)",
                    filename=mp4_path.name
                )
            
            if result.returncode == 0:
                # Validate output file
                if not self._validate_output_file(flac_path):
                    raise AudioProcessingError(
                        f"Output validation failed: {flac_path.name}",
                        filename=mp4_path.name
                    )
                
                file_size_mb = flac_path.stat().st_size / (1024 * 1024)
                log_success(self.logger, f"Converted {mp4_path.name} to FLAC ({file_size_mb:.1f}MB)")
                
                if file_size_mb > self.max_file_size_mb:
                    log_warning(self.logger, f"FLAC file is {file_size_mb:.1f}MB (>{self.max_file_size_mb}MB), will need chunking")
                
                return flac_path
            else:
                # Parse FFmpeg error for better messaging
                error_msg = self._parse_ffmpeg_error(result.stderr)
                raise AudioProcessingError(
                    f"FFmpeg conversion failed: {error_msg}",
                    filename=mp4_path.name,
                    ffmpeg_output=result.stderr
                )
                
        except AudioProcessingError:
            raise  # Re-raise our custom errors
        except ResourceError:
            raise  # Re-raise resource errors
        except Exception as e:
            raise AudioProcessingError(
                f"Unexpected error converting {mp4_path.name}: {str(e)}",
                filename=mp4_path.name
            )
    
    def _check_disk_space(self, input_file: Path, safety_margin: float = 2.0) -> bool:
        """Check if sufficient disk space is available"""
        try:
            input_size = input_file.stat().st_size
            required_space = input_size * safety_margin  # Assume 2x space needed
            
            statvfs = os.statvfs(self.output_dir)
            available_space = statvfs.f_frsize * statvfs.f_bavail
            
            return available_space > required_space
        except Exception as e:
            self.logger.warning(f"Could not check disk space: {e}")
            return True  # Assume space is available if check fails
    
    def _validate_input_file(self, file_path: Path) -> bool:
        """Validate input file is readable and appears to be valid media"""
        try:
            # Check file is readable
            with open(file_path, 'rb') as f:
                f.read(1024)  # Try to read first 1KB
            
            # Quick ffprobe check to validate it's a valid media file
            result = subprocess.run(
                ['ffprobe', '-v', 'quiet', str(file_path)],
                capture_output=True,
                timeout=30
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def _validate_output_file(self, file_path: Path) -> bool:
        """Validate output file was created successfully"""
        try:
            if not file_path.exists():
                return False
            
            # Check file size is reasonable (not empty)
            if file_path.stat().st_size < 1024:  # Less than 1KB is suspicious
                return False
            
            # Quick probe to ensure it's a valid audio file
            result = subprocess.run(
                ['ffprobe', '-v', 'quiet', str(file_path)],
                capture_output=True,
                timeout=10
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def _parse_ffmpeg_error(self, stderr: str) -> str:
        """Parse ffmpeg error output for user-friendly messages"""
        if not stderr:
            return "Unknown ffmpeg error"
        
        stderr_lower = stderr.lower()
        
        if "no such file or directory" in stderr_lower:
            return "Input file not found or inaccessible"
        elif "permission denied" in stderr_lower:
            return "Permission denied accessing file"
        elif "no space left on device" in stderr_lower:
            return "Insufficient disk space"
        elif "invalid data" in stderr_lower or "could not find codec" in stderr_lower:
            return "File appears to be corrupted or not a valid media file"
        elif "connection refused" in stderr_lower or "network" in stderr_lower:
            return "Network error while accessing file"
        else:
            # Return the most relevant error line
            lines = stderr.strip().split('\n')
            for line in reversed(lines):
                if line.strip() and not line.startswith('['):
                    return line.strip()
            return "Unknown conversion error"
    
    def chunk_audio_file(self, audio_path: Path, chunk_duration_minutes: int = 10) -> List[Path]:
        """Split large audio file into smaller chunks for Whisper processing"""
        try:
            chunks = []
            chunk_duration_seconds = chunk_duration_minutes * 60
            
            # Get audio duration first
            duration = self._get_audio_duration(audio_path)
            if duration is None:
                log_error(self.logger, f"Could not determine duration of {audio_path.name}")
                return []
            
            self.logger.info(f"🔪 Chunking {audio_path.name} ({duration:.1f}s) into {chunk_duration_minutes}min segments")
            
            # Create chunks
            chunk_number = 0
            for start_time in range(0, int(duration), chunk_duration_seconds):
                chunk_number += 1
                chunk_filename = f"{audio_path.stem}_chunk_{chunk_number:02d}.flac"
                chunk_path = audio_path.parent / chunk_filename
                
                success = self._create_audio_chunk(
                    audio_path, chunk_path, start_time, chunk_duration_seconds, chunk_number
                )
                
                if success:
                    chunks.append(chunk_path)
                else:
                    log_warning(self.logger, f"Failed to create chunk {chunk_number}")
            
            log_success(self.logger, f"Created {len(chunks)} audio chunks")
            return chunks
            
        except Exception as e:
            log_error(self.logger, f"Error chunking {audio_path.name}", e)
            return []
    
    def _get_audio_duration(self, audio_path: Path) -> Optional[float]:
        """Get duration of audio file in seconds"""
        try:
            cmd = [
                'ffprobe', '-v', 'quiet', 
                '-show_entries', 'format=duration', 
                '-of', 'csv=p=0', 
                str(audio_path)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
            else:
                self.logger.debug(f"ffprobe failed: {result.stderr}")
                return None
                
        except Exception as e:
            self.logger.debug(f"Error getting duration: {e}")
            return None
    
    def _create_audio_chunk(self, source_path: Path, chunk_path: Path, 
                           start_time: int, duration: int, chunk_number: int) -> bool:
        """Create a single audio chunk"""
        try:
            cmd = [
                'ffmpeg', '-i', str(source_path),
                '-ss', str(start_time),
                '-t', str(duration),
                '-ac', '1',  # Mono
                '-ar', '16000',  # 16kHz sample rate
                '-acodec', 'flac',
                '-compression_level', '12',
                '-y',  # Overwrite
                str(chunk_path)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                chunk_size_mb = chunk_path.stat().st_size / (1024 * 1024)
                self.logger.debug(f"✓ Created chunk {chunk_number}: {chunk_path.name} ({chunk_size_mb:.1f}MB)")
                return True
            else:
                self.logger.debug(f"✗ Chunk {chunk_number} creation failed: {result.stderr}")
                return False
                
        except Exception as e:
            self.logger.debug(f"✗ Error creating chunk {chunk_number}: {e}")
            return False
    
    def cleanup_chunks(self, base_filename: str):
        """Clean up chunk files after processing"""
        try:
            pattern = f"{base_filename}_chunk_*.flac"
            chunk_files = list(self.output_dir.glob(pattern))
            
            for chunk_file in chunk_files:
                chunk_file.unlink()
                self.logger.debug(f"🗑️  Cleaned up chunk: {chunk_file.name}")
            
            if chunk_files:
                self.logger.info(f"🗑️  Cleaned up {len(chunk_files)} chunk files")
                
        except Exception as e:
            log_warning(self.logger, f"Error cleaning up chunks: {e}")
    
    def validate_ffmpeg_installation(self) -> bool:
        """Check if ffmpeg and ffprobe are available"""
        try:
            # Test ffmpeg
            result = subprocess.run(['ffmpeg', '-version'], 
                                  capture_output=True, text=True)
            if result.returncode != 0:
                return False
            
            # Test ffprobe
            result = subprocess.run(['ffprobe', '-version'], 
                                  capture_output=True, text=True)
            if result.returncode != 0:
                return False
            
            self.logger.debug("✓ FFmpeg installation validated")
            return True
            
        except FileNotFoundError:
            log_error(self.logger, "FFmpeg not found - install ffmpeg to process audio files")
            return False
        except Exception as e:
            log_error(self.logger, "Error validating FFmpeg installation", e)
            return False