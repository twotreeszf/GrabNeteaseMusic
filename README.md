# GrabNeteaseMusic

A powerful Python tool for downloading albums from NetEase Cloud Music, featuring high-quality audio downloads and comprehensive metadata management.

## Features

- Multiple Audio Quality Support
  - Standard Quality (128kbps)
  - Higher Quality (320kbps)
  - Excellent Quality (320kbps)
  - Lossless Quality (FLAC)
  - Hi-Res Quality

- Comprehensive Metadata Support
  - Multiple format support (MP3/FLAC/M4A/AAC)
  - Automatic album artwork embedding
  - Complete ID3 tag support (title, artist, album, year, etc.)
  - Multi-CD and track numbering support

- Smart File Management
  - Automatic hierarchical music library structure
  - Organization by artist/year-album
  - Intelligent file naming and duplicate handling
  - Clean and organized music library

- User-Friendly Features
  - QR code login support
  - Progress bar for downloads
  - Colored terminal output
  - Download speed and ETA display
  - Detailed error handling and feedback

## Requirements

- Python 3.6+
- Node.js (for NetEase Cloud Music API)
- Required Python packages:
  - requests
  - Pillow
  - mutagen

## Installation

1. Clone the repository:
```bash
git clone https://github.com/twotreeszf/GrabNeteaseMusic.git
cd GrabNeteaseMusic
```

2. Install Python dependencies:
```bash
pip install -r requirements.txt
```

3. Install NetEase Cloud Music API:
```bash
git clone https://github.com/Binaryify/NeteaseCloudMusicApi.git
cd NeteaseCloudMusicApi
npm install
```

## Usage

1. Run the program:
```bash
python GrabNeteaseMusic.py
```

2. On first use, the program will display a QR code. Scan it with your NetEase Cloud Music app to log in.

3. Enter a NetEase Cloud Music album URL or ID:
   - Format: https://music.163.com/#/album?id=XXXXX
   - Or directly enter the album ID

4. The program will automatically:
   - Fetch album information
   - Download album artwork
   - Download all music files
   - Embed metadata and album artwork
   - Organize into the music library

## Directory Structure

Downloaded files will be organized as follows:
```
Download/
├── Covers/
│   └── [AlbumID].jpg
├── Songs/
│   └── [Temporary download files]
└── MusicLibrary/
    └── [Artist]/
        └── [Year]-[Album]/
            └── [DiscNumber]-[TrackNumber]-[SongName].[Format]
```

## Important Notes

- Requires a NetEase Cloud Music account
- Premium membership required for high-quality audio downloads
- Please comply with relevant laws and regulations
- Download speed depends on network conditions
- Login status is automatically saved in cookies.json

## Error Handling

- Failed downloads are skipped automatically
- Files are saved even if metadata embedding fails
- Network errors are reported with retry options
- Login failures prompt for re-authentication

## Roadmap

- [ ] Batch album download support
- [ ] Playlist download support
- [ ] Resume interrupted downloads
- [ ] Custom directory structure
- [ ] Additional audio format support
- [ ] Graphical user interface

## Contributing

Issues and Pull Requests are welcome to help improve this project.

## License

MIT License

## Disclaimer

This project is for educational purposes only. Please respect copyright and use responsibly. 