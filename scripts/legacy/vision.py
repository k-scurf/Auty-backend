import cv2
import numpy as np
import pickle
import time
from deepface import DeepFace  # ONLY used for embedding extraction ONCE per face

# -----------------------------
# LOAD DATABASE
# -----------------------------
with open("face_db.pkl", "rb") as f:
    db = pickle.load(f)

def cosine(a, b):
    a = np.array(a)
    b = np.array(b)
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

# -----------------------------
# FAST DETECTOR (OpenCV — avoids mediapipe/protobuf conflicts)
# -----------------------------
face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)

cap = cv2.VideoCapture(0)

# -----------------------------
# SESSION MEMORY (RESET EACH RUN)
# -----------------------------
session_tracks = {}
session_names = {}
next_id = 0

SMOOTH = 0.6
frame_count = 0

def center(x, y, w, h):
    return (x + w // 2, y + h // 2)

def match(cx, cy):
    best_id = None
    best_dist = 999

    for tid, (x, y, w, h) in session_tracks.items():
        tx, ty = center(x, y, w, h)
        dist = np.sqrt((cx - tx)**2 + (cy - ty)**2)

        if dist < 90 and dist < best_dist:
            best_dist = dist
            best_id = tid

    return best_id

# -----------------------------
# MAIN LOOP
# -----------------------------
while True:
    ret, frame = cap.read()
    if not ret:
        break

    frame = cv2.flip(frame, 1)

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = [
        (x, y, fw, fh)
        for (x, y, fw, fh) in face_cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
        )
    ]

    current_name = "UNKNOWN"

    # -----------------------------
    # RECOGNITION (LIGHTWEIGHT)
    # -----------------------------
    if frame_count % 15 == 0:
        try:
            embedding = DeepFace.represent(
                img_path=frame,
                enforce_detection=False
            )[0]["embedding"]

            best_name = "UNKNOWN"
            best_score = -1

            for name, db_emb in db.items():
                score = cosine(embedding, db_emb)
                if score > best_score:
                    best_score = score
                    best_name = name

            current_name = best_name if best_score > 0.6 else "UNKNOWN"

        except:
            current_name = "UNKNOWN"

    frame_count += 1

    new_tracks = {}

    # -----------------------------
    # TRACK + UI
    # -----------------------------
    for (x, y, fw, fh) in faces:

        cx, cy = center(x, y, fw, fh)

        tid = match(cx, cy)

        if tid is None:
            tid = next_id
            next_id += 1

        # smoothing
        if tid in session_tracks:
            px, py, pw, ph = session_tracks[tid]

            x = int(px * SMOOTH + x * (1 - SMOOTH))
            y = int(py * SMOOTH + y * (1 - SMOOTH))
            fw = int(pw * SMOOTH + fw * (1 - SMOOTH))
            fh = int(ph * SMOOTH + fh * (1 - SMOOTH))

        new_tracks[tid] = (x, y, fw, fh)

        if frame_count % 15 == 0:
            session_names[tid] = current_name

        name = session_names.get(tid, "UNKNOWN")

        # -----------------------------
        # DRAW UI
        # -----------------------------
        cv2.rectangle(frame, (x, y), (x+fw, y+fh), (0, 255, 0), 2)

        cx = x + fw + 10
        cy = y

        cv2.rectangle(frame, (cx, cy), (cx+200, cy+90), (0, 0, 0), -1)
        cv2.rectangle(frame, (cx, cy), (cx+200, cy+90), (0, 255, 0), 2)

        cv2.putText(frame, name,
                    (cx+10, cy+40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                    (0, 255, 0), 2)

    session_tracks = new_tracks

    cv2.imshow("SESSION VISION SYSTEM", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()