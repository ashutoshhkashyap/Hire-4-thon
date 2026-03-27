import os
import uuid
import datetime
import numpy as np
import requests
import io
import cv2

from PIL import Image, ImageFilter, ImageOps
from flask import Flask, request, jsonify, render_template, send_from_directory, redirect
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
import jwt
from authlib.integrations.flask_client import OAuth
from functools import wraps

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ── APP SETUP ────────────────────────────────────────────────────────────────

app = Flask(__name__, template_folder='.', static_folder='.', static_url_path='')
CORS(app, supports_credentials=True)

app.config['SECRET_KEY']                  = os.environ.get('SECRET_KEY', 'docuclean-secret-change-in-prod')
app.config['SQLALCHEMY_DATABASE_URI']     = 'sqlite:///docuclean.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# ── Credentials (set in .env) ─────────────────────────────────────────────────
GOOGLE_CLIENT_ID     = os.environ.get('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')
CLIPDROP_API_KEY = os.environ.get('CLIPDROP_API_KEY', '')  # clipdrop.co/apis

# Clipdrop cleanup endpoint — always on, no cold starts, 100 free calls/day
CLIPDROP_URL = "https://clipdrop-api.co/cleanup/v1"

db     = SQLAlchemy(app)
bcrypt = Bcrypt(app)
oauth  = OAuth(app)

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ── DATABASE MODEL ────────────────────────────────────────────────────────────

class User(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    full_name  = db.Column(db.String(120), nullable=False)
    email      = db.Column(db.String(120), unique=True, nullable=False)
    password   = db.Column(db.String(200), nullable=True)
    google_id  = db.Column(db.String(100), nullable=True)
    avatar_url = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def to_dict(self):
        return {
            'id':         self.id,
            'full_name':  self.full_name,
            'email':      self.email,
            'avatar_url': self.avatar_url,
        }

with app.app_context():
    db.create_all()
    print("✅ Database ready (docuclean.db)")


# ── GOOGLE OAUTH ──────────────────────────────────────────────────────────────

google = oauth.register(
    name='google',
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)


# ── JWT HELPERS ───────────────────────────────────────────────────────────────

JWT_EXPIRY_HOURS = 72

def generate_token(user_id):
    payload = {
        'user_id': user_id,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=JWT_EXPIRY_HOURS)
    }
    return jwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256')

def decode_token(token):
    return jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token      = None
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
        if not token:
            return jsonify({'error': 'Authentication required'}), 401
        try:
            data         = decode_token(token)
            current_user = User.query.get(data['user_id'])
            if not current_user:
                return jsonify({'error': 'User not found'}), 401
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Session expired. Please login again.'}), 401
        except Exception:
            return jsonify({'error': 'Invalid token'}), 401
        return f(current_user, *args, **kwargs)
    return decorated


# ── AUTH ROUTES ───────────────────────────────────────────────────────────────

@app.route('/auth/register', methods=['POST'])
def register():
    data      = request.get_json()
    full_name = (data.get('full_name') or '').strip()
    email     = (data.get('email') or '').strip().lower()
    password  = data.get('password') or ''

    if not full_name or not email or not password:
        return jsonify({'error': 'All fields are required'}), 400
    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'An account with this email already exists'}), 409

    hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
    user = User(full_name=full_name, email=email, password=hashed_pw)
    db.session.add(user)
    db.session.commit()

    return jsonify({'token': generate_token(user.id), 'user': user.to_dict()}), 201


@app.route('/auth/login', methods=['POST'])
def login():
    data     = request.get_json()
    email    = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not email or not password:
        return jsonify({'error': 'Email and password are required'}), 400

    user = User.query.filter_by(email=email).first()
    if not user or not user.password:
        return jsonify({'error': 'Invalid email or password'}), 401
    if not bcrypt.check_password_hash(user.password, password):
        return jsonify({'error': 'Invalid email or password'}), 401

    return jsonify({'token': generate_token(user.id), 'user': user.to_dict()})


