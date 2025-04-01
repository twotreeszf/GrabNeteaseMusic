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
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, TRCK, TPOS, TYER
from mutagen.mp3 import MP3
from mutagen.flac import FLAC, Picture
from datetime import datetime

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
                print("Failed to get QR code key")
                return False
                
            # Step 2: Get QR code image
            qr_data = self._get_login_qrcode(key)
            if not qr_data:
                print("Failed to get QR code image")
                return False
                
            # Step 3: Display QR code
            print("Please scan the QR code with the NetEase Cloud Music app")
            self.show_qr_code(qr_data)
            
            # Step 4: Poll login status
            print("Waiting for scan and confirmation...")
            while True:
                status = self._check_qr_login_status(key)
                if not status:
                    print("Error checking login status")
                    return False
                    
                if status['code'] == 803:
                    self.cookies = self._parse_cookies(status['cookie'])
                    self.save_cookies()
                    print("Login successful!")
                    return True
                elif status['code'] == 800:
                    print("QR code expired")
                    return False
                elif status['code'] == 802:
                    print("QR code scanned, waiting for confirmation...")
                elif status['code'] == 801:
                    pass  # Still waiting for scan, no need to print repeatedly
                
                time.sleep(1)  # Poll every 1 second
                
        except Exception as e:
            print(f"Error during login process: {str(e)}")
            return False

    def logout(self):
        """Log out from NetEase Cloud Music
        
        Returns:
            bool: True if logout successful, False otherwise
        """
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
                print("Invalid album info or cover URL")
                return None
                
            # Create download directory if it doesn't exist
            download_dir = os.path.join(os.getcwd(), "Download", "Covers")
            os.makedirs(download_dir, exist_ok=True)
            
            # Generate filename using album ID
            # Most album covers are JPG images
            filename = f"{album.album_id}.jpg"
            file_path = os.path.join(download_dir, filename)
            
            # Download the file
            print(f"Downloading album cover to {file_path}...")
            response = requests.get(album.album_cover_url, stream=True)
            
            if response.status_code != 200:
                print(f"Failed to download cover: HTTP {response.status_code}")
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
            print("\nCover download completed!")
            return file_path
            
        except Exception as e:
            print(f"Error downloading album cover: {str(e)}")
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
                print("Invalid download info or URL")
                return None
                
            # Create download directory if it doesn't exist
            download_dir = os.path.join(os.getcwd(), "Download", "Songs")
            os.makedirs(download_dir, exist_ok=True)
            
            # Generate timestamp-based filename
            filename = f"{download_info.song_id}{download_info.ext_name}"
            file_path = os.path.join(download_dir, filename)
            
            # Download the file
            print(f"Downloading song to {file_path}...")
            response = requests.get(download_info.url, stream=True)
            
            if response.status_code != 200:
                print(f"Failed to download: HTTP {response.status_code}")
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
            print(f"Error downloading song: {str(e)}")
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
                print(f"Song file not found: {song_path}")
                return False
                
            if not os.path.exists(cover_path):
                print(f"Cover file not found: {cover_path}")
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
            
            else:
                print(f"Unsupported file format: {ext}")
                return False
            
            print(f"Successfully added metadata to {song_path}")
            return True
            
        except Exception as e:
            print(f"Error merging metadata: {str(e)}")
            return False
        

if __name__ == "__main__":
    grabber = NeteaseGrabber()
    grabber.start_server()

    grabber.load_cookies()
    if not grabber.check_login_status():
        grabber.login()

    # Test getting album information
    album = grabber.get_album_info(6394)
    print(f"Album: {album.album_name} - {album.artist.artist_name}")
    
    # Download album cover
    cover_path = grabber.download_album_cover(album)
    if cover_path:
        print(f"Album cover downloaded to: {cover_path}")
    else:
        print("Failed to download album cover")
    
    # If the album has songs, try to get the download link for the first song
    if album and album.songs:
        first_song = album.songs[0]
        print(f"Song: {first_song.song_name}")
        
        # Get download information for the song
        download_info = grabber.get_song_url(first_song.song_id)
        if download_info and download_info.url:
            print(f"Download URL: {download_info.url}")
            print(f"File extension: {download_info.ext_name}")
            
            # Download the song
            file_path = grabber.download_song_file(download_info)
            if file_path:
                print(f"Song downloaded to: {file_path}")
                
                # Merge metadata
                if grabber.merge_song_file_metadata(file_path, cover_path, first_song, album):
                    print("Successfully added metadata to the song")
                else:
                    print("Failed to add metadata")
            else:
                print("Failed to download song")
        else:
            print("Failed to get download URL")

    time.sleep(30)