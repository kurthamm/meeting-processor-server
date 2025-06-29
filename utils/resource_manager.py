"""
Resource management utilities for Meeting Processor
Handles file cleanup, memory management, and connection pooling
"""

import gc
import os
import tempfile
import threading
import weakref
from pathlib import Path
from typing import Optional, Set, ContextManager, Any
from contextlib import contextmanager
from utils.logger import LoggerMixin, log_warning, log_error, log_success


class ResourceManager(LoggerMixin):
    """Manages temporary files and memory cleanup"""
    
    def __init__(self):
        self._temp_files: Set[Path] = set()
        self._temp_dirs: Set[Path] = set()
        self._lock = threading.RLock()
        self._cleanup_on_exit = True
    
    @contextmanager
    def temporary_file(self, suffix: str = '', prefix: str = 'mp_', 
                      delete_on_exit: bool = True) -> ContextManager[Path]:
        """
        Context manager for temporary files that are automatically cleaned up
        
        Args:
            suffix: File suffix (e.g., '.mp3', '.txt')
            prefix: File prefix
            delete_on_exit: Whether to delete file when context exits
        
        Yields:
            Path: Path to temporary file
        """
        temp_file = None
        try:
            # Create temporary file
            fd, temp_path = tempfile.mkstemp(suffix=suffix, prefix=prefix)
            os.close(fd)  # Close file descriptor immediately
            temp_file = Path(temp_path)
            
            with self._lock:
                self._temp_files.add(temp_file)
            
            self.logger.info(f"📁 Created temporary file: {temp_file.name}")
            yield temp_file
            
        except Exception as e:
            log_error(self.logger, f"Error with temporary file: {e}")
            raise
        finally:
            if temp_file and delete_on_exit:
                self._cleanup_temp_file(temp_file)
    
    @contextmanager
    def temporary_directory(self, prefix: str = 'mp_dir_', 
                          delete_on_exit: bool = True) -> ContextManager[Path]:
        """
        Context manager for temporary directories
        
        Args:
            prefix: Directory prefix
            delete_on_exit: Whether to delete directory when context exits
        
        Yields:
            Path: Path to temporary directory
        """
        temp_dir = None
        try:
            temp_dir = Path(tempfile.mkdtemp(prefix=prefix))
            
            with self._lock:
                self._temp_dirs.add(temp_dir)
            
            self.logger.info(f"📁 Created temporary directory: {temp_dir.name}")
            yield temp_dir
            
        except Exception as e:
            log_error(self.logger, f"Error with temporary directory: {e}")
            raise
        finally:
            if temp_dir and delete_on_exit:
                self._cleanup_temp_dir(temp_dir)
    
    def _cleanup_temp_file(self, temp_file: Path) -> None:
        """Safely cleanup a temporary file"""
        try:
            if temp_file.exists():
                temp_file.unlink()
                self.logger.info(f"🗑️ Cleaned up temporary file: {temp_file.name}")
            
            with self._lock:
                self._temp_files.discard(temp_file)
                
        except Exception as e:
            log_warning(self.logger, f"Failed to cleanup temporary file {temp_file}: {e}")
    
    def _cleanup_temp_dir(self, temp_dir: Path) -> None:
        """Safely cleanup a temporary directory"""
        try:
            if temp_dir.exists():
                import shutil
                shutil.rmtree(temp_dir)
                self.logger.info(f"🗑️ Cleaned up temporary directory: {temp_dir.name}")
            
            with self._lock:
                self._temp_dirs.discard(temp_dir)
                
        except Exception as e:
            log_warning(self.logger, f"Failed to cleanup temporary directory {temp_dir}: {e}")
    
    def cleanup_all(self) -> None:
        """Clean up all tracked temporary files and directories"""
        self.logger.info("🧹 Starting resource cleanup...")
        
        with self._lock:
            # Cleanup temporary files
            temp_files = self._temp_files.copy()
            for temp_file in temp_files:
                self._cleanup_temp_file(temp_file)
            
            # Cleanup temporary directories
            temp_dirs = self._temp_dirs.copy()
            for temp_dir in temp_dirs:
                self._cleanup_temp_dir(temp_dir)
        
        # Force garbage collection
        gc.collect()
        self.logger.info("✅ Resource cleanup completed")
    
    def get_memory_usage(self) -> dict:
        """Get current memory usage statistics"""
        try:
            import psutil
            process = psutil.Process()
            memory_info = process.memory_info()
            
            return {
                'rss_mb': memory_info.rss / 1024 / 1024,
                'vms_mb': memory_info.vms / 1024 / 1024,
                'percent': process.memory_percent(),
                'temp_files': len(self._temp_files),
                'temp_dirs': len(self._temp_dirs)
            }
        except ImportError:
            # psutil not available
            return {
                'temp_files': len(self._temp_files),
                'temp_dirs': len(self._temp_dirs)
            }


