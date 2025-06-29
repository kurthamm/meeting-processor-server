"""
Interactive Setup Wizard for Meeting Processor
Guides users through configuration with validation and helpful defaults
"""

import os
import json
import getpass
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
import re
from urllib.parse import urlparse


@dataclass
class ConfigField:
    """Configuration field definition"""
    name: str
    display_name: str
    description: str
    required: bool = True
    default: Optional[str] = None
    validator: Optional[callable] = None
    masked: bool = False  # For passwords/API keys
    help_url: Optional[str] = None


class SetupWizard:
    """Interactive setup wizard with validation and guidance"""
    
    def __init__(self):
        self.config = {}
        self.errors = []
        self.warnings = []
        
        # Define configuration fields
        self.config_fields = [
            ConfigField(
                name="OPENAI_API_KEY",
                display_name="OpenAI API Key",
                description="API key for OpenAI Whisper transcription service",
                required=True,
                validator=self._validate_openai_key,
                masked=True,
                help_url="https://platform.openai.com/api-keys"
            ),
            ConfigField(
                name="ANTHROPIC_API_KEY", 
                display_name="Anthropic API Key",
                description="API key for Claude AI analysis service",
                required=True,
                validator=self._validate_anthropic_key,
                masked=True,
                help_url="https://console.anthropic.com/account/keys"
            ),
            ConfigField(
                name="OBSIDIAN_VAULT_PATH",
                display_name="Obsidian Vault Path",
                description="Path to your Obsidian vault directory",
                required=True,
                default=self._detect_obsidian_vault(),
                validator=self._validate_vault_path,
                help_url="https://help.obsidian.md/Getting+started/Create+a+vault"
            ),
            ConfigField(
                name="STORAGE_MODE",
                display_name="Storage Mode", 
                description="Choose storage mode (local or google_drive)",
                required=True,
                default="local",
                validator=self._validate_storage_mode
            ),
            ConfigField(
                name="GOOGLE_DRIVE_INPUT_FOLDER_ID",
                display_name="Google Drive Input Folder ID",
                description="Google Drive folder ID for input MP4 files",
                required=False,
                validator=self._validate_folder_id,
                help_url="https://docs.anthropic.com/claude-code/google-drive"
            ),
            ConfigField(
                name="GOOGLE_DRIVE_OUTPUT_FOLDER_ID",
                display_name="Google Drive Output Folder ID", 
                description="Google Drive folder ID for output files",
                required=False,
                validator=self._validate_folder_id
            ),
            ConfigField(
                name="GOOGLE_DRIVE_PROCESSED_FOLDER_ID",
                display_name="Google Drive Processed Folder ID",
                description="Google Drive folder ID for processed files",
                required=False,
                validator=self._validate_folder_id
            ),
            ConfigField(
                name="FILE_NAMING_TEMPLATE",
                display_name="File Naming Template",
                description="Template for generating filenames",
                required=False,
                default="{topic}_{date}_{time}_{metadata}",
                validator=self._validate_naming_template
            )
        ]
    
    def run_interactive_setup(self) -> bool:
        """Run the complete interactive setup process"""
        print("🚀 Meeting Processor Setup Wizard")
        print("=" * 50)
        print("Welcome! This wizard will help you configure Meeting Processor.")
        print("You can press Ctrl+C at any time to exit.\n")
        
        try:
            # Step 1: Check existing configuration
            self._check_existing_config()
            
            # Step 2: Collect configuration
            self._collect_configuration()
            
            # Step 3: Validate configuration
            self._validate_configuration()
            
            # Step 4: Test configuration
            if self._prompt_yes_no("Test the configuration now?", default=True):
                self._test_configuration()
            
            # Step 5: Save configuration
            if self._save_configuration():
                print("\n✅ Setup completed successfully!")
                print("You can now run: python main.py")
                return True
            else:
                print("\n❌ Setup failed. Please try again.")
                return False
        
        except KeyboardInterrupt:
            print("\n\n👋 Setup cancelled by user.")
            return False
        except Exception as e:
            print(f"\n❌ Setup failed with error: {e}")
            return False
    
    def _check_existing_config(self):
        """Check for existing configuration"""
        env_file = Path(".env")
        
        if env_file.exists():
            print("📄 Found existing .env file")
            if self._prompt_yes_no("Would you like to update the existing configuration?", default=True):
                # Load existing values as defaults
                self._load_existing_env(env_file)
                print("✅ Loaded existing configuration as defaults\n")
            else:
                print("🔄 Starting fresh configuration\n")
        else:
            print("📁 No existing configuration found, starting fresh\n")
    
    def _load_existing_env(self, env_file: Path):
        """Load existing environment file"""
        try:
            with open(env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        # Remove quotes if present
                        value = value.strip('"\'')
                        self.config[key] = value
        except Exception as e:
            print(f"⚠️ Could not load existing configuration: {e}")
    
    def _collect_configuration(self):
        """Collect configuration from user input"""
        print("📝 Configuration Setup")
        print("-" * 30)
        
        for field in self.config_fields:
            # Skip Google Drive fields if using local storage
            if (field.name.startswith("GOOGLE_DRIVE") and 
                self.config.get("STORAGE_MODE", "local") == "local"):
                continue
            
            self._collect_field(field)
            print()  # Add spacing between fields
    
    def _collect_field(self, field: ConfigField):
        """Collect a single configuration field"""
        print(f"📋 {field.display_name}")
        print(f"   {field.description}")
        
        if field.help_url:
            print(f"   📖 Help: {field.help_url}")
        
        # Get current/default value
        current_value = self.config.get(field.name, field.default)
        if current_value:
            display_value = "***hidden***" if field.masked else current_value
            print(f"   Current: {display_value}")
        
        # Prompt for new value
        while True:
            if field.masked:
                prompt = f"   Enter {field.display_name}"
                if current_value:
                    prompt += " (press Enter to keep current)"
                prompt += ": "
                
                value = getpass.getpass(prompt)
                if not value and current_value:
                    value = current_value
            else:
                prompt = f"   Enter {field.display_name}"
                if current_value:
                    prompt += f" [{current_value}]"
                prompt += ": "
                
                value = input(prompt).strip()
                if not value and current_value:
                    value = current_value
            
            # Skip if not required and empty
            if not field.required and not value:
                print("   ⏭️ Skipped (optional)")
                break
            
            # Validate if required or value provided
            if field.required and not value:
                print("   ❌ This field is required")
                continue
            
            if value and field.validator:
                is_valid, message = field.validator(value)
                if not is_valid:
                    print(f"   ❌ {message}")
                    continue
            
            # Value is valid
            if value:
                self.config[field.name] = value
                print("   ✅ Valid")
            break
    
    def _validate_configuration(self):
        """Validate the complete configuration"""
        print("🔍 Validating Configuration")
        print("-" * 30)
        
        self.errors.clear()
        self.warnings.clear()
        
        # Check required fields
        for field in self.config_fields:
            if field.required and field.name not in self.config:
                self.errors.append(f"Missing required field: {field.display_name}")
        
        # Storage mode specific validation
        storage_mode = self.config.get("STORAGE_MODE", "local")
        if storage_mode == "google_drive":
            google_drive_fields = [
                "GOOGLE_DRIVE_INPUT_FOLDER_ID",
                "GOOGLE_DRIVE_OUTPUT_FOLDER_ID", 
                "GOOGLE_DRIVE_PROCESSED_FOLDER_ID"
            ]
            
            for field_name in google_drive_fields:
                if field_name not in self.config or not self.config[field_name]:
                    self.errors.append(f"Google Drive mode requires: {field_name}")
        
        # Display results
        if self.errors:
            print("❌ Configuration Errors:")
            for error in self.errors:
                print(f"   • {error}")
        
        if self.warnings:
            print("⚠️ Configuration Warnings:")
            for warning in self.warnings:
                print(f"   • {warning}")
        
        if not self.errors and not self.warnings:
            print("✅ Configuration is valid!")
        
        print()
    
    def _test_configuration(self):
        """Test the configuration by attempting to connect to services"""
        print("🧪 Testing Configuration")
        print("-" * 30)
        
        # Test OpenAI API
        if "OPENAI_API_KEY" in self.config:
            print("🔄 Testing OpenAI API connection...")
            if self._test_openai_connection():
                print("✅ OpenAI API: Connected successfully")
            else:
                print("❌ OpenAI API: Connection failed")
        
        # Test Anthropic API
        if "ANTHROPIC_API_KEY" in self.config:
            print("🔄 Testing Anthropic API connection...")
            if self._test_anthropic_connection():
                print("✅ Anthropic API: Connected successfully")
            else:
                print("❌ Anthropic API: Connection failed")
        
        # Test Obsidian vault
        if "OBSIDIAN_VAULT_PATH" in self.config:
            print("🔄 Testing Obsidian vault access...")
            if self._test_vault_access():
                print("✅ Obsidian Vault: Accessible")
            else:
                print("❌ Obsidian Vault: Access failed")
        
        # Test Google Drive (if configured)
        if self.config.get("STORAGE_MODE") == "google_drive":
            print("🔄 Testing Google Drive access...")
            if self._test_google_drive_access():
                print("✅ Google Drive: Accessible")
            else:
                print("❌ Google Drive: Access failed")
        
        print()
    
    def _save_configuration(self) -> bool:
        """Save configuration to .env file"""
        print("💾 Saving Configuration")
        print("-" * 30)
        
        try:
            env_content = self._generate_env_content()
            
            # Create backup of existing .env
            env_file = Path(".env")
            if env_file.exists():
                backup_file = Path(".env.backup")
                env_file.rename(backup_file)
                print(f"📄 Created backup: {backup_file}")
            
            # Write new .env file
            with open(env_file, 'w') as f:
                f.write(env_content)
            
            print(f"✅ Configuration saved to: {env_file}")
            
            # Set appropriate permissions
            os.chmod(env_file, 0o600)  # Read/write for owner only
            print("🔒 Set secure file permissions")
            
            return True
            
        except Exception as e:
            print(f"❌ Failed to save configuration: {e}")
            return False
    
    def _generate_env_content(self) -> str:
        """Generate .env file content"""
        lines = [
            "# Meeting Processor Configuration",
            "# Generated by Setup Wizard",
            f"# Created: {datetime.now().isoformat()}",
            "",
            "# API Keys",
        ]
        
        # Add API keys
        api_keys = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"]
        for key in api_keys:
            if key in self.config:
                lines.append(f'{key}="{self.config[key]}"')
        
        lines.extend([
            "",
            "# Storage Configuration",
        ])
        
        # Add storage config
        storage_keys = ["STORAGE_MODE", "OBSIDIAN_VAULT_PATH"]
        for key in storage_keys:
            if key in self.config:
                lines.append(f'{key}="{self.config[key]}"')
        
        # Add Google Drive config if needed
        if self.config.get("STORAGE_MODE") == "google_drive":
            lines.extend([
                "",
                "# Google Drive Configuration",
            ])
            
            gd_keys = [
                "GOOGLE_DRIVE_INPUT_FOLDER_ID",
                "GOOGLE_DRIVE_OUTPUT_FOLDER_ID",
                "GOOGLE_DRIVE_PROCESSED_FOLDER_ID"
            ]
            for key in gd_keys:
                if key in self.config:
                    lines.append(f'{key}="{self.config[key]}"')
        
        # Add optional settings
        lines.extend([
            "",
            "# Optional Settings",
        ])
        
        optional_keys = ["FILE_NAMING_TEMPLATE"]
        for key in optional_keys:
            if key in self.config:
                lines.append(f'{key}="{self.config[key]}"')
        
        return "\n".join(lines) + "\n"
    
    # Validation methods
    def _validate_openai_key(self, key: str) -> Tuple[bool, str]:
        """Validate OpenAI API key format"""
        if not key.startswith("sk-"):
            return False, "OpenAI API keys should start with 'sk-'"
        if len(key) < 20:
            return False, "OpenAI API key seems too short"
        return True, "Valid format"
    
    def _validate_anthropic_key(self, key: str) -> Tuple[bool, str]:
        """Validate Anthropic API key format"""
        if not key.startswith("sk-ant-"):
            return False, "Anthropic API keys should start with 'sk-ant-'"
        if len(key) < 20:
            return False, "Anthropic API key seems too short"
        return True, "Valid format"
    
    def _validate_vault_path(self, path: str) -> Tuple[bool, str]:
        """Validate Obsidian vault path"""
        vault_path = Path(path)
        if not vault_path.exists():
            return False, "Path does not exist"
        if not vault_path.is_dir():
            return False, "Path is not a directory"
        
        # Check for .obsidian directory (indicates it's a vault)
        obsidian_dir = vault_path / ".obsidian"
        if not obsidian_dir.exists():
            return False, "Directory does not appear to be an Obsidian vault (missing .obsidian folder)"
        
        return True, "Valid Obsidian vault"
    
    def _validate_storage_mode(self, mode: str) -> Tuple[bool, str]:
        """Validate storage mode"""
        valid_modes = ["local", "google_drive"]
        if mode not in valid_modes:
            return False, f"Storage mode must be one of: {', '.join(valid_modes)}"
        return True, "Valid storage mode"
    
    def _validate_folder_id(self, folder_id: str) -> Tuple[bool, str]:
        """Validate Google Drive folder ID format"""
        if not folder_id:
            return True, "Optional field"
        
        # Basic format validation
        if len(folder_id) < 10:
            return False, "Folder ID seems too short"
        
        # Check for valid characters
        if not re.match(r'^[a-zA-Z0-9_-]+$', folder_id):
            return False, "Folder ID contains invalid characters"
        
        return True, "Valid format"
    
    def _validate_naming_template(self, template: str) -> Tuple[bool, str]:
        """Validate file naming template"""
        if not template:
            return False, "Naming template cannot be empty"
        
        # Check for valid placeholders
        valid_placeholders = ["{topic}", "{date}", "{time}", "{metadata}", "{type}", "{duration}"]
        if not any(placeholder in template for placeholder in valid_placeholders):
            return False, f"Template should contain at least one placeholder: {', '.join(valid_placeholders)}"
        
        return True, "Valid template"
    
    # Detection methods
    def _detect_obsidian_vault(self) -> Optional[str]:
        """Auto-detect Obsidian vault location"""
        common_paths = [
            Path.home() / "Documents" / "Obsidian",
            Path.home() / "Obsidian",
            Path.home() / "vault",
            Path.home() / "Notes",
            Path("/obsidian_vault"),  # Docker default
        ]
        
        for path in common_paths:
            if path.exists() and (path / ".obsidian").exists():
                return str(path)
        
        return None
    
    # Test methods
    def _test_openai_connection(self) -> bool:
        """Test OpenAI API connection"""
        try:
            import openai
            client = openai.OpenAI(api_key=self.config["OPENAI_API_KEY"])
            models = client.models.list()
            return len(models.data) > 0
        except Exception:
            return False
    
    def _test_anthropic_connection(self) -> bool:
        """Test Anthropic API connection"""
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.config["ANTHROPIC_API_KEY"])
            # Simple test message
            response = client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=10,
                messages=[{"role": "user", "content": "Hi"}]
            )
            return bool(response.content)
        except Exception:
            return False
    
    def _test_vault_access(self) -> bool:
        """Test Obsidian vault access"""
        try:
            vault_path = Path(self.config["OBSIDIAN_VAULT_PATH"])
            test_file = vault_path / "test_write_access.tmp"
            
            # Try to create and delete a file
            test_file.write_text("test")
            test_file.unlink()
            
            return True
        except Exception:
            return False
    
    def _test_google_drive_access(self) -> bool:
        """Test Google Drive access (simplified)"""
        # In a real implementation, this would test the Google Drive API
        # For now, just check if the folder IDs are provided
        required_fields = [
            "GOOGLE_DRIVE_INPUT_FOLDER_ID",
            "GOOGLE_DRIVE_OUTPUT_FOLDER_ID",
            "GOOGLE_DRIVE_PROCESSED_FOLDER_ID"
        ]
        
        return all(self.config.get(field) for field in required_fields)
    
    # Utility methods
    def _prompt_yes_no(self, question: str, default: bool = True) -> bool:
        """Prompt for yes/no answer"""
        default_str = "Y/n" if default else "y/N"
        while True:
            answer = input(f"{question} ({default_str}): ").strip().lower()
            
            if not answer:
                return default
            elif answer in ['y', 'yes']:
                return True
            elif answer in ['n', 'no']:
                return False
            else:
                print("Please answer 'y' or 'n'")


def run_setup_wizard() -> bool:
    """Run the setup wizard"""
    wizard = SetupWizard()
    return wizard.run_interactive_setup()


if __name__ == "__main__":
    # Allow running the wizard standalone
    from datetime import datetime
    success = run_setup_wizard()
    exit(0 if success else 1)