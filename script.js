/**
 * =============================================
 * NAVIGATION
 * =============================================
 */
function toggleNav(e) {
    if (e) e.preventDefault();
    const nav = document.getElementById("side-nav");
    const main = document.getElementById("main-content");
    const isOpen = nav.classList.contains("open");
    nav.classList.toggle("open", !isOpen);
    main.classList.toggle("nav-shifted", !isOpen);
}

/**
 * =============================================
 * LOGIN MODAL
 * =============================================
 */
function openLoginModal() {
    document.getElementById("login-modal").style.display = "flex";
}

function closeLoginModal() {
    document.getElementById("login-modal").style.display = "none";
}

function closeModalOnOverlay(e) {
    if (e.target === document.getElementById("login-modal")) {
        closeLoginModal();
    }
}

function switchTab(tab, btn) {
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach(c => c.style.display = "none");
    btn.classList.add("active");
    document.getElementById("tab-" + tab).style.display = "flex";
}

/**
 * =============================================
 * CANVAS & DRAWING
 * =============================================
 */
const imageInput = document.getElementById("image-upload");
const editorArea = document.getElementById("editor-area");
const imageCanvas = document.getElementById("imageCanvas");
const maskCanvas = document.getElementById("maskCanvas");
const imgCtx = imageCanvas.getContext("2d");
const maskCtx = maskCanvas.getContext("2d");

let currentFile = null;
let drawing = false;
let brushSize = 25;

// Drag-and-drop support
const uploadZone = document.getElementById("upload-zone");
uploadZone.addEventListener("dragover", e => { e.preventDefault(); uploadZone.classList.add("drag-over"); });
uploadZone.addEventListener("dragleave", () => uploadZone.classList.remove("drag-over"));
uploadZone.addEventListener("drop", e => {
    e.preventDefault();
    uploadZone.classList.remove("drag-over");
    const file = e.dataTransfer.files[0];
    if (file) loadFile(file);
});

// Brush size control
document.getElementById("brush-size").addEventListener("input", function () {
    brushSize = parseInt(this.value);
});

// File picker
imageInput.addEventListener("change", function () {
    if (this.files[0]) loadFile(this.files[0]);
});

function loadFile(file) {
    if (!file.type.match(/image\/(jpeg|png)/)) {
        alert("Only JPG and PNG images are accepted.");
        return;
    }
    if (file.size > 10 * 1024 * 1024) {
        alert("File size must be under 10MB.");
        return;
    }

    currentFile = file;
    const img = new Image();
    img.src = URL.createObjectURL(file);
    img.onload = () => {
        imageCanvas.width = maskCanvas.width = img.naturalWidth;
        imageCanvas.height = maskCanvas.height = img.naturalHeight;

        imgCtx.drawImage(img, 0, 0);
        maskCtx.clearRect(0, 0, maskCanvas.width, maskCanvas.height);

        // Show UI elements
        editorArea.style.display = "block";
        document.getElementById("instructions").style.display = "flex";
        document.getElementById("brush-controls").style.display = "flex";
        document.getElementById("process-btn").style.display = "inline-flex";
        document.getElementById("upload-zone").style.display = "none";
    };
}

function clearMask() {
    maskCtx.clearRect(0, 0, maskCanvas.width, maskCanvas.height);
}

/**
 * Get scaled coordinates accounting for CSS-vs-internal resolution
 */
function getPos(e) {
    const rect = maskCanvas.getBoundingClientRect();
    const scaleX = maskCanvas.width / rect.width;
    const scaleY = maskCanvas.height / rect.height;
    const clientX = e.touches ? e.touches[0].clientX : e.clientX;
    const clientY = e.touches ? e.touches[0].clientY : e.clientY;
    return {
        x: (clientX - rect.left) * scaleX,
        y: (clientY - rect.top) * scaleY,
        scale: scaleX
    };
}

function startDraw(e) {
    e.preventDefault();
    drawing = true;
    const { x, y } = getPos(e);
    maskCtx.beginPath();
    maskCtx.moveTo(x, y);
}

function draw(e) {
    e.preventDefault();
    if (!drawing) return;
    const { x, y, scale } = getPos(e);

    maskCtx.lineWidth = brushSize * scale;
    maskCtx.lineCap = "round";
    maskCtx.lineJoin = "round";
    maskCtx.strokeStyle = "rgba(255, 80, 80, 0.7)";

    maskCtx.lineTo(x, y);
    maskCtx.stroke();
    maskCtx.beginPath();
    maskCtx.moveTo(x, y);
}

