# Production Deployment Guide - Daily Drill Report

## ✅ Your app is now production-ready!

This guide will help you deploy to **Render.com** (recommended - free PostgreSQL included).

---

## 🚀 Option 1: Deploy to Render.com (RECOMMENDED)

Render provides free PostgreSQL database and easy deployment.

### Step 1: Create Render Account
1. Go to https://render.com
2. Sign up with GitHub (recommended)

### Step 2: Push Code to GitHub
```powershell
# Initialize git (if not already done)
git init
git add .
git commit -m "Prepare for production deployment"

# Create repository on GitHub, then:
git remote add origin https://github.com/yourusername/dailydrillreport.git
git branch -M main
git push -u origin main
```

### Step 3: Create PostgreSQL Database on Render
1. In Render Dashboard, click **"New +"** → **"PostgreSQL"**
2. Name: `dailydrillreport-db`
3. Region: Choose closest to your users
4. Plan: **Free** (or Starter for production)
5. Click **"Create Database"**
6. **SAVE** the connection details (Internal Database URL)

### Step 4: Create Web Service
1. Click **"New +"** → **"Web Service"**
2. Connect your GitHub repository
3. Configure:
   - **Name**: `dailydrillreport`
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn DailyDrillReport.wsgi:application`
   - **Plan**: Free (or Starter for production)

### Step 5: Set Environment Variables
In the Render dashboard, go to **Environment** tab and add:

```
SECRET_KEY=your-super-secret-key-change-this-in-production-12345
DEBUG=False
ALLOWED_HOSTS=your-app-name.onrender.com
DB_ENGINE=django.db.backends.postgresql
DATABASE_URL=<paste-internal-database-url-from-step-3>
REDIS_URL=redis://red-xxxxx:6379/0
```

`REDIS_URL` is optional for single-instance development, but recommended in production if you want WebSocket updates to work reliably across restarts or multiple app instances. On Render, create a Redis service and copy its internal connection string here.

**Generate a secure SECRET_KEY:**
```python
# Run this locally to generate a key:
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### Step 6: Deploy
1. Click **"Create Web Service"**
2. Render will automatically:
   - Install dependencies
   - Run migrations
   - Collect static files
   - Start your app!

### Step 7: Create Superuser
After deployment, go to **Shell** tab in Render dashboard:
```bash
python manage.py createsuperuser
```

### Step 8: Access Your App
Your app will be live at: `https://your-app-name.onrender.com`

---

## 🌐 Option 2: Deploy to Railway.app

Railway also provides free PostgreSQL and is very simple.

### Step 1: Create Railway Account
1. Go to https://railway.app
2. Sign up with GitHub

### Step 2: Create New Project
1. Click **"New Project"**
2. Select **"Deploy from GitHub repo"**
3. Choose your repository

### Step 3: Add PostgreSQL
1. Click **"New"** → **"Database"** → **"Add PostgreSQL"**
2. Railway automatically sets `DATABASE_URL` variable

### Step 4: Set Environment Variables
Click on your web service → **Variables** tab:

```
SECRET_KEY=your-super-secret-key-change-this
DEBUG=False
ALLOWED_HOSTS=your-app.railway.app
DB_ENGINE=django.db.backends.postgresql
```

### Step 5: Deploy
Railway will automatically deploy. Access at: `https://your-app.railway.app`

---

## ☁️ Option 3: Deploy to Heroku

### Prerequisites
```powershell
# Install Heroku CLI
winget install Heroku.HerokuCLI

# Login
heroku login
```

### Deploy Commands
```powershell
# Create app
heroku create your-app-name

# Add PostgreSQL
heroku addons:create heroku-postgresql:essential-0

# Set environment variables
heroku config:set SECRET_KEY="your-secret-key"
heroku config:set DEBUG=False
heroku config:set ALLOWED_HOSTS="your-app-name.herokuapp.com"
heroku config:set DB_ENGINE="django.db.backends.postgresql"

# Deploy
git push heroku main

# Run migrations
heroku run python manage.py migrate

# Create superuser
heroku run python manage.py createsuperuser

# Open app
heroku open
```

---

## 📋 Environment Variables Reference

All platforms need these environment variables:

| Variable | Example | Required |
|----------|---------|----------|
| `SECRET_KEY` | `django-insecure-xyz...` | ✅ Yes |
| `DEBUG` | `False` | ✅ Yes |
| `ALLOWED_HOSTS` | `your-app.onrender.com` | ✅ Yes |
| `DB_ENGINE` | `django.db.backends.postgresql` | ✅ Yes |
| `DATABASE_URL` | `postgresql://user:pass@host:5432/db` | ✅ Yes (auto-set on Render/Railway) |

