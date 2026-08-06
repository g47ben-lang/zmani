# 🎵 הורדת שירים בענן → קישור להורדה / Google Drive

מקבל **רשימת שמות שירים**, מחפש כל אחד ב-YouTube, מוריד את השמע כ-MP3, ומספק
לך אותם באחת משתי דרכים — **קישור הורדה לזיפ** או תיקייה ב-**Google Drive**.
הכל רץ בענן: הקבצים לא נשמרים אצלך במחשב.

---

## ⭐ הדרך הכי פשוטה: Google Colab (בלי להתקין כלום)

לא צריך מחשב חזק או התקנות — הכל בדפדפן, חינם:

1. פתח את המחברת בלחיצה אחת:
   👉 **https://colab.research.google.com/github/g47ben-lang/zmani/blob/claude/music-upload-script-ebrvui/music_downloader_colab.ipynb**
2. בתא השני — הדבק את רשימת השירים שלך (שיר בכל שורה).
3. תפריט **Runtime → Run all** (או הרץ תא-תא בכפתור ▶).
4. בסוף מודפס **קישור הורדה** לזיפ עם כל השירים. זהו.

הזיפ עולה ל-`send.magicode.me` (ואם זה נופל — אוטומטית ל-`0x0.st`).

> אם YouTube מבקש אימות בשרתי הענן ("Sign in to confirm…"), נסה שוב מאוחר
> יותר — זה קורה לפעמים ל-IP-ים של Colab.

---

## אופציה ב': קישור הורדה משרת משלך (בלי Google Drive)

אותה תוצאה בלי המחברת — על כל שרת/Codespace עם `python3`:

```bash
./setup.sh
python3 download_songs.py --list songs.txt --link \
    --send-host https://send.magicode.me/
```

בסוף מודפס `>>> DOWNLOAD LINK: ...`. צריך `ffsend` בשביל Send (setup.sh
מנסה, אבל התקנה ידנית: הורד את הבינארי מ-
https://github.com/timvisee/ffsend/releases). בלי ffsend — נופל ל-`0x0.st`.

---

## אופציה ג': Google Drive

---

## מה צריך פעם אחת (התקנה)

הסקריפט משתמש בשלושה כלים:

| כלי      | לְמה                          |
|----------|-------------------------------|
| `yt-dlp` | מוריד את השמע מ-YouTube        |
| `ffmpeg` | ממיר ל-MP3                     |
| `rclone` | מעלה ל-Google Drive           |

להתקנה אוטומטית:

```bash
./setup.sh
```

(אם `setup.sh` לא רץ, הפעל קודם `chmod +x setup.sh`.)

---

## חיבור ל-Google Drive (פעם אחת)

`rclone` מתחבר ל-Drive שלך דרך הרשאה חד-פעמית:

```bash
rclone config
```

ואז:

1. `n` — remote חדש
2. שם: הקלד **`gdrive`**
3. סוג storage: בחר את המספר של **Google Drive** (`drive`)
4. `client_id` / `client_secret` — אפשר להשאיר ריק (Enter)
5. scope: בחר **`1`** (גישה מלאה) או **`drive.file`** אם אתה רוצה שהסקריפט
   יראה רק קבצים שהוא עצמו יצר
6. `Use auto config?` —
   * אם אתה על מחשב עם דפדפן: **`y`**, וייפתח חלון להתחברות לגוגל.
   * אם אתה על שרת בלי דפדפן: **`n`**, ואז rclone ייתן לך פקודה להריץ על
     מחשב אחר עם דפדפן (`rclone authorize "drive"`), ואתה מדביק בחזרה את
     הטוקן שקיבלת.
7. `Configure this as a Shared Drive?` → **`n`**
8. `y` לאישור, `q` ליציאה.

בדיקה שהחיבור עובד:

```bash
rclone lsd gdrive:
```

אמור להראות את התיקיות ב-Drive שלך.

---

## איך משתמשים

1. ערוך את `songs.txt` — **שיר אחד בכל שורה**. הכי טוב בפורמט
   `שם אמן - שם שיר`. שורות שמתחילות ב-`#` מתעלמים מהן.

   ```
   Idan Raichel - Mimaamakim
   Hadag Nachash - Zman Lehitorer
   ```

2. הרץ:

   ```bash
   python3 download_songs.py --list songs.txt --remote gdrive:Music
   ```

   * `--remote gdrive:Music` = העלה לתיקייה בשם `Music` ב-Drive
     (rclone יוצר אותה אם היא לא קיימת).
   * הקבצים המקומיים נמחקים אחרי העלאה מוצלחת (אלא אם הוספת `--keep`).

3. פתח את Google Drive → תיקיית `Music` → הקבצים שם. תוריד מה שאתה רוצה.

---

## אפשרויות שימושיות

| דגל              | מה זה עושה                                                      |
|------------------|----------------------------------------------------------------|
| `--list FILE`    | קובץ רשימת השירים (חובה).                                       |
| `--remote R:F`   | יעד ב-rclone, למשל `gdrive:Music`. בלי זה — רק הורדה מקומית.     |
| `--out DIR`      | תיקיית ההורדה הזמנית (ברירת מחדל `./downloads`).                |
| `--upload-each`  | להעלות כל שיר מיד אחרי שירד (טוב לרשימות ארוכות / רשת לא יציבה). |
| `--keep`         | לא למחוק את הקבצים המקומיים אחרי העלאה.                          |
| `--quality 0..9` | איכות MP3: `0` = הכי טוב (ברירת מחדל), `9` = הכי קטן.           |

דוגמה מלאה:

```bash
python3 download_songs.py --list songs.txt --remote gdrive:Music \
    --upload-each --quality 0
```

---

## שאלות נפוצות

**שיר ירד לא נכון / גרסה חיה במקום המקורית?**
הוסף לשורה בקובץ מילים כמו `official audio` או שם האלבום, למשל:
`Rita - Shvil Habricha official audio`. הסקריפט לוקח את התוצאה הראשונה
ב-YouTube, אז ניסוח מדויק יותר = תוצאה מדויקת יותר.

**שיר נכשל?**
בסוף הריצה מודפסת רשימת השירים שנכשלו. בדוק איות ונסה שוב רק אותם.

**רוצה יעד אחר (Dropbox / S3 / שרת)?**
כל יעד ש-rclone תומך בו עובד — פשוט הגדר remote אחר ב-`rclone config`
ותן את שמו ב-`--remote`.

---

## הערה על זכויות יוצרים

הכלי מיועד להורדת תוכן שמותר לך להוריד — יצירות שלך, תוכן ברישיון פתוח
(Creative Commons), נחלת הכלל, או שימוש אישי המותר לפי החוק במקומך. אחריות
השימוש עליך.
