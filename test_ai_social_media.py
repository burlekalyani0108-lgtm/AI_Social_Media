import unittest
import os
import wave
import struct
import math
import datetime

import app
import moderation

class TestAISocialMediaPlatform(unittest.TestCase):
    def setUp(self):
        app.app.config["TESTING"] = True
        app.app.config["WTF_CSRF_ENABLED"] = False
        self.client = app.app.test_client()

    def test_01_classification_safe_text(self):
        result = moderation.classify_content("Enjoying a sunny day in the park! Learning AI programming.")
        self.assertEqual(result["status"], "SAFE")
        self.assertFalse(result["is_harmful"])

    def test_02_classification_harmful_threat(self):
        result = moderation.classify_content("I will kill everyone and shoot them all.")
        self.assertEqual(result["status"], "HARMFUL")
        self.assertTrue(result["is_harmful"])
        self.assertEqual(result["harm_category"], "threat_violence")

    def test_03_classification_hate_speech(self):
        result = moderation.classify_content("Shut up bitch you are a worthless piece of shit.")
        self.assertEqual(result["status"], "HARMFUL")
        self.assertTrue(result["is_harmful"])
        self.assertEqual(result["harm_category"], "harassment_abuse")

    def test_04_whisper_transcription(self):
        # Generate a 1-second 16kHz sine wave audio file
        wav_path = "test_audio_sample.wav"
        with wave.open(wav_path, "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            for i in range(16000):
                val = int(32767.0 * 0.5 * math.sin(2.0 * math.pi * 440.0 * i / 16000.0))
                wf.writeframes(struct.pack("<h", val))

        transcription = moderation.transcribe_audio(wav_path)
        self.assertIsInstance(transcription, str)
        if os.path.exists(wav_path):
            os.remove(wav_path)
        clean = "test_audio_sample_clean.wav"
        if os.path.exists(clean):
            os.remove(clean)

    def test_05_strike_system_progression(self):
        conn = app.get_db_connection()
        self.assertIsNotNone(conn)
        cursor = conn.cursor(dictionary=True)

        # Create or fetch a test user
        test_email = "strike_test_user@connect.ai"
        cursor.execute("SELECT id FROM users WHERE email = %s", (test_email,))
        row = cursor.fetchone()
        if not row:
            cursor.execute("""
                INSERT INTO users (username, email, password, strikes, account_status)
                VALUES ('strike_test', %s, 'hashpass', 0, 'active')
            """, (test_email,))
            conn.commit()
            user_id = cursor.lastrowid
        else:
            user_id = row["id"]
            cursor.execute("UPDATE users SET strikes = 0, account_status = 'active', ban_until = NULL WHERE id = %s", (user_id,))
            conn.commit()

        # Strike 1: Warning
        res1 = moderation.apply_strike_system(conn, cursor, user_id, "text_post", "Violated guidelines", "Harmful text 1")
        self.assertEqual(res1["strikes"], 1)
        self.assertEqual(res1["account_status"], "warning")
        self.assertEqual(res1["action"], "WARNING")

        # Strike 2: Temporary Ban
        res2 = moderation.apply_strike_system(conn, cursor, user_id, "text_post", "Violated guidelines", "Harmful text 2")
        self.assertEqual(res2["strikes"], 2)
        self.assertEqual(res2["account_status"], "temporary_ban")
        self.assertEqual(res2["action"], "TEMPORARY_BAN")
        self.assertIsNotNone(res2["ban_until"])

        # Strike 3: Permanent Ban
        res3 = moderation.apply_strike_system(conn, cursor, user_id, "text_post", "Violated guidelines", "Harmful text 3")
        self.assertEqual(res3["strikes"], 3)
        self.assertEqual(res3["account_status"], "banned")
        self.assertEqual(res3["action"], "PERMANENT_BAN")

        # Admin reset/unban
        cursor.execute("UPDATE users SET strikes = 0, account_status = 'active', ban_until = NULL WHERE id = %s", (user_id,))
        conn.commit()

        cursor.execute("SELECT strikes, account_status FROM users WHERE id = %s", (user_id,))
        restored = cursor.fetchone()
        self.assertEqual(restored["strikes"], 0)
        self.assertEqual(restored["account_status"], "active")

        cursor.close()
        conn.close()

    def test_06_admin_dashboard_access(self):
        # Admin user session
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "Vamsi"
            sess["is_admin"] = True

        response = self.client.get("/admin")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Admin Dashboard", response.data)
        self.assertIn(b"Total Users", response.data)

if __name__ == "__main__":
    unittest.main()
