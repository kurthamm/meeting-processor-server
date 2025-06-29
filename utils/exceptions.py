"""
Custom Exception Hierarchy for Meeting Processor
Provides domain-specific exceptions with actionable guidance
"""

from typing import Optional, Dict, Any, List


class MeetingProcessorError(Exception):
    """Base exception for Meeting Processor with enhanced error reporting"""
    
    def __init__(self, message: str, details: Optional[str] = None, 
                 solutions: Optional[List[str]] = None, help_url: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.details = details
        self.solutions = solutions or []
        self.help_url = help_url
    
    def get_error_report(self) -> Dict[str, Any]:
        """Generate structured error report"""
        return {
            'error_type': self.__class__.__name__,
            'message': self.message,
            'details': self.details,
            'solutions': self.solutions,
            'help_url': self.help_url
        }
    
    def get_user_friendly_message(self) -> str:
        """Get formatted message for user display"""
        msg = f"❌ {self.message}"
        if self.details:
            msg += f"\n   Details: {self.details}"
        if self.solutions:
            msg += f"\n   💡 Solutions:"
            for i, solution in enumerate(self.solutions, 1):
                msg += f"\n      {i}. {solution}"
        if self.help_url:
            msg += f"\n   📖 Help: {self.help_url}"
        return msg


class ConfigurationError(MeetingProcessorError):
    """Configuration validation errors with specific guidance"""
    
    def __init__(self, message: str, config_field: Optional[str] = None, 
                 expected_value: Optional[str] = None, current_value: Optional[str] = None):
        solutions = []
        details = None
        
        if config_field:
            details = f"Configuration field: {config_field}"
            if current_value and expected_value:
                details += f" (current: {current_value}, expected: {expected_value})"
            
            # Add specific solutions based on common config issues
            if "api_key" in config_field.lower():
                solutions = [
                    f"Set {config_field} in your .env file",
                    "Ensure the API key is valid and has proper permissions",
                    "Check that the .env file is in the correct directory"
                ]
                help_url = "https://docs.anthropic.com/claude-code/configuration"
            elif "path" in config_field.lower():
                solutions = [
                    f"Verify that the path in {config_field} exists and is accessible",
                    "Use absolute paths to avoid confusion",
                    "Check file/directory permissions"
                ]
            elif "folder_id" in config_field.lower():
                solutions = [
                    "Verify the Google Drive folder ID is correct",
                    "Ensure the service account has access to the folder",
                    "Check that the folder exists and is not in Trash"
                ]
                help_url = "https://docs.anthropic.com/claude-code/google-drive"
        
        super().__init__(message, details, solutions, help_url)
        self.config_field = config_field
        self.expected_value = expected_value
        self.current_value = current_value


class ProcessingError(MeetingProcessorError):
    """Base class for file processing errors"""
    
    def __init__(self, message: str, filename: Optional[str] = None, 
                 stage: Optional[str] = None, **kwargs):
        super().__init__(message, **kwargs)
        self.filename = filename
        self.stage = stage


class AudioProcessingError(ProcessingError):
    """Audio conversion and processing errors"""
    
    def __init__(self, message: str, filename: Optional[str] = None, 
                 ffmpeg_output: Optional[str] = None):
        # Parse ffmpeg errors for better solutions
        solutions = []
        details = None
        
        if ffmpeg_output:
            details = f"FFmpeg output: {ffmpeg_output[:200]}..."
            
            if "No such file or directory" in ffmpeg_output:
                solutions = [
                    "Verify the input file exists and is accessible",
                    "Check file permissions",
                    "Ensure the file path doesn't contain special characters"
                ]
            elif "Permission denied" in ffmpeg_output:
                solutions = [
                    "Check file permissions for both input and output directories",
                    "Ensure the user has write access to the output directory",
                    "Try running with elevated permissions if necessary"
                ]
            elif "No space left on device" in ffmpeg_output:
                solutions = [
                    "Free up disk space on the system",
                    "Move files to a drive with more space",
                    "Clean up temporary files"
                ]
            elif "Invalid data" in ffmpeg_output:
                solutions = [
                    "Verify the input file is a valid audio/video file",
                    "Try opening the file in a media player to test it",
                    "Re-record or re-download the file if it's corrupted"
                ]
            else:
                solutions = [
                    "Ensure FFmpeg is installed and accessible",
                    "Verify the input file format is supported",
                    "Check system resources (CPU, memory, disk space)"
                ]
        else:
            solutions = [
                "Ensure FFmpeg is installed and in your system PATH",
                "Verify the input file is a valid media file",
                "Check available disk space and memory"
            ]
        
        super().__init__(
            message, 
            filename=filename, 
            stage="audio_conversion",
            details=details,
            solutions=solutions,
            help_url="https://docs.anthropic.com/claude-code/troubleshooting#audio-issues"
        )
        self.ffmpeg_output = ffmpeg_output


class TranscriptionError(ProcessingError):
    """Transcription service errors"""
    
    def __init__(self, message: str, filename: Optional[str] = None, 
                 api_error: Optional[str] = None, file_duration: Optional[float] = None):
        solutions = []
        details = None
        
        if api_error:
            details = f"API Error: {api_error}"
            
            if "rate limit" in api_error.lower():
                solutions = [
                    "Wait a few minutes before retrying",
                    "Implement request throttling",
                    "Upgrade your OpenAI plan for higher rate limits"
                ]
            elif "quota" in api_error.lower():
                solutions = [
                    "Check your OpenAI account billing and usage",
                    "Add credits to your OpenAI account",
                    "Wait for quota reset if on free tier"
                ]
            elif "invalid" in api_error.lower():
                solutions = [
                    "Verify your OpenAI API key is correct",
                    "Check that your API key has Whisper access",
                    "Regenerate your API key if necessary"
                ]
            elif "timeout" in api_error.lower():
                solutions = [
                    "Try splitting large audio files into smaller chunks",
                    "Check your internet connection stability",
                    "Retry the operation"
                ]
        else:
            solutions = [
                "Verify your OpenAI API key is configured correctly",
                "Check your internet connection",
                "Ensure the audio file is in a supported format"
            ]
        
        if file_duration and file_duration > 1800:  # 30 minutes
            solutions.append("Consider splitting audio files longer than 30 minutes")
        
        super().__init__(
            message,
            filename=filename,
            stage="transcription",
            details=details,
            solutions=solutions,
            help_url="https://docs.anthropic.com/claude-code/troubleshooting#transcription-issues"
        )
        self.api_error = api_error
        self.file_duration = file_duration


class AnalysisError(ProcessingError):
    """AI analysis errors"""
    
    def __init__(self, message: str, filename: Optional[str] = None, 
                 api_error: Optional[str] = None, transcript_length: Optional[int] = None):
        solutions = []
        details = None
        
        if api_error:
            details = f"API Error: {api_error}"
            
            if "rate limit" in api_error.lower():
                solutions = [
                    "Wait before retrying to respect rate limits",
                    "Implement exponential backoff",
                    "Consider upgrading your Anthropic plan"
                ]
            elif "context" in api_error.lower() or "token" in api_error.lower():
                solutions = [
                    "Try processing shorter transcript chunks",
                    "Summarize the transcript before analysis",
                    "Use a model with larger context window"
                ]
            elif "invalid" in api_error.lower():
                solutions = [
                    "Verify your Anthropic API key is correct",
                    "Check API key permissions and quota",
                    "Regenerate your API key if necessary"
                ]
        else:
            solutions = [
                "Verify your Anthropic API key is configured correctly",
                "Check your internet connection",
                "Ensure the transcript is not empty"
            ]
        
        if transcript_length and transcript_length > 100000:  # Very long transcript
            solutions.append("Consider summarizing very long transcripts before analysis")
        
        super().__init__(
            message,
            filename=filename,
            stage="analysis",
            details=details,
            solutions=solutions,
            help_url="https://docs.anthropic.com/claude-code/troubleshooting#analysis-issues"
        )
        self.api_error = api_error
        self.transcript_length = transcript_length


class StorageError(ProcessingError):
    """File storage and vault errors"""
    
    def __init__(self, message: str, filename: Optional[str] = None, 
                 storage_type: Optional[str] = None, operation: Optional[str] = None):
        solutions = []
        details = f"Storage: {storage_type}, Operation: {operation}" if storage_type and operation else None
        
        if storage_type == "google_drive":
            solutions = [
                "Check Google Drive API credentials and permissions",
                "Verify folder IDs are correct and accessible",
                "Ensure sufficient Google Drive storage space",
                "Check internet connection stability"
            ]
            help_url = "https://docs.anthropic.com/claude-code/google-drive"
        elif storage_type == "local":
            solutions = [
                "Check local file system permissions",
                "Verify sufficient disk space",
                "Ensure the Obsidian vault path is correct",
                "Check that directories are writable"
            ]
        else:
            solutions = [
                "Verify storage configuration is correct",
                "Check available disk space",
                "Ensure proper file permissions"
            ]
        
        super().__init__(
            message,
            filename=filename,
            stage="storage",
            details=details,
            solutions=solutions,
            help_url=help_url
        )
        self.storage_type = storage_type
        self.operation = operation


class ResourceError(MeetingProcessorError):
    """System resource errors (memory, disk space, etc.)"""
    
    def __init__(self, message: str, resource_type: str, current_usage: Optional[str] = None,
                 threshold: Optional[str] = None):
        solutions = []
        details = None
        
        if current_usage and threshold:
            details = f"{resource_type} usage: {current_usage} (threshold: {threshold})"
        
        if resource_type == "memory":
            solutions = [
                "Close other applications to free memory",
                "Process smaller files or split large files",
                "Restart the application to clear memory leaks",
                "Consider upgrading system memory"
            ]
        elif resource_type == "disk":
            solutions = [
                "Free up disk space by deleting unnecessary files",
                "Move processed files to external storage",
                "Clean up temporary files",
                "Consider expanding disk capacity"
            ]
        elif resource_type == "cpu":
            solutions = [
                "Close CPU-intensive applications",
                "Process files sequentially instead of in parallel",
                "Wait for other processes to complete"
            ]
        
        super().__init__(
            message,
            details=details,
            solutions=solutions,
            help_url="https://docs.anthropic.com/claude-code/troubleshooting#resource-issues"
        )
        self.resource_type = resource_type
        self.current_usage = current_usage
        self.threshold = threshold


class NetworkError(MeetingProcessorError):
    """Network connectivity and API access errors"""
    
    def __init__(self, message: str, service: Optional[str] = None, 
                 status_code: Optional[int] = None, retry_after: Optional[int] = None):
        solutions = []
        details = None
        
        if service:
            details = f"Service: {service}"
            if status_code:
                details += f", Status: {status_code}"
        
        if status_code:
            if status_code == 429:  # Rate limited
                solutions = [
                    "Wait before retrying (rate limit exceeded)",
                    "Implement exponential backoff",
                    "Check your API plan limits"
                ]
                if retry_after:
                    solutions.insert(0, f"Wait {retry_after} seconds before retrying")
            elif status_code >= 500:  # Server error
                solutions = [
                    "Retry the operation (server error)",
                    "Check service status page",
                    "Try again in a few minutes"
                ]
            elif status_code == 401:  # Unauthorized
                solutions = [
                    "Check your API key is correct",
                    "Verify API key permissions",
                    "Regenerate your API key if necessary"
                ]
            elif status_code == 404:  # Not found
                solutions = [
                    "Verify the endpoint URL is correct",
                    "Check that the requested resource exists",
                    "Confirm API version compatibility"
                ]
        else:
            solutions = [
                "Check your internet connection",
                "Verify DNS resolution is working",
                "Try again in a few minutes",
                "Check if you're behind a firewall or proxy"
            ]
        
        super().__init__(
            message,
            details=details,
            solutions=solutions,
            help_url="https://docs.anthropic.com/claude-code/troubleshooting#network-issues"
        )
        self.service = service
        self.status_code = status_code
        self.retry_after = retry_after


# Error reporting utilities
def create_error_report(error: MeetingProcessorError, context: Optional[Dict[str, Any]] = None) -> str:
    """Create a detailed error report for user debugging"""
    from datetime import datetime
    
    report_data = error.get_error_report()
    
    # Add context information
    if context:
        report_data['context'] = context
    
    # Generate markdown report
    content = f"""# Meeting Processor Error Report

## Error Information
- **Type:** {report_data['error_type']}
- **Message:** {report_data['message']}
- **Time:** {datetime.now().isoformat()}

"""
    
    if report_data.get('details'):
        content += f"## Details\n{report_data['details']}\n\n"
    
    if report_data.get('solutions'):
        content += "## Recommended Solutions\n"
        for i, solution in enumerate(report_data['solutions'], 1):
            content += f"{i}. {solution}\n"
        content += "\n"
    
    if context:
        content += "## Context Information\n"
        for key, value in context.items():
            content += f"- **{key.replace('_', ' ').title()}:** {value}\n"
        content += "\n"
    
    if report_data.get('help_url'):
        content += f"## Additional Help\nFor more information, see: {report_data['help_url']}\n\n"
    
    content += """## Next Steps
1. Review the error message and details above
2. Try the recommended solutions in order
3. Check system resources (disk space, memory, network)
4. Retry the operation if the issue might be temporary
5. Check the troubleshooting guide if problems persist

---
*Generated by Meeting Processor Error Reporting System*
"""
    
    return content


def handle_error_with_report(error: Exception, filename: str, output_dir: str, 
                           context: Optional[Dict[str, Any]] = None) -> str:
    """Handle an error and create a detailed report file"""
    import os
    from pathlib import Path
    
    # Convert to MeetingProcessorError if needed
    if not isinstance(error, MeetingProcessorError):
        if "ffmpeg" in str(error).lower():
            error = AudioProcessingError(str(error), filename)
        elif "openai" in str(error).lower() or "whisper" in str(error).lower():
            error = TranscriptionError(str(error), filename)
        elif "anthropic" in str(error).lower() or "claude" in str(error).lower():
            error = AnalysisError(str(error), filename)
        else:
            error = MeetingProcessorError(str(error))
    
    # Create error report
    report_content = create_error_report(error, context)
    
    # Save to file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_filename = filename.replace('.', '_').replace(' ', '_')
    report_filename = f"ERROR-{error.__class__.__name__}-{safe_filename}-{timestamp}.md"
    
    report_path = Path(output_dir) / report_filename
    try:
        report_path.write_text(report_content, encoding="utf-8")
        return str(report_path)
    except Exception:
        return ""  # Couldn't save report