# 🚀 Production Deployment Guide

## Quick Setup: Render + Vercel (FREE!)

### Part 1: Deploy API to Render (5 minutes)

1. **Go to [render.com](https://render.com)** and sign up (free)
2. **Click "New +" → "Blueprint"**
3. **Connect your GitHub repo**: `Dotan-Peleh/hs-automation`
4. **Render auto-detects** `render.yaml` and creates:
   - Web service (API)
   - Worker service
   - PostgreSQL database

5. **Set environment variables** in Render dashboard:
   ```
   HS_CLIENT_ID=your_helpscout_client_id
   HS_CLIENT_SECRET=your_helpscout_client_secret
   HS_WEBHOOK_SECRET=your_webhook_secret
   HS_API_TOKEN=your_api_token (if using PAT)
   ```

6. **Copy your API URL**: `https://hs-trends-api.onrender.com`

### Part 2: Deploy Dashboard to Vercel (2 minutes)

1. **Go to [vercel.com](https://vercel.com)** and sign up (free)
2. **Import project** → Select GitHub repo: `Dotan-Peleh/hs-automation`
3. **IMPORTANT - Configure Project:**
   - Framework Preset: **Next.js**
   - Root Directory: **`dashboard`** (click "Edit" and type `dashboard`)
   - Build Command: Leave default (`npm run build`)
   - Output Directory: Leave default (`.next`)

4. **Before clicking Deploy**, go to **Environment Variables** section:
   - Click "Add New"
   - Key: `NEXT_PUBLIC_API_BASE`
   - Value: `https://hs-trends-api.onrender.com` (or your Render URL from Part 1)
   - Select: Production, Preview, Development

5. **Click "Deploy"** → Your dashboard will be at `https://your-project.vercel.app`

**Note:** If you see the secret error, just delete any environment variable entries in Vercel and re-add them through the UI.

### Part 3: Update Help Scout Webhook

1. Go to Help Scout → Manage → Apps → Webhooks
2. Update callback URL to: `https://hs-trends-api.onrender.com/helpscout/webhook`
3. Save

## ✅ Done! Your Dashboard is Live

- **Dashboard**: https://your-project.vercel.app/dashboard
- **API**: https://hs-trends-api.onrender.com
- **Health Check**: https://hs-trends-api.onrender.com/healthz

## 🧠 Automatic Learning System

Your dashboard now **learns automatically**:

1. **You correct a tag** → Saved to database
2. **System extracts patterns** → Builds rules
3. **Next similar ticket** → Auto-tagged correctly!
4. **No manual work needed** → Just keep correcting when you see mistakes

Check learning status: `https://hs-trends-api.onrender.com/admin/learning/stats`

## 🔥 Performance Benefits

**Render Free Tier:**
- Cold start: 30-60 seconds (first request after idle)
- After warmed up: Fast responses (< 500ms)

**Vercel:**
- Edge network: Ultra-fast (< 100ms globally)
- No cold starts for dashboard

**Much faster than localhost** because:
- ✅ No Docker overhead
- ✅ Global CDN for dashboard
- ✅ Optimized build pipeline
- ✅ Professional infrastructure

## 💾 Database Migrations

On first deploy, Render will:
1. Create PostgreSQL database
2. Run migrations automatically
3. Schema ready to use

Your feedback data migrates automatically!

## 🎯 Cost

**Total: $0/month (Free Tier)**

- Render Web Service: Free (750 hours/month)
- Render PostgreSQL: Free (90 days, then $7/month)
- Vercel: Free forever for hobby projects

After 90 days, upgrade Render DB for $7/month or switch to another free PostgreSQL provider.

