"""
Configuration settings for Meeting Processor
"""

import os
from pathlib import Path
from anthropic import Anthropic
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class ConfigurationError(Exception):
    """Custom exception for configuration errors"""
    pass


class Settings:
    """Centralized configuration management"""
    
    # Agile/Scrum Task Standards
    TASK_STATUSES = ['new', 'ready', 'in_progress', 'in_review', 'done', 'blocked', 'cancelled']
    TASK_PRIORITIES = ['critical', 'high', 'medium', 'low']
    TASK_CATEGORIES = ['technical', 'business', 'process', 'documentation', 'research']
    
    # Task Status Emoji Mapping
    STATUS_EMOJIS = {
        'new': '🆕',
        'ready': '📋',
        'in_progress': '🚀',
        'in_review': '🔍',
        'done': '✅',
        'blocked': '🚫',
        'cancelled': '❌'
    }
    
    # Priority Emoji Mapping
    PRIORITY_EMOJIS = {
        'critical': '🚨',
        'high': '🔥',
        'medium': '⚡',
        'low': '📌'
    }
    
    # Category Emoji Mapping
    CATEGORY_EMOJIS = {
        'technical': '💻',
        'business': '💼',
        'process': '📋',
        'documentation': '📝',
        'research': '🔍'
    }
    
    # Dashboard Update Thresholds (configurable via environment)
    DEFAULT_DASHBOARD_THRESHOLDS = {
        'hours_between_updates': 6,  # Regular update interval
        'morning_refresh_hour': 9,   # Hour for morning refresh (24-hour format)
        'high_priority_tasks': 2,    # Threshold for high priority tasks
        'critical_tasks': 1,         # Threshold for critical tasks
        'urgent_tasks': 1,           # Threshold for urgent tasks
        'new_companies': 2,          # Threshold for new companies
        'new_people': 3,             # Threshold for new people
        'total_tasks': 5,            # Threshold for total tasks in a meeting
        'urgent_task_days': 3,       # Days until deadline to consider urgent
        'high_impact_keywords': [    # Keywords that indicate important meetings
            'client', 'sales', 'contract', 'deal', 'strategy', 'executive',
            'board', 'crisis', 'urgent', 'critical', 'launch', 'review',
            'kickoff', 'milestone', 'deadline', 'emergency', 'investor',
            'partnership', 'acquisition', 'merger'
        ]
    }
    
    def __init__(self):
        # API Keys
        self.openai_api_key = os.getenv('OPENAI_API_KEY', '').strip()
        self.anthropic_api_key = os.getenv('ANTHROPIC_API_KEY', '').strip()
        
        # Obsidian Configuration
        self.obsidian_vault_path = os.getenv('OBSIDIAN_VAULT_PATH', '/obsidian_vault')
        self.obsidian_folder_path = os.getenv('OBSIDIAN_FOLDER_PATH', 'Meetings')
        
        # User Configuration
        self.obsidian_user_name = os.getenv('OBSIDIAN_USER_NAME', 'Me').strip()
        self.obsidian_company_name = os.getenv('OBSIDIAN_COMPANY_NAME', 'My Company').strip()
        
        # Storage mode: 'local' or 'google_drive'
        self.storage_mode = os.getenv('STORAGE_MODE', 'local').lower()
        
        # Docker paths (used for local storage mode)
        self.input_dir = os.getenv('INPUT_DIR', '/app/input')
        self.output_dir = os.getenv('OUTPUT_DIR', '/app/output')
        self.processed_dir = os.getenv('PROCESSED_DIR', '/app/processed')
        
        # Google Drive configuration
        self.google_drive_credentials_path = os.getenv('GOOGLE_DRIVE_CREDENTIALS_PATH', '/app/credentials.json')
        self.google_drive_token_path = os.getenv('GOOGLE_DRIVE_TOKEN_PATH', '/app/token.json')
        self.google_drive_input_folder_id = os.getenv('GOOGLE_DRIVE_INPUT_FOLDER_ID', '').strip()
        self.google_drive_output_folder_id = os.getenv('GOOGLE_DRIVE_OUTPUT_FOLDER_ID', '').strip()
        self.google_drive_processed_folder_id = os.getenv('GOOGLE_DRIVE_PROCESSED_FOLDER_ID', '').strip()
        self.google_drive_vault_folder_id = os.getenv('GOOGLE_DRIVE_VAULT_FOLDER_ID', '').strip()
        
        # Entity folders for Obsidian
        self.entity_folders = ['People', 'Companies', 'Technologies', 'Tasks', 'Meta/dashboards']
        
        # Task configuration
        self.task_folder = 'Tasks'
        self.task_dashboard_path = 'Meta/dashboards/Task-Dashboard.md'
        
        # Testing mode
        self.testing_mode = os.getenv('TESTING_MODE', 'false').lower() == 'true'
        
        # Load dashboard update thresholds from environment or use defaults
        self.dashboard_update_thresholds = self._load_dashboard_thresholds()
        
        # Initialize API clients
        self.openai_client = self._init_openai_client()
        self.anthropic_client = self._init_anthropic_client()
        
        # Validate configuration
        self._validate_configuration()
    
    def _load_dashboard_thresholds(self) -> dict:
        """Load dashboard update thresholds from environment variables"""
        thresholds = self.DEFAULT_DASHBOARD_THRESHOLDS.copy()
        
        # Override with environment variables if present
        env_mappings = {
            'DASHBOARD_UPDATE_HOURS': 'hours_between_updates',
            'DASHBOARD_MORNING_HOUR': 'morning_refresh_hour',
            'DASHBOARD_HIGH_PRIORITY_THRESHOLD': 'high_priority_tasks',
            'DASHBOARD_CRITICAL_THRESHOLD': 'critical_tasks',
            'DASHBOARD_URGENT_THRESHOLD': 'urgent_tasks',
            'DASHBOARD_NEW_COMPANIES_THRESHOLD': 'new_companies',
            'DASHBOARD_NEW_PEOPLE_THRESHOLD': 'new_people',
            'DASHBOARD_TOTAL_TASKS_THRESHOLD': 'total_tasks',
            'DASHBOARD_URGENT_DAYS': 'urgent_task_days'
        }
        
        for env_key, config_key in env_mappings.items():
            env_value = os.getenv(env_key)
            if env_value:
                try:
                    thresholds[config_key] = int(env_value)
                except ValueError:
                    print(f"⚠️  Invalid value for {env_key}: {env_value} (must be integer)")
        
        # Load high impact keywords if provided
        keywords_env = os.getenv('DASHBOARD_HIGH_IMPACT_KEYWORDS')
        if keywords_env:
            thresholds['high_impact_keywords'] = [k.strip() for k in keywords_env.split(',')]
        
        return thresholds
    
    def _init_openai_client(self):
        """Initialize OpenAI client if API key is available"""
        if self.openai_api_key:
            try:
                client = OpenAI(api_key=self.openai_api_key)
                # Test the API key with a simple request
                try:
                    client.models.list()
                    print("✅ OpenAI client initialized and validated")
                    return client
                except Exception as e:
                    print(f"⚠️  OpenAI API key appears invalid: {e}")
                    return None
            except Exception as e:
                print(f"⚠️  Error initializing OpenAI client: {e}")
                return None
        else:
            print("⚠️  No OpenAI API key found - transcription will not be available")
            return None
    
    def _init_anthropic_client(self):
        """Initialize Anthropic client if API key is available"""
        if self.anthropic_api_key:
            try:
                client = Anthropic(api_key=self.anthropic_api_key)
                print("✅ Anthropic client initialized")
                return client
            except Exception as e:
                print(f"⚠️  Error initializing Anthropic client: {e}")
                return None
        else:
            print("⚠️  No Anthropic API key found - AI analysis will not be available")
            return None
    
    def _validate_configuration(self):
        """Validate configuration settings"""
        errors = []
        warnings = []
        
        # Validate storage mode
        if self.storage_mode not in ['local', 'google_drive']:
            errors.append(f"Invalid STORAGE_MODE: {self.storage_mode}. Must be 'local' or 'google_drive'")
        
        # Storage-specific validation
        if self.storage_mode == 'local':
            # Check required local directories
            required_dirs = [
                ('input_dir', self.input_dir),
                ('output_dir', self.output_dir),
                ('processed_dir', self.processed_dir)
            ]
            
            for name, path in required_dirs:
                if not Path(path).exists():
                    try:
                        Path(path).mkdir(parents=True, exist_ok=True)
                        print(f"✅ Created missing directory: {path}")
                    except Exception as e:
                        errors.append(f"Cannot create {name} at {path}: {e}")
        
        elif self.storage_mode == 'google_drive':
            # Check Google Drive configuration
            if not self.google_drive_input_folder_id:
                errors.append("GOOGLE_DRIVE_INPUT_FOLDER_ID is required when using Google Drive storage")
            if not self.google_drive_output_folder_id:
                errors.append("GOOGLE_DRIVE_OUTPUT_FOLDER_ID is required when using Google Drive storage")
            if not self.google_drive_processed_folder_id:
                errors.append("GOOGLE_DRIVE_PROCESSED_FOLDER_ID is required when using Google Drive storage")
            
            # Check vault configuration for Google Drive mode
            if self.google_drive_vault_folder_id:
                # Vault folder ID is provided, so we'll use Google Drive for vault
                print("✅ Google Drive vault folder configured")
            
            # Check credentials file
            if not Path(self.google_drive_credentials_path).exists():
                errors.append(f"Google Drive credentials file not found: {self.google_drive_credentials_path}")
                errors.append("Please download credentials.json from Google Cloud Console")
            
            # Create temp directories for Google Drive mode
            temp_dirs = ['/tmp/meeting_processor']
            for temp_dir in temp_dirs:
                try:
                    Path(temp_dir).mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    warnings.append(f"Cannot create temp directory {temp_dir}: {e}")
        
        # Check Obsidian vault path (only for local storage mode)
        if self.storage_mode == 'local' and not Path(self.obsidian_vault_path).exists():
            errors.append(f"Obsidian vault path does not exist: {self.obsidian_vault_path}")
            errors.append("Please ensure your Obsidian vault is mounted correctly in docker-compose.yml")
        elif self.storage_mode == 'google_drive' and not self.google_drive_vault_folder_id:
            errors.append("Google Drive vault folder ID not configured for Google Drive storage mode")
            errors.append("Please set GOOGLE_DRIVE_VAULT_FOLDER_ID in your environment")
        
        # Check API keys
        if not self.openai_api_key and not self.testing_mode:
            warnings.append("OpenAI API key not configured - transcription disabled")
            warnings.append("Get your key at: https://platform.openai.com/api-keys")
        
        if not self.anthropic_api_key:
            warnings.append("Anthropic API key not configured - AI analysis disabled")
            warnings.append("Get your key at: https://console.anthropic.com/")
        
        # Check user configuration
        if self.obsidian_user_name == 'Me':
            warnings.append("OBSIDIAN_USER_NAME not customized - using default 'Me'")
            warnings.append("Set OBSIDIAN_USER_NAME in .env for personalized dashboards")
        
        if self.obsidian_company_name == 'My Company':
            warnings.append("OBSIDIAN_COMPANY_NAME not customized - using default 'My Company'")
            warnings.append("Set OBSIDIAN_COMPANY_NAME in .env for accurate entity relationships")
        
        # Validate dashboard thresholds
        for key, value in self.dashboard_update_thresholds.items():
            if key.endswith('_threshold') or key.endswith('_days') or key.endswith('_hour') or key == 'hours_between_updates':
                if isinstance(value, int) and value < 0:
                    warnings.append(f"Dashboard threshold {key} is negative: {value}")
        
        # Print errors first (critical)
        if errors:
            print("\n❌ Configuration Errors (must fix):")
            for error in errors:
                print(f"   - {error}")
            raise ConfigurationError("Configuration validation failed. Please fix the errors above.")
        
        # Print warnings (non-critical)
        if warnings:
            print("\n⚠️  Configuration Warnings:")
            for warning in warnings:
                print(f"   - {warning}")
            print()
        else:
            print("\n✅ Configuration validated successfully")
    
    @classmethod
    def get_status_emoji(cls, status: str) -> str:
        """Get emoji for a task status"""
        return cls.STATUS_EMOJIS.get(status.lower(), '📋')
    
    @classmethod
    def get_priority_emoji(cls, priority: str) -> str:
        """Get emoji for a task priority"""
        return cls.PRIORITY_EMOJIS.get(priority.lower(), '📋')
    
    @classmethod
    def get_category_emoji(cls, category: str) -> str:
        """Get emoji for a task category"""
        return cls.CATEGORY_EMOJIS.get(category.lower(), '📝')
    
    def get_dashboard_threshold(self, key: str, default: int = 6) -> int:
        """Get a specific dashboard threshold value"""
        return self.dashboard_update_thresholds.get(key, default)
    
    def get_config_summary(self) -> dict:
        """Get configuration summary for logging"""
        summary = {
            'storage_mode': self.storage_mode,
            'vault_path': self.obsidian_vault_path,
            'user_name': self.obsidian_user_name,
            'company_name': self.obsidian_company_name,
            'testing_mode': self.testing_mode,
            'openai_configured': bool(self.openai_api_key),
            'anthropic_configured': bool(self.anthropic_api_key),
            'dashboard_update_hours': self.dashboard_update_thresholds['hours_between_updates'],
            'morning_refresh_hour': self.dashboard_update_thresholds['morning_refresh_hour']
        }
        
        if self.storage_mode == 'google_drive':
            summary.update({
                'google_drive_input_folder': self.google_drive_input_folder_id,
                'google_drive_output_folder': self.google_drive_output_folder_id,
                'google_drive_processed_folder': self.google_drive_processed_folder_id,
                'credentials_file_exists': Path(self.google_drive_credentials_path).exists()
            })
        
        return summary
    
    def print_dashboard_settings(self):
        """Print current dashboard update settings"""
        print("\n📊 Dashboard Update Settings:")
        print(f"   - Update interval: {self.dashboard_update_thresholds['hours_between_updates']} hours")
        print(f"   - Morning refresh: {self.dashboard_update_thresholds['morning_refresh_hour']}:00")
        print(f"   - High priority threshold: {self.dashboard_update_thresholds['high_priority_tasks']} tasks")
        print(f"   - Critical threshold: {self.dashboard_update_thresholds['critical_tasks']} tasks")
        print(f"   - New companies threshold: {self.dashboard_update_thresholds['new_companies']}")
        print(f"   - Total tasks threshold: {self.dashboard_update_thresholds['total_tasks']}")
        print(f"   - Urgent task days: {self.dashboard_update_thresholds['urgent_task_days']} days")
        print(f"   - High impact keywords: {len(self.dashboard_update_thresholds['high_impact_keywords'])} configured")