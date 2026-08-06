#!/bin/bash
# Runs automatically on a fresh DigitalOcean droplet (as cloud-init "User Data").
# Needs no SSH / console: it downloads the songs and serves them over HTTP on
# port 80, so the user just opens http://<droplet-ip>/ in a browser.
set -x
exec >/var/log/songs.log 2>&1
cd /root
mkdir -p site

# Put up a status page + web server immediately, so reachability can be tested
# within a minute of boot (before the long download finishes).
cat > site/index.html <<'EOF'
<!doctype html><html lang="he"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<body style="font-family:sans-serif;direction:rtl;max-width:720px;margin:40px auto;padding:0 16px">
<h1>&#9203; &#1502;&#1493;&#1512;&#1497;&#1491; &#1488;&#1514; &#1492;&#1513;&#1497;&#1512;&#1497;&#1501;&#8230;</h1>
<p>&#1492;&#1491;&#1507; &#1497;&#1514;&#1506;&#1491;&#1499;&#1503;. &#1512;&#1506;&#1504;&#1503; &#1489;&#1506;&#1493;&#1491; &#1499;-10 &#1491;&#1511;&#1493;&#1514; &#1493;&#1514;&#1511;&#1489;&#1500; &#1511;&#1497;&#1513;&#1493;&#1512; &#1492;&#1493;&#1512;&#1491;&#1492;.</p>
</body></html>
EOF
( cd site && nohup python3 -m http.server 80 >/dev/null 2>&1 & )

# --- tools ---
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y ffmpeg zip curl python3
curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/local/bin/yt-dlp
chmod +x /usr/local/bin/yt-dlp

# --- our downloader + the full song list (from the repo) ---
SHA=f755614ac531b1c6c35a3b97e3665b038d1720c8
REPO="https://raw.githubusercontent.com/g47ben-lang/zmani/$SHA"
curl -fsSL "$REPO/download_songs.py" -o download_songs.py
curl -fsSL "$REPO/songs_full.txt"   -o songs.txt

# --- download + zip + best-effort upload ---
DEBUG_SOURCES=1 python3 download_songs.py --list songs.txt --link --keep \
  --send-host "https://send.magicode.me/" > run.log 2>&1
cp -f songs.zip site/songs.zip 2>/dev/null

# --- build the finished page ---
{
  echo '<!doctype html><html lang="he"><meta charset="utf-8">'
  echo '<meta name="viewport" content="width=device-width,initial-scale=1">'
  echo '<body style="font-family:sans-serif;direction:rtl;max-width:720px;margin:40px auto;padding:0 16px">'
  echo '<h1>&#9989; &#1502;&#1493;&#1499;&#1503;!</h1>'
  if [ -f site/songs.zip ]; then
    SZ=$(du -h site/songs.zip | cut -f1)
    echo "<p style=font-size:26px><a href=\"songs.zip\">&#11015;&#65039; &#1492;&#1493;&#1512;&#1491; &#1488;&#1514; &#1499;&#1500; &#1492;&#1513;&#1497;&#1512;&#1497;&#1501; (songs.zip, $SZ)</a></p>"
  fi
  echo '<h3>&#1511;&#1497;&#1513;&#1493;&#1512;&#1497;&#1501; &#1495;&#1500;&#1493;&#1508;&#1497;&#1497;&#1501;:</h3><ul>'
  grep -oE 'https?://[^ ]+' run.log | grep -viE 'github|youtube|soundcloud|raw\.githubusercontent' | sort -u \
    | while read -r u; do echo "<li><a href=\"$u\">$u</a></li>"; done
  echo '</ul><hr><h3>&#1508;&#1497;&#1512;&#1493;&#1496;:</h3>'
  echo '<pre style="font-size:13px;direction:ltr;white-space:pre-wrap">'
  sed 's/&/\&amp;/g; s/</\&lt;/g' run.log
  echo '</pre></body></html>'
} > site/index.html