**Or individual database variables:**
```
DB_NAME=dailydrillreport
DB_USER=postgres
DB_PASSWORD=your_db_password
DB_HOST=your-db-host.com
DB_PORT=5432
```

---

## 🔐 Production Checklist

Before going live:

### Security
- [ ] Generate new `SECRET_KEY` (never use the default!)
- [ ] Set `DEBUG=False`
- [ ] Update `ALLOWED_HOSTS` with your domain
- [ ] Enable HTTPS (automatic on Render/Railway/Heroku)
- [ ] Review user permissions

### Database
- [ ] PostgreSQL database created
- [ ] Migrations run successfully
- [ ] Superuser created
- [ ] Test data backed up locally

### Static Files
- [ ] Static files collected (`python manage.py collectstatic`)
- [ ] WhiteNoise configured (already done ✅)
- [ ] CSS/JS loading correctly

### Media Files
- [ ] Media uploads directory configured
- [ ] Consider using cloud storage (AWS S3, Cloudinary) for uploaded images
- [ ] Core tray images uploaded successfully

### Testing
- [ ] Test user login/logout
- [ ] Test creating shifts
- [ ] Test drilling progress with images
- [ ] Test PDF export
- [ ] Test filters (date, status, hole number)
- [ ] Test 24-hour combined view
- [ ] Test on mobile devices

---

## 📦 Post-Deployment: Migrating Existing Data

If you have existing data in SQLite, migrate it to production PostgreSQL:

### Option A: Use the migration script
```powershell
# 1. Set production database credentials in .env
# 2. Run migration script
python migrate_to_pg.py
```

### Option B: Manual migration via Render/Railway Shell
```bash
# Load your backup files
python manage.py loaddata users_backup.json
python manage.py loaddata accounts_backup.json
python manage.py loaddata core_backup.json
```

---

## 🎯 Recommended: Render.com Setup

**Why Render?**
- ✅ Free PostgreSQL database (1GB)
- ✅ Auto-deploys from GitHub
- ✅ Free SSL certificates
- ✅ Easy environment variables
- ✅ Good free tier (750 hours/month)
- ✅ No credit card required for free tier

**Complete Render Setup (5 minutes):**

1. **Create account**: https://render.com (use GitHub login)
2. **Create PostgreSQL**: New+ → PostgreSQL → Free plan
3. **Create Web Service**: New+ → Web Service → Connect GitHub repo
4. **Set env vars** (from Step 5 above)
5. **Deploy** (automatic)
6. **Create admin**: Shell tab → `python manage.py createsuperuser`

**Done!** Your app is live at: `https://dailydrillreport-xxxx.onrender.com`

---

## 🆘 Troubleshooting

### Fly.io build fails with mise invalid gzip header

If your Fly.io deployment or local mise install fails with errors like:

```
mise failed to extract tar ... .tar.zst
mise failed to iterate over archive
mise invalid gzip header
```

This is caused by broken or incompatible precompiled Python binaries (zstd compressed) from indygreg/python-build-standalone. Fix by pinning Python and forcing source compilation:

1) Pin Python version in `runtime.txt` to a supported release (use 3.12.12 for best compatibility):

```
python-3.12.12
```

2) Add or update `.mise.toml` to force compilation:

```
[tools]
python = "3.12.12"

[settings]
python_compile = true
```

Commit and push, then redeploy on Fly or rerun `mise use -g python@3.12.12` locally. Compilation is slower but avoids the broken prebuilt extraction step.

### Static files not loading
```bash
# In Render/Railway shell
python manage.py collectstatic --noinput
```

### Database connection error
- Check `DATABASE_URL` environment variable
- Verify PostgreSQL database is running
- Check database credentials

### 500 Internal Server Error
- Set `DEBUG=True` temporarily to see error details
- Check logs in hosting platform dashboard
- Verify all environment variables are set

### Images not displaying
- Check `MEDIA_ROOT` and `MEDIA_URL` settings
- Consider using AWS S3 or Cloudinary for production media files
- Verify media folder has write permissions

---

## 📞 Support

For deployment issues:
- **Render**: https://render.com/docs
- **Railway**: https://docs.railway.app
- **Heroku**: https://devcenter.heroku.com

---

## 🎉 You're Production Ready!

Your Daily Drill Report application is now configured for professional deployment with:
- ✅ PostgreSQL database
- ✅ Production security settings
- ✅ Static files optimized
- ✅ HTTPS/SSL ready
- ✅ Gunicorn production server
- ✅ Environment-based configuration

Choose a platform above and deploy! 🚀
