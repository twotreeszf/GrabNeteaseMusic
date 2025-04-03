import requests
from enum import Enum
import subprocess
import time
import os
import signal
import atexit
import base64
import io
import json
from PIL import Image
from urllib.parse import urlparse
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TPE2, TALB, TRCK, TPOS, TYER
from mutagen.mp3 import MP3
from mutagen.flac import FLAC, Picture
from mutagen.mp4 import MP4
from datetime import datetime
import sys

# Terminal colors
class Colors:
    GREEN = '\033[92m'
    BLUE = '\033[94m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    PURPLE = '\033[95m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'

def print_success(message):
    print(f"{Colors.GREEN}{message}{Colors.END}")

def print_info(message):
    print(message)

def print_error(message):
    print(f"{Colors.RED}{message}{Colors.END}")

def print_warning(message):
    print(f"{Colors.YELLOW}{message}{Colors.END}")

def print_highlight(message):
    print(f"{Colors.BOLD}{message}{Colors.END}")

class NeteaseAudioQuality(Enum):
    """Audio quality enumeration
    
    - STANDARD: Standard quality (128kbps)
    - HIGHER: Higher quality (320kbps)
    - EXHIGH: Excellent quality (320kbps)
    - LOSSLESS: Lossless quality (FLAC)
    - HIRES: Hi-Res quality
    """
    STANDARD = 'standard'
    HIGHER = 'higher'
    EXHIGH = 'exhigh'
    LOSSLESS = 'lossless'
    HIRES = 'hires'

class NeteaseSong:
    def __init__(self, song_id, song_name, cd_number, track_number):
        self.song_id = song_id
        self.song_name = song_name
        self.cd_number = cd_number
        self.track_number = track_number
        self.avalibe_qualities = []

    def add_quality(self, quality: NeteaseAudioQuality):
        self.avalibe_qualities.append(quality)

class NeteaseSongDownloadInfo:
    def __init__(self, song_id, ext_name, url):
        self.song_id = song_id
        self.ext_name = ext_name
        self.url = url
        
    def __str__(self):
        return f"Download Info - Song ID: {self.song_id}, Extension: {self.ext_name}, URL available: {'Yes' if self.url else 'No'}"

class NeteaseArtist:
    def __init__(self, artist_id, artist_name):
        self.artist_id = artist_id
        self.artist_name = artist_name

class NeteaseAlbum:
    def __init__(self, album_id, album_name, publish_time, publish_company, tracks_count, album_cover_url, artist: NeteaseArtist):
        self.album_id = album_id
        self.album_name = album_name
        self.publish_time = publish_time
        self.publish_company = publish_company
        self.tracks_count = tracks_count
        self.album_cover_url = album_cover_url
        self.artist = artist
        self.songs = []

    def add_song(self, song: NeteaseSong):
        self.songs.append(song)
        

class NeteaseGrabber:
    def __init__(self, port=9979):
        self.port = port
        self.server_process = None
        self.base_url = f'http://localhost:{port}'
        self.cookies = None
        # Register cleanup function on program exit
        atexit.register(self._stop_server)
    
    def start_server(self):
        """Start the NetEase Cloud Music API server
        
        Returns:
            bool: Whether the server was successfully started
        """
        if self.server_process is not None:
            print("Server is already running")
            return True
            
        try:
            # Create environment variables with PORT set
            env = os.environ.copy()
            env['PORT'] = str(self.port)
            
            # Build the command (no need to specify port in command line args since we use ENV)
            cmd = ['node', 'NeteaseCloudMusicApi/node_modules/NeteaseCloudMusicApi/app.js']
            
            # Start the server process with the custom environment
            self.server_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                preexec_fn=os.setsid  # Create a new process group
            )
            
            # Wait for the server to start
            max_retries = 30
            retries = 0
            while retries < max_retries:
                try:
                    # Test if the server is responsive
                    response = requests.get(self.base_url)
                    if response.status_code == 200:
                        print(f"NetEase Cloud Music API server started on port {self.port}")
                        return True
                except requests.exceptions.ConnectionError:
                    retries += 1
                    time.sleep(1)
            
            print("Server startup timed out")
            self._stop_server()
            return False
            
        except Exception as e:
            print(f"Error starting server: {str(e)}")
            self._stop_server()
            return False
    
    def _stop_server(self):
        """Clean up server process"""
        if self.server_process:
            try:
                # Terminate the entire process group
                os.killpg(os.getpgid(self.server_process.pid), signal.SIGTERM)
                self.server_process = None
            except:
                pass

    def _parse_cookies(self, cookie_string):
        """Parse cookie string into a dictionary
        
        Args:
            cookie_string (str): Cookie string from API response
            
        Returns:
            dict: Dictionary of cookie name-value pairs
        """
        cookies = {}
        if not cookie_string:
            return cookies
            
        # Split cookies by semicolon
        cookie_parts = cookie_string.split(';')
        
        for part in cookie_parts:
            part = part.strip()
            if not part or '=' not in part:
                continue
                
            # Split into name and value
            name, value = part.split('=', 1)
            
            # Skip metadata like Path, Expires, etc.
            if name in ('Path', 'Max-Age', 'Expires', 'HTTPOnly', 'Secure'):
                continue
                
            cookies[name] = value
            
        return cookies
        
    def check_login_status(self):
        """Check if user is logged in
        
        Returns:
            bool: True if logged in, False otherwise
        """
        try:
            timestamp = int(time.time() * 1000)
            response = requests.get(f"{self.base_url}/login/status", params={"timestamp": timestamp}, cookies=self.cookies)
            if response.status_code != 200:
                return False
                
            data = response.json()
            
            # Check login status based on account.type field
            # type=1 means logged in, type=1000 means not logged in
            account_data = data.get('data', {}).get('account', {})
            if account_data.get('type') == 1:
                return True
                
            return False
        except Exception as e:
            print(f"Error checking login status: {str(e)}")
            return False

    def login(self):
        """Login to NetEase Cloud Music
        
        Returns:
            bool: True if login successful, False otherwise
        """
        try:
            # Step 1: Get QR code key
            key = self._get_login_qrkey()
            if not key:
                print_error("Failed to get QR code key")
                return False
                
            # Step 2: Get QR code image
            time.sleep(1)
            qr_data = self._get_login_qrcode(key)
            if not qr_data:
                print_error("Failed to get QR code image")
                return False
                
            # Step 3: Display QR code
            time.sleep(1)
            print_highlight("Please scan the QR code with the NetEase Cloud Music app")
            self.show_qr_code(qr_data)
            
            # Step 4: Poll login status
            time.sleep(1)
            print_info("Waiting for scan and confirmation...")
            while True:
                status = self._check_qr_login_status(key)
                if not status:
                    print_error("Error checking login status")
                    return False
                    
                if status['code'] == 803:
                    self.cookies = self._parse_cookies(status['cookie'])
                    self.save_cookies()
                    print_success("Login successful!")
                    return True
                elif status['code'] == 800:
                    print_error("QR code expired")
                    return False
                elif status['code'] == 802:
                    print_info("QR code scanned, waiting for confirmation...")
                elif status['code'] == 801:
                    pass  # Still waiting for scan, no need to print repeatedly
                
                time.sleep(1)  # Poll every 1 second
                
        except Exception as e:
            print_error(f"Error during login process: {str(e)}")
            return False

    def logout(self):
        """Log out from NetEase Cloud Music
        
        Returns:
            bool: True if logout successful, False otherwise
        """
        time.sleep(1)
        try:
            timestamp = int(time.time() * 1000)
            response = requests.get(f"{self.base_url}/logout", params={"timestamp": timestamp}, cookies=self.cookies)
            if response.status_code != 200:
                return False
                
            data = response.json()
            
            # Check if logout is successful (code == 200)
            if data.get('code') == 200:
                # Clear cookies
                self.cookies = None
                if os.path.exists('cookies.json'):
                    os.remove('cookies.json')
                return True
                
            return False
        except Exception as e:
            print(f"Error during logout: {str(e)}")
            return False
        
    def save_cookies(self):
        """Save cookies to a file"""
        if self.cookies:
            with open('cookies.json', 'w') as f:
                json.dump(self.cookies, f)

    def load_cookies(self):
        """Load cookies from a file"""
        if os.path.exists('cookies.json'):
            with open('cookies.json', 'r') as f:
                self.cookies = json.load(f)
        
    def show_qr_code(self, image_data):
        """Show QR code image and optionally save it
        
        Args:
            image_data (bytes): PNG image data
            
        Returns:
            bool: True if the image was successfully displayed, False otherwise
        """
        try:
            # Create image from binary data
            img = Image.open(io.BytesIO(image_data))
            
            # Display the image
            img.show()
            return True
        except Exception as e:
            print(f"Error displaying QR code: {str(e)}")
            return False

    def _get_login_qrkey(self):
        """Get QR code key for login
        
        Returns:
            str or None: QR code unikey if successful, None otherwise
        """
        try:
            timestamp = int(time.time() * 1000)
            response = requests.get(f"{self.base_url}/login/qr/key", params={"timestamp": timestamp})
            if response.status_code != 200:
                return None
                
            data = response.json()
            
            # Check if request is successful and extract unikey
            if data.get('code') == 200 and data.get('data', {}).get('code') == 200:
                return data.get('data', {}).get('unikey')
                
            return None
        except Exception as e:
            print(f"Error getting QR key: {str(e)}")
            return None

    def _get_login_qrcode(self, key):
        """Get QR code image for login
        
        Args:
            key (str): The QR code key obtained from _get_login_qrkey
            
        Returns:
            bytes or None: PNG image data if successful, None otherwise
        """
        try:
            # Get QR code with image data
            timestamp = int(time.time() * 1000)
            response = requests.get(f"{self.base_url}/login/qr/create", 
                                   params={"key": key, "qrimg": "true", "timestamp": timestamp})
            if response.status_code != 200:
                return None
                
            data = response.json()
            
            # Check if request is successful
            if data.get('code') == 200:
                # Extract the base64 image data
                qrimg_base64 = data.get('data', {}).get('qrimg')
                if not qrimg_base64:
                    return None
                
                # Remove the data:image/png;base64, prefix
                if qrimg_base64.startswith('data:image/png;base64,'):
                    qrimg_base64 = qrimg_base64.split(',', 1)[1]
                
                # Decode the base64 data
                png_data = base64.b64decode(qrimg_base64)
                return png_data
                
            return None
        except Exception as e:
            print(f"Error getting QR code: {str(e)}")
            return None

    def _check_qr_login_status(self, key):
        """Check the status of QR code login
        
        Args:
            key (str): The QR code key obtained from _get_login_qrkey
            
        Returns:
            dict or None: Dictionary containing status code and message if successful, None otherwise
            
        Status codes:
            800: QR code expired
            801: Waiting for scan
            802: Waiting for confirmation
            803: Login successful
        """
        try:
            timestamp = int(time.time() * 1000)
            response = requests.get(f"{self.base_url}/login/qr/check",
                                   params={"key": key, "timestamp": timestamp})
            if response.status_code != 200:
                return None
                
            data = response.json()
            
            # Return status code and message
            return {
                'code': data.get('code'),
                'message': data.get('message'),
                'cookie': data.get('cookie')
            }
        except Exception as e:
            print(f"Error checking QR login status: {str(e)}")
            return None
    
    def get_album_info(self, album_id):
        """Get album information
        
        Args:
            album_id (int): Album ID
            
        Returns:
            NeteaseAlbum or None: Album object if successful, None otherwise
        """
        time.sleep(1)
        try:
            timestamp = int(time.time() * 1000)
            response = requests.get(f"{self.base_url}/album", 
                                 params={"id": album_id},
                                 cookies=self.cookies)
            if response.status_code != 200:
                return None
                
            data = response.json()
            
            # Check if resource is available
            if not data.get('resourceState'):
                print("Album resource is not available")
                return None
                
            # Parse album information
            album_data = data.get('album', {})
            artist_data = album_data.get('artist', {})
            
            # Create artist object
            artist = NeteaseArtist(
                artist_id=artist_data.get('id'),
                artist_name=artist_data.get('name')
            )
            
            # Create album object
            album = NeteaseAlbum(
                album_id=album_data.get('id'),
                album_name=album_data.get('name'),
                publish_time=album_data.get('publishTime'),
                publish_company=album_data.get('company'),
                tracks_count=album_data.get('size'),
                album_cover_url=album_data.get('picUrl'),
                artist=artist
            )
            
            # Parse songs
            songs_data = data.get('songs', [])
            for song_data in songs_data:
                # Create song object
                song = NeteaseSong(
                    song_id=song_data.get('id'),
                    song_name=song_data.get('name'),
                    cd_number=song_data.get('cd'),
                    track_number=song_data.get('no')
                )
                
                # Add available qualities
                if song_data.get('hr'):
                    song.add_quality(NeteaseAudioQuality.HIRES)
                if song_data.get('sq'):
                    song.add_quality(NeteaseAudioQuality.LOSSLESS)
                if song_data.get('h'):
                    song.add_quality(NeteaseAudioQuality.EXHIGH)
                if song_data.get('m'):
                    song.add_quality(NeteaseAudioQuality.HIGHER)
                if song_data.get('l'):
                    song.add_quality(NeteaseAudioQuality.STANDARD)
                    
                album.add_song(song)
                
            return album
            
        except Exception as e:
            print(f"Error getting album info: {str(e)}")
            return None

    def get_song_url(self, song_id, quality: NeteaseAudioQuality = NeteaseAudioQuality.EXHIGH):
        """Get song download URL and information
        
        Args:
            song_id (int): Song ID
            quality (NeteaseAudioQuality, optional): Desired audio quality. Defaults to EXHIGH.
            
        Returns:
            NeteaseSongDownloadInfo: Object containing song download information, or None if failed
        """
        time.sleep(1)
        try:
            timestamp = int(time.time() * 1000)
            response = requests.get(f"{self.base_url}/song/url/v1", 
                                  params={
                                      "id": song_id, 
                                      "level": quality.value
                                  },
                                  cookies=self.cookies)
            
            if response.status_code != 200:
                return None
                
            data = response.json()
            
            # Check if data exists and has at least one item
            if data.get('code') != 200 or not data.get('data') or len(data.get('data')) == 0:
                return None
                
            # Get the first item's URL
            song_url = data.get('data')[0].get('url')
            song_ext_name = None
            
            # Extract file extension from URL if URL exists
            if song_url:
                try:
                    parsed_url = urlparse(song_url)
                    file_name = os.path.basename(parsed_url.path)
                    _, song_ext_name = os.path.splitext(file_name)
                except Exception as e:
                    print(f"Error parsing URL extension: {str(e)}")
            
            # Create and return download info object
            return NeteaseSongDownloadInfo(
                song_id=song_id,
                ext_name=song_ext_name,
                url=song_url
            )
            
        except Exception as e:
            print(f"Error getting song URL: {str(e)}")
            return None
        
    def download_album_cover(self, album: NeteaseAlbum):
        """Download album cover
        
        Args:
            album (NeteaseAlbum): Object containing album information
            
        Returns:
            str or None: Path to downloaded file if successful, None otherwise
        """
        try:
            # Check if album info is valid
            if not album or not album.album_cover_url:
                print_error("Invalid album info or cover URL")
                return None
                
            # Create download directory if it doesn't exist
            download_dir = os.path.join(os.getcwd(), "Download", "Covers")
            os.makedirs(download_dir, exist_ok=True)
            
            # Generate filename using album ID
            # Most album covers are JPG images
            filename = f"{album.album_id}.jpg"
            file_path = os.path.join(download_dir, filename)
            
            # Download the file
            print_info(f"Downloading album cover to {file_path}...")
            response = requests.get(album.album_cover_url, stream=True)
            
            if response.status_code != 200:
                print_error(f"Failed to download cover: HTTP {response.status_code}")
                return None
            
            # Get file size from headers (if available)
            total_size = int(response.headers.get('content-length', 0))
            downloaded_size = 0
            start_time = time.time()
            
            # Save the file with progress reporting
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        
                        # Update progress bar
                        if total_size > 0:
                            progress = int((downloaded_size / total_size) * 100)
                            bar_length = 30
                            filled_length = int(bar_length * downloaded_size // total_size)
                            bar = '█' * filled_length + '-' * (bar_length - filled_length)
                            
                            # Calculate download speed and ETA
                            elapsed = time.time() - start_time
                            speed = downloaded_size / elapsed / 1024  # KB/s
                            if speed > 0:
                                eta = (total_size - downloaded_size) / (speed * 1024)
                                print(f"\r[{bar}] {progress}% | {downloaded_size/1024/1024:.1f}MB/{total_size/1024/1024:.1f}MB | {speed:.1f} KB/s | ETA: {int(eta//60)}m {int(eta%60)}s", end='')
                            else:
                                print(f"\r[{bar}] {progress}% | {downloaded_size/1024/1024:.1f}MB/{total_size/1024/1024:.1f}MB", end='')
                        else:
                            print(f"\rDownloaded: {downloaded_size/1024/1024:.1f}MB", end='')
            
            # Print new line after progress bar
            print_success("\nCover download completed!")
            return file_path
            
        except Exception as e:
            print_error(f"Error downloading album cover: {str(e)}")
            return None
    
    def download_song_file(self, download_info: NeteaseSongDownloadInfo):
        """Download song from NetEase Cloud Music
        
        Args:
            download_info (NeteaseSongDownloadInfo): Object containing song download information
            
        Returns:
            str or None: Path to downloaded file if successful, None otherwise
        """
        try:
            # Check if download info is valid
            if not download_info or not download_info.url:
                print_error("Invalid download info or URL")
                return None
                
            # Create download directory if it doesn't exist
            download_dir = os.path.join(os.getcwd(), "Download", "Songs")
            os.makedirs(download_dir, exist_ok=True)
            
            # Generate timestamp-based filename
            filename = f"{download_info.song_id}{download_info.ext_name}"
            file_path = os.path.join(download_dir, filename)
            
            # Download the file
            print_info(f"Downloading song to {file_path}...")
            response = requests.get(download_info.url, stream=True)
            
            if response.status_code != 200:
                print_error(f"Failed to download: HTTP {response.status_code}")
                return None
            
            # Get file size from headers (if available)
            total_size = int(response.headers.get('content-length', 0))
            downloaded_size = 0
            start_time = time.time()
            
            # Save the file with progress reporting
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        
                        # Update progress bar
                        if total_size > 0:
                            progress = int((downloaded_size / total_size) * 100)
                            bar_length = 30
                            filled_length = int(bar_length * downloaded_size // total_size)
                            bar = '█' * filled_length + '-' * (bar_length - filled_length)
                            
                            # Calculate download speed and ETA
                            elapsed = time.time() - start_time
                            speed = downloaded_size / elapsed / 1024  # KB/s
                            if speed > 0:
                                eta = (total_size - downloaded_size) / (speed * 1024)
                                print(f"\r[{bar}] {progress}% | {downloaded_size/1024/1024:.1f}MB/{total_size/1024/1024:.1f}MB | {speed:.1f} KB/s | ETA: {int(eta//60)}m {int(eta%60)}s", end='')
                            else:
                                print(f"\r[{bar}] {progress}% | {downloaded_size/1024/1024:.1f}MB/{total_size/1024/1024:.1f}MB", end='')
                        else:
                            print(f"\rDownloaded: {downloaded_size/1024/1024:.1f}MB", end='')
            
            # Print new line after progress bar
            print("\nDownload completed!")
            return file_path
            
        except Exception as e:
            print_error(f"Error downloading song: {str(e)}")
            return None
        
    def merge_song_file_metadata(self, song_path, cover_path, song: NeteaseSong, album: NeteaseAlbum):
        """Download song file and merge metadata
        
        Args:
            song_path (str): Path to song file
            cover_path (str): Path to cover file
            song (NeteaseSong): Object containing song information
            album (NeteaseAlbum): Object containing album information
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Check if files exist
            if not os.path.exists(song_path):
                print_error(f"Song file not found: {song_path}")
                return False
                
            if not os.path.exists(cover_path):
                print_warning(f"Cover file not found: {cover_path}")
                # Continue without cover
            
            # Get file extension to determine file type
            _, ext = os.path.splitext(song_path)
            ext = ext.lower()
            
            # Read cover image data if available
            cover_data = None
            cover_mime = "image/jpeg"  # Default mime type
            if os.path.exists(cover_path):
                with open(cover_path, "rb") as f:
                    cover_data = f.read()
            
            # Convert publish time from timestamp to year
            publish_year = ""
            if album.publish_time:
                try:
                    # Convert milliseconds timestamp to datetime
                    publish_date = datetime.fromtimestamp(album.publish_time / 1000)
                    publish_year = str(publish_date.year)
                except:
                    # If conversion fails, leave it blank
                    pass
            
            # Handle MP3 files
            if ext == '.mp3':
                # Create or load ID3 tags
                try:
                    audio = ID3(song_path)
                except:
                    # If the file doesn't have an ID3 tag, create one
                    audio = ID3()
                
                # Set title
                audio["TIT2"] = TIT2(encoding=3, text=song.song_name)
                
                # Set artist
                audio["TPE1"] = TPE1(encoding=3, text=album.artist.artist_name)
                
                # Set album artist
                audio["TPE2"] = TPE2(encoding=3, text=album.artist.artist_name)
                
                # Set album
                audio["TALB"] = TALB(encoding=3, text=album.album_name)
                
                # Set track number (format: track/total)
                if song.track_number:
                    track_str = f"{song.track_number}/{album.tracks_count}" if album.tracks_count else str(song.track_number)
                    audio["TRCK"] = TRCK(encoding=3, text=track_str)
                
                # Set disc number
                if song.cd_number:
                    audio["TPOS"] = TPOS(encoding=3, text=song.cd_number)
                
                # Set year
                if publish_year:
                    audio["TYER"] = TYER(encoding=3, text=publish_year)
                
                # Add album artwork
                if cover_data:
                    audio["APIC"] = APIC(
                        encoding=3,           # UTF-8
                        mime=cover_mime,      # image/jpeg or image/png
                        type=3,               # Cover (front)
                        desc="Cover",
                        data=cover_data
                    )
                
                # Save the file
                audio.save(song_path)
                
            # Handle FLAC files
            elif ext == '.flac':
                audio = FLAC(song_path)
                
                # Set basic metadata
                audio["TITLE"] = song.song_name
                audio["ARTIST"] = album.artist.artist_name
                audio["ALBUMARTIST"] = album.artist.artist_name
                audio["ALBUM"] = album.album_name
                
                # Set track number
                if song.track_number:
                    audio["TRACKNUMBER"] = str(song.track_number)
                
                # Set total tracks
                if album.tracks_count:
                    audio["TOTALTRACKS"] = str(album.tracks_count)
                
                # Set disc number
                if song.cd_number:
                    audio["DISCNUMBER"] = song.cd_number
                
                # Set year
                if publish_year:
                    audio["DATE"] = publish_year
                
                # Add album artwork
                if cover_data:
                    picture = Picture()
                    picture.type = 3                # Cover (front)
                    picture.mime = cover_mime       # MIME type
                    picture.desc = "Cover"          # Description
                    picture.data = cover_data       # Image data
                    
                    # Add picture to the file
                    audio.add_picture(picture)
                
                # Save the file
                audio.save()
                
            # Handle M4A files
            elif ext == '.m4a' or ext == '.aac':
                audio = MP4(song_path)
                
                # MP4/M4A tags use different naming scheme
                # Title
                audio["\xa9nam"] = [song.song_name]
                
                # Artist
                audio["\xa9ART"] = [album.artist.artist_name]
                
                # Album Artist
                audio["aART"] = [album.artist.artist_name]
                
                # Album
                audio["\xa9alb"] = [album.album_name]
                
                # Track number (format: [track, total])
                if song.track_number:
                    track_num = int(song.track_number)
                    total_tracks = int(album.tracks_count) if album.tracks_count else 0
                    # iTunes-style track number tuple (track, total)
                    audio["trkn"] = [(track_num, total_tracks)]
                
                # Disc number
                if song.cd_number:
                    try:
                        disc_num = int(song.cd_number)
                        # iTunes-style disc number tuple (disc, total discs)
                        audio["disk"] = [(disc_num, 0)]
                    except ValueError:
                        pass
                
                # Year
                if publish_year:
                    audio["\xa9day"] = [publish_year]
                
                # Add album artwork
                if cover_data:
                    from mutagen.mp4 import MP4Cover
                    if cover_mime == "image/jpeg":
                        cover_format = MP4Cover.FORMAT_JPEG
                    elif cover_mime == "image/png":
                        cover_format = MP4Cover.FORMAT_PNG
                    else:
                        cover_format = MP4Cover.FORMAT_JPEG
                    
                    audio["covr"] = [MP4Cover(cover_data, cover_format)]
                
                # Save the file
                audio.save()
            
            else:
                print_error(f"Unsupported file format: {ext}")
                return False
            
            print_success(f"Successfully added metadata to {song_path}")
            return True
            
        except Exception as e:
            print_error(f"Error merging metadata: {str(e)}")
            return False
        
    def get_archive_path(self, song: NeteaseSong, album: NeteaseAlbum, ext: str) -> str:
        """Get the destination path for the song file
        
        Args:
            song (NeteaseSong): Object containing song information
            album (NeteaseAlbum): Object containing album information
            ext (str): File extension
            
        Returns:
            str: Destination path for the song file
        """
        # Process artist name
        artist_name = album.artist.artist_name
        artist_name = self._sanitize_filename(artist_name)
        
        # Process album year from publish time
        album_year = ""
        if album.publish_time:
            try:
                # Convert milliseconds timestamp to datetime
                publish_date = datetime.fromtimestamp(album.publish_time / 1000)
                album_year = str(publish_date.year)
            except:
                # If conversion fails, use unknown
                album_year = "Unknown"
        else:
            album_year = "Unknown"
            
        # Process album name
        album_name = album.album_name
        album_name = self._sanitize_filename(album_name)
        
        # Process CD number
        cd_number = song.cd_number if song.cd_number else "01"
        
        # Process track number
        track_number = str(song.track_number).zfill(2) if song.track_number else "00"
        
        # Process song name
        song_name = song.song_name
        song_name = self._sanitize_filename(song_name)
        
        # Create path components
        music_base_dir = os.path.join(os.getcwd(), "Download", "MusicLibrary")
        artist_dir = os.path.join(music_base_dir, artist_name)
        album_dir = os.path.join(artist_dir, f"{album_year}-{album_name}")
        
        # Create final filename
        filename = f"{cd_number}-{track_number}-{song_name}{ext}"
        dest_path = os.path.join(album_dir, filename)
        
        return dest_path

    def archive_song_file(self, song_path, ext, song: NeteaseSong, album: NeteaseAlbum):
        """Archive song file
        
        Args:
            song_path (str): Path to song file
            song (NeteaseSong): Object containing song information
            album (NeteaseAlbum): Object containing album information
            
        Returns:
            str or None: Path to archived file if successful, None otherwise
        """
        try:
            # Check if files exist
            if not os.path.exists(song_path):
                print(f"Song file not found: {song_path}")
                return None
                
            # Get destination path
            dest_path = self.get_archive_path(song, album, ext)
            
            # Create directory structure
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            
            # Copy file to destination
            import shutil
            shutil.copy2(song_path, dest_path)
            
            print(f"Archived song to: {dest_path}")
            return dest_path
            
        except Exception as e:
            print(f"Error archiving song: {str(e)}")
            return None
    
    def _sanitize_filename(self, filename):
        """Remove illegal characters from filename
        
        Args:
            filename (str): Original filename
            
        Returns:
            str: Sanitized filename
        """
        # Replace characters that are not allowed in filenames
        invalid_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        
        # Trim excessive whitespace and dots
        filename = filename.strip().strip('.')
        
        # Ensure the filename is not empty
        if not filename:
            filename = "unnamed"
            
        return filename

if __name__ == "__main__":
    grabber = NeteaseGrabber()
    print_info("Starting NetEase Music API server...")
    if not grabber.start_server():
        print_error("Failed to start server. Exiting...")
        sys.exit(1)
    print_success("Server started successfully!")

    print_info("Loading cookies and checking login status...")
    grabber.load_cookies()
    if not grabber.check_login_status():
        print_info("Not logged in. Starting login process...")
        if not grabber.login():
            print_error("Login failed. Exiting...")
            sys.exit(1)
        print_success("Login successful!")
    else:
        print_success("Already logged in!")
    
    # Ask user for album URL
    while True:
        print_highlight("\nEnter NetEase album URL (or 'exit' to quit):")
        print_info("Format: https://music.163.com/#/album?id=XXXXX")
        user_input = input("> ")
        
        if user_input.lower() == 'exit':
            print_info("Exiting program...")
            break
        
        # Extract album ID from URL
        album_id = None
        if '/album?id=' in user_input:
            try:
                album_id = int(user_input.split('/album?id=')[1].split('&')[0])
                print_info(f"Detected album ID: {album_id}")
            except (ValueError, IndexError):
                print_error("Invalid URL format. Could not extract album ID.")
                continue
        else:
            try:
                # Try to parse input directly as album ID
                album_id = int(user_input)
                print_info(f"Using direct album ID: {album_id}")
            except ValueError:
                print_error("Invalid input. Please enter a valid URL or album ID.")
                continue
        
        # Get album information
        print_info(f"Fetching album information for ID: {album_id}...")
        album = grabber.get_album_info(album_id)
        if not album:
            print_error("Failed to get album information.")
            continue
        
        print_highlight(f"\n=== Album Information ===")
        print_success(f"Title: {album.album_name}")
        print_success(f"Artist: {album.artist.artist_name}")
        print_success(f"Tracks: {album.tracks_count}")
        print_success(f"Published: {datetime.fromtimestamp(album.publish_time / 1000).strftime('%Y-%m-%d') if album.publish_time else 'Unknown'}")
        
        # Download album cover
        print_info("\nDownloading album cover...")
        cover_path = grabber.download_album_cover(album)
        if cover_path:
            print_success(f"Album cover downloaded to: {cover_path}")
        else:
            print_warning("Failed to download album cover, continuing without cover.")
            cover_path = None
        
        # Process all songs in the album
        if album.songs:
            print_highlight(f"\nPreparing to download {len(album.songs)} songs from album...")
            
            success_count = 0
            for i, song in enumerate(album.songs):
                print_highlight(f"\n[{i+1}/{len(album.songs)}] Processing: {song.song_name}")
                
                # Get song download URL
                print_info(f"Getting download URL for '{song.song_name}'...")
                download_info = grabber.get_song_url(song.song_id)
                
                if not download_info or not download_info.url:
                    print_error(f"Failed to get download URL for '{song.song_name}', skipping.")
                    continue

                archive_path = grabber.get_archive_path(song, album, download_info.ext_name)
                if os.path.exists(archive_path):
                    print_success(f"Song already exists in archive: {archive_path}")
                    success_count += 1
                    continue
                
                # Download the song
                print_info(f"Downloading '{song.song_name}'...")
                file_path = grabber.download_song_file(download_info)
                
                if not file_path:
                    print_error(f"Failed to download '{song.song_name}', skipping.")
                    continue
                
                # Add metadata
                print_info(f"Adding metadata to '{song.song_name}'...")
                if grabber.merge_song_file_metadata(file_path, cover_path, song, album):
                    print_success(f"Successfully added metadata to '{song.song_name}'")
                else:
                    print_warning(f"Failed to add metadata to '{song.song_name}', continuing anyway.")
                
                # Archive song
                print_info(f"Archiving '{song.song_name}' to music library...")
                archive_path = grabber.archive_song_file(file_path, download_info.ext_name, song, album)
                
                if archive_path:
                    print_success(f"Song archived to: {archive_path}")
                    success_count += 1
                else:
                    print_error(f"Failed to archive '{song.song_name}'")
            
            print_highlight(f"\n=== Download Summary ===")
            print_success(f"Album: {album.album_name} - {album.artist.artist_name}")
            print_success(f"Total tracks: {len(album.songs)}")
            print_success(f"Successfully downloaded: {success_count}/{len(album.songs)}")
            print_success(f"All available songs have been processed!")
        else:
            print_warning("No songs found in the album.")
            
    print_success("\nThank you for using GrabNeteaseMusic!")

    