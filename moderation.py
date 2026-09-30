import os
import sys
import re
import shutil
import subprocess
import datetime
import traceback
import imageio_ffmpeg

# Ensure ffmpeg.exe is accessible in PATH
_scripts_dir = os.path.dirname(sys.executable)
_ffmpeg_in_scripts = os.path.join(_scripts_dir, 'ffmpeg.exe')
if not os.path.exists(_ffmpeg_in_scripts):
    try:
        shutil.copyfile(imageio_ffmpeg.get_ffmpeg_exe(), _ffmpeg_in_scripts)
    except Exception as e:
        pass

if _scripts_dir not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _scripts_dir + os.pathsep + os.environ.get("PATH", "")

# Cache for loaded AI models
_whisper_pipe = None
_distilbert_pipe = None

def get_ffmpeg_binary():
    if os.path.exists(_ffmpeg_in_scripts):
        return _ffmpeg_in_scripts
    return imageio_ffmpeg.get_ffmpeg_exe()

def extract_audio_from_video(video_path, output_audio_path=None):
    """
    Extracts audio track from a video file and converts to 16kHz mono WAV for Whisper.
    """
    if not os.path.exists(video_path):
        return None
    
    if output_audio_path is None:
        base, _ = os.path.splitext(video_path)
        output_audio_path = f"{base}_audio.wav"
        
    ffmpeg_exe = get_ffmpeg_binary()
    cmd = [
        ffmpeg_exe,
        "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        output_audio_path
    ]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        if os.path.exists(output_audio_path) and os.path.getsize(output_audio_path) > 0:
            return output_audio_path
    except Exception as e:
        print(f"[Moderation] Video audio extraction error: {e}")
    return None

def convert_audio_to_wav(audio_path, output_wav_path=None):
    """
    Converts any audio file (e.g. webm, ogg, mp3, m4a) to 16kHz mono WAV for Whisper.
    """
    if not os.path.exists(audio_path):
        return None
    
    if output_wav_path is None:
        base, _ = os.path.splitext(audio_path)
        output_wav_path = f"{base}_clean.wav"
        
    ffmpeg_exe = get_ffmpeg_binary()
    cmd = [
        ffmpeg_exe,
        "-y",
        "-i", audio_path,
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        output_wav_path
    ]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        if os.path.exists(output_wav_path) and os.path.getsize(output_wav_path) > 0:
            return output_wav_path
    except Exception as e:
        print(f"[Moderation] Audio conversion error: {e}")
    return audio_path

def get_whisper_pipeline():
    global _whisper_pipe
    if _whisper_pipe is None:
        try:
            print("[Moderation] Loading Whisper model (openai/whisper-tiny)...")
            from transformers import pipeline
            _whisper_pipe = pipeline(
                "automatic-speech-recognition",
                model="openai/whisper-tiny",
                device="cpu"
            )
            print("[Moderation] Whisper model loaded successfully.")
        except Exception as e:
            print(f"[Moderation] Failed to load Whisper pipeline: {e}")
            _whisper_pipe = None
    return _whisper_pipe

def transcribe_audio(audio_path):
    """
    Transcribes audio to text using Whisper.
    Converts audio to clean 16kHz WAV first for uniform processing.
    """
    if not audio_path or not os.path.exists(audio_path):
        return ""
    
    clean_wav = convert_audio_to_wav(audio_path)
    pipe = get_whisper_pipeline()
    
    if pipe is not None and clean_wav and os.path.exists(clean_wav):
        try:
            result = pipe(clean_wav, generate_kwargs={"task": "transcribe", "language": "en"}, return_timestamps=False)
            text = result.get("text", "").strip() if isinstance(result, dict) else str(result).strip()
            # Clean up non-speech / music note symbols like ♪
            text = re.sub(r"[♪♫#\*\(\)]", "", text).strip()
            try:
                print(f"[Moderation] Whisper transcribed: \"{text}\"")
            except Exception:
                print(f"[Moderation] Whisper transcribed text successfully.")
            return text
        except Exception as e:
            print(f"[Moderation] Whisper transcription error: {e}")
            
    return ""

def get_distilbert_pipeline():
    global _distilbert_pipe
    if _distilbert_pipe is None:
        try:
            print("[Moderation] Loading DistilBERT model...")
            from transformers import pipeline
            _distilbert_pipe = pipeline(
                "text-classification",
                model="distilbert/distilbert-base-uncased-finetuned-sst-2-english",
                device="cpu"
            )
            print("[Moderation] DistilBERT model loaded successfully.")
        except Exception as e:
            print(f"[Moderation] Failed to load DistilBERT pipeline: {e}")
            _distilbert_pipe = None
    return _distilbert_pipe

# Comprehensive safety rules for hate speech, harassment, violence, profanity abuse, threats
HARMFUL_PATTERNS = [
    (r"\b(kill\s+(yourself|urself|him|her|them|all|everyone|you))\b", "threat_violence", 0.99),
    (r"\b(i\s+will|i'm\s+gonna|i\s+gonna)\s+(kill|murder|shoot|stab|slit|bomb|attack|destroy)\b", "threat_violence", 0.99),
    (r"\b(die\s+in\s+a\s+fire|hope\s+you\s+die|go\s+die|hang\s+yourself)\b", "threat_violence", 0.98),
    (r"\b(terrorist|bombing|massacre|genocide|slaughter)\b", "threat_violence", 0.95),
    (r"\b(hate\s+all\s+(blacks|whites|asians|muslims|jews|christians|gays|lgbtq|immigrants))\b", "hate_speech", 0.98),
    (r"\b(nigger|nigga|faggot|fag|kike|chink|spic|retard|cunt)\b", "hate_speech", 0.99),
    (r"\b(shut\s+up\s+bitch|you\s+ugly\s+bitch|whore|slut|worthless\s+piece\s+of\s+shit)\b", "harassment_abuse", 0.95),
    (r"\b(fuck\s+(you|off|your|u)|motherfucker|bastard|asshole|idiot|dipshit|scumbag)\b", "toxic_profanity", 0.90),
    (r"\b(i\s+hate\s+you|you\s+suck|burn\s+in\s+hell)\b", "toxic_harassment", 0.88),
]