class ConnectionPool:
    """Simple connection pool for reusing expensive objects"""
    
    def __init__(self, max_size: int = 10):
        self.max_size = max_size
        self._pool = []
        self._in_use = set()
        self._lock = threading.RLock()
        self._factory = None
    
    def set_factory(self, factory_func):
        """Set the factory function for creating new connections"""
        self._factory = factory_func
    
    @contextmanager
    def get_connection(self):
        """Get a connection from the pool"""
        conn = None
        try:
            conn = self._acquire()
            yield conn
        finally:
            if conn:
                self._release(conn)
    
    def _acquire(self):
        """Acquire a connection from the pool"""
        with self._lock:
            # Try to get from pool
            if self._pool:
                conn = self._pool.pop()
                self._in_use.add(id(conn))
                return conn
            
            # Create new connection if factory is available
            if self._factory:
                conn = self._factory()
                self._in_use.add(id(conn))
                return conn
            
            raise RuntimeError("No factory function set for connection pool")
    
    def _release(self, conn):
        """Release a connection back to the pool"""
        with self._lock:
            conn_id = id(conn)
            if conn_id in self._in_use:
                self._in_use.remove(conn_id)
                
                # Add back to pool if not full
                if len(self._pool) < self.max_size:
                    self._pool.append(conn)
    
    def close_all(self):
        """Close all connections in the pool"""
        with self._lock:
            for conn in self._pool:
                if hasattr(conn, 'close'):
                    try:
                        conn.close()
                    except:
                        pass
            self._pool.clear()
            self._in_use.clear()


