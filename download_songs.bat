@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==================================================
echo   Song downloader - just wait, do not close
echo ==================================================
echo.
echo [1/3] Getting the download tool (yt-dlp)...
curl -L -o yt-dlp.exe https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe
echo       Getting the song list...
curl -fsSL -o songs.txt "https://raw.githubusercontent.com/g47ben-lang/zmani/f755614ac531b1c6c35a3b97e3665b038d1720c8/songs_full.txt"
echo.
echo [2/3] Downloading the songs. This can take 10-25 minutes...
echo.
yt-dlp.exe -a songs.txt --default-search "ytsearch1:" -f "bestaudio[ext=m4a]/bestaudio" -o "songs\%%(title)s.%%(ext)s" -i --no-warnings --no-playlist
echo.
echo [3/3] Packing everything into songs.zip ...
powershell -NoLogo -NoProfile -Command "Compress-Archive -Path 'songs\*' -DestinationPath 'songs.zip' -Force"
echo.
echo ==================================================
echo   DONE!  Your file is:  songs.zip
echo   (in the same folder as this file)
echo ==================================================
echo.
echo If most songs FAILED with "Sign in to confirm you're not a bot",
echo close Chrome completely and tell me - I'll send an updated file.
echo.
pause
