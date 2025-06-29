"""
Retry handling utilities with exponential backoff for Meeting Processor
Provides robust error handling for API calls and I/O operations
"""

import time
import random
import functools
from typing import Type, Tuple, Callable, Any, Optional, List
from utils.logger import LoggerMixin, log_warning, log_error


class RetryableError(Exception):
    """Base exception for errors that should be retried"""
    pass


class APIRetryableError(RetryableError):
    """API-related errors that should be retried"""
    pass


class IORetryableError(RetryableError):
    """I/O-related errors that should be retried"""
    pass


class RetryHandler(LoggerMixin):
    """Handles retry logic with exponential backoff and jitter"""
    
    def __init__(self, 
                 max_attempts: int = 3,
                 base_delay: float = 1.0,
                 max_delay: float = 60.0,
                 exponential_base: float = 2.0,
                 jitter: bool = True):
        """
        Initialize retry handler
        
        Args:
            max_attempts: Maximum number of retry attempts
            base_delay: Base delay in seconds
            max_delay: Maximum delay in seconds
            exponential_base: Base for exponential backoff
            jitter: Whether to add random jitter to delays
        """
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
    
    def calculate_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt number"""
        if attempt <= 0:
            return 0
        
        # Exponential backoff
        delay = self.base_delay * (self.exponential_base ** (attempt - 1))
        
        # Cap at max delay
        delay = min(delay, self.max_delay)
        
        # Add jitter to prevent thundering herd
        if self.jitter:
            delay = delay * (0.5 + random.random() * 0.5)
        
        return delay
    
    def retry(self, 
              retryable_exceptions: Tuple[Type[Exception], ...] = (RetryableError,),
              non_retryable_exceptions: Tuple[Type[Exception], ...] = (),
              context: Optional[str] = None):
        """
        Decorator for retry logic
        
        Args:
            retryable_exceptions: Tuple of exception types to retry on
            non_retryable_exceptions: Tuple of exception types to never retry on
            context: Optional context string for logging
        """
        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            def wrapper(*args, **kwargs) -> Any:
                last_exception = None
                func_name = func.__name__
                
                for attempt in range(1, self.max_attempts + 1):
                    try:
                        return func(*args, **kwargs)
                    
                    except non_retryable_exceptions as e:
                        # Don't retry these exceptions
                        log_error(f"❌ Non-retryable error in {func_name}: {e}")
                        raise
                    
                    except retryable_exceptions as e:
                        last_exception = e
                        
                        if attempt == self.max_attempts:
                            # Final attempt failed
                            context_str = f" ({context})" if context else ""
                            log_error(f"💥 All retry attempts failed for {func_name}{context_str}: {e}")
                            raise
                        
                        # Calculate delay and wait
                        delay = self.calculate_delay(attempt)
                        context_str = f" ({context})" if context else ""
                        log_warning(f"🔄 Attempt {attempt}/{self.max_attempts} failed for {func_name}{context_str}: {e}. Retrying in {delay:.2f}s...")
                        
                        time.sleep(delay)
                    
                    except Exception as e:
                        # Unexpected exception - don't retry
                        log_error(f"❌ Unexpected error in {func_name}: {e}")
                        raise
                
                # This should never be reached, but just in case
                if last_exception:
                    raise last_exception
                
            return wrapper
        return decorator


# Pre-configured retry handlers for common scenarios
api_retry = RetryHandler(
    max_attempts=3,
    base_delay=2.0,
    max_delay=30.0,
    exponential_base=2.0,
    jitter=True
)

io_retry = RetryHandler(
    max_attempts=2,
    base_delay=0.5,
    max_delay=5.0,
    exponential_base=2.0,
    jitter=True
)

network_retry = RetryHandler(
    max_attempts=5,
    base_delay=1.0,
    max_delay=60.0,
    exponential_base=2.0,
    jitter=True
)


def with_retry(retryable_exceptions: Tuple[Type[Exception], ...] = (RetryableError,),
               max_attempts: int = 3,
               base_delay: float = 1.0,
               context: Optional[str] = None):
    """
    Simple retry decorator factory
    
    Args:
        retryable_exceptions: Exceptions to retry on
        max_attempts: Maximum retry attempts
        base_delay: Base delay in seconds
        context: Optional context for logging
    """
    handler = RetryHandler(max_attempts=max_attempts, base_delay=base_delay)
    return handler.retry(retryable_exceptions=retryable_exceptions, context=context)


# Common exception mappings for API services
OPENAI_RETRYABLE_EXCEPTIONS = (
    # Add OpenAI specific retryable exceptions here
    ConnectionError,
    TimeoutError,
    APIRetryableError,
)

ANTHROPIC_RETRYABLE_EXCEPTIONS = (
    # Add Anthropic specific retryable exceptions here
    ConnectionError,
    TimeoutError,
    APIRetryableError,
)

GOOGLE_DRIVE_RETRYABLE_EXCEPTIONS = (
    # Add Google Drive API specific retryable exceptions here
    ConnectionError,
    TimeoutError,
    APIRetryableError,
)

FILE_IO_RETRYABLE_EXCEPTIONS = (
    PermissionError,
    IORetryableError,
    OSError,  # General OS errors
)


def handle_api_errors(func: Callable) -> Callable:
    """Decorator to convert API errors to retryable errors"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            # Convert specific API errors to retryable errors
            error_message = str(e).lower()
            
            # Rate limiting
            if any(term in error_message for term in ['rate limit', 'quota', 'too many requests']):
                raise APIRetryableError(f"Rate limited: {e}")
            
            # Network issues
            if any(term in error_message for term in ['timeout', 'connection', 'network']):
                raise APIRetryableError(f"Network error: {e}")
            
            # Server errors (5xx)
            if any(term in error_message for term in ['server error', '500', '502', '503', '504']):
                raise APIRetryableError(f"Server error: {e}")
            
            # Re-raise as is if not retryable
            raise
    
    return wrapper


def handle_file_errors(func: Callable) -> Callable:
    """Decorator to convert file I/O errors to retryable errors"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (PermissionError, OSError) as e:
            error_message = str(e).lower()
            
            # Temporary file locks or permission issues
            if any(term in error_message for term in ['permission denied', 'file in use', 'locked']):
                raise IORetryableError(f"File access error: {e}")
            
            # Disk space issues (generally not retryable)
            if 'no space left' in error_message:
                raise  # Don't retry disk space issues
            
            # Network drive issues
            if any(term in error_message for term in ['network', 'remote']):
                raise IORetryableError(f"Network drive error: {e}")
            
            # Re-raise as is
            raise
    
    return wrapper