class MemoryMonitor(LoggerMixin):
    """Monitor memory usage and trigger cleanup when needed"""
    
    def __init__(self, threshold_mb: int = 500, resource_manager: Optional[ResourceManager] = None):
        self.threshold_mb = threshold_mb
        self.resource_manager = resource_manager
        self._last_check_size = 0
        self._alert_threshold = 0.85  # Alert at 85% of system memory
        self._critical_threshold = 0.95  # Critical at 95% of system memory
    
    def check_memory_usage(self) -> bool:
        """
        Check if memory usage is above threshold with enhanced monitoring
        
        Returns:
            bool: True if cleanup was triggered
        """
        try:
            import psutil
            
            # Get system memory info
            system_memory = psutil.virtual_memory()
            system_usage_percent = system_memory.percent / 100
            
            # Get process memory info
            process = psutil.Process()
            process_memory_mb = process.memory_info().rss / 1024 / 1024
            
            # Check critical system memory usage
            if system_usage_percent > self._critical_threshold:
                log_warning(self.logger, f"🚨 CRITICAL: System memory usage: {system_usage_percent*100:.1f}%")
                self._trigger_emergency_cleanup()
                return True
            
            # Check alert threshold
            elif system_usage_percent > self._alert_threshold:
                log_warning(self.logger, f"⚠️ High system memory usage: {system_usage_percent*100:.1f}%")
                self._log_memory_details()
            
            # Check process memory threshold
            if process_memory_mb > self.threshold_mb:
                log_warning(self.logger, f"🚨 Process memory usage high: {process_memory_mb:.1f}MB (threshold: {self.threshold_mb}MB)")
                self._trigger_cleanup()
                return True
            
            # Log significant memory increases
            if process_memory_mb > self._last_check_size + 100:  # 100MB increase
                self.logger.info(f"📊 Memory usage: {process_memory_mb:.1f}MB (system: {system_usage_percent*100:.1f}%)")
            
            self._last_check_size = process_memory_mb
            return False
            
        except ImportError:
            # psutil not available, skip monitoring
            self.logger.warning("⚠️ psutil not available - memory monitoring disabled")
            return False
    
    def check_disk_space(self, path: str = "/", threshold_percent: float = 0.9) -> bool:
        """
        Check disk space availability
        
        Args:
            path: Path to check (default: root)
            threshold_percent: Threshold as percentage (0.9 = 90%)
            
        Returns:
            bool: True if disk space is sufficient
        """
        try:
            import psutil
            disk = psutil.disk_usage(path)
            usage_percent = disk.used / disk.total
            
            if usage_percent > threshold_percent:
                log_warning(self.logger, f"🚨 Disk space low: {usage_percent*100:.1f}% used (threshold: {threshold_percent*100:.1f}%)")
                self._log_disk_details(disk)
                return False
            
            return True
            
        except Exception as e:
            self.logger.warning(f"Could not check disk space: {e}")
            return True  # Assume sufficient if check fails
    
    def get_resource_status(self) -> Dict[str, Any]:
        """Get comprehensive resource status"""
        try:
            import psutil
            
            # Memory info
            system_memory = psutil.virtual_memory()
            process = psutil.Process()
            process_memory = process.memory_info()
            
            # Disk info
            disk = psutil.disk_usage('/')
            
            # CPU info
            cpu_percent = psutil.cpu_percent(interval=0.1)
            cpu_count = psutil.cpu_count()
            
            status = {
                'timestamp': datetime.now().isoformat(),
                'memory': {
                    'system_total_gb': system_memory.total / (1024**3),
                    'system_used_percent': system_memory.percent,
                    'system_available_gb': system_memory.available / (1024**3),
                    'process_rss_mb': process_memory.rss / (1024**2),
                    'process_vms_mb': process_memory.vms / (1024**2),
                    'alerts': {
                        'system_high': system_memory.percent > (self._alert_threshold * 100),
                        'system_critical': system_memory.percent > (self._critical_threshold * 100),
                        'process_high': (process_memory.rss / (1024**2)) > self.threshold_mb
                    }
                },
                'disk': {
                    'total_gb': disk.total / (1024**3),
                    'used_percent': (disk.used / disk.total) * 100,
                    'free_gb': disk.free / (1024**3),
                    'alerts': {
                        'low_space': (disk.used / disk.total) > 0.9
                    }
                },
                'cpu': {
                    'usage_percent': cpu_percent,
                    'core_count': cpu_count,
                    'alerts': {
                        'high_usage': cpu_percent > 80
                    }
                },
                'temp_files': len(self.resource_manager._temp_files) if self.resource_manager else 0,
                'temp_dirs': len(self.resource_manager._temp_dirs) if self.resource_manager else 0
            }
            
            return status
            
        except ImportError:
            return {
                'timestamp': datetime.now().isoformat(),
                'error': 'psutil not available - resource monitoring disabled'
            }
        except Exception as e:
            return {
                'timestamp': datetime.now().isoformat(),
                'error': f'Error getting resource status: {e}'
            }
    
    def _log_memory_details(self):
        """Log detailed memory information"""
        try:
            import psutil
            
            memory = psutil.virtual_memory()
            self.logger.info(f"💾 Memory Details:")
            self.logger.info(f"   Total: {memory.total / (1024**3):.1f} GB")
            self.logger.info(f"   Available: {memory.available / (1024**3):.1f} GB")
            self.logger.info(f"   Used: {memory.used / (1024**3):.1f} GB ({memory.percent:.1f}%)")
            
            # Show top memory consuming processes
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'memory_info']):
                try:
                    info = proc.info
                    if info['memory_info']:
                        memory_mb = info['memory_info'].rss / (1024**2)
                        if memory_mb > 50:  # Only show processes using >50MB
                            processes.append((info['name'], memory_mb))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            if processes:
                processes.sort(key=lambda x: x[1], reverse=True)
                self.logger.info("   Top memory consumers:")
                for name, mem_mb in processes[:5]:
                    self.logger.info(f"     {name}: {mem_mb:.1f} MB")
            
        except Exception as e:
            self.logger.debug(f"Could not get detailed memory info: {e}")
    
    def _log_disk_details(self, disk):
        """Log detailed disk information"""
        self.logger.info(f"💿 Disk Details:")
        self.logger.info(f"   Total: {disk.total / (1024**3):.1f} GB")
        self.logger.info(f"   Free: {disk.free / (1024**3):.1f} GB")
        self.logger.info(f"   Used: {disk.used / (1024**3):.1f} GB ({(disk.used/disk.total)*100:.1f}%)")
    
    def _trigger_emergency_cleanup(self):
        """Emergency cleanup for critical memory situations"""
        self.logger.warning("🚨 Triggering emergency cleanup due to critical memory usage")
        
        # Force garbage collection multiple times
        import gc
        for i in range(3):
            collected = gc.collect()
            self.logger.debug(f"GC pass {i+1}: collected {collected} objects")
        
        # Cleanup resources aggressively
        if self.resource_manager:
            self.resource_manager.cleanup_all()
        
        # Clear any caches if available
        try:
            import functools
            functools.lru_cache.cache_clear = getattr(functools.lru_cache, 'cache_clear', lambda: None)
        except:
            pass
        
        self.logger.info("🧹 Emergency cleanup completed")
    
    def _trigger_cleanup(self):
        """Trigger memory cleanup"""
        self.logger.info("🧹 Triggering memory cleanup...")
        
        # Cleanup resources if manager available
        if self.resource_manager:
            self.resource_manager.cleanup_all()
        
        # Force garbage collection
        gc.collect()
        
        self.logger.info("✅ Memory cleanup completed")


