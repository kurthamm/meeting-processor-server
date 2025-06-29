"""
Async Batch Processing for Meeting Processor
Handles concurrent processing of multiple files with rate limiting and resource management
"""

import asyncio
import aiofiles
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Dict, Optional, Any, Callable, Awaitable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
from utils.logger import LoggerMixin, log_success, log_error


@dataclass
class ProcessingJob:
    """Represents a processing job for a single file"""
    file_path: Path
    file_info: Optional[Dict] = None
    priority: int = 1  # Higher numbers = higher priority
    submitted_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[Dict] = None
    error: Optional[str] = None
    progress: float = 0.0
    
    @property
    def is_completed(self) -> bool:
        return self.completed_at is not None
    
    @property
    def is_running(self) -> bool:
        return self.started_at is not None and self.completed_at is None
    
    @property
    def duration_seconds(self) -> Optional[float]:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None


class AsyncBatchProcessor(LoggerMixin):
    """Async batch processor with intelligent queueing and resource management"""
    
    def __init__(self, 
                 max_concurrent: int = 3,
                 max_queue_size: int = 50,
                 thread_pool_size: int = 5):
        """
        Initialize async batch processor
        
        Args:
            max_concurrent: Maximum concurrent processing jobs
            max_queue_size: Maximum queue size
            thread_pool_size: Size of thread pool for CPU-bound operations
        """
        self.max_concurrent = max_concurrent
        self.max_queue_size = max_queue_size
        
        # Async management
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.processing_queue = asyncio.Queue(maxsize=max_queue_size)
        self.priority_queue = asyncio.PriorityQueue(maxsize=max_queue_size)
        
        # Thread pool for CPU-bound operations
        self.thread_pool = ThreadPoolExecutor(max_workers=thread_pool_size)
        
        # Job tracking
        self.active_jobs: Dict[str, ProcessingJob] = {}
        self.completed_jobs: List[ProcessingJob] = []
        self.failed_jobs: List[ProcessingJob] = []
        
        # Rate limiting
        self.api_rate_limiter = asyncio.Semaphore(2)  # Max 2 concurrent API calls
        self.last_api_call = {}  # Track last API call time per service
        
        # Statistics
        self.stats = {
            'total_submitted': 0,
            'total_completed': 0,
            'total_failed': 0,
            'cache_hits': 0,
            'processing_time_total': 0.0
        }
        
        # Background tasks
        self._processor_task = None
        self._monitor_task = None
        self._running = False
    
    async def start(self):
        """Start the async processor"""
        if self._running:
            return
        
        self._running = True
        
        # Start background tasks
        self._processor_task = asyncio.create_task(self._process_queue())
        self._monitor_task = asyncio.create_task(self._monitor_resources())
        
        self.logger.info(f"🚀 Started async batch processor (max_concurrent: {self.max_concurrent})")
    
    async def stop(self):
        """Stop the async processor"""
        self._running = False
        
        # Cancel background tasks
        if self._processor_task:
            self._processor_task.cancel()
        if self._monitor_task:
            self._monitor_task.cancel()
        
        # Wait for current jobs to complete
        await self._wait_for_completion()
        
        # Shutdown thread pool
        self.thread_pool.shutdown(wait=True)
        
        self.logger.info("🛑 Stopped async batch processor")
    
    async def submit_file(self, file_path: Path, file_info: Optional[Dict] = None, 
                         priority: int = 1) -> str:
        """
        Submit a file for processing
        
        Args:
            file_path: Path to the file to process
            file_info: Optional metadata about the file
            priority: Priority level (higher = processed first)
            
        Returns:
            job_id: Unique identifier for tracking the job
        """
        if not self._running:
            await self.start()
        
        job_id = f"{file_path.name}_{datetime.now().timestamp()}"
        job = ProcessingJob(
            file_path=file_path,
            file_info=file_info,
            priority=priority
        )
        
        self.active_jobs[job_id] = job
        self.stats['total_submitted'] += 1
        
        # Add to priority queue (negative priority for max-heap behavior)
        await self.priority_queue.put((-priority, job_id))
        
        self.logger.debug(f"📥 Submitted job: {job_id} (priority: {priority})")
        return job_id
    
    async def submit_multiple_files(self, file_paths: List[Path], 
                                  batch_priority: int = 1) -> List[str]:
        """
        Submit multiple files for batch processing
        
        Args:
            file_paths: List of file paths to process
            batch_priority: Base priority for all files in batch
            
        Returns:
            List of job IDs
        """
        job_ids = []
        
        # Sort files by size (process smaller files first for faster feedback)
        files_with_size = []
        for path in file_paths:
            try:
                size = path.stat().st_size if path.exists() else 0
                files_with_size.append((path, size))
            except Exception:
                files_with_size.append((path, 0))
        
        # Sort by size, then submit with adjusted priorities
        files_with_size.sort(key=lambda x: x[1])
        
        for i, (path, size) in enumerate(files_with_size):
            # Give higher priority to smaller files in the batch
            file_priority = batch_priority + (len(files_with_size) - i)
            job_id = await self.submit_file(path, {"batch_index": i, "file_size": size}, file_priority)
            job_ids.append(job_id)
        
        self.logger.info(f"📥 Submitted batch of {len(file_paths)} files")
        return job_ids
    
    async def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a specific job"""
        if job_id in self.active_jobs:
            job = self.active_jobs[job_id]
            return {
                'job_id': job_id,
                'file_path': str(job.file_path),
                'status': 'running' if job.is_running else 'queued',
                'progress': job.progress,
                'submitted_at': job.submitted_at.isoformat(),
                'started_at': job.started_at.isoformat() if job.started_at else None,
                'duration': job.duration_seconds,
                'error': job.error
            }
        
        # Check completed jobs
        for job in self.completed_jobs + self.failed_jobs:
            if job.file_path.name in job_id:  # Loose matching
                return {
                    'job_id': job_id,
                    'file_path': str(job.file_path),
                    'status': 'completed' if job in self.completed_jobs else 'failed',
                    'progress': 1.0 if job in self.completed_jobs else job.progress,
                    'submitted_at': job.submitted_at.isoformat(),
                    'started_at': job.started_at.isoformat() if job.started_at else None,
                    'completed_at': job.completed_at.isoformat() if job.completed_at else None,
                    'duration': job.duration_seconds,
                    'error': job.error,
                    'result': job.result
                }
        
        return None
    
    async def get_queue_status(self) -> Dict[str, Any]:
        """Get overall queue and processing status"""
        active_count = len([j for j in self.active_jobs.values() if j.is_running])
        queued_count = len([j for j in self.active_jobs.values() if not j.is_running])
        
        avg_processing_time = 0
        if self.stats['total_completed'] > 0:
            avg_processing_time = self.stats['processing_time_total'] / self.stats['total_completed']
        
        return {
            'timestamp': datetime.now().isoformat(),
            'queue_size': queued_count,
            'active_jobs': active_count,
            'completed_jobs': len(self.completed_jobs),
            'failed_jobs': len(self.failed_jobs),
            'cache_hit_rate': self.stats['cache_hits'] / max(self.stats['total_submitted'], 1),
            'avg_processing_time_seconds': avg_processing_time,
            'total_submitted': self.stats['total_submitted'],
            'success_rate': self.stats['total_completed'] / max(self.stats['total_submitted'], 1),
            'is_running': self._running
        }
    
    async def wait_for_completion(self, timeout: Optional[float] = None) -> bool:
        """
        Wait for all jobs to complete
        
        Args:
            timeout: Maximum time to wait in seconds
            
        Returns:
            True if all jobs completed, False if timeout
        """
        try:
            await asyncio.wait_for(self._wait_for_completion(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False
    
    async def _wait_for_completion(self):
        """Internal method to wait for completion"""
        while self.active_jobs or not self.priority_queue.empty():
            await asyncio.sleep(0.1)
    
    async def _process_queue(self):
        """Background task to process the queue"""
        while self._running:
            try:
                # Get next job from priority queue
                try:
                    priority, job_id = await asyncio.wait_for(
                        self.priority_queue.get(), 
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                if job_id not in self.active_jobs:
                    continue
                
                # Process job with semaphore to limit concurrency
                asyncio.create_task(self._process_job(job_id))
                
            except Exception as e:
                log_error(self.logger, f"Error in queue processor: {e}")
                await asyncio.sleep(1)
    
    async def _process_job(self, job_id: str):
        """Process a single job"""
        async with self.semaphore:
            job = self.active_jobs.get(job_id)
            if not job:
                return
            
            try:
                job.started_at = datetime.now()
                self.logger.info(f"🔄 Processing: {job.file_path.name}")
                
                # Import here to avoid circular imports
                from main import MeetingProcessor
                
                # Create processor instance for this job
                # Note: In a real implementation, you'd want to reuse the processor
                # This is a simplified version for demonstration
                processor = MeetingProcessor()
                
                # Process the file using the existing processor
                await self._run_in_thread(
                    processor._process_meeting_file,
                    job.file_path,
                    job.file_info
                )
                
                job.completed_at = datetime.now()
                job.progress = 1.0
                
                # Move to completed
                self.completed_jobs.append(job)
                del self.active_jobs[job_id]
                
                self.stats['total_completed'] += 1
                if job.duration_seconds:
                    self.stats['processing_time_total'] += job.duration_seconds
                
                log_success(self.logger, f"Completed: {job.file_path.name} ({job.duration_seconds:.1f}s)")
                
            except Exception as e:
                job.error = str(e)
                job.completed_at = datetime.now()
                
                # Move to failed
                self.failed_jobs.append(job)
                del self.active_jobs[job_id]
                
                self.stats['total_failed'] += 1
                
                log_error(self.logger, f"Failed: {job.file_path.name}: {e}")
    
    async def _run_in_thread(self, func: Callable, *args, **kwargs):
        """Run a synchronous function in the thread pool"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.thread_pool, func, *args, **kwargs)
    
    async def _monitor_resources(self):
        """Background task to monitor resources and adjust processing"""
        while self._running:
            try:
                # Check system resources
                try:
                    import psutil
                    memory_percent = psutil.virtual_memory().percent
                    cpu_percent = psutil.cpu_percent(interval=1)
                    
                    # Adjust concurrency based on resource usage
                    if memory_percent > 85 or cpu_percent > 90:
                        # Reduce concurrency if resources are stressed
                        if self.max_concurrent > 1:
                            self.max_concurrent = max(1, self.max_concurrent - 1)
                            self.semaphore = asyncio.Semaphore(self.max_concurrent)
                            self.logger.warning(f"⚠️ Reduced concurrency to {self.max_concurrent} due to high resource usage")
                    elif memory_percent < 70 and cpu_percent < 70:
                        # Increase concurrency if resources are available
                        if self.max_concurrent < 5:
                            self.max_concurrent += 1
                            self.semaphore = asyncio.Semaphore(self.max_concurrent)
                            self.logger.info(f"📈 Increased concurrency to {self.max_concurrent}")
                    
                except ImportError:
                    pass  # psutil not available
                
                await asyncio.sleep(30)  # Check every 30 seconds
                
            except Exception as e:
                self.logger.debug(f"Error in resource monitor: {e}")
                await asyncio.sleep(60)
    
    async def cleanup_completed_jobs(self, max_age_hours: int = 24):
        """Clean up old completed/failed jobs"""
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
        
        # Cleanup completed jobs
        old_completed = [j for j in self.completed_jobs if j.completed_at and j.completed_at < cutoff_time]
        for job in old_completed:
            self.completed_jobs.remove(job)
        
        # Cleanup failed jobs
        old_failed = [j for j in self.failed_jobs if j.completed_at and j.completed_at < cutoff_time]
        for job in old_failed:
            self.failed_jobs.remove(job)
        
        if old_completed or old_failed:
            self.logger.info(f"🧹 Cleaned up {len(old_completed)} completed and {len(old_failed)} failed jobs")
    
    async def export_job_history(self, output_path: Path) -> bool:
        """Export job history to JSON file"""
        try:
            history = {
                'export_time': datetime.now().isoformat(),
                'statistics': self.stats,
                'completed_jobs': [
                    {
                        'file_path': str(job.file_path),
                        'submitted_at': job.submitted_at.isoformat(),
                        'started_at': job.started_at.isoformat() if job.started_at else None,
                        'completed_at': job.completed_at.isoformat() if job.completed_at else None,
                        'duration_seconds': job.duration_seconds,
                        'file_info': job.file_info
                    }
                    for job in self.completed_jobs
                ],
                'failed_jobs': [
                    {
                        'file_path': str(job.file_path),
                        'submitted_at': job.submitted_at.isoformat(),
                        'started_at': job.started_at.isoformat() if job.started_at else None,
                        'completed_at': job.completed_at.isoformat() if job.completed_at else None,
                        'error': job.error,
                        'file_info': job.file_info
                    }
                    for job in self.failed_jobs
                ]
            }
            
            async with aiofiles.open(output_path, 'w') as f:
                await f.write(json.dumps(history, indent=2))
            
            self.logger.info(f"📊 Exported job history to {output_path}")
            return True
            
        except Exception as e:
            log_error(self.logger, f"Failed to export job history: {e}")
            return False


# Global async processor instance
_global_async_processor = None


def get_async_processor(max_concurrent: int = 3) -> AsyncBatchProcessor:
    """Get the global async processor instance"""
    global _global_async_processor
    if _global_async_processor is None:
        _global_async_processor = AsyncBatchProcessor(max_concurrent=max_concurrent)
    return _global_async_processor