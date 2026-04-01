# app_multiplatform.py
import os
import subprocess
import json
import re
from flask import Flask, render_template, request, jsonify, send_file
from pathlib import Path
import uuid
import threading
import time

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'downloads'
app.config['CLIPS_FOLDER'] = 'clips'
app.config['COOKIES_FILE'] = 'cookies.txt'  # For Netflix authentication

# Create necessary directories
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['CLIPS_FOLDER'], exist_ok=True)

# Supported platforms and their notes
SUPPORTED_PLATFORMS = {
    'youtube': ['youtube.com', 'youtu.be'],
    'netflix': ['netflix.com'],
    'amazon': ['amazon.com', 'primevideo.com'],
    'disney': ['disneyplus.com', 'hotstar.com'],
    'hulu': ['hulu.com'],
    'hbomax': ['hbomax.com', 'max.com'],
    'peacock': ['peacocktv.com'],
    'paramount': ['paramountplus.com'],
    'apple': ['tv.apple.com'],
    'vimeo': ['vimeo.com'],
    'dailymotion': ['dailymotion.com'],
    'facebook': ['facebook.com'],
    'instagram': ['instagram.com'],
    'twitter': ['twitter.com', 'x.com'],
    'tiktok': ['tiktok.com'],
    'twitch': ['twitch.tv']
}

def detect_platform(url):
    """Detect which streaming platform the URL is from"""
    for platform, domains in SUPPORTED_PLATFORMS.items():
        for domain in domains:
            if domain in url.lower():
                return platform
    return 'unknown'

def get_platform_instructions(platform):
    """Get platform-specific instructions"""
    instructions = {
        'netflix': """
        ⚠️ Netflix requires authentication:
        1. Install browser extension to export cookies
        2. Save cookies.txt file in the app directory
        3. Make sure you're logged into Netflix
        """,
        'amazon': """
        ⚠️ Amazon Prime requires authentication:
        1. Export cookies from your browser
        2. Save as cookies.txt
        3. Must have active Prime subscription
        """,
        'disney': """
        ⚠️ Disney+ requires authentication:
        1. Export cookies after logging in
        2. Save as cookies.txt
        3. Active subscription required
        """,
        'hulu': """
        ⚠️ Hulu requires authentication:
        1. Export cookies from browser
        2. Save as cookies.txt
        """,
        'default': "Standard download (no authentication needed)"
    }
    return instructions.get(platform, instructions['default'])