@app.route('/auth/me', methods=['GET'])
@token_required
def get_me(current_user):
    return jsonify({'user': current_user.to_dict()})


@app.route('/auth/google')
def google_login():
    if not GOOGLE_CLIENT_ID:
        return jsonify({'error': 'Google OAuth not configured'}), 500
    return google.authorize_redirect('http://127.0.0.1:5000/auth/google/callback')


@app.route('/auth/google/callback')
def google_callback():
    try:
        token_data = google.authorize_access_token()
        user_info  = token_data.get('userinfo') or google.parse_id_token(token_data)
        google_id  = user_info['sub']
        email      = user_info['email'].lower()
        full_name  = user_info.get('name', email.split('@')[0])
        avatar_url = user_info.get('picture', '')

        user = User.query.filter_by(google_id=google_id).first()
        if not user:
            user = User.query.filter_by(email=email).first()
            if user:
                user.google_id  = google_id
                user.avatar_url = avatar_url
            else:
                user = User(full_name=full_name, email=email,
                            google_id=google_id, avatar_url=avatar_url)
                db.session.add(user)
        db.session.commit()

        token = generate_token(user.id)
        return redirect(f'http://127.0.0.1:5500/index.html?token={token}')
    except Exception as e:
        print(f"Google OAuth error: {e}")
        return redirect('http://127.0.0.1:5500/index.html?error=google_auth_failed')


# ── AI STAIN DETECTION (auto-generate mask) ───────────────────────────────────

def auto_generate_mask(image: Image.Image) -> Image.Image:
    """
    Automatically detects stains / marks on a document image and returns
    a binary mask (white = area to inpaint, black = keep).

    Strategy:
      1. Convert to grayscale.
      2. Apply a gentle Gaussian blur to reduce noise.
      3. Adaptive threshold to separate dark marks from white paper.
      4. Invert so marks are white (inpaint targets).
      5. Dilate slightly so HF model gets clear context around each mark.
      6. Exclude very large dark regions (likely real text) using contour area.
    """
    gray = image.convert("L")

    # Blur to smooth noise
    blurred = gray.filter(ImageFilter.GaussianBlur(radius=1))

    # Convert to numpy for OpenCV adaptive threshold
    arr = np.array(blurred)

    # Adaptive threshold — works well for uneven lighting / aged paper
    thresh = cv2.adaptiveThreshold(
        arr, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        blockSize=31,
        C=10
    )

    # Remove large blobs (real text characters) — keep only stain-sized blobs
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(thresh, connectivity=8)
    mask = np.zeros_like(thresh)
    img_area = image.width * image.height

    for i in range(1, num_labels):
        area = stats[i, cv2.CC_STAT_AREA]
        w    = stats[i, cv2.CC_STAT_WIDTH]
        h    = stats[i, cv2.CC_STAT_HEIGHT]
        aspect = w / (h + 1e-5)

        # Stains tend to be: blobs not shaped like letters,
        # larger than noise but smaller than page-wide marks
        is_noise      = area < 20
        is_huge_block = area > img_area * 0.05
        is_letter_shaped = (0.1 < aspect < 10) and (area < 800)

        if not is_noise and not is_huge_block and not is_letter_shaped:
            mask[labels == i] = 255

    # Dilate mask so the inpainting model sees clean context around each stain
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask   = cv2.dilate(mask, kernel, iterations=2)

    return Image.fromarray(mask)


# ── HUGGING FACE INPAINTING ───────────────────────────────────────────────────