# Global resource manager instance
_global_resource_manager = None
_global_memory_monitor = None


def get_resource_manager() -> ResourceManager:
    """Get the global resource manager instance"""
    global _global_resource_manager
    if _global_resource_manager is None:
        _global_resource_manager = ResourceManager()
    return _global_resource_manager


def get_memory_monitor() -> MemoryMonitor:
    """Get the global memory monitor instance"""
    global _global_memory_monitor
    if _global_memory_monitor is None:
        resource_manager = get_resource_manager()
        _global_memory_monitor = MemoryMonitor(resource_manager=resource_manager)
    return _global_memory_monitor


def cleanup_resources():
    """Cleanup all global resources"""
    global _global_resource_manager, _global_memory_monitor
    
    if _global_resource_manager:
        _global_resource_manager.cleanup_all()
    
    if _global_memory_monitor:
        _global_memory_monitor._trigger_cleanup()


# Context managers for easy use
@contextmanager
def temp_file(suffix: str = '', prefix: str = 'mp_') -> ContextManager[Path]:
    """Convenient temporary file context manager"""
    resource_manager = get_resource_manager()
    with resource_manager.temporary_file(suffix=suffix, prefix=prefix) as temp_path:
        yield temp_path


@contextmanager
def temp_directory(prefix: str = 'mp_dir_') -> ContextManager[Path]:
    """Convenient temporary directory context manager"""
    resource_manager = get_resource_manager()
    with resource_manager.temporary_directory(prefix=prefix) as temp_path:
        yield temp_path