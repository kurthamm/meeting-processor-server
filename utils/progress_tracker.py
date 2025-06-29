"""
Enhanced Progress Tracking for Meeting Processor
Provides detailed progress feedback with percentages, ETAs, and stage tracking
"""

import time
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from utils.logger import LoggerMixin, log_success


@dataclass
class ProcessingStage:
    """Represents a stage in the processing pipeline"""
    name: str
    display_name: str
    emoji: str
    estimated_duration: float = 0.0  # seconds
    weight: float = 1.0  # relative weight for progress calculation


@dataclass
class ProcessingProgress:
    """Tracks progress through processing stages"""
    filename: str
    stages: List[ProcessingStage] = field(default_factory=list)
    current_stage_index: int = 0
    stage_progress: float = 0.0  # 0.0 to 1.0
    start_time: datetime = field(default_factory=datetime.now)
    stage_start_time: datetime = field(default_factory=datetime.now)
    file_size_mb: float = 0.0
    
    def __post_init__(self):
        if not self.stages:
            self.stages = self._default_stages()
    
    def _default_stages(self) -> List[ProcessingStage]:
        """Default processing stages for meeting files"""
        return [
            ProcessingStage("validate", "Validating File", "🔍", 5.0, 0.5),
            ProcessingStage("convert", "Converting Audio", "🎵", 30.0, 2.0),
            ProcessingStage("transcribe", "Transcribing", "🎤", 120.0, 3.0),
            ProcessingStage("analyze", "AI Analysis", "🧠", 60.0, 2.0),
            ProcessingStage("entities", "Extracting Entities", "🏷️", 15.0, 1.0),
            ProcessingStage("save", "Saving Results", "💾", 10.0, 0.5),
        ]
    
    @property
    def current_stage(self) -> ProcessingStage:
        """Get current processing stage"""
        if self.current_stage_index < len(self.stages):
            return self.stages[self.current_stage_index]
        return self.stages[-1]
    
    @property
    def overall_progress(self) -> float:
        """Calculate overall progress as percentage (0-100)"""
        if not self.stages:
            return 0.0
        
        total_weight = sum(stage.weight for stage in self.stages)
        completed_weight = sum(stage.weight for stage in self.stages[:self.current_stage_index])
        current_stage_weight = self.current_stage.weight * self.stage_progress
        
        return ((completed_weight + current_stage_weight) / total_weight) * 100
    
    @property
    def estimated_total_duration(self) -> float:
        """Estimate total processing time based on file size"""
        base_duration = sum(stage.estimated_duration for stage in self.stages)
        # Adjust based on file size (larger files take longer)
        size_multiplier = max(1.0, self.file_size_mb / 10.0)  # 10MB baseline
        return base_duration * size_multiplier
    
    @property
    def eta_seconds(self) -> Optional[float]:
        """Calculate estimated time to completion"""
        progress = self.overall_progress
        if progress <= 0:
            return None
        
        elapsed = (datetime.now() - self.start_time).total_seconds()
        if progress >= 100:
            return 0
        
        total_estimated = elapsed * (100 / progress)
        return max(0, total_estimated - elapsed)
    
    @property
    def eta_formatted(self) -> str:
        """Get formatted ETA string"""
        eta = self.eta_seconds
        if eta is None:
            return "calculating..."
        elif eta < 60:
            return f"{eta:.0f}s"
        elif eta < 3600:
            return f"{eta/60:.1f}m"
        else:
            return f"{eta/3600:.1f}h"


