import os
import uuid
import datetime
import numpy as np
import cv2
from PIL import Image

from flask import Flask, request, jsonify, render_template, send_from_directory, redirect, session
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


# APP SETUP

app = Flask(__name__, template_folder='.', static_folder='.', static_url_path='')
CORS(app, supports_credentials=True)

app.config['SECRET_KEY']         = os.environ.get('SECRET_KEY', 'docuclean-secret-change-in-prod')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///docuclean.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Google OAuth credentials — set these in your .env file
# Get them free at: https://console.cloud.google.com → APIs & Services → Credentials
GOOGLE_CLIENT_ID     = os.environ.get('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')

db     = SQLAlchemy(app)
bcrypt = Bcrypt(app)
oauth  = OAuth(app)

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# DATABASE MODEL

class User(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    full_name  = db.Column(db.String(120), nullable=False)
    email      = db.Column(db.String(120), unique=True, nullable=False)
    password   = db.Column(db.String(200), nullable=True)   # null for Google-only users
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


# GOOGLE OAUTH SETUP

google = oauth.register(
    name='google',
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)


# JWT HELPERS

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
    """Decorator — protects routes that need a logged-in user."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
        if not token:
            return jsonify({'error': 'Authentication required'}), 401
        try:
            data = decode_token(token)
            current_user = User.query.get(data['user_id'])
            if not current_user:
                return jsonify({'error': 'User not found'}), 401
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Session expired. Please login again.'}), 401
        except Exception:
            return jsonify({'error': 'Invalid token'}), 401
        return f(current_user, *args, **kwargs)
    return decorated


# AUTH ROUTES


@app.route('/auth/register', methods=['POST'])
def register():
    data = request.get_json()
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

    token = generate_token(user.id)
    return jsonify({'token': token, 'user': user.to_dict()}), 201


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

    token = generate_token(user.id)
    return jsonify({'token': token, 'user': user.to_dict()})


@app.route('/auth/me', methods=['GET'])
@token_required
def get_me(current_user):
    return jsonify({'user': current_user.to_dict()})


#    Google OAuth 

@app.route('/auth/google')
def google_login():
    if not GOOGLE_CLIENT_ID:
        return jsonify({'error': 'Google OAuth not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env'}), 500
    redirect_uri = 'http://127.0.0.1:5000/auth/google/callback'
    return google.authorize_redirect(redirect_uri)


@app.route('/auth/google/callback')
def google_callback():
    try:
        token_data = google.authorize_access_token()
        user_info  = token_data.get('userinfo') or google.parse_id_token(token_data)

        google_id  = user_info['sub']
        email      = user_info['email'].lower()
        full_name  = user_info.get('name', email.split('@')[0])
        avatar_url = user_info.get('picture', '')

        # Find existing user by Google ID or email
        user = User.query.filter_by(google_id=google_id).first()
        if not user:
            user = User.query.filter_by(email=email).first()
            if user:
                # Link Google to existing email account
                user.google_id  = google_id
                user.avatar_url = avatar_url
            else:
                # Brand new user via Google
                user = User(
                    full_name=full_name,
                    email=email,
                    google_id=google_id,
                    avatar_url=avatar_url
                )
                db.session.add(user)
        db.session.commit()

        token = generate_token(user.id)
        # Redirect to frontend with token in URL — JS will pick it up
        return redirect(f'http://127.0.0.1:5500/index.html?token={token}')

    except Exception as e:
        print(f"Google OAuth error: {e}")
        return redirect('http://127.0.0.1:5500/index.html?error=google_auth_failed')


# IMAGE CLEANING (OpenCV — fast, no GPU)

print("✅ DocuClean backend ready! Using OpenCV inpainting (fast, no GPU needed).")

def clean_image(image_path, mask_path, job_id):
    try:
        image = cv2.imread(image_path)
        if image is None:
            return None

        h, w = image.shape[:2]
        mask_pil = Image.open(mask_path).convert("L")
        mask_pil = mask_pil.resize((w, h), Image.NEAREST)
        mask = np.array(mask_pil)

        _, mask_bin = cv2.threshold(mask, 10, 255, cv2.THRESH_BINARY)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask_bin = cv2.dilate(mask_bin, kernel, iterations=1)

        result = cv2.inpaint(image, mask_bin, inpaintRadius=10, flags=cv2.INPAINT_TELEA)

        result_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_result.png")
        cv2.imwrite(result_path, result)
        print(f"✅ Done! Saved to {result_path}")
        return result_path

    except Exception as e:
        print(f"❌ Inpainting Error: {e}")
        return None
    finally:
        for path in [image_path, mask_path]:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass


# MAIN ROUTES


@app.route('/result/<filename>')
def serve_result(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/clean', methods=['POST'])
def clean():
    try:
        if 'image' not in request.files or 'mask' not in request.files:
            return jsonify({'error': 'Missing image or mask file'}), 400

        job_id     = str(uuid.uuid4())
        image_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_src.png")
        mask_path  = os.path.join(UPLOAD_FOLDER, f"{job_id}_mask.png")

        request.files['image'].save(image_path)
        request.files['mask'].save(mask_path)

        result_path = clean_image(image_path, mask_path, job_id)
        if not result_path:
            return jsonify({'error': 'Processing failed'}), 500

        filename   = os.path.basename(result_path)
        result_url = f"http://127.0.0.1:5000/result/{filename}"
        return jsonify({'result': result_url})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(port=5000, debug=False, threaded=True)