function stopDraw(e) {
    e.preventDefault();
    drawing = false;
    maskCtx.beginPath();
}

// Mouse events
maskCanvas.addEventListener("mousedown", startDraw);
maskCanvas.addEventListener("mousemove", draw);
maskCanvas.addEventListener("mouseup", stopDraw);
maskCanvas.addEventListener("mouseleave", stopDraw);

// Touch events (mobile support)
maskCanvas.addEventListener("touchstart", startDraw, { passive: false });
maskCanvas.addEventListener("touchmove", draw, { passive: false });
maskCanvas.addEventListener("touchend", stopDraw, { passive: false });

/**
 * =============================================
 * MASK GENERATION — Correct pixel-level B&W conversion
 * CSS filters do NOT work on canvas context.
 * We must read each pixel manually.
 * =============================================
 */
async function getMaskForAPI() {
    const w = maskCanvas.width;
    const h = maskCanvas.height;

    const tempCanvas = document.createElement("canvas");
    tempCanvas.width = w;
    tempCanvas.height = h;
    const tCtx = tempCanvas.getContext("2d");

    // Black background
    tCtx.fillStyle = "black";
    tCtx.fillRect(0, 0, w, h);

    // Read pixels from the drawing canvas
    const srcData = maskCtx.getImageData(0, 0, w, h);
    const destData = tCtx.getImageData(0, 0, w, h);

    for (let i = 0; i < srcData.data.length; i += 4) {
        const alpha = srcData.data[i + 3]; // Alpha channel of red stroke
        if (alpha > 10) {
            // Painted pixel → white in the mask
            destData.data[i] = 255; // R
            destData.data[i + 1] = 255; // G
            destData.data[i + 2] = 255; // B
            destData.data[i + 3] = 255; // A
        }
        // else: stays black (already set)
    }

    tCtx.putImageData(destData, 0, 0);

    return new Promise(resolve => tempCanvas.toBlob(resolve, "image/png"));
}

/**
 * =============================================
 * SEND TO BACKEND
 * =============================================
 */
document.getElementById("process-btn").addEventListener("click", async function () {
    if (!currentFile) {
        alert("Please upload an image first.");
        return;
    }

    // Check if any mask has been drawn
    const srcData = maskCtx.getImageData(0, 0, maskCanvas.width, maskCanvas.height);
    const hasMask = srcData.data.some((v, i) => i % 4 === 3 && v > 10); // any non-transparent pixel
    if (!hasMask) {
        alert("Please paint over the areas you want to clean before processing.");
        return;
    }

    const btn = this;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Processing...';
    btn.disabled = true;

    try {
        const maskBlob = await getMaskForAPI();
        const formData = new FormData();
        formData.append("image", currentFile);
        formData.append("mask", maskBlob, "mask.png");

        const res = await fetch("http://localhost:5000/clean", {
            method: "POST",
            body: formData
        });

        if (!res.ok) {
            const errData = await res.json();
            throw new Error(errData.error || `Server error ${res.status}`);
        }

        const data = await res.json();

        if (data.result) {
            localStorage.setItem("resultUrl", data.result);
            window.location.href = "output.html";
        } else {
            throw new Error(data.error || "Processing failed with no result.");
        }

    } catch (err) {
        if (err.message.includes("Failed to fetch")) {
            alert("Cannot reach the server. Make sure your Python backend is running on port 5000.");
        } else {
            alert("Error: " + err.message);
        }
    } finally {
        btn.innerHTML = '<i class="fas fa-wand-magic-sparkles"></i> Process Now';
        btn.disabled = false;
    }
});

/**
 * =============================================
 * AUTH — Login / Register / Google / Logout
 * =============================================
 */
const API = 'http://127.0.0.1:5000';

// ── Token helpers ──────────────────────────────────────────────────────────
function saveToken(token) { localStorage.setItem('authToken', token); }
function getToken() { return localStorage.getItem('authToken'); }
function clearToken() { localStorage.removeItem('authToken'); }

// ── Update UI based on auth state ──────────────────────────────────────────
function updateAuthUI(user) {
    const loggedOut = document.getElementById('side-nav-logged-out');
    const loggedIn = document.getElementById('side-nav-logged-in');
    const headerBtn = document.getElementById('header-login-btn');

    if (user) {
        loggedOut.style.display = 'none';
        loggedIn.style.display = 'flex';
        headerBtn.style.display = 'none';
        document.getElementById('user-fullname').textContent = user.full_name;
        document.getElementById('user-email').textContent = user.email;
    } else {
        loggedOut.style.display = 'flex';
        loggedIn.style.display = 'none';
        headerBtn.style.display = 'inline-flex';
    }
}

