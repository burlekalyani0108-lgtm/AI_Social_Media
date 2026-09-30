import os
import uuid
import datetime
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    jsonify,
    flash,
)
import mysql.connector
from mysql.connector import Error
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

import moderation

# =========================================================
# FLASK CONFIGURATION
# =========================================================
app = Flask(__name__)
app.secret_key = "connect_social_media_secret_key_2026"
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024  # 64 MB for media

app.config["UPLOAD_FOLDER"] = os.path.join(app.root_path, "static", "uploads")
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
ALLOWED_AUDIO_EXTENSIONS = {"mp3", "wav", "ogg", "m4a", "webm", "aac"}
ALLOWED_VIDEO_EXTENSIONS = {"mp4", "webm", "mov", "avi", "mkv"}
ALLOWED_EXTENSIONS = ALLOWED_IMAGE_EXTENSIONS | ALLOWED_AUDIO_EXTENSIONS | ALLOWED_VIDEO_EXTENSIONS

# =========================================================
# MYSQL CONFIGURATION
# =========================================================
DB_HOST = "localhost"
DB_PORT = 3307
DB_USER = "root"
DB_PASSWORD = "Kalyani@2005"
DB_NAME = "ai_social_media"

def get_db_connection():
    try:
        connection = mysql.connector.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME
        )
        if connection.is_connected():
            return connection
    except Error as e:
        print("MYSQL CONNECTION ERROR:", e)
    return None

