# Apple Music Integration Setup Guide

Dynamic Player now supports full Apple Music API integration! This provides enhanced metadata, high-quality album artwork, and playlist/album management.

## Setup Modes

### 1. Basic Mode (No API Credentials)
- **What you get**: Apple Music playback detection via Windows Media Player
- **Limitations**: Basic album art from system, limited metadata
- **Setup**: No additional setup required - just play music in Apple Music!

### 2. Enhanced Mode (With API Credentials)
- **What you get**: 
  - High-quality album artwork
  - Rich metadata from Apple Music catalog
  - Playlist and album browsing
  - Better color theme extraction
- **Requirements**: Apple Developer account and MusicKit credentials

## Getting Apple Music API Credentials

### Step 1: Apple Developer Account
1. Go to [developer.apple.com](https://developer.apple.com/)
2. Sign in with your Apple ID
3. Enroll in the Apple Developer Program (free tier available)

### Step 2: Create MusicKit Key
1. Navigate to [Certificates, Identifiers & Profiles](https://developer.apple.com/account/resources/authkeys/list)
2. Click the "+" button to create a new key
3. Name it (e.g., "Dynamic Player MusicKit")
4. Check "MusicKit" in the list of services
5. Click "Continue" and then "Register"
6. Download the `.p8` private key file (save it securely - you can't download it again!)
7. Note your **Key ID** (displayed on the confirmation page)

### Step 3: Find Your Team ID
1. Go to [Membership page](https://developer.apple.com/account/#/membership/)
2. Your **Team ID** is listed under your name

### Step 4: Configure Dynamic Player
1. Launch Dynamic Player (it will show the Apple Music setup dialog on first run)
2. OR press 'C' to open settings, then navigate to API Setup
3. Enter your:
   - **Team ID**: From step 3
   - **Key ID**: From step 2
   - **Private Key**: Either paste the contents of your `.p8` file, or click "Load from .p8 file..."
4. Click "Save Credentials"

### Optional: User Token (For Personal Library)
- The **User Token** is optional and enables access to your personal Apple Music library
- This requires additional MusicKit JS integration (web-based auth)
- Leave blank for catalog-only access

## Priority System

Dynamic Player uses a smart priority system for media sources:

1. **Spotify** (highest priority when actively playing)
2. **Apple Music** (second priority)
3. **Windows Media Player** (fallback for other apps like YouTube Music, VLC, etc.)

This means:
- If Spotify is playing, it takes over
- If Spotify is paused, Apple Music or Windows media can take over
- When Apple Music stops, the display reverts to Spotify if it has a paused track

## Troubleshooting

### "Failed to generate developer token"
- Make sure you have installed: `pip install PyJWT cryptography`
- Verify your Team ID, Key ID, and private key are correct
- Check that the private key includes the header and footer lines:
  ```
  -----BEGIN PRIVATE KEY-----
  [your key content]
  -----END PRIVATE KEY-----
  ```

### "Apple Music not detected"
- Basic detection works automatically via Windows Media Player
- Make sure Apple Music (iTunes) is running on Windows
- Check that media controls are enabled in Windows settings

### Playlists not showing
- User Token is required for personal library access
- Catalog playlists work without user token
- Try "Skip this step" to use basic integration

## Compatibility with Spotify

All your existing Spotify settings, saved playlists, and color customizations remain intact. Apple Music integration runs alongside Spotify without conflicts.

- Saved playlists/albums from both services appear in the same panel
- Each album/track retains its custom color settings (stored by album ID)
- You can switch between services seamlessly

## Changing Your Mind After Skipping

If you initially skipped Spotify or Apple Music setup but want to configure them later:

### Option 1: Via Settings Dialog
1. Open settings (press 'C')
2. Go to API Setup tab
3. Click "Configure Spotify" or "Configure Apple Music"
4. Enter your credentials

### Option 2: Manual Registry Reset (Windows)
If you want to force the setup dialogs to appear again on next launch:
1. Press Windows+R and type `regedit`
2. Navigate to: `HKEY_CURRENT_USER\Software\SpotifySync\App`
3. Delete these values (if present):
   - `spotify_setup_skipped`
   - `apple_music_setup_skipped`
4. Restart Dynamic Player

## Uninstalling Integration

### Remove Spotify
To remove Spotify credentials:
- Open settings → API Setup → Reset Spotify Credentials
- OR delete registry values: `spotify_client_id`, `spotify_client_secret`

### Remove Apple Music
To remove Apple Music credentials:
- Open settings → API Setup → Reset Apple Music Credentials  
- OR delete registry values: `apple_music_team_id`, `apple_music_key_id`, `apple_music_private_key`, `apple_music_user_token`

Basic playback detection via Windows Media Player will continue to work even without API credentials.

---

For more info, see: [Apple MusicKit Documentation](https://developer.apple.com/documentation/musickit/)
