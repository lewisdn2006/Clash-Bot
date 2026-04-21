import cv2
import os
from pathlib import Path

SCALE_X = 1920 / 1729  # 1.1105
SCALE_Y = 1080 / 972   # 1.1111

IMAGE_FOLDER = Path(r"C:\Users\lewis\OneDrive\Documents\Files\Important\OX M24\Python\Clash Bot")

BACKUP_FOLDER = IMAGE_FOLDER / "templates_backup_windowed"
BACKUP_FOLDER.mkdir(exist_ok=True)

png_files = list(IMAGE_FOLDER.glob("*.png"))
print(f"Found {len(png_files)} PNG files")

for img_path in png_files:
    img = cv2.imread(str(img_path), cv2.IMREAD_UNCHANGED)
    if img is None:
        print(f"  SKIP (could not read): {img_path.name}")
        continue

    backup_path = BACKUP_FOLDER / img_path.name
    cv2.imwrite(str(backup_path), img)

    h, w = img.shape[:2]
    new_w = round(w * SCALE_X)
    new_h = round(h * SCALE_Y)

    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)

    cv2.imwrite(str(img_path), resized)
    print(f"  {img_path.name}: {w}x{h} -> {new_w}x{new_h}")

print("\nDone! Originals backed up to:", BACKUP_FOLDER)