def initialize_database():
    connection = get_db_connection()
    if connection is None:
        print("DATABASE CONNECTION FAILED. Check MySQL service.")
        return

    cursor = connection.cursor(dictionary=True)
    try:
        # Users
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(100) NOT NULL UNIQUE,
                email VARCHAR(150) NOT NULL UNIQUE,
                password VARCHAR(255) NOT NULL,
                profile_pic VARCHAR(500) NULL,
                bio TEXT NULL,
                strikes INT NOT NULL DEFAULT 0,
                account_status VARCHAR(20) NOT NULL DEFAULT 'active',
                ban_until DATETIME NULL,
                is_admin TINYINT(1) NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Posts
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                image VARCHAR(500) NULL,
                media_file VARCHAR(500) NULL,
                post_type VARCHAR(20) NOT NULL DEFAULT 'image',
                caption TEXT NULL,
                extracted_text TEXT NULL,
                moderation_status VARCHAR(20) NOT NULL DEFAULT 'safe',
                moderation_reason VARCHAR(255) NULL,
                likes INT NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # Likes
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS likes (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                post_id INT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY unique_like (user_id, post_id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
            )
        """)

        # Comments
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS comments (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                post_id INT NOT NULL,
                comment TEXT NOT NULL,
                comment_type VARCHAR(20) NOT NULL DEFAULT 'text',
                audio_file VARCHAR(500) NULL,
                extracted_text TEXT NULL,
                moderation_status VARCHAR(20) NOT NULL DEFAULT 'safe',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
            )
        """)

        # Follows
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS follows (
                id INT AUTO_INCREMENT PRIMARY KEY,
                follower_id INT NOT NULL,
                following_id INT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY unique_follow (follower_id, following_id),
                FOREIGN KEY (follower_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (following_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # Moderation Logs
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS moderation_logs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                content_type VARCHAR(50) NOT NULL,
                content_id INT NULL,
                media_file VARCHAR(500) NULL,
                extracted_text TEXT NULL,
                classification VARCHAR(50) NOT NULL,
                harm_category VARCHAR(100) NULL,
                confidence FLOAT NULL,
                action_taken VARCHAR(50) NOT NULL,
                strike_applied TINYINT(1) DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        connection.commit()

        # Idempotent Column Additions
        def add_col(tbl, col, defn):
            cursor.execute(f"SHOW COLUMNS FROM {tbl} LIKE %s", (col,))
            if not cursor.fetchone():
                cursor.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {defn}")
                connection.commit()

        add_col("users", "strikes", "INT NOT NULL DEFAULT 0")
        add_col("users", "account_status", "VARCHAR(20) NOT NULL DEFAULT 'active'")
        add_col("users", "ban_until", "DATETIME NULL")
        add_col("users", "is_admin", "TINYINT(1) NOT NULL DEFAULT 0")

        add_col("posts", "media_file", "VARCHAR(500) NULL")
        add_col("posts", "post_type", "VARCHAR(20) NOT NULL DEFAULT 'image'")
        add_col("posts", "extracted_text", "TEXT NULL")
        add_col("posts", "moderation_status", "VARCHAR(20) NOT NULL DEFAULT 'safe'")
        add_col("posts", "moderation_reason", "VARCHAR(255) NULL")

        add_col("comments", "comment_type", "VARCHAR(20) NOT NULL DEFAULT 'text'")
        add_col("comments", "audio_file", "VARCHAR(500) NULL")
        add_col("comments", "extracted_text", "TEXT NULL")
        add_col("comments", "moderation_status", "VARCHAR(20) NOT NULL DEFAULT 'safe'")

        # Ensure first user is admin
        cursor.execute("UPDATE users SET is_admin = 1 WHERE id = 1")
        connection.commit()

        print("----------------------------------------")
        print("DATABASE INITIALIZED & READY")
        print("Database :", DB_NAME)
        print("MySQL    :", DB_HOST, "Port:", DB_PORT)
        print("----------------------------------------")
    except Error as e:
        connection.rollback()
        print("DATABASE INITIALIZATION ERROR:", e)
    finally:
        cursor.close()
        connection.close()

# =========================================================
# HELPERS
# =========================================================
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def get_file_type(filename):
    if not filename or "." not in filename:
        return None
    ext = filename.rsplit(".", 1)[1].lower()
    if ext in ALLOWED_IMAGE_EXTENSIONS:
        return "image"
    if ext in ALLOWED_AUDIO_EXTENSIONS:
        return "audio"
    if ext in ALLOWED_VIDEO_EXTENSIONS:
        return "video"
    return None

def is_ajax_request():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json

def check_user_active_status(user_id):
    connection = get_db_connection()
    if connection is None:
        return None
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, username, email, strikes, account_status, ban_until, is_admin, profile_pic, bio FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        if not user:
            return None

        # Check temporary ban expiration
        if user.get("account_status") == "temporary_ban":
            ban_until = user.get("ban_until")
            if ban_until and datetime.datetime.now() > ban_until:
                cursor.execute("UPDATE users SET account_status = 'active', ban_until = NULL WHERE id = %s", (user_id,))
                connection.commit()
                user["account_status"] = "active"
                user["ban_until"] = None

        return user
    finally:
        cursor.close()
        connection.close()

def password_is_valid(stored_password, entered_password):
    if not stored_password:
        return False
    try:
        if stored_password.startswith(("scrypt:", "pbkdf2:")):
            return check_password_hash(stored_password, entered_password)
    except Exception:
        return False
    return stored_password == entered_password

# =========================================================
# ROUTES: AUTHENTICATION
# =========================================================
@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("home"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    username_or_email = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if not username_or_email or not password:
        return render_template("login.html", error="Username/email and password are required.")

    connection = get_db_connection()
    if connection is None:
        return render_template("login.html", error="Database connection failed.")

    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT id, username, email, password, profile_pic, bio, account_status, strikes, ban_until, is_admin
            FROM users
            WHERE LOWER(username) = LOWER(%s) OR LOWER(email) = LOWER(%s)
            LIMIT 1
        """, (username_or_email, username_or_email))
        user = cursor.fetchone()

        if not user:
            return render_template("login.html", error="User not found.")

        # Check if permanently banned
        if user.get("account_status") == "banned":
            return render_template("login.html", error="Your account has been permanently banned due to severe community guideline violations (Strike 3/3).")

        # Check temporary ban
        if user.get("account_status") == "temporary_ban":
            ban_until = user.get("ban_until")
            if ban_until and datetime.datetime.now() > ban_until:
                cursor.execute("UPDATE users SET account_status = 'active', ban_until = NULL WHERE id = %s", (user["id"],))
                connection.commit()
                user["account_status"] = "active"
            else:
                expiry_str = ban_until.strftime('%Y-%m-%d %H:%M') if ban_until else '24 hours'
                return render_template("login.html", error=f"Your account is temporarily suspended until {expiry_str} due to strike violations (Strike 2/3).")

        if not password_is_valid(user["password"], password):
            return render_template("login.html", error="Incorrect password.")

        if not user["password"].startswith(("scrypt:", "pbkdf2:")):
            new_password = generate_password_hash(password, method="scrypt")
            cursor.execute("UPDATE users SET password = %s WHERE id = %s", (new_password, user["id"]))
            connection.commit()

        session.clear()
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["email"] = user["email"]
        session["is_admin"] = bool(user.get("is_admin"))

        return redirect(url_for("home"))
    except Error as e:
        print("LOGIN ERROR:", e)
        return render_template("login.html", error="Login error occurred.")
    finally:
        cursor.close()
        connection.close()

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not username or not email or not password or not confirm_password:
        return render_template("register.html", error="All fields are required.")

    if password != confirm_password:
        return render_template("register.html", error="Passwords do not match.")

    connection = get_db_connection()
    if connection is None:
        return render_template("register.html", error="Database connection failed.")

    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id FROM users WHERE LOWER(username) = LOWER(%s) OR LOWER(email) = LOWER(%s) LIMIT 1", (username, email))
        if cursor.fetchone():
            return render_template("register.html", error="Username or email is already registered.")

        hashed_password = generate_password_hash(password, method="scrypt")
        cursor.execute("""
            INSERT INTO users (username, email, password, strikes, account_status)
            VALUES (%s, %s, %s, 0, 'active')
        """, (username, email, hashed_password))
        connection.commit()

        return redirect(url_for("login"))
    except Error as e:
        connection.rollback()
        return render_template("register.html", error=f"Registration failed: {e}")
    finally:
        cursor.close()
        connection.close()

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# =========================================================
# ROUTES: HOME FEED & PLATFORM
# =========================================================
@app.route("/home")
def home():
    if "user_id" not in session:
        return redirect(url_for("login"))

    current_user_id = session["user_id"]
    current_user = check_user_active_status(current_user_id)
    if not current_user:
        session.clear()
        return redirect(url_for("login"))

    if current_user.get("account_status") == "banned":
        session.clear()
        return render_template("login.html", error="Your account has been permanently banned.")

    connection = get_db_connection()
    if connection is None:
        return "Database connection failed."

    cursor = connection.cursor(dictionary=True)
    try:
        # Fetch posts (display only safe moderated posts)
        cursor.execute("""
            SELECT
                p.id,
                p.user_id,
                p.image,
                p.media_file,
                p.post_type,
                p.caption,
                p.extracted_text,
                p.moderation_status,
                p.created_at,
                u.username,
                u.profile_pic,
                (
                    SELECT COUNT(*)
                    FROM likes l
                    WHERE l.post_id = p.id
                ) AS likes,
                EXISTS (
                    SELECT 1
                    FROM likes l2
                    WHERE l2.post_id = p.id
                    AND l2.user_id = %s
                ) AS user_liked,
                EXISTS (
                    SELECT 1
                    FROM follows f
                    WHERE f.follower_id = %s
                    AND f.following_id = p.user_id
                ) AS is_following
            FROM posts p
            INNER JOIN users u ON p.user_id = u.id
            WHERE (p.moderation_status = 'safe' OR p.moderation_status IS NULL)
            ORDER BY p.created_at DESC
        """, (current_user_id, current_user_id))
        posts = cursor.fetchall()

        # Fetch comments for each post
        for post in posts:
            cursor.execute("""
                SELECT
                    c.id,
                    c.comment,
                    c.comment_type,
                    c.audio_file,
                    c.extracted_text,
                    c.created_at,
                    u.username
                FROM comments c
                INNER JOIN users u ON c.user_id = u.id
                WHERE c.post_id = %s AND (c.moderation_status = 'safe' OR c.moderation_status IS NULL)
                ORDER BY c.created_at ASC
            """, (post["id"],))
            post["comments"] = cursor.fetchall()

        # Counts
        cursor.execute("SELECT COUNT(*) AS total FROM follows WHERE following_id = %s", (current_user_id,))
        followers_count = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(*) AS total FROM follows WHERE follower_id = %s", (current_user_id,))
        following_count = cursor.fetchone()["total"]

        # Suggested users (users not yet followed)
        cursor.execute("""
            SELECT u.id, u.username, u.profile_pic, u.bio
            FROM users u
            WHERE u.id != %s
            AND NOT EXISTS (
                SELECT 1 FROM follows f WHERE f.follower_id = %s AND f.following_id = u.id
            )
            ORDER BY u.created_at DESC
            LIMIT 5
        """, (current_user_id, current_user_id))
        suggested_users = cursor.fetchall()

        return render_template(
            "index.html",
            current_user=current_user,
            user=current_user,
            current_user_id=current_user_id,
            posts=posts,
            followers_count=followers_count,
            following_count=following_count,
            suggested_users=suggested_users
        )
    except Error as e:
        print("HOME ERROR:", e)
        return f"Error loading feed: {e}"
    finally:
        cursor.close()
        connection.close()

# =========================================================
# ROUTES: CREATE POST (IMAGE, AUDIO, VIDEO) + MODERATION
# =========================================================
@app.route("/create-post", methods=["GET", "POST"])
def create_post():
    if "user_id" not in session:
        return redirect(url_for("login"))

    current_user_id = session["user_id"]
    current_user = check_user_active_status(current_user_id)
    if not current_user:
        session.clear()
        return redirect(url_for("login"))

    # Check strike suspension
    if current_user.get("account_status") == "banned":
        session.clear()
        return render_template("login.html", error="Your account has been permanently banned.")

    if current_user.get("account_status") == "temporary_ban":
        ban_str = current_user["ban_until"].strftime("%Y-%m-%d %H:%M") if current_user.get("ban_until") else "24 hours"
        return render_template("create_post.html", error=f"Your account is currently under temporary ban until {ban_str} due to policy violations (Strike 2/3). Posting is suspended.", user=current_user)

    if request.method == "GET":
        return render_template("create_post.html", user=current_user)

    caption = request.form.get("caption", "").strip()
    if not caption:
        caption = request.form.get("content", "").strip()

    media_file = request.files.get("media") or request.files.get("image") or request.files.get("audio") or request.files.get("video")
    
    recorded_audio = request.files.get("recorded_audio")
    if recorded_audio and recorded_audio.filename:
        media_file = recorded_audio

    explicit_type = request.form.get("post_type", "").lower()
    post_type = explicit_type if explicit_type in ("image", "audio", "video") else None

    saved_filename = None
    media_path = None
    extracted_text = ""

    if media_file and media_file.filename:
        original_name = secure_filename(media_file.filename)
        ext = os.path.splitext(original_name)[1].lower()
        if not ext and media_file.content_type:
            if "webm" in media_file.content_type:
                ext = ".webm"
            elif "wav" in media_file.content_type:
                ext = ".wav"
            elif "ogg" in media_file.content_type:
                ext = ".ogg"
            elif "mp4" in media_file.content_type:
                ext = ".mp4"

        clean_ext = ext.lstrip(".")
        if clean_ext not in ALLOWED_EXTENSIONS:
            return render_template("create_post.html", error=f"Unsupported file format '.{clean_ext}'. Supported: Images, Audio, Video.", user=current_user)

        detected_type = get_file_type(f"file.{clean_ext}")
        if not post_type:
            post_type = detected_type or "image"

        saved_filename = f"{uuid.uuid4().hex}{ext}"
        media_path = os.path.join(app.config["UPLOAD_FOLDER"], saved_filename)
        media_file.save(media_path)
    else:
        post_type = "text"

    if not caption and not saved_filename:
        return render_template("create_post.html", error="Please provide a caption or upload media.", user=current_user)

    # ---------------------------------------------------------
    # AI PROCESSING & MODERATION PIPELINE
    # ---------------------------------------------------------
    print(f"[Create Post] Processing {post_type} post by user {current_user_id}...")
    
    # 1. Video Post: Extract Audio -> Whisper -> Speech to Text
    if post_type == "video" and media_path:
        audio_extracted_path = moderation.extract_audio_from_video(media_path)
        if audio_extracted_path and os.path.exists(audio_extracted_path):
            extracted_text = moderation.transcribe_audio(audio_extracted_path)
            try:
                os.remove(audio_extracted_path)
            except Exception:
                pass
        else:
            print("[Create Post] Video had no detectable audio stream.")

    # 2. Audio Post: Whisper -> Speech to Text
    elif post_type == "audio" and media_path:
        extracted_text = moderation.transcribe_audio(media_path)

    # 3. Content to classify: Extracted Speech Text + Caption
    combined_content = f"{caption} {extracted_text}".strip()

    # 4. DistilBERT Content Classification
    classification = moderation.classify_content(combined_content)
    print(f"[Create Post] Moderation result: {classification['status']} ({classification['reason']})")

    connection = get_db_connection()
    if connection is None:
        return render_template("create_post.html", error="Database connection failed.", user=current_user)

    cursor = connection.cursor(dictionary=True)
    try:
        # ---------------------------------------------------------
        # IF HARMFUL -> BLOCK -> STRIKE SYSTEM
        # ---------------------------------------------------------
        if classification["is_harmful"]:
            if media_path and os.path.exists(media_path):
                try:
                    os.remove(media_path)
                except Exception:
                    pass

            strike_info = moderation.apply_strike_system(
                connection=connection,
                cursor=cursor,
                user_id=current_user_id,
                content_type=f"{post_type}_post",
                reason=classification["reason"],
                content_text=combined_content,
                media_file=saved_filename,
                confidence=classification["confidence"]
            )

            if strike_info and strike_info.get("account_status") == "banned":
                session.clear()

            if is_ajax_request():
                return jsonify({
                    "success": False,
                    "harmful": True,
                    "strike_info": strike_info,
                    "message": strike_info["message"],
                    "reason": classification["reason"],
                    "extracted_text": extracted_text
                }), 403

            return render_template(
                "create_post.html",
                user=current_user,
                harmful=True,
                strike_info=strike_info,
                error=strike_info["message"],
                extracted_text=extracted_text,
                reason=classification["reason"]
            )

        # ---------------------------------------------------------
        # IF SAFE -> PUBLISH
        # ---------------------------------------------------------
        cursor.execute("""
            INSERT INTO posts (user_id, image, media_file, post_type, caption, extracted_text, moderation_status, likes)
            VALUES (%s, %s, %s, %s, %s, %s, 'safe', 0)
        """, (
            current_user_id,
            saved_filename,
            saved_filename,
            post_type,
            caption,
            extracted_text if extracted_text else None
        ))
        new_post_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO moderation_logs (user_id, content_type, content_id, media_file, extracted_text, classification, action_taken, strike_applied)
            VALUES (%s, %s, %s, %s, %s, 'safe', 'published', 0)
        """, (
            current_user_id,
            f"{post_type}_post",
            new_post_id,
            saved_filename,
            extracted_text if extracted_text else caption
        ))
        connection.commit()

        if is_ajax_request():
            return jsonify({
                "success": True,
                "message": "Post published successfully!",
                "post_id": new_post_id,
                "post_type": post_type,
                "extracted_text": extracted_text
            })

        return redirect(url_for("home"))
    except Error as e:
        connection.rollback()
        print("CREATE POST DB ERROR:", e)
        return render_template("create_post.html", error=f"Post error: {e}", user=current_user)
    finally:
        cursor.close()
        connection.close()

# =========================================================
# ROUTES: COMMENTS (TEXT & AUDIO) + MODERATION
# =========================================================
@app.route("/comment/<int:post_id>", methods=["POST"])
def add_comment(post_id):
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Please login first."}), 401

    current_user_id = session["user_id"]
    current_user = check_user_active_status(current_user_id)
    if not current_user:
        return jsonify({"success": False, "message": "User session expired."}), 401

    if current_user.get("account_status") == "banned":
        session.clear()
        return jsonify({"success": False, "message": "Account permanently banned."}), 403

    if current_user.get("account_status") == "temporary_ban":
        ban_str = current_user["ban_until"].strftime("%Y-%m-%d %H:%M") if current_user.get("ban_until") else "24 hours"
        return jsonify({"success": False, "message": f"Account temporarily suspended until {ban_str}."}), 403

    connection = get_db_connection()
    if connection is None:
        return jsonify({"success": False, "message": "Database connection failed."}), 500

    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id FROM posts WHERE id = %s LIMIT 1", (post_id,))
        if not cursor.fetchone():
            return jsonify({"success": False, "message": "Post not found."}), 404

        comment_type = "text"
        comment_text = ""
        audio_filename = None
        extracted_text = ""

        audio_file = request.files.get("audio") or request.files.get("voice_note") or request.files.get("recorded_audio")
        if audio_file and audio_file.filename:
            comment_type = "audio"
            orig_name = secure_filename(audio_file.filename)
            ext = os.path.splitext(orig_name)[1].lower() or ".webm"
            audio_filename = f"comment_{uuid.uuid4().hex}{ext}"
            audio_path = os.path.join(app.config["UPLOAD_FOLDER"], audio_filename)
            audio_file.save(audio_path)

            print(f"[Audio Comment] Transcribing audio comment...")
            extracted_text = moderation.transcribe_audio(audio_path)
            comment_text = extracted_text if extracted_text else "(Voice note)"
        else:
            data = request.get_json(silent=True)
            if data:
                comment_text = (data.get("comment") or data.get("text") or "").strip()
            else:
                comment_text = request.form.get("comment", "").strip()

        if not comment_text and not audio_filename:
            return jsonify({"success": False, "message": "Comment cannot be empty."}), 400

        content_to_check = extracted_text if comment_type == "audio" else comment_text
        classification = moderation.classify_content(content_to_check)
        print(f"[Comment Moderation] Result: {classification['status']} ({classification['reason']})")

        # -----------------------------------------------------
        # HARMFUL COMMENT -> BLOCK + STRIKE SYSTEM
        # -----------------------------------------------------
        if classification["is_harmful"]:
            if audio_filename:
                audio_path = os.path.join(app.config["UPLOAD_FOLDER"], audio_filename)
                if os.path.exists(audio_path):
                    try:
                        os.remove(audio_path)
                    except Exception:
                        pass

            strike_info = moderation.apply_strike_system(
                connection=connection,
                cursor=cursor,
                user_id=current_user_id,
                content_type="audio_comment" if comment_type == "audio" else "text_comment",
                reason=classification["reason"],
                content_text=content_to_check,
                media_file=audio_filename,
                confidence=classification["confidence"]
            )

            if strike_info and strike_info.get("account_status") == "banned":
                session.clear()

            return jsonify({
                "success": False,
                "harmful": True,
                "strike_info": strike_info,
                "message": strike_info["message"],
                "reason": classification["reason"],
                "extracted_text": extracted_text
            }), 403

        # -----------------------------------------------------
        # SAFE COMMENT -> APPROVE & PUBLISH
        # -----------------------------------------------------
        cursor.execute("""
            INSERT INTO comments (post_id, user_id, comment, comment_type, audio_file, extracted_text, moderation_status)
            VALUES (%s, %s, %s, %s, %s, %s, 'safe')
        """, (
            post_id,
            current_user_id,
            comment_text,
            comment_type,
            audio_filename,
            extracted_text if extracted_text else None
        ))
        new_comment_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO moderation_logs (user_id, content_type, content_id, media_file, extracted_text, classification, action_taken, strike_applied)
            VALUES (%s, %s, %s, %s, %s, 'safe', 'approved', 0)
        """, (
            current_user_id,
            f"{comment_type}_comment",
            new_comment_id,
            audio_filename,
            content_to_check
        ))
        connection.commit()

        return jsonify({
            "success": True,
            "comment_id": new_comment_id,
            "username": current_user["username"],
            "comment": comment_text,
            "comment_type": comment_type,
            "audio_url": url_for("static", filename="uploads/" + audio_filename) if audio_filename else None,
            "extracted_text": extracted_text,
            "created_at": "Just now"
        })
    except Error as e:
        connection.rollback()
        print("ADD COMMENT ERROR:", e)
        return jsonify({"success": False, "message": f"Unable to add comment: {e}"}), 500
    finally:
        cursor.close()
        connection.close()

# =========================================================
# ROUTES: LIKE / UNLIKE
# =========================================================
@app.route("/like/<int:post_id>", methods=["POST"])
def like_post(post_id):
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Please login first."}), 401

    current_user_id = session["user_id"]
    connection = get_db_connection()
    if connection is None:
        return jsonify({"success": False, "message": "Database connection failed."}), 500

    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id FROM posts WHERE id = %s LIMIT 1", (post_id,))
        if not cursor.fetchone():
            return jsonify({"success": False, "message": "Post not found."}), 404

        cursor.execute("SELECT id FROM likes WHERE user_id = %s AND post_id = %s LIMIT 1", (current_user_id, post_id))
        existing_like = cursor.fetchone()

        if existing_like:
            cursor.execute("DELETE FROM likes WHERE id = %s", (existing_like["id"],))
            liked = False
        else:
            cursor.execute("INSERT INTO likes (user_id, post_id) VALUES (%s, %s)", (current_user_id, post_id))
            liked = True

        cursor.execute("SELECT COUNT(*) AS total FROM likes WHERE post_id = %s", (post_id,))
        like_count = cursor.fetchone()["total"]
        cursor.execute("UPDATE posts SET likes = %s WHERE id = %s", (like_count, post_id))
        connection.commit()

        return jsonify({"success": True, "liked": liked, "likes": like_count})
    except Error as e:
        connection.rollback()
        print("LIKE ERROR:", e)
        return jsonify({"success": False, "message": "Unable to process like."}), 500
    finally:
        cursor.close()
        connection.close()

# =========================================================
# ROUTES: PROFILE & FOLLOW
# =========================================================
@app.route("/profile/<int:user_id>")
def profile(user_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    current_user_id = session["user_id"]
    current_user = check_user_active_status(current_user_id)
    if not current_user:
        session.clear()
        return redirect(url_for("login"))

    connection = get_db_connection()
    if connection is None:
        return "Database connection failed."

    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, username, email, profile_pic, bio, strikes, account_status, is_admin FROM users WHERE id = %s LIMIT 1", (user_id,))
        profile_user = cursor.fetchone()
        if not profile_user:
            return "User not found.", 404

        cursor.execute("""
            SELECT
                p.id, p.user_id, p.image, p.media_file, p.post_type, p.caption, p.extracted_text, p.created_at,
                (SELECT COUNT(*) FROM likes l WHERE l.post_id = p.id) AS likes,
                (SELECT COUNT(*) FROM comments c WHERE c.post_id = p.id AND (c.moderation_status = 'safe' OR c.moderation_status IS NULL)) AS comments_count,
                EXISTS (SELECT 1 FROM likes l2 WHERE l2.post_id = p.id AND l2.user_id = %s) AS user_liked
            FROM posts p
            WHERE p.user_id = %s AND (p.moderation_status = 'safe' OR p.moderation_status IS NULL)
            ORDER BY p.created_at DESC
        """, (current_user_id, user_id))
        posts = cursor.fetchall()

        cursor.execute("SELECT COUNT(*) AS total FROM follows WHERE following_id = %s", (user_id,))
        followers_count = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(*) AS total FROM follows WHERE follower_id = %s", (user_id,))
        following_count = cursor.fetchone()["total"]

        is_following = False
        if current_user_id != user_id:
            cursor.execute("SELECT id FROM follows WHERE follower_id = %s AND following_id = %s LIMIT 1", (current_user_id, user_id))
            is_following = cursor.fetchone() is not None

        return render_template(
            "profile.html",
            profile_user=profile_user,
            user=profile_user,
            current_user=current_user,
            posts=posts,
            post_count=len(posts),
            followers_count=followers_count,
            following_count=following_count,
            is_following=is_following,
            is_own_profile=(current_user_id == user_id),
            current_user_id=current_user_id
        )
    except Error as e:
        print("PROFILE ERROR:", e)
        return f"Profile error: {e}"
    finally:
        cursor.close()
        connection.close()

@app.route("/follow/<int:user_id>", methods=["POST"])
def follow_user(user_id):
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Please login first."}), 401

    current_user_id = session["user_id"]
    if current_user_id == user_id:
        return jsonify({"success": False, "message": "You cannot follow yourself."}), 400

    connection = get_db_connection()
    if connection is None:
        return jsonify({"success": False, "message": "Database connection failed."}), 500

    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id FROM follows WHERE follower_id = %s AND following_id = %s LIMIT 1", (current_user_id, user_id))
        existing_follow = cursor.fetchone()

        if existing_follow:
            cursor.execute("DELETE FROM follows WHERE id = %s", (existing_follow["id"],))
            following = False
        else:
            cursor.execute("INSERT INTO follows (follower_id, following_id) VALUES (%s, %s)", (current_user_id, user_id))
            following = True

        cursor.execute("SELECT COUNT(*) AS total FROM follows WHERE following_id = %s", (user_id,))
        followers_count = cursor.fetchone()["total"]
        connection.commit()

        return jsonify({"success": True, "following": following, "followers_count": followers_count})
    except Error as e:
        connection.rollback()
        return jsonify({"success": False, "message": f"Follow action failed: {e}"}), 500
    finally:
        cursor.close()
        connection.close()

@app.route("/followers")
@app.route("/followers/<int:user_id>")
def followers(user_id=None):
    if "user_id" not in session:
        return redirect(url_for("login"))
    if user_id is None:
        user_id = session["user_id"]
    current_user_id = session["user_id"]

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, username, email, profile_pic, bio FROM users WHERE id = %s LIMIT 1", (user_id,))
        profile_user = cursor.fetchone()
        cursor.execute("""
            SELECT u.id, u.username, u.email, u.profile_pic, u.bio
            FROM follows f
            INNER JOIN users u ON f.follower_id = u.id
            WHERE f.following_id = %s
            ORDER BY f.created_at DESC
        """, (user_id,))
        users = cursor.fetchall()
        return render_template("followers.html", users=users, profile_user=profile_user, user=profile_user, current_user=profile_user, current_user_id=current_user_id)
    finally:
        cursor.close()
        connection.close()

@app.route("/following")
@app.route("/following/<int:user_id>")
def following(user_id=None):
    if "user_id" not in session:
        return redirect(url_for("login"))
    if user_id is None:
        user_id = session["user_id"]
    current_user_id = session["user_id"]

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, username, email, profile_pic, bio FROM users WHERE id = %s LIMIT 1", (user_id,))
        profile_user = cursor.fetchone()
        cursor.execute("""
            SELECT u.id, u.username, u.email, u.profile_pic, u.bio
            FROM follows f
            INNER JOIN users u ON f.following_id = u.id
            WHERE f.follower_id = %s
            ORDER BY f.created_at DESC
        """, (user_id,))
        users = cursor.fetchall()
        return render_template("following.html", users=users, profile_user=profile_user, user=profile_user, current_user=profile_user, current_user_id=current_user_id)
    finally:
        cursor.close()
        connection.close()

@app.route("/search")
def search():
    if "user_id" not in session:
        return redirect(url_for("login"))

    query = request.args.get("search", "").strip()
    users = []
    if query:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute("SELECT id, username, email, profile_pic FROM users WHERE username LIKE %s LIMIT 20", (f"%{query}%",))
            users = cursor.fetchall()
        finally:
            cursor.close()
            connection.close()
    return render_template("search.html", users=users, query=query, current_user_id=session["user_id"])

# =========================================================
# ROUTES: ADMIN DASHBOARD & STRIKE MONITORING
# =========================================================
@app.route("/admin")
def admin_dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    current_admin = check_user_active_status(session["user_id"])
    if not current_admin or not current_admin.get("is_admin"):
        return render_template("login.html", error="Administrator access required. Please log in with an admin account.")

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT COUNT(*) AS total FROM users")
        total_users = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(*) AS total FROM users WHERE account_status = 'active'")
        active_users = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(*) AS total FROM users WHERE strikes > 0")
        users_with_strikes = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(*) AS total FROM users WHERE account_status = 'temporary_ban'")
        temp_banned = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(*) AS total FROM users WHERE account_status = 'banned'")
        perm_banned = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(*) AS total FROM posts")
        total_posts = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(*) AS total FROM comments")
        total_comments = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(*) AS total FROM moderation_logs WHERE classification = 'harmful'")
        flagged_violations = cursor.fetchone()["total"]

        cursor.execute("""
            SELECT id, username, email, strikes, account_status, ban_until, is_admin, created_at
            FROM users
            ORDER BY strikes DESC, id ASC
        """)
        users_list = cursor.fetchall()

        cursor.execute("""
            SELECT
                m.id, m.user_id, m.content_type, m.media_file, m.extracted_text,
                m.classification, m.harm_category, m.confidence, m.action_taken,
                m.strike_applied, m.created_at, u.username
            FROM moderation_logs m
            INNER JOIN users u ON m.user_id = u.id
            ORDER BY m.created_at DESC
            LIMIT 50
        """)
        moderation_logs = cursor.fetchall()

        stats = {
            "total_users": total_users,
            "active_users": active_users,
            "users_with_strikes": users_with_strikes,
            "temp_banned": temp_banned,
            "perm_banned": perm_banned,
            "total_posts": total_posts,
            "total_comments": total_comments,
            "flagged_violations": flagged_violations
        }

        return render_template(
            "admin_dashboard.html",
            user=current_admin,
            stats=stats,
            users=users_list,
            logs=moderation_logs
        )
    finally:
        cursor.close()
        connection.close()

@app.route("/admin/user/<int:target_user_id>/action", methods=["POST"])
def admin_user_action(target_user_id):
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    current_admin = check_user_active_status(session["user_id"])
    if not current_admin or not current_admin.get("is_admin"):
        return jsonify({"success": False, "message": "Admin privileges required."}), 403

    data = request.get_json(silent=True) or request.form
    action = data.get("action")

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        now = datetime.datetime.now()
        if action == "warn":
            cursor.execute("UPDATE users SET strikes = GREATEST(strikes + 1, 1), account_status = 'warning' WHERE id = %s", (target_user_id,))
        elif action == "temp_ban":
            ban_time = now + datetime.timedelta(hours=24)
            cursor.execute("UPDATE users SET strikes = GREATEST(strikes, 2), account_status = 'temporary_ban', ban_until = %s WHERE id = %s", (ban_time, target_user_id))
        elif action == "perm_ban":
            cursor.execute("UPDATE users SET strikes = GREATEST(strikes, 3), account_status = 'banned', ban_until = NULL WHERE id = %s", (target_user_id,))
        elif action in ("unban", "reset"):
            cursor.execute("UPDATE users SET strikes = 0, account_status = 'active', ban_until = NULL WHERE id = %s", (target_user_id,))
        elif action == "toggle_admin":
            cursor.execute("UPDATE users SET is_admin = IF(is_admin = 1, 0, 1) WHERE id = %s", (target_user_id,))
        else:
            return jsonify({"success": False, "message": "Unknown action."}), 400

        connection.commit()
        return jsonify({"success": True, "message": f"Action '{action}' executed successfully."})
    finally:
        cursor.close()
        connection.close()

@app.route("/admin/post/<int:target_post_id>/delete", methods=["POST"])
def admin_delete_post(target_post_id):
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    current_admin = check_user_active_status(session["user_id"])
    if not current_admin or not current_admin.get("is_admin"):
        return jsonify({"success": False, "message": "Admin privileges required."}), 403

    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("DELETE FROM posts WHERE id = %s", (target_post_id,))
        connection.commit()
        return jsonify({"success": True, "message": "Post deleted."})
    finally:
        cursor.close()
        connection.close()

# =========================================================
# RUN SERVER
# =========================================================
if __name__ == "__main__":
    initialize_database()
    print("----------------------------------------")
    print("AI SOCIAL MEDIA PLATFORM (INSTAGRAM-LIKE)")
    print("AI Moderation : Whisper STT + DistilBERT")
    print("Strike System : Warning -> Temp Ban -> Perm Ban")
    print("Admin Portal  : http://127.0.0.1:5000/admin")
    print("Platform URL  : http://127.0.0.1:5000")
    print("----------------------------------------")
    app.run(host="127.0.0.1", port=5000, debug=True)
