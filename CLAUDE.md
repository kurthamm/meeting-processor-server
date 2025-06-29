# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Development Commands

#### Local Storage Mode (Default)
```bash
# Build and run with Docker Compose (local file system)
docker-compose up --build -d

# View logs
docker logs -f meeting-processor

# Stop and remove containers
docker-compose down

# Rebuild from scratch
docker-compose down && docker-compose up --build -d

# Run Python directly (for development)
python main.py
```

#### Google Drive Mode
```bash
# Set up Google Drive mode in .env file
# STORAGE_MODE=google_drive
# GOOGLE_DRIVE_INPUT_FOLDER_ID=your_input_folder_id
# GOOGLE_DRIVE_OUTPUT_FOLDER_ID=your_output_folder_id
# GOOGLE_DRIVE_PROCESSED_FOLDER_ID=your_processed_folder_id

# Mount credentials file and run
docker-compose up --build -d

# First run will prompt for Google authentication
# Follow the browser authentication flow
```

### Testing
- No formal test framework is currently implemented
- Use `TESTING_MODE=true` in `.env` for development/debugging

#### Local Storage Testing
- Manual testing: drop MP4 files into `input/` directory and monitor logs

#### Google Drive Testing  
- Upload MP4 files to your designated Google Drive input folder
- Monitor logs: `docker logs -f meeting-processor`
- Check output folder in Google Drive for results

### File Operations

#### Local Storage Mode
```bash
# Check processing status
ls input/     # Unprocessed MP4 files
ls output/    # JSON and MD outputs
ls processed/ # Archived MP4 files

# Monitor file system in real-time
docker logs -f meeting-processor
```

#### Google Drive Mode
```bash
# All file operations happen in Google Drive
# Monitor processing status through logs
docker logs -f meeting-processor

# Files are automatically:
# - Downloaded from input folder for processing
# - Uploaded to output folder after processing  
# - Moved to processed folder when complete
```

## Architecture Overview

### Core Processing Pipeline
The system follows a multi-stage processing pipeline:

1. **File Monitoring** (`monitoring/file_watcher.py`) - Watchdog detects new MP4 files
2. **Audio Processing** (`core/audio_processor.py`) - FFmpeg converts MP4 → FLAC with chunking
3. **Transcription** (`core/transcription.py`) - OpenAI Whisper processes audio
4. **AI Analysis** (`core/claude_analyzer.py`) - Anthropic Claude analyzes transcript
5. **Entity Detection** (`entities/detector.py`) - AI identifies people, companies, technologies
6. **Task Extraction** (`core/task_extractor.py`) - Extracts Agile tasks with priorities
7. **Knowledge Generation** - Creates interconnected Obsidian notes
8. **Dashboard Updates** (`core/dashboard_orchestrator.py`) - Refreshes analytics

### Key Components

**Main Orchestrator** (`main.py`)
- `MeetingProcessor` class coordinates all components
- Multi-threaded queue processing with worker threads
- Graceful shutdown handling and file tracking

**Configuration** (`config/settings.py`)
- Centralized settings validation with environment variables
- API client initialization for OpenAI and Anthropic
- Path management and validation

**Entity System** (`entities/`)
- AI-powered entity detection and relationship mapping
- Creates structured Obsidian notes for people, companies, technologies
- Maintains bi-directional links and context

**Task Management** (`core/task_extractor.py`)
- Full Agile workflow: new → ready → in_progress → in_review → done
- YAML frontmatter with priorities (critical, high, medium, low)
- Categories: technical, business, process, documentation, research

**Dashboard System** (`core/dashboard_*.py`)
- Real-time Dataview queries for analytics
- Configurable update thresholds and schedules
- Command Center and Task Dashboard with live data

### File Structure
```
/app/
├── input/           # Drop MP4 files here
├── output/          # JSON analysis + MD notes
├── processed/       # Archived MP4 files
├── obsidian_vault/  # Mounted Obsidian vault
└── logs/           # Application logs
```

### Obsidian Integration
The system creates structured notes in your Obsidian vault:
- **Meetings/** - Meeting notes with analysis and transcripts
- **Tasks/** - Individual task files with YAML frontmatter
- **People/** - Person profiles with meeting history
- **Companies/** - Company relationships and technologies
- **Technologies/** - Implementation status and usage
- **Meta/dashboards/** - Live analytics dashboards

### API Requirements
- **ANTHROPIC_API_KEY** - Required for AI analysis, entity detection, task extraction
- **OPENAI_API_KEY** - Required for Whisper transcription
- Both APIs are required for full functionality; system will create reminder notes if missing

### Storage Configuration

#### Local Storage (Default)
Set `STORAGE_MODE=local` or leave unset. Requires local directory mounts:
- `INPUT_DIR` - Directory for MP4 files
- `OUTPUT_DIR` - Directory for processed outputs
- `PROCESSED_DIR` - Archive directory for completed files

#### Google Drive Storage
Set `STORAGE_MODE=google_drive` and configure:
- **GOOGLE_DRIVE_INPUT_FOLDER_ID** - Google Drive folder ID for input MP4 files
- **GOOGLE_DRIVE_OUTPUT_FOLDER_ID** - Google Drive folder ID for output files
- **GOOGLE_DRIVE_PROCESSED_FOLDER_ID** - Google Drive folder ID for processed files
- **GOOGLE_DRIVE_CREDENTIALS_PATH** - Path to credentials.json (default: /app/credentials.json)
- **GOOGLE_DRIVE_TOKEN_PATH** - Path to store token.json (default: /app/token.json)

##### Google Drive Setup Steps:
1. Create a Google Cloud Project
2. Enable Google Drive API
3. Create service account or OAuth2 credentials
4. Download credentials.json file
5. Mount credentials.json into the container
6. Create three folders in Google Drive (input, output, processed)
7. Get folder IDs from Google Drive URLs and set in environment variables

### Error Handling
- Comprehensive logging with structured output (`utils/logger.py`)
- File processing is atomic - failures don't affect other files
- Graceful degradation when API keys are missing
- Duplicate file detection prevents reprocessing

### Development Notes
- All paths use `pathlib.Path` for cross-platform compatibility
- Thread-safe file operations with locking mechanisms
- Container runs as non-root user with configurable UID/GID
- Volume mounts support Windows paths in docker-compose.yml
- No formal testing framework - relies on integration testing with real files