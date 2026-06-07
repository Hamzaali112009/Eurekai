# EUREKAI — Free Public Access via Cloudflare Tunnel (No Account Needed!)

## Option 1: Cloudflare Tunnel (BEST — Free, Permanent URL, No Sign-up)

### Step 1: Download cloudflared
Open PowerShell as Administrator and run:
```powershell
# Download cloudflared
Invoke-WebRequest -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -OutFile "$env:TEMP\cloudflared.exe"
```

### Step 2: Start EUREKAI locally
In one terminal:
```cmd
cd C:\EUREKAI\eurekai_v5
python app.py
```

### Step 3: Create tunnel (in another terminal)
```powershell
# Run this in a NEW terminal while app.py is running
$env:TEMP\cloudflared.exe tunnel --url http://localhost:5000
```

You'll see output like:
```
Your quick Tunnel has been created! You can now access it at:
https://something-try-cloudflare.trycloudflare.com
```

**Anyone in the world** can now access your EUREKAI at that URL!

The URL changes each time you restart. For a **permanent URL**, run once:
```powershell
$env:TEMP\cloudflared.exe tunnel login
$env:TEMP\cloudflared.exe tunnel create eurekai
$env:TEMP\cloudflared.exe tunnel route dns eurekai yourname.eurekai.workers.dev
```

---

## Option 2: ngrok (Simplest)

### Step 1: Download ngrok
Go to https://ngrok.com/download and download ngrok for Windows.
Extract `ngrok.exe` to your Desktop.

### Step 2: Start EUREKAI
```cmd
cd C:\EUREKAI\eurekai_v5
python app.py
```

### Step 3: Create tunnel
```cmd
cd Desktop
ngrok.exe http 5000
```

You'll see:
```
Forwarding: https://abc123.ngrok-free.app -> http://localhost:5000
```

Share that URL! Free tier gives you random URLs that expire when you close ngrok.

---

## Option 3: PythonAnywhere (Truly Free Hosting)

### Step 1: Sign up
Go to https://www.pythonanywhere.com and create a free account.

### Step 2: Upload files
In the PythonAnywhere dashboard:
1. Go to **Files** tab
2. Create folder: `eurekai`
3. Upload all files from your `eurekai_v5` folder

### Step 3: Install dependencies
Go to **Consoles** → **Bash**:
```bash
cd eurekai
pip install flask mediapipe opencv-python numpy ultralytics --user
```

### Step 4: Create web app
1. Go to **Web** tab
2. Click **Add a new web app**
3. Select **Flask**
4. Python version: **3.10**
5. Path: `/home/yourusername/eurekai/app.py`

### Step 5: Configure
In the Web tab, set:
- **Source code**: `/home/yourusername/eurekai`
- **Working directory**: `/home/yourusername/eurekai`

Click **Reload** and your app will be live at `yourusername.pythonanywhere.com`!

**Limitations of free tier**: 512MB RAM (tight for YOLO), CPU limited, sleeps after inactivity.

---

## Comparison

| Method | Cost | Setup Time | URL Persistence | Best For |
|--------|------|-----------|----------------|----------|
| **Cloudflare Tunnel** | Free | 2 min | Permanent (with login) | Sharing with team/clients |
| **ngrok** | Free | 3 min | Temporary (changes each run) | Quick demos |
| **PythonAnywhere** | Free | 15 min | Permanent | 24/7 hosting (with limits) |

---

## Recommendation

**Use Cloudflare Tunnel** for now:
1. Free
2. No account needed for basic use
3. Works with your existing Windows setup
4. Public HTTPS URL in 2 minutes
5. All video processing happens on YOUR machine (no cloud costs)

Just share the tunnel URL with anyone who needs access!
