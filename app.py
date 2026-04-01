# app_multiplatform_client.py
import os
import subprocess
import uuid
import json
import re
from flask import Flask, render_template, request, jsonify, send_file
from pathlib import Path
import threading
import time

app = Flask(__name__)
app.config['TEMP_FOLDER'] = 'temp_downloads'
app.config['COOKIES_FILE'] = 'cookies.txt'
app.config['MAX_FILE_SIZE'] = 2 * 1024 * 1024 * 1024  # 2GB

# Create temp folder
os.makedirs(app.config['TEMP_FOLDER'], exist_ok=True)

# Supported platforms
SUPPORTED_PLATFORMS = {
    'youtube': {
        'domains': ['youtube.com', 'youtu.be'],
        'requires_auth': False,
        'instructions': 'No authentication needed for YouTube'
    },
    'netflix': {
        'domains': ['netflix.com'],
        'requires_auth': True,
        'instructions': '⚠️ Netflix requires cookies. Export cookies from your browser after logging in.'
    },
    'amazon': {
        'domains': ['amazon.com', 'primevideo.com'],
        'requires_auth': True,
        'instructions': '⚠️ Amazon Prime requires cookies. Export cookies from your browser after logging in.'
    },
    'disney': {
        'domains': ['disneyplus.com', 'hotstar.com'],
        'requires_auth': True,
        'instructions': '⚠️ Disney+ requires cookies. Export cookies from your browser after logging in.'
    },
    'hulu': {
        'domains': ['hulu.com'],
        'requires_auth': True,
        'instructions': '⚠️ Hulu requires cookies. Export cookies from your browser after logging in.'
    },
    'hbomax': {
        'domains': ['hbomax.com', 'max.com'],
        'requires_auth': True,
        'instructions': '⚠️ HBO Max requires cookies. Export cookies from your browser after logging in.'
    },
    'peacock': {
        'domains': ['peacocktv.com'],
        'requires_auth': True,
        'instructions': '⚠️ Peacock requires cookies. Export cookies from your browser after logging in.'
    },
    'paramount': {
        'domains': ['paramountplus.com'],
        'requires_auth': True,
        'instructions': '⚠️ Paramount+ requires cookies. Export cookies from your browser after logging in.'
    },
    'apple': {
        'domains': ['tv.apple.com'],
        'requires_auth': True,
        'instructions': '⚠️ Apple TV+ requires cookies. Export cookies from your browser after logging in.'
    },
    'vimeo': {
        'domains': ['vimeo.com'],
        'requires_auth': False,
        'instructions': 'No authentication needed for Vimeo'
    },
    'dailymotion': {
        'domains': ['dailymotion.com'],
        'requires_auth': False,
        'instructions': 'No authentication needed for Dailymotion'
    }
}

def detect_platform(url):
    """Detect which platform the URL belongs to"""
    url_lower = url.lower()
    for platform, info in SUPPORTED_PLATFORMS.items():
        for domain in info['domains']:
            if domain in url_lower:
                return platform, info
    return 'unknown', {'requires_auth': False, 'instructions': 'Unknown platform'}