def download_video_multiplatform(url, cookies_file=None):
    """Download video from any supported platform using yt-dlp"""
    try:
        video_id = str(uuid.uuid4())[:8]
        output_template = os.path.join(app.config['UPLOAD_FOLDER'], f'video_{video_id}.%(ext)s')
        
        # Base command
        cmd = [
            'yt-dlp',
            '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            '-o', output_template,
            '--merge-output-format', 'mp4',
            '--no-playlist',  # Don't download entire playlist
            '--restrict-filenames',  # Safer filenames
        ]
        
        # Add cookies if available
        if cookies_file and os.path.exists(cookies_file):
            cmd.extend(['--cookies', cookies_file])
        
        # Add platform-specific options
        platform = detect_platform(url)
        
        if platform == 'netflix':
            cmd.extend([
                '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                '--add-header', 'Accept-Language:en-US,en;q=0.9'
            ])
        elif platform == 'amazon':
            cmd.extend([
                '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            ])
        elif platform == 'disney':
            cmd.extend([
                '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                '--add-header', 'Accept-Language:en-US,en;q=0.9'
            ])
        
        # Add URL
        cmd.append(url)
        
        print(f"Running command: {' '.join(cmd)}")  # Debug output
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            # Check for authentication errors
            if 'Private video' in result.stderr or 'Sign in' in result.stderr:
                raise Exception(f"Authentication required! Please provide cookies.txt file for {platform}")
            elif 'HTTP Error 403' in result.stderr:
                raise Exception(f"Access denied. {get_platform_instructions(platform)}")
            else:
                raise Exception(f"Download failed: {result.stderr}")
        
        # Find the downloaded file
        downloaded_files = list(Path(app.config['UPLOAD_FOLDER']).glob(f'video_{video_id}.*'))
        if not downloaded_files:
            raise Exception("No file downloaded")
        
        video_path = str(downloaded_files[0])
        
        # Get video title
        title_cmd = ['yt-dlp', '--get-title', url]
        if cookies_file and os.path.exists(cookies_file):
            title_cmd.extend(['--cookies', cookies_file])
        
        title_result = subprocess.run(title_cmd, capture_output=True, text=True)
        title = title_result.stdout.strip() if title_result.returncode == 0 else f"Video_{video_id}"
        
        return video_path, title, platform
        
    except Exception as e:
        raise Exception(f"Download failed: {str(e)}")

def get_available_formats(url, cookies_file=None):
    """Get available formats for a video"""
    try:
        cmd = ['yt-dlp', '-F', url]
        if cookies_file and os.path.exists(cookies_file):
            cmd.extend(['--cookies', cookies_file])
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            return None
        
        # Parse format codes
        formats = []
        for line in result.stdout.split('\n'):
            if 'mp4' in line or 'm4a' in line:
                parts = line.split()
                if parts and parts[0].isdigit():
                    formats.append({
                        'code': parts[0],
                        'info': line.strip()
                    })
        
        return formats[:20]  # Return first 20 formats
    except:
        return None

def split_video(video_path, num_clips, clip_duration=None):
    """Split video using ffmpeg with optional custom duration"""
    try:
        # Get video duration
        duration_cmd = [
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', video_path
        ]
        duration_result = subprocess.run(duration_cmd, capture_output=True, text=True)
        video_duration = float(duration_result.stdout.strip())
        
        # Use custom clip duration if provided, otherwise auto-calculate
        if clip_duration and clip_duration > 0:
            num_clips = int(video_duration / clip_duration) + 1
            clip_duration_sec = clip_duration
        else:
            # Auto-calculate for 3-5 minute clips
            min_duration = 180
            max_duration = 300
            total_duration_needed = num_clips * min_duration
            
            if total_duration_needed > video_duration:
                num_clips = max(1, int(video_duration // min_duration))
            
            clip_duration_sec = video_duration / num_clips
            if clip_duration_sec > max_duration:
                clip_duration_sec = max_duration
                num_clips = int(video_duration // clip_duration_sec) + 1
        
        clips_info = []
        
        # Split video
        for i in range(num_clips):
            start_time = i * clip_duration_sec
            end_time = min((i + 1) * clip_duration_sec, video_duration)
            
            if start_time >= video_duration:
                break
            
            clip_filename = f"clip_{i+1}_{uuid.uuid4().hex[:8]}.mp4"
            clip_path = os.path.join(app.config['CLIPS_FOLDER'], clip_filename)
            
            # Extract clip with re-encoding for compatibility
            ffmpeg_cmd = [
                'ffmpeg', '-i', video_path,
                '-ss', str(start_time),
                '-to', str(end_time),
                '-c:v', 'libx264',
                '-c:a', 'aac',
                '-preset', 'fast',
                '-crf', '23',
                clip_path, '-y'
            ]
            
            result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                # Try copy codec as fallback
                ffmpeg_cmd = [
                    'ffmpeg', '-i', video_path,
                    '-ss', str(start_time),
                    '-to', str(end_time),
                    '-c', 'copy',
                    clip_path, '-y'
                ]
                result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
                
                if result.returncode != 0:
                    raise Exception(f"Clip extraction failed: {result.stderr}")
            
            clip_duration_actual = end_time - start_time
            clips_info.append({
                'filename': clip_filename,
                'path': clip_path,
                'start': start_time,
                'end': end_time,
                'duration': clip_duration_actual,
                'duration_minutes': f"{int(clip_duration_actual // 60)}:{(int(clip_duration_actual % 60)):02d}"
            })
        
        return clips_info
        
    except Exception as e:
        raise Exception(f"Video splitting failed: {str(e)}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/detect_platform', methods=['POST'])
def detect_platform_endpoint():
    try:
        data = request.get_json()
        url = data.get('url')
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        platform = detect_platform(url)
        instructions = get_platform_instructions(platform)
        
        # Get available formats
        formats = get_available_formats(url, app.config['COOKIES_FILE'])
        
        return jsonify({
            'platform': platform,
            'instructions': instructions,
            'requires_auth': platform in ['netflix', 'amazon', 'disney', 'hulu', 'hbomax'],
            'formats': formats
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download', methods=['POST'])
def download_video():
    try:
        data = request.get_json()
        url = data.get('url')
        format_code = data.get('format_code', 'best')
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        # Get platform info first
        platform = detect_platform(url)
        
        # Download video
        video_path, title, downloaded_platform = download_video_multiplatform(
            url, 
            app.config['COOKIES_FILE'] if os.path.exists(app.config['COOKIES_FILE']) else None
        )
        
        return jsonify({
            'success': True,
            'message': f'Video downloaded successfully from {downloaded_platform}',
            'video_path': video_path,
            'title': title,
            'platform': downloaded_platform
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/split', methods=['POST'])
def split_video_endpoint():
    try:
        data = request.get_json()
        video_path = data.get('video_path')
        num_clips = int(data.get('num_clips', 3))
        clip_duration = data.get('clip_duration')  # Optional custom duration in seconds
        
        if not video_path:
            return jsonify({'error': 'Video path is required'}), 400
        
        if not os.path.exists(video_path):
            return jsonify({'error': 'Video file not found'}), 404
        
        # Ensure num_clips is between 1 and 10
        num_clips = max(1, min(10, num_clips))
        
        clips = split_video(video_path, num_clips, clip_duration)
        
        return jsonify({
            'success': True,
            'message': f'Video split into {len(clips)} clips successfully',
            'clips': clips
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download_clip/<filename>')
def download_clip(filename):
    try:
        clip_path = os.path.join(app.config['CLIPS_FOLDER'], filename)
        if os.path.exists(clip_path):
            return send_file(clip_path, as_attachment=True, download_name=filename)
        else:
            return jsonify({'error': 'Clip not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/cleanup', methods=['POST'])
def cleanup():
    try:
        for folder in [app.config['UPLOAD_FOLDER'], app.config['CLIPS_FOLDER']]:
            for file in os.listdir(folder):
                file_path = os.path.join(folder, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
        
        return jsonify({'success': True, 'message': 'Cleanup completed'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/upload_cookies', methods=['POST'])
def upload_cookies():
    try:
        if 'cookies_file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['cookies_file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        file.save(app.config['COOKIES_FILE'])
        
        return jsonify({'success': True, 'message': 'Cookies uploaded successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)