def classify_content(text):
    """
    Classifies text as SAFE or HARMFUL using DistilBERT model + Safety Pattern Evaluator.
    Returns dict:
    {
        'status': 'SAFE' or 'HARMFUL',
        'is_harmful': bool,
        'harm_category': str or None,
        'confidence': float,
        'reason': str
    }
    """
    if not text or not text.strip():
        return {
            "status": "SAFE",
            "is_harmful": False,
            "harm_category": None,
            "confidence": 1.0,
            "reason": "Content is empty or neutral"
        }
    
    cleaned = text.strip()
    lower_text = cleaned.lower()
    
    # 1. Check against safety patterns (Hate speech, violent threats, abusive profanity)
    for pattern, category, conf in HARMFUL_PATTERNS:
        match = re.search(pattern, lower_text, re.IGNORECASE)
        if match:
            category_label = category.replace('_', ' ').title()
            return {
                "status": "HARMFUL",
                "is_harmful": True,
                "harm_category": category,
                "confidence": conf,
                "reason": f"Violates Community Guidelines: {category_label} detected ('{match.group(0)}')",
                "flagged_token": match.group(0)
            }
            
    # 2. DistilBERT text classification inference
    distilbert = get_distilbert_pipeline()
    if distilbert is not None:
        try:
            res = distilbert(cleaned[:512])[0]
            label = res.get("label", "").upper()
            score = float(res.get("score", 0.0))
            
            # If strongly negative and contains abusive / toxic sentiment words
            if label == "NEGATIVE" and score > 0.98:
                toxic_triggers = ["hate", "kill", "die", "destroy", "disgusting", "terrible", "awful", "stupid", "worst", "threat"]
                if any(w in lower_text for w in toxic_triggers):
                    return {
                        "status": "HARMFUL",
                        "is_harmful": True,
                        "harm_category": "toxic_sentiment",
                        "confidence": round(score, 4),
                        "reason": f"DistilBERT classified as severe negative toxicity (confidence {round(score * 100, 1)}%)"
                    }
            
            return {
                "status": "SAFE",
                "is_harmful": False,
                "harm_category": None,
                "confidence": round(score, 4),
                "reason": f"DistilBERT classified as {label.lower()} sentiment (confidence {round(score * 100, 1)}%)"
            }
        except Exception as e:
            print(f"[Moderation] DistilBERT classification error: {e}")
            
    return {
        "status": "SAFE",
        "is_harmful": False,
        "harm_category": None,
        "confidence": 0.95,
        "reason": "Content passed safety checks"
    }

def apply_strike_system(connection, cursor, user_id, content_type, reason, content_text=None, media_file=None, confidence=0.95):
    """
    Applies the Strike System according to community guidelines:
    - Strike 1: WARNING
    - Strike 2: TEMPORARY BAN (24 hours suspension)
    - Strike 3+: PERMANENT BAN
    
    Inserts a record into moderation_logs and updates the user record.
    """
    cursor.execute("SELECT id, username, strikes, account_status, ban_until FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()
    if not user:
        return None
        
    current_strikes = user.get("strikes", 0) or 0
    new_strikes = current_strikes + 1
    now = datetime.datetime.now()
    
    if new_strikes == 1:
        new_status = "warning"
        action = "WARNING"
        ban_until = None
        message = "Strike 1 of 3: Warning Issued. Your content contained harmful material and was blocked. Further violations will lead to temporary or permanent bans."
    elif new_strikes == 2:
        new_status = "temporary_ban"
        action = "TEMPORARY_BAN"
        ban_until = now + datetime.timedelta(hours=24)
        message = "Strike 2 of 3: Temporary Ban. Your account has been temporarily suspended from posting and commenting for 24 hours."
    else:
        new_status = "banned"
        action = "PERMANENT_BAN"
        ban_until = None
        message = "Strike 3 of 3: Permanent Ban. Your account has been permanently banned due to repeated harmful content violations."
        
    cursor.execute("""
        UPDATE users
        SET strikes = %s, account_status = %s, ban_until = %s
        WHERE id = %s
    """, (new_strikes, new_status, ban_until, user_id))
    
    cursor.execute("""
        INSERT INTO moderation_logs
        (user_id, content_type, media_file, extracted_text, classification, harm_category, confidence, action_taken, strike_applied)
        VALUES
        (%s, %s, %s, %s, 'harmful', %s, %s, %s, 1)
    """, (
        user_id,
        content_type,
        media_file,
        content_text,
        reason,
        confidence,
        action
    ))
    
    connection.commit()
    
    return {
        "user_id": user_id,
        "username": user.get("username"),
        "strikes": new_strikes,
        "account_status": new_status,
        "action": action,
        "ban_until": ban_until.strftime("%Y-%m-%d %H:%M:%S") if ban_until else None,
        "message": message,
        "reason": reason
    }