class ProgressTracker(LoggerMixin):
    """Enhanced progress tracker with detailed logging and notifications"""
    
    def __init__(self):
        self.active_sessions: Dict[str, ProcessingProgress] = {}
        self.last_update_time: Dict[str, datetime] = {}
        self.update_interval = 10.0  # seconds between progress updates
    
    def start_processing(self, filename: str, file_size_mb: float = 0.0) -> ProcessingProgress:
        """Start tracking progress for a file"""
        progress = ProcessingProgress(
            filename=filename,
            file_size_mb=file_size_mb
        )
        
        self.active_sessions[filename] = progress
        self.last_update_time[filename] = datetime.now()
        
        self.logger.info(f"🎬 Starting processing: {filename} ({file_size_mb:.1f}MB)")
        self._log_progress(progress, force=True)
        
        return progress
    
    def update_stage(self, filename: str, stage_name: str, progress: float = 0.0, 
                    details: str = "") -> None:
        """Update current stage progress"""
        if filename not in self.active_sessions:
            return
        
        session = self.active_sessions[filename]
        
        # Find stage index
        stage_index = -1
        for i, stage in enumerate(session.stages):
            if stage.name == stage_name:
                stage_index = i
                break
        
        if stage_index == -1:
            self.logger.warning(f"Unknown stage: {stage_name}")
            return
        
        # Update stage if we've progressed
        if stage_index > session.current_stage_index:
            session.current_stage_index = stage_index
            session.stage_start_time = datetime.now()
            session.stage_progress = 0.0
        
        # Update progress within current stage
        session.stage_progress = max(0.0, min(1.0, progress))
        
        # Log progress if enough time has passed or significant change
        self._log_progress_if_needed(session, details)
    
    def complete_stage(self, filename: str, stage_name: str, details: str = "") -> None:
        """Mark a stage as complete"""
        self.update_stage(filename, stage_name, 1.0, details)
        
        if filename in self.active_sessions:
            session = self.active_sessions[filename]
            stage = session.current_stage
            stage_duration = (datetime.now() - session.stage_start_time).total_seconds()
            
            self.logger.info(
                f"✅ {stage.emoji} {stage.display_name} complete: {filename} "
                f"({stage_duration:.1f}s) {details}"
            )
    
    def complete_processing(self, filename: str, success: bool = True) -> None:
        """Mark processing as complete"""
        if filename not in self.active_sessions:
            return
        
        session = self.active_sessions[filename]
        total_duration = (datetime.now() - session.start_time).total_seconds()
        
        if success:
            log_success(
                self.logger, 
                f"Processing complete: {filename} "
                f"({total_duration/60:.1f}m total, {session.file_size_mb:.1f}MB)"
            )
        else:
            self.logger.error(f"❌ Processing failed: {filename} after {total_duration/60:.1f}m")
        
        # Clean up
        del self.active_sessions[filename]
        if filename in self.last_update_time:
            del self.last_update_time[filename]
    
    def _log_progress_if_needed(self, session: ProcessingProgress, details: str = "") -> None:
        """Log progress if enough time has passed"""
        now = datetime.now()
        last_update = self.last_update_time.get(session.filename, session.start_time)
        
        if (now - last_update).total_seconds() >= self.update_interval:
            self._log_progress(session, details)
            self.last_update_time[session.filename] = now
    
    def _log_progress(self, session: ProcessingProgress, details: str = "", force: bool = False) -> None:
        """Log detailed progress information"""
        stage = session.current_stage
        progress_pct = session.overall_progress
        eta = session.eta_formatted
        
        # Create progress bar
        bar_length = 20
        filled_length = int(bar_length * progress_pct / 100)
        bar = '█' * filled_length + '░' * (bar_length - filled_length)
        
        # Build status message
        status_parts = [
            f"{stage.emoji} {stage.display_name}",
            f"[{bar}] {progress_pct:.1f}%",
            f"ETA: {eta}"
        ]
        
        if details:
            status_parts.append(f"({details})")
        
        status = " • ".join(status_parts)
        
        # Log with appropriate level
        if force or progress_pct % 25 == 0:  # Log at major milestones
            self.logger.info(f"🔄 {session.filename}: {status}")
        else:
            self.logger.debug(f"Progress {session.filename}: {status}")
    
    def get_active_sessions(self) -> Dict[str, ProcessingProgress]:
        """Get all active processing sessions"""
        return self.active_sessions.copy()
    
    def get_overall_stats(self) -> Dict[str, Any]:
        """Get overall processing statistics"""
        if not self.active_sessions:
            return {"active_files": 0, "total_progress": 0}
        
        total_progress = sum(s.overall_progress for s in self.active_sessions.values())
        avg_progress = total_progress / len(self.active_sessions)
        
        return {
            "active_files": len(self.active_sessions),
            "average_progress": avg_progress,
            "total_progress": total_progress,
            "sessions": {
                filename: {
                    "progress": session.overall_progress,
                    "stage": session.current_stage.display_name,
                    "eta": session.eta_formatted
                }
                for filename, session in self.active_sessions.items()
            }
        }


# Global progress tracker instance
_global_progress_tracker = None


def get_progress_tracker() -> ProgressTracker:
    """Get the global progress tracker instance"""
    global _global_progress_tracker
    if _global_progress_tracker is None:
        _global_progress_tracker = ProgressTracker()
    return _global_progress_tracker