// ── Show error inside modal ────────────────────────────────────────────────
function showModalError(id, msg) {
    const el = document.getElementById(id);
    el.textContent = msg;
    el.style.display = 'block';
}
function clearModalErrors() {
    ['login-error', 'signup-error'].forEach(id => {
        const el = document.getElementById(id);
        if (el) { el.textContent = ''; el.style.display = 'none'; }
    });
}
async function loadReEditImage() {
    const reEditUrl = localStorage.getItem("reEditUrl");
    if (!reEditUrl) return;

    // Clean up immediately so it doesn't re-trigger on future visits
    localStorage.removeItem("reEditUrl");

    try {
        // Fetch the image from the result URL and convert to a File object
        const response = await fetch(reEditUrl);
        if (!response.ok) throw new Error("Could not fetch image");

        const blob = await response.blob();
        const file = new File([blob], "reedit-image.png", { type: "image/png" });

        // Reuse your existing loadFile() function
        loadFile(file);
    } catch (err) {
        console.error("Re-edit load failed:", err);
        alert("Could not reload the image for re-editing. The server result may have expired.");
    }
}

loadReEditImage();
checkAuth();








// ── Check token on page load ───────────────────────────────────────────────
async function checkAuth() {
    // Handle Google OAuth redirect token in URL
    const params = new URLSearchParams(window.location.search);
    const urlToken = params.get('token');
    if (urlToken) {
        saveToken(urlToken);
        window.history.replaceState({}, '', window.location.pathname);
    }

    const token = getToken();
    if (!token) { updateAuthUI(null); return; }

    try {
        const res = await fetch(`${API}/auth/me`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if (res.ok) {
            const data = await res.json();
            updateAuthUI(data.user);
        } else {
            clearToken();
            updateAuthUI(null);
        }
    } catch {
        updateAuthUI(null);
    }
}

// ── Register ───────────────────────────────────────────────────────────────
async function submitRegister() {
    clearModalErrors();
    const full_name = document.getElementById('signup-name').value.trim();
    const email = document.getElementById('signup-email').value.trim();
    const password = document.getElementById('signup-password').value;

    if (!full_name || !email || !password) {
        showModalError('signup-error', 'All fields are required.'); return;
    }

    const btn = document.querySelector('#tab-signup .modal-submit-btn');
    btn.textContent = 'Creating account...';
    btn.disabled = true;

    try {
        const res = await fetch(`${API}/auth/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ full_name, email, password })
        });
        const data = await res.json();

        if (!res.ok) { showModalError('signup-error', data.error); return; }

        saveToken(data.token);
        updateAuthUI(data.user);
        closeLoginModal();
    } catch {
        showModalError('signup-error', 'Could not reach server. Is backend running?');
    } finally {
        btn.textContent = 'Create Account';
        btn.disabled = false;
    }
}

// ── Login ──────────────────────────────────────────────────────────────────
async function submitLogin() {
    clearModalErrors();
    const email = document.getElementById('login-email').value.trim();
    const password = document.getElementById('login-password').value;

    if (!email || !password) {
        showModalError('login-error', 'Email and password are required.'); return;
    }

    const btn = document.querySelector('#tab-login .modal-submit-btn');
    btn.textContent = 'Logging in...';
    btn.disabled = true;

    try {
        const res = await fetch(`${API}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        });
        const data = await res.json();

        if (!res.ok) { showModalError('login-error', data.error); return; }

        saveToken(data.token);
        updateAuthUI(data.user);
        closeLoginModal();
    } catch {
        showModalError('login-error', 'Could not reach server. Is backend running?');
    } finally {
        btn.textContent = 'Login';
        btn.disabled = false;
    }
}

// ── Logout ─────────────────────────────────────────────────────────────────
document.getElementById('logout-btn').addEventListener('click', function (e) {
    e.preventDefault();
    clearToken();
    updateAuthUI(null);
    // Close nav
    document.getElementById('side-nav').classList.remove('open');
    document.getElementById('main-content').classList.remove('nav-shifted');
});

// ── Clear errors when switching tabs ──────────────────────────────────────
const origSwitchTab = window.switchTab;
window.switchTab = function (tab, btn) {
    origSwitchTab(tab, btn);
    clearModalErrors();
};

// ── Boot ───────────────────────────────────────────────────────────────────
checkAuth();