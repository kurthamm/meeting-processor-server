"""
Intelligent Caching System for Meeting Processor
Caches AI analysis results and detects similar meetings for reuse
"""

import json
import hashlib
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from utils.logger import LoggerMixin, log_success, log_warning


@dataclass
class CacheEntry:
    """Represents a cached analysis entry"""
    transcript_hash: str
    analysis: Dict[str, Any]
    entities: Dict[str, List[str]]
    metadata: Dict[str, Any]
    created_at: datetime
    access_count: int = 0
    last_accessed: Optional[datetime] = None
    similarity_keywords: List[str] = None
    file_size: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        data['created_at'] = self.created_at.isoformat()
        data['last_accessed'] = self.last_accessed.isoformat() if self.last_accessed else None
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CacheEntry':
        """Create from dictionary"""
        data['created_at'] = datetime.fromisoformat(data['created_at'])
        if data['last_accessed']:
            data['last_accessed'] = datetime.fromisoformat(data['last_accessed'])
        return cls(**data)


class IntelligentCache(LoggerMixin):
    """Intelligent caching system with similarity detection and automatic cleanup"""
    
    def __init__(self, cache_dir: Path, max_entries: int = 1000, max_age_days: int = 30):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.max_entries = max_entries
        self.max_age_days = max_age_days
        self.similarity_threshold = 0.7  # Minimum similarity for reuse
        
        # In-memory cache for faster access
        self._memory_cache: Dict[str, CacheEntry] = {}
        self._similarity_index: Dict[str, List[str]] = {}  # keyword -> [hashes]
        
        # Cache files
        self.index_file = self.cache_dir / "cache_index.json"
        self.metadata_file = self.cache_dir / "cache_metadata.json"
        
        # Load existing cache
        self._load_cache()
        
        # Cleanup old entries
        self._cleanup_old_entries()
    
    def get_cached_analysis(self, transcript: str, file_metadata: Optional[Dict] = None) -> Optional[CacheEntry]:
        """
        Get cached analysis for transcript, or find similar cached analysis
        
        Args:
            transcript: Meeting transcript text
            file_metadata: Optional metadata about the file
            
        Returns:
            CacheEntry if found, None otherwise
        """
        transcript_hash = self._calculate_transcript_hash(transcript)
        
        # Try exact match first
        if transcript_hash in self._memory_cache:
            entry = self._memory_cache[transcript_hash]
            entry.access_count += 1
            entry.last_accessed = datetime.now()
            self.logger.debug(f"🎯 Cache hit (exact): {transcript_hash[:8]}")
            return entry
        
        # Try similarity match
        similar_entry = self._find_similar_cached_analysis(transcript, file_metadata)
        if similar_entry:
            similar_entry.access_count += 1
            similar_entry.last_accessed = datetime.now()
            self.logger.debug(f"🎯 Cache hit (similar): {similar_entry.transcript_hash[:8]}")
            return similar_entry
        
        self.logger.debug(f"❌ Cache miss: {transcript_hash[:8]}")
        return None
    
    def cache_analysis(self, transcript: str, analysis: Dict[str, Any], 
                      entities: Dict[str, List[str]], file_metadata: Optional[Dict] = None) -> str:
        """
        Cache analysis results
        
        Args:
            transcript: Meeting transcript text
            analysis: AI analysis results
            entities: Extracted entities
            file_metadata: Optional metadata about the file
            
        Returns:
            transcript_hash: Hash of the cached transcript
        """
        transcript_hash = self._calculate_transcript_hash(transcript)
        
        # Extract keywords for similarity matching
        keywords = self._extract_keywords(transcript, analysis, entities)
        
        # Create cache entry
        entry = CacheEntry(
            transcript_hash=transcript_hash,
            analysis=analysis,
            entities=entities,
            metadata=file_metadata or {},
            created_at=datetime.now(),
            similarity_keywords=keywords,
            file_size=len(transcript.encode('utf-8'))
        )
        
        # Store in memory cache
        self._memory_cache[transcript_hash] = entry
        
        # Update similarity index
        for keyword in keywords:
            if keyword not in self._similarity_index:
                self._similarity_index[keyword] = []
            if transcript_hash not in self._similarity_index[keyword]:
                self._similarity_index[keyword].append(transcript_hash)
        
        # Persist to disk
        self._save_cache_entry(entry)
        self._save_cache_index()
        
        log_success(self.logger, f"Cached analysis: {transcript_hash[:8]} ({len(keywords)} keywords)")
        
        # Cleanup if cache is getting too large
        if len(self._memory_cache) > self.max_entries:
            self._cleanup_lru_entries()
        
        return transcript_hash
    
    def get_similar_meetings(self, transcript: str, min_similarity: float = 0.5, 
                           max_results: int = 5) -> List[Dict[str, Any]]:
        """
        Find similar meetings based on content
        
        Args:
            transcript: Current meeting transcript
            min_similarity: Minimum similarity threshold
            max_results: Maximum number of results to return
            
        Returns:
            List of similar meeting information
        """
        current_keywords = self._extract_keywords_from_text(transcript)
        similar_meetings = []
        
        for hash_key, entry in self._memory_cache.items():
            if not entry.similarity_keywords:
                continue
            
            similarity = self._calculate_similarity(current_keywords, entry.similarity_keywords)
            
            if similarity >= min_similarity:
                similar_meetings.append({
                    'hash': hash_key,
                    'similarity': similarity,
                    'created_at': entry.created_at,
                    'metadata': entry.metadata,
                    'entities': entry.entities,
                    'keywords': entry.similarity_keywords[:10],  # Top 10 keywords
                    'file_size': entry.file_size
                })
        
        # Sort by similarity and return top results
        similar_meetings.sort(key=lambda x: x['similarity'], reverse=True)
        return similar_meetings[:max_results]
    
    def get_cache_statistics(self) -> Dict[str, Any]:
        """Get cache statistics and health information"""
        now = datetime.now()
        total_size_mb = sum(entry.file_size for entry in self._memory_cache.values()) / (1024 * 1024)
        
        # Age distribution
        age_buckets = {'<1d': 0, '1-7d': 0, '7-30d': 0, '>30d': 0}
        access_counts = []
        
        for entry in self._memory_cache.values():
            age_days = (now - entry.created_at).days
            if age_days < 1:
                age_buckets['<1d'] += 1
            elif age_days < 7:
                age_buckets['1-7d'] += 1
            elif age_days < 30:
                age_buckets['7-30d'] += 1
            else:
                age_buckets['>30d'] += 1
            
            access_counts.append(entry.access_count)
        
        stats = {
            'total_entries': len(self._memory_cache),
            'total_size_mb': total_size_mb,
            'age_distribution': age_buckets,
            'avg_access_count': sum(access_counts) / len(access_counts) if access_counts else 0,
            'similarity_keywords': len(self._similarity_index),
            'cache_hit_potential': self._calculate_hit_potential(),
            'disk_usage_mb': self._get_disk_usage_mb()
        }
        
        return stats
    
    def _calculate_transcript_hash(self, transcript: str) -> str:
        """Calculate a hash for the transcript content"""
        # Normalize transcript for consistent hashing
        normalized = self._normalize_transcript(transcript)
        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()
    
    def _normalize_transcript(self, transcript: str) -> str:
        """Normalize transcript for consistent comparison"""
        import re
        
        # Convert to lowercase
        text = transcript.lower()
        
        # Remove timestamps and speaker indicators
        text = re.sub(r'\b\d{1,2}:\d{2}(:\d{2})?\b', '', text)
        text = re.sub(r'\b(speaker|participant)\s*\d+\b', '', text)
        
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        return text
    
    def _extract_keywords(self, transcript: str, analysis: Dict[str, Any], 
                         entities: Dict[str, List[str]]) -> List[str]:
        """Extract keywords for similarity matching"""
        keywords = set()
        
        # Keywords from transcript
        keywords.update(self._extract_keywords_from_text(transcript))
        
        # Keywords from analysis
        if analysis.get('analysis'):
            keywords.update(self._extract_keywords_from_text(analysis['analysis']))
        
        # Keywords from entities
        for entity_list in entities.values():
            for entity in entity_list:
                # Split multi-word entities
                words = entity.lower().split()
                keywords.update(words)
        
        # Filter and clean keywords
        keywords = self._clean_keywords(keywords)
        
        # Return top keywords by relevance
        return self._rank_keywords(list(keywords), transcript)[:50]  # Top 50 keywords
    
    def _extract_keywords_from_text(self, text: str) -> List[str]:
        """Extract keywords from text using simple NLP techniques"""
        import re
        
        # Convert to lowercase and remove punctuation
        text = re.sub(r'[^\w\s]', ' ', text.lower())
        words = text.split()
        
        # Common stop words to exclude
        stop_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of',
            'with', 'by', 'is', 'are', 'was', 'were', 'be', 'been', 'have', 'has', 'had',
            'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might',
            'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it', 'we', 'they',
            'me', 'him', 'her', 'us', 'them', 'my', 'your', 'his', 'her', 'its', 'our',
            'their', 'what', 'which', 'who', 'when', 'where', 'why', 'how', 'all', 'any',
            'both', 'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor',
            'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very', 'can', 'just',
            'now', 'really', 'also', 'like', 'well', 'get', 'go', 'know', 'think', 'see',
            'want', 'need', 'going', 'make', 'take', 'come', 'good', 'great', 'right',
            'okay', 'yeah', 'yes', 'no', 'thanks', 'thank', 'please'
        }
        
        # Filter words
        keywords = []
        for word in words:
            if (len(word) > 2 and 
                word not in stop_words and 
                not word.isdigit() and
                len(word) < 20):  # Exclude very long words
                keywords.append(word)
        
        return keywords
    
    def _clean_keywords(self, keywords: set) -> set:
        """Clean and filter keywords"""
        cleaned = set()
        
        for keyword in keywords:
            # Skip very short or very long keywords
            if len(keyword) < 3 or len(keyword) > 20:
                continue
            
            # Skip numbers
            if keyword.isdigit():
                continue
            
            # Skip common filler words
            if keyword in ['um', 'uh', 'uhm', 'hmm', 'mmm', 'err']:
                continue
            
            cleaned.add(keyword.lower())
        
        return cleaned
    
    def _rank_keywords(self, keywords: List[str], text: str) -> List[str]:
        """Rank keywords by frequency and relevance"""
        from collections import Counter
        
        # Count frequency in text
        text_lower = text.lower()
        keyword_counts = Counter()
        
        for keyword in keywords:
            count = text_lower.count(keyword)
            if count > 0:
                keyword_counts[keyword] = count
        
        # Sort by frequency, then alphabetically
        ranked = sorted(keyword_counts.items(), key=lambda x: (-x[1], x[0]))
        return [keyword for keyword, count in ranked]
    
    def _calculate_similarity(self, keywords1: List[str], keywords2: List[str]) -> float:
        """Calculate similarity between two keyword lists using Jaccard similarity"""
        set1 = set(keywords1)
        set2 = set(keywords2)
        
        if not set1 or not set2:
            return 0.0
        
        intersection = len(set1.intersection(set2))
        union = len(set1.union(set2))
        
        return intersection / union if union > 0 else 0.0
    
    def _find_similar_cached_analysis(self, transcript: str, 
                                    file_metadata: Optional[Dict] = None) -> Optional[CacheEntry]:
        """Find similar cached analysis using keyword matching"""
        current_keywords = self._extract_keywords_from_text(transcript)
        best_match = None
        best_similarity = 0.0
        
        for hash_key, entry in self._memory_cache.items():
            if not entry.similarity_keywords:
                continue
            
            similarity = self._calculate_similarity(current_keywords, entry.similarity_keywords)
            
            if similarity > best_similarity and similarity >= self.similarity_threshold:
                best_similarity = similarity
                best_match = entry
        
        return best_match
    
    def _save_cache_entry(self, entry: CacheEntry):
        """Save cache entry to disk"""
        try:
            entry_file = self.cache_dir / f"{entry.transcript_hash}.json"
            with open(entry_file, 'w', encoding='utf-8') as f:
                json.dump(entry.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            log_warning(self.logger, f"Could not save cache entry: {e}")
    
    def _save_cache_index(self):
        """Save cache index to disk"""
        try:
            index_data = {
                'memory_cache_keys': list(self._memory_cache.keys()),
                'similarity_index': self._similarity_index,
                'last_updated': datetime.now().isoformat()
            }
            
            with open(self.index_file, 'w', encoding='utf-8') as f:
                json.dump(index_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log_warning(self.logger, f"Could not save cache index: {e}")
    
    def _load_cache(self):
        """Load existing cache from disk"""
        try:
            if not self.index_file.exists():
                self.logger.info("🗂️ No existing cache found, starting fresh")
                return
            
            with open(self.index_file, 'r', encoding='utf-8') as f:
                index_data = json.load(f)
            
            # Load cache entries
            loaded_count = 0
            for hash_key in index_data.get('memory_cache_keys', []):
                entry_file = self.cache_dir / f"{hash_key}.json"
                if entry_file.exists():
                    try:
                        with open(entry_file, 'r', encoding='utf-8') as f:
                            entry_data = json.load(f)
                        
                        entry = CacheEntry.from_dict(entry_data)
                        self._memory_cache[hash_key] = entry
                        loaded_count += 1
                    except Exception as e:
                        self.logger.debug(f"Could not load cache entry {hash_key}: {e}")
            
            # Load similarity index
            self._similarity_index = index_data.get('similarity_index', {})
            
            self.logger.info(f"🗂️ Loaded {loaded_count} cache entries with {len(self._similarity_index)} keywords")
            
        except Exception as e:
            log_warning(self.logger, f"Could not load cache: {e}")
    
    def _cleanup_old_entries(self):
        """Remove old cache entries"""
        cutoff_date = datetime.now() - timedelta(days=self.max_age_days)
        removed_count = 0
        
        # Find entries to remove
        to_remove = []
        for hash_key, entry in self._memory_cache.items():
            if entry.created_at < cutoff_date:
                to_remove.append(hash_key)
        
        # Remove entries
        for hash_key in to_remove:
            self._remove_cache_entry(hash_key)
            removed_count += 1
        
        if removed_count > 0:
            self.logger.info(f"🧹 Cleaned up {removed_count} old cache entries")
    
    def _cleanup_lru_entries(self):
        """Remove least recently used entries when cache is full"""
        if len(self._memory_cache) <= self.max_entries:
            return
        
        # Sort by last accessed time (least recent first)
        entries_by_access = sorted(
            self._memory_cache.items(),
            key=lambda x: x[1].last_accessed or x[1].created_at
        )
        
        # Remove oldest entries
        entries_to_remove = len(self._memory_cache) - self.max_entries + 10  # Remove extra for buffer
        removed_count = 0
        
        for hash_key, entry in entries_by_access[:entries_to_remove]:
            self._remove_cache_entry(hash_key)
            removed_count += 1
        
        self.logger.info(f"🧹 Removed {removed_count} LRU cache entries")
    
    def _remove_cache_entry(self, hash_key: str):
        """Remove a cache entry from memory and disk"""
        # Remove from memory cache
        if hash_key in self._memory_cache:
            del self._memory_cache[hash_key]
        
        # Remove from similarity index
        for keyword, hash_list in self._similarity_index.items():
            if hash_key in hash_list:
                hash_list.remove(hash_key)
        
        # Remove empty keyword entries
        self._similarity_index = {k: v for k, v in self._similarity_index.items() if v}
        
        # Remove from disk
        entry_file = self.cache_dir / f"{hash_key}.json"
        if entry_file.exists():
            try:
                entry_file.unlink()
            except Exception as e:
                self.logger.debug(f"Could not remove cache file {hash_key}: {e}")
    
    def _calculate_hit_potential(self) -> float:
        """Calculate potential for cache hits based on similarity"""
        if len(self._memory_cache) < 2:
            return 0.0
        
        entries = list(self._memory_cache.values())
        similar_pairs = 0
        total_pairs = 0
        
        for i in range(len(entries)):
            for j in range(i + 1, min(i + 10, len(entries))):  # Check up to 10 pairs per entry
                if entries[i].similarity_keywords and entries[j].similarity_keywords:
                    similarity = self._calculate_similarity(
                        entries[i].similarity_keywords,
                        entries[j].similarity_keywords
                    )
                    if similarity > 0.3:  # Lower threshold for potential
                        similar_pairs += 1
                    total_pairs += 1
        
        return similar_pairs / total_pairs if total_pairs > 0 else 0.0
    
    def _get_disk_usage_mb(self) -> float:
        """Calculate disk usage of cache directory"""
        try:
            total_size = 0
            for file_path in self.cache_dir.glob("*.json"):
                total_size += file_path.stat().st_size
            return total_size / (1024 * 1024)
        except Exception:
            return 0.0


# Global cache instance
_global_cache = None


def get_intelligent_cache(cache_dir: Path) -> IntelligentCache:
    """Get the global intelligent cache instance"""
    global _global_cache
    if _global_cache is None:
        _global_cache = IntelligentCache(cache_dir)
    return _global_cache