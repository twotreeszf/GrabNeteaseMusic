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
    def __init__(self, song_id, song_name):
        self.song_id = song_id
        self.song_name = song_name
        self.avalibe_qualities = []

    def add_quality(self, quality: NeteaseAudioQuality):
        self.avalibe_qualities.append(quality)

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
    
    def get_album_info(self):
        pass

    def get_song_url(self):
        pass

if __name__ == "__main__":
    grabber = NeteaseGrabber()
    grabber.start_server()

    grabber.load_cookies()
    if not grabber.check_login_status():
        grabber.login()

    time.sleep(30)
    
    