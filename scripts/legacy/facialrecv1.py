import cv2
import mediapipe as mp
import os

# -----------------------------
# Setup
# -----------------------------

mp_face_detection = mp.solutions.face_detection
face_detection = mp_face_detection.FaceDetection(
    min_detection_confidence=0.7
)

cap = cv2.VideoCapture(0)

# Create folder
os.makedirs("captures", exist_ok=True)

captured_faces = []
capture_done = False

# -----------------------------
# Blur Score Function
# -----------------------------

def blur_score(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Laplacian variance
    score = cv2.Laplacian(
        gray,
        cv2.CV_64F
    ).var()

    return score

# -----------------------------
# Main Loop
# -----------------------------

while True:
    success, frame = cap.read()

    if not success:
        break

    frame = cv2.flip(frame, 1)

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    results = face_detection.process(rgb)

    h, w, _ = frame.shape

    if results.detections:

        for detection in results.detections:

            bbox = detection.location_data.relative_bounding_box

            x = int(bbox.xmin * w)
            y = int(bbox.ymin * h)
            width = int(bbox.width * w)
            height = int(bbox.height * h)

            # Draw box
            cv2.rectangle(
                frame,
                (x, y),
                (x + width, y + height),
                (0, 255, 0),
                2
            )

            cv2.putText(
                frame,
                "UNKNOWN",
                (x, y - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2
            )

            # Capture only once
            if not capture_done:

                # Crop face
                face_crop = frame[
                    y:y + height,
                    x:x + width
                ]

                if face_crop.size != 0:

                    captured_faces.append(face_crop)

                    print(
                        f"Captured {len(captured_faces)}/10"
                    )

                    cv2.waitKey(150)

                # Once 10 images collected
                if len(captured_faces) >= 10:

                    best_score = -1
                    best_image = None

                    for img in captured_faces:

                        score = blur_score(img)

                        print("Score:", score)

                        if score > best_score:
                            best_score = score
                            best_image = img

                    # Save best image
                    cv2.imwrite(
                        "captures/best_face.jpg",
                        best_image
                    )

                    print(
                        "Best image saved!"
                    )

                    capture_done = True

    cv2.imshow("Enrollment Capture", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()