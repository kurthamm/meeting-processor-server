# Google Drive Setup Guide

This guide walks you through setting up the Meeting Processor to use Google Drive for file storage instead of local directories.

## Prerequisites

- Google account with access to Google Drive
- Google Cloud Platform account (free tier is sufficient)
- Docker and Docker Compose installed

## Step 1: Google Cloud Setup

### 1.1 Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click "New Project" or select an existing project
3. Give your project a name (e.g., "meeting-processor")
4. Note your Project ID

### 1.2 Enable Google Drive API

1. In the Google Cloud Console, go to "APIs & Services" > "Library"
2. Search for "Google Drive API"
3. Click on it and press "Enable"

### 1.3 Create Credentials

1. Go to "APIs & Services" > "Credentials"
2. Click "Create Credentials" > "OAuth client ID"
3. Choose "Desktop application" as the application type
4. Give it a name (e.g., "Meeting Processor")
5. Click "Create"
6. Download the JSON file (this is your `credentials.json`)

## Step 2: Google Drive Folder Setup

### 2.1 Create Folders

Create four folders in your Google Drive:
- `meeting-processor-input` (for MP4 files to process)
- `meeting-processor-output` (for processed results)
- `meeting-processor-processed` (for archived MP4 files)
- `meeting-processor-vault` (for Obsidian vault sync - optional)

### 2.2 Get Folder IDs

For each folder:
1. Open the folder in Google Drive in your browser
2. Look at the URL: `https://drive.google.com/drive/folders/FOLDER_ID_HERE`
3. Copy the folder ID (the long string after `/folders/`)

Example:
- URL: `https://drive.google.com/drive/folders/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms`
- Folder ID: `1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms`

## Step 3: Application Configuration

### 3.1 Prepare Environment File

1. Copy the example environment file:
   ```bash
   cp .env.google-drive-example .env
   ```

2. Edit `.env` and configure:
   ```env
   STORAGE_MODE=google_drive
   GOOGLE_DRIVE_INPUT_FOLDER_ID=your_input_folder_id_here
   GOOGLE_DRIVE_OUTPUT_FOLDER_ID=your_output_folder_id_here
   GOOGLE_DRIVE_PROCESSED_FOLDER_ID=your_processed_folder_id_here
   GOOGLE_DRIVE_VAULT_FOLDER_ID=your_vault_folder_id_here
   ```

3. Add your API keys:
   ```env
   ANTHROPIC_API_KEY=your_anthropic_key
   OPENAI_API_KEY=your_openai_key
   ```

4. Configure vault location (optional):
   ```env
   # Vault location options:
   # - Leave GOOGLE_DRIVE_VAULT_FOLDER_ID empty: Use local vault (traditional)
   # - Set GOOGLE_DRIVE_VAULT_FOLDER_ID: Store vault directly in Google Drive
   GOOGLE_DRIVE_VAULT_FOLDER_ID=your_vault_folder_id_here
   ```

### 3.2 Update Docker Compose

Edit `docker-compose.yml` to mount your credentials file:

```yaml
volumes:
  # Mount your credentials.json file
  - "/path/to/your/credentials.json:/app/credentials.json:ro"
  - "/path/to/store/token.json:/app/token.json:rw"
  # Keep the Obsidian vault mount
  - "/path/to/your/obsidian/vault:/app/obsidian_vault:rw"
```

Replace `/path/to/your/credentials.json` with the actual path to your downloaded credentials file.

## Step 4: First Run and Authentication

### 4.1 Build and Start

```bash
docker-compose up --build
```

### 4.2 Complete OAuth Flow

On first run, the application will:
1. Print a URL to the console
2. Ask you to visit the URL in your browser
3. Complete the Google OAuth flow
4. Authorize the application to access your Google Drive

The authorization token will be saved and reused for future runs.

## Step 5: Testing

### 5.1 Upload Test File

1. Upload an MP4 file to your input folder in Google Drive
2. Monitor the application logs:
   ```bash
   docker logs -f meeting-processor
   ```

### 5.2 Verify Processing

The application should:
1. Detect the new MP4 file
2. Download it for processing
3. Upload results (JSON and MD files) to the output folder
4. Move the original MP4 to the processed folder

## Troubleshooting

### Authentication Issues

- **Error: `credentials.json not found`**
  - Ensure the credentials file is mounted correctly in docker-compose.yml
  - Verify the file path exists and is readable

- **Error: `Invalid credentials`**
  - Re-download credentials.json from Google Cloud Console
  - Ensure you're using OAuth client credentials, not service account

### API Issues

- **Error: `Google Drive API not enabled`**
  - Go to Google Cloud Console > APIs & Services > Library
  - Search for and enable "Google Drive API"

- **Error: `Insufficient permissions`**
  - The OAuth scope includes full Google Drive access
  - Re-run the authentication flow if needed

### Folder Issues

- **Error: `Folder not found`**
  - Verify folder IDs are correct
  - Ensure the authenticated Google account has access to the folders
  - Check that folders aren't in Trash

### Network Issues

- **Error: `Connection timeout`**
  - Check internet connectivity
  - Verify firewall isn't blocking Google APIs
  - Try running outside of corporate network if applicable

## Security Notes

- Store your `credentials.json` file securely
- The `token.json` file contains your access token - keep it private
- Consider using service accounts for production deployments
- Regularly review and rotate credentials as needed

## Vault Storage Options

The application supports two vault storage approaches:

### Local Vault (Default)
- **Use case**: Traditional setup where you access Obsidian on the same machine
- **Configuration**: Leave `GOOGLE_DRIVE_VAULT_FOLDER_ID` empty or unset
- **Behavior**: Vault files stored locally, requires local Obsidian access
- **Best for**: Desktop deployments, single-user setups

### Google Drive Vault 
- **Use case**: Server deployment where you want vault accessible anywhere
- **Configuration**: Set `GOOGLE_DRIVE_VAULT_FOLDER_ID` to your vault folder ID
- **Behavior**: All vault files stored directly in Google Drive
- **Best for**: Server deployments, multi-device access
- **Access**: Edit vault files directly through Google Drive web interface or mobile app

### Recommended Setup for Server Deployment

1. **Use Google Drive vault** for maximum accessibility
2. **Create a dedicated folder** in Google Drive for your vault
3. **Access your vault** through any device with Google Drive
4. **No local Obsidian needed** - view/edit through Google Drive directly

## Switching Back to Local Storage

To switch back to local file system storage:

1. Set `STORAGE_MODE=local` in your `.env` file
2. Remove or empty `GOOGLE_DRIVE_VAULT_FOLDER_ID` to use local vault
3. Ensure local volume mounts are configured in docker-compose.yml
4. Restart the application

The application supports both modes and can be switched without code changes.