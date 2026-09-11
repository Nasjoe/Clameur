import sys, time
import numpy as np, cv2, zxingcpp
from PIL import Image, ImageFilter
from qart import qart, render

def decode(img):
    arr = np.asarray(img.convert("L"))
    z = zxingcpp.read_barcodes(arr)
    zt = z[0].text if z else None
    try:
        ct, _, _ = cv2.QRCodeDetector().detectAndDecode(arr)
    except Exception:
        ct = ""
    return zt, (ct or None)

def degrade(img, module_px=3.0, n=65):
    # simule une photo au telephone : reduit, floute, tourne, bruite
    w = int(img.width * module_px / 8)
    im = img.resize((w, w), Image.BILINEAR).filter(ImageFilter.GaussianBlur(0.8))
    im = im.rotate(7, expand=True, fillcolor=255, resample=Image.BILINEAR)
    a = np.asarray(im).astype(float) + np.random.default_rng(0).normal(0, 18, (im.height, im.width))
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))

URLS = {
    "long": "https://clameur.exemple.fr/c/3f2b9c1e-7a4d-4e8b-9f61-2c5d8e0a4b17",
    "court": "https://clameur.exemple.fr/c/3f2b9c1e",
}