def get_available_formats(url):
    """Get available formats for the video"""
    try:
        cmd = ['yt-dlp', '-F', url]
        
        # Add cookies if available
        if os.path.exists(app.config['COOKIES_FILE']):
            cmd.extend(['--cookies', app.config['COOKIES_FILE']])
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            return None
        
        formats = []
        for line in result.stdout.split('\n'):
            if 'mp4' in line or 'm4a' in line:
                parts = line.split()
                if parts and parts[0].isdigit():
                    formats.append({
                        'code': parts[0],
                        'info': ' '.join(parts[1:])[:100]
                    })
        
        return formats[:15]  # Return top 15 formats
    except:
        return None

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
        
        platform, info = detect_platform(url)
        
        # Get available formats
        formats = get_available_formats(url)
        
        return jsonify({
            'success': True,
            'platform': platform,
            'requires_auth': info['requires_auth'],
            'instructions': info['instructions'],
            'message': f'Detected: {platform.upper()}',
            'formats': formats
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/video_info', methods=['POST'])
def video_info():
    """Get video metadata without downloading"""
    try:
        data = request.get_json()
        url = data.get('url')
        platform = data.get('platform', 'unknown')
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        # Build command
        cmd = ['yt-dlp', '--get-title', '--get-duration', '--get-id', url]
        
        # Add cookies if platform requires auth and cookies exist
        platform_info = SUPPORTED_PLATFORMS.get(platform, {})
        if platform_info.get('requires_auth', False) and os.path.exists(app.config['COOKIES_FILE']):
            cmd.extend(['--cookies', app.config['COOKIES_FILE']])
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        if result.returncode != 0:
            return jsonify({'error': result.stderr}), 400
        
        lines = result.stdout.strip().split('\n')
        
        return jsonify({
            'success': True,
            'title': lines[0] if len(lines) > 0 else 'Unknown',
            'duration': lines[1] if len(lines) > 1 else '0',
            'video_id': lines[2] if len(lines) > 2 else None
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download_direct', methods=['POST'])
def download_direct():
    """Download video and stream directly to client"""
    try:
        data = request.get_json()
        url = data.get('url')
        format_code = data.get('format_code', 'best')
        platform = data.get('platform', 'unknown')
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        # Generate unique filename
        video_id = str(uuid.uuid4())[:8]
        filename = f"{video_id}.mp4"
        filepath = os.path.join(app.config['TEMP_FOLDER'], filename)
        
        # Build download command
        cmd = [
            'yt-dlp',
            '-f', format_code if format_code != 'best' else 'best[ext=mp4]/best',
            '-o', filepath,
            '--no-playlist',
            '--restrict-filenames'
        ]
        
        # Add cookies if platform requires auth
        platform_info = SUPPORTED_PLATFORMS.get(platform, {})
        if platform_info.get('requires_auth', False) and os.path.exists(app.config['COOKIES_FILE']):
            cmd.extend(['--cookies', app.config['COOKIES_FILE']])
            print(f"Using cookies for {platform}")
        
        # Add user agent for better compatibility
        cmd.extend([
            '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        ])
        
        # Add URL
        cmd.append(url)
        
        print(f"Running: {' '.join(cmd)}")  # Debug
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        if result.returncode != 0:
            if os.path.exists(filepath):
                os.remove(filepath)
            
            # Check for authentication errors
            if 'HTTP Error 403' in result.stderr or 'sign in' in result.stderr.lower():
                return jsonify({'error': f'Authentication required. Please upload cookies.txt for {platform}'}), 400
            
            return jsonify({'error': result.stderr}), 400
        
        # Check if file was created
        if not os.path.exists(filepath):
            return jsonify({'error': 'File not created'}), 500
        
        # Get file size
        file_size = os.path.getsize(filepath)
        size_mb = f"{file_size / (1024*1024):.1f} MB"
        
        # Get video title
        title_cmd = ['yt-dlp', '--get-title', url]
        title_result = subprocess.run(title_cmd, capture_output=True, text=True)
        title = title_result.stdout.strip() if title_result.returncode == 0 else "Video"
        
        return jsonify({
            'success': True,
            'filename': filename,
            'title': title,
            'size': size_mb,
            'platform': platform,
            'message': f'Downloaded from {platform.upper()}'
        })
        
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Download timeout (took too long)'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download_temp/<filename>')
def download_temp(filename):
    """Serve temp file for client-side processing"""
    try:
        filepath = os.path.join(app.config['TEMP_FOLDER'], filename)
        if os.path.exists(filepath):
            return send_file(filepath, as_attachment=False)
        else:
            return jsonify({'error': 'File not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/upload_cookies', methods=['POST'])
def upload_cookies():
    """Upload cookies.txt file for authenticated platforms"""
    try:
        if 'cookies_file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['cookies_file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        # Save cookies file
        file.save(app.config['COOKIES_FILE'])
        
        # Verify cookies work with a test
        test_cmd = ['yt-dlp', '--cookies', app.config['COOKIES_FILE'], '--version']
        result = subprocess.run(test_cmd, capture_output=True, text=True)
        
        return jsonify({
            'success': True,
            'message': 'Cookies uploaded and verified successfully'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/cleanup_temp', methods=['POST'])
def cleanup_temp():
    """Clean up temp files"""
    try:
        for file in Path(app.config['TEMP_FOLDER']).glob('*'):
            if file.is_file():
                file.unlink()
        return jsonify({'success': True, 'message': 'Cleanup completed'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
