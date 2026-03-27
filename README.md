# Hire-4-thon
# DocuClean — AI Document Cleaner

DocuClean is a web app that removes stains, marks, and blemishes from scanned documents using AI-powered inpainting. Upload an image, paint over the areas you want removed, and the backend restores the document instantly — no GPU required.

---

## Features

- **Canvas-based mask editor** — paint over stains with an adjustable brush; supports mouse and touch
- **OpenCV inpainting** — fast, CPU-only image restoration using the TELEA algorithm
- **Re-edit loop** — not satisfied? Send the cleaned result back into the editor for another pass
- **User accounts** — register/login with email & password, or via Google OAuth
- **JWT authentication** — 72-hour sessions stored in `localStorage`
- **Dark UI** — responsive design with Syne + DM Sans typography

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Vanilla HTML/CSS/JS, HTML5 Canvas |
| Backend | Python, Flask, Flask-CORS |
| Image processing | OpenCV (`cv2.inpaint`), NumPy, Pillow |
| Database | SQLite via Flask-SQLAlchemy |
| Auth | Flask-Bcrypt (passwords), PyJWT (tokens), Authlib (Google OAuth) |

---

## Project Structure

```
├── index.html       # Main page — upload, mask editor, auth modal
├── output.html      # Result page — view, download, or re-edit cleaned image
├── style.css        # All styles and design tokens
├── script.js        # Frontend logic — canvas drawing, API calls, auth
├── backend.py       # Flask server — auth routes, image cleaning endpoint
└── uploads/         # Temporary folder for processed images (auto-created)
```

---

## Prerequisites

- Python 3.8+
- Node.js is **not** required — the frontend is plain HTML/JS
- A modern browser (Chrome, Firefox, Safari, Edge)

---

## Setup & Installation

### 1. Clone the repository

```bash
git clone https://github.com/your-username/docuclean.git
cd docuclean
```

### 2. Install Python dependencies

```bash
pip install flask flask-cors flask-sqlalchemy flask-bcrypt pyjwt authlib opencv-python pillow numpy python-dotenv
```

### 3. Configure environment variables

Create a `.env` file in the project root:

```env
SECRET_KEY=your-secret-key-here

# Optional — only needed for Google OAuth
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
```

> **Google OAuth setup:** Go to [Google Cloud Console](https://console.cloud.google.com) → APIs & Services → Credentials → Create OAuth 2.0 Client ID. Add `http://127.0.0.1:5000/auth/google/callback` as an authorised redirect URI.

### 4. Start the backend

```bash
python backend.py
```

The Flask server starts on `http://127.0.0.1:5000`. The SQLite database (`docuclean.db`) is created automatically on first run.

### 5. Open the frontend

Open `index.html` in your browser. If using VS Code, the **Live Server** extension works well (serves on port 5500 by default, which matches the Google OAuth redirect URL).

---

## Usage

1. Click the upload zone or drag and drop a JPG/PNG document (max 10 MB)
2. Use the brush to paint over any stains, stamps, or marks
3. Adjust the brush size with the slider; click **Clear** to start the mask over
4. Click **Process Now** — the backend cleans the image and redirects to the result page
5. Download the cleaned image, or click **Re-edit This Image** to refine it further

---

## API Endpoints

| Method | Route | Description |
|---|---|---|
| `POST` | `/clean` | Accepts `image` + `mask` form files; returns `{ result: url }` |
| `POST` | `/auth/register` | Register with `full_name`, `email`, `password` |
| `POST` | `/auth/login` | Login; returns JWT token |
| `GET` | `/auth/me` | Returns current user (requires `Authorization: Bearer <token>`) |
| `GET` | `/auth/google` | Initiates Google OAuth flow |
| `GET` | `/auth/google/callback` | Google OAuth callback |
| `GET` | `/result/<filename>` | Serves a processed image file |

---

## Configuration Notes

- **Ports:** Backend runs on `:5000`, frontend is expected on `:5500`. If you change either, update the hardcoded URLs in `backend.py` and `script.js`.
- **Uploads folder:** Processed images are saved temporarily to `./uploads/` and source/mask files are deleted after processing.
- **JWT expiry:** Tokens expire after 72 hours (configurable via `JWT_EXPIRY_HOURS` in `backend.py`).
- **Inpaint radius:** Set to `10px` in `clean_image()`. Increase for larger stains.

---

## License

MIT — free to use and modify.