def _img_to_bytes(img: Image.Image, fmt='PNG') -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def inpaint_with_clipdrop(image: Image.Image, mask: Image.Image) -> Image.Image | None:
    """
    Sends image + mask to Clipdrop Cleanup API (Stability AI).
    - Always on, no cold starts
    - 100 free calls/day
    - Mask: white = remove/clean, black = keep
    Returns the cleaned PIL Image, or None on failure.
    """
    if not CLIPDROP_API_KEY:
        print("❌ CLIPDROP_API_KEY not set in .env")
        return None

    orig_size = image.size

    headers = {
        "x-api-key": CLIPDROP_API_KEY,
    }

    files = {
        "image_file": ("image.png", io.BytesIO(_img_to_bytes(image)), "image/png"),
        "mask_file":  ("mask.png",  io.BytesIO(_img_to_bytes(mask)),  "image/png"),
    }

    print("🎨 Sending to Clipdrop Cleanup API …")
    try:
        resp = requests.post(
            CLIPDROP_URL,
            headers=headers,
            files=files,
            timeout=60
        )
    except requests.exceptions.Timeout:
        print("❌ Clipdrop request timed out")
        return None

    if resp.status_code != 200:
        print(f"❌ Clipdrop API error {resp.status_code}: {resp.text[:300]}")
        return None

    # Response is raw PNG bytes
    result_img = Image.open(io.BytesIO(resp.content)).convert("RGB")

    # Restore original dimensions if needed
    if result_img.size != orig_size:
        result_img = result_img.resize(orig_size, Image.LANCZOS)

    print("✅ Clipdrop cleanup complete!")
    return result_img


# ── MAIN CLEAN PIPELINE ───────────────────────────────────────────────────────

def clean_image(image_path: str, mask_path: str | None, job_id: str) -> str | None:
    """
    Full pipeline:
      1. Load uploaded image.
      2. If a manual mask was provided, use it; otherwise auto-detect stains.
      3. Call HF inpainting API.
      4. Save and return the result path.
    """
    try:
        image = Image.open(image_path).convert("RGB")

        # Use manual mask if provided, else auto-generate
        if mask_path and os.path.exists(mask_path):
            mask_raw = Image.open(mask_path).convert("L")
            mask_arr = np.array(mask_raw)
            _, mask_bin = cv2.threshold(mask_arr, 10, 255, cv2.THRESH_BINARY)
            mask = Image.fromarray(mask_bin)
            print("🖌️  Using manual mask from frontend")
        else:
            print("🔍 Auto-detecting stains …")
            mask = auto_generate_mask(image)

        # Check mask has content (non-zero pixels)
        mask_np = np.array(mask)
        if mask_np.max() == 0:
            print("ℹ️  No stains detected — returning original image")
            result_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_result.png")
            image.save(result_path)
            return result_path

        # Inpaint via Clipdrop
        result = inpaint_with_clipdrop(image, mask)
        if result is None:
            return None

        result_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_result.png")
        result.save(result_path)
        return result_path

    except Exception as e:
        print(f"❌ Pipeline error: {e}")
        return None
    finally:
        for path in [image_path, mask_path]:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass


# ── ROUTES ────────────────────────────────────────────────────────────────────

@app.route('/result/<filename>')
def serve_result(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route('/')
def home():
    return render_template('index.html')


@app.route('/clean', methods=['POST'])
def clean():
    """
    Accepts:
      - image  (required) — the document image file
      - mask   (optional) — painted mask from frontend; if absent, auto-detect
    """
    try:
        if 'image' not in request.files:
            return jsonify({'error': 'Missing image file'}), 400

        job_id     = str(uuid.uuid4())
        image_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_src.png")
        mask_path  = None

        request.files['image'].save(image_path)

        if 'mask' in request.files:
            mask_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_mask.png")
            request.files['mask'].save(mask_path)

        result_path = clean_image(image_path, mask_path, job_id)
        if not result_path:
            return jsonify({'error': 'Processing failed. The HF model may be loading — please retry in ~20 seconds.'}), 500

        filename   = os.path.basename(result_path)
        result_url = f"http://127.0.0.1:5000/result/{filename}"
        return jsonify({'result': result_url})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


print("✅ DocuClean backend ready! Using Clipdrop Cleanup API (Stability AI).")

if __name__ == '__main__':
    app.run(port=5000, debug=False, threaded=True)
