import requests
from enum import Enum
import subprocess
import time
import os
import signal
import atexit

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

    def check_login_status(self):
        pass

    def login(self):
        pass

    def logout(self):
        pass

    def _get_login_qrkey(self):
        pass

    def _get_login_qrcode(self):
        pass

    def _check_qr_login_status(self):
        pass    
    
    def get_album_info(self):
        pass

    def get_song_url(self):
        pass

if __name__ == "__main__":
    grabber = NeteaseGrabber()
    grabber.start_server()
    time.sleep(30)
