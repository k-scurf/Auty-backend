import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk
import json
import os

# -----------------------------
# Setup
# -----------------------------

IMAGE_PATH = "captures/best_face.jpg"

os.makedirs("profiles", exist_ok=True)
os.makedirs("database", exist_ok=True)

# -----------------------------
# Save Function
# -----------------------------

def save_profile():

    name = name_entry.get()
    age = age_entry.get()
    status = status_entry.get()

    if not name:
        messagebox.showerror(
            "Error",
            "Name required"
        )
        return

    # Profile data
    profile = {
        "name": name,
        "age": age,
        "status": status,
        "image": f"profiles/{name}.jpg"
    }

    # Save image copy
    image = Image.open(IMAGE_PATH)
    image.save(f"profiles/{name}.jpg")

    # Save JSON
    with open(
        f"database/{name}.json",
        "w"
    ) as f:

        json.dump(
            profile,
            f,
            indent=4
        )

    messagebox.showinfo(
        "Success",
        "Profile saved!"
    )

# -----------------------------
# UI Window
# -----------------------------

root = tk.Tk()
root.title("Face Enrollment")
root.geometry("400x500")

# -----------------------------
# Face Image
# -----------------------------
print(os.path.abspath(IMAGE_PATH))
image = Image.open(IMAGE_PATH)
image = image.resize((200, 200))

photo = ImageTk.PhotoImage(image)

image_label = tk.Label(
    root,
    image=photo
)

image_label.pack(pady=10)

# -----------------------------
# Form Fields
# -----------------------------

tk.Label(root, text="Name").pack()

name_entry = tk.Entry(root)
name_entry.pack()

tk.Label(root, text="Age").pack()

age_entry = tk.Entry(root)
age_entry.pack()

tk.Label(root, text="Status").pack()

status_entry = tk.Entry(root)
status_entry.pack()

# -----------------------------
# Save Button
# -----------------------------

save_button = tk.Button(
    root,
    text="Save Profile",
    command=save_profile
)

save_button.pack(pady=20)

root.mainloop()