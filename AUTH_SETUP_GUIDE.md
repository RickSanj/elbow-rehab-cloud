# Doctor Authentication - Setup Guide

A complete authentication system (login + signup) for the Elbow Rehab doctor dashboard using vanilla HTML, CSS, and JavaScript.

## 📁 What Was Created

```
web/
├── auth/                    ← 🆕 Authentication pages
│   ├── login.html          # Doctor login page
│   ├── signup.html         # Doctor signup page
│   ├── styles.css          # Shared styles
│   ├── auth.js             # Shared utilities
│   └── README.md           # Full documentation
├── index.html              # Main entry point (auth check)
├── public/
│   └── index.html          # React app entry
└── ...
```

## 🚀 Quick Start

### Option 1: Simple HTTP Server

```bash
cd web

# Using Python
python -m http.server 3000

# Or using Node.js
npx http-server -p 3000
```

Then open: **http://localhost:3000/auth/login.html**

### Option 2: With React Dashboard

```bash
cd web
npm install
npm start
```

React app opens at **http://localhost:3000**. Auth check is automatic.

## 📋 Features

### Login Page (`auth/login.html`)
✅ Email/password input
✅ Form validation
✅ "Remember me" checkbox (auto-fills email)
✅ Error messages
✅ Loading spinner during request
✅ Link to signup page

### Signup Page (`auth/signup.html`)
✅ Email validation
✅ Strong password check (min 8 chars)
✅ Password confirmation
✅ Real-time password match validation
✅ Terms acceptance checkbox
✅ Link to login page

### Shared JavaScript (`auth/auth.js`)
✅ Email validation
✅ Token management
✅ API calls with auth header
✅ Auto token refresh
✅ Error handling

## 🔌 API Integration

### Backend Endpoints Needed

Your FastAPI backend needs these endpoints:

#### 1. Login
```
POST /auth/login
Content-Type: application/json

{
  "email": "doctor@example.com",
  "password": "password123"
}

Response:
{
  "token": "eyJ...",
  "refreshToken": "eyJ...",
  "uid": "doctor_id_123"
}
```

#### 2. Signup
```
POST /auth/signup
Content-Type: application/json

{
  "email": "doctor@example.com",
  "password": "password123"
}

Response:
{
  "message": "Doctor created successfully",
  "doctor_id": "doctor_id_123",
  "warning": null
}
```

### Verify in Backend

Your backend already has these endpoints (from our earlier refactor):
- ✅ `/auth/signup` - POST
- ✅ `/auth/login` - POST
- ✅ `/auth/ping` - POST (token validation)

## 💾 Data Flow

### Login Flow
```
User enters email/password
         ↓
Client validates (email format, password length)
         ↓
POST /auth/login
         ↓
Backend validates Firebase + returns token
         ↓
localStorage.setItem('token', token)
         ↓
Redirect to dashboard
```

### Signup Flow
```
User enters email/password/confirmation
         ↓
Client validates (email, password match, terms)
         ↓
POST /auth/signup
         ↓
Backend creates Firebase user + doctor record
         ↓
User redirected to login page
         ↓
Login again with new credentials
```

## 🎨 Customization

### Change Colors

Edit `auth/styles.css`:
```css
:root {
  --primary-color: #3498db;      /* Blue button */
  --primary-dark: #2980b9;
  --danger-color: #e74c3c;       /* Red errors */
  --success-color: #27ae60;      /* Green success */
  --light-gray: #ecf0f1;
  --dark-gray: #34495e;
}
```

### Change Background

Edit `auth/styles.css` body:
```css
body {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  /* Change to your colors */
}
```

### Change Logo/Emoji

Edit login.html and signup.html:
```html
<div class="app-logo">💪</div>  <!-- Change emoji here -->
```

Or use an image:
```html
<img src="logo.png" alt="Logo" style="width: 48px; height: 48px;" />
```

## 🔒 Security Notes

### Current Implementation
- ✅ Form validation on client side
- ✅ Email format checking
- ✅ Password strength requirement
- ✅ Token stored in localStorage
- ✅ Auto-refresh expired tokens

### Production Improvements Needed
- ⚠️ Use HTTPS only
- ⚠️ Move tokens to httpOnly cookies (more secure)
- ⚠️ Add CSRF protection
- ⚠️ Implement rate limiting
- ⚠️ Add password reset flow
- ⚠️ Consider 2FA for doctors

### Backend CORS Setup

Make sure your FastAPI app allows requests:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://yourdomain.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## 📱 Responsive Design

- ✅ Mobile: 100% width with padding
- ✅ Tablet: Centered card (max 420px)
- ✅ Desktop: Same centered layout
- ✅ Touch-friendly buttons (48px minimum)

Test on mobile:
```
DevTools → Toggle device toolbar (Ctrl+Shift+M)
```

## 🧪 Testing

### Test Login
1. Open http://localhost:3000/auth/login.html
2. Enter: `doctor@example.com` / `password123`
3. Should redirect to dashboard or show error

### Test Signup
1. Open http://localhost:3000/auth/signup.html
2. Enter new email and password (min 8 chars)
3. Password must match confirmation
4. Should create account and redirect to login

### Test Validation
- Invalid email → "Invalid email" error
- Short password → "Min 8 characters" error
- Mismatched passwords → Error highlighted
- Missing terms → Can't submit

### Test Remember Me
1. Check "Remember me" on login
2. Close browser
3. Open login page again
4. Email should be auto-filled

## 🚨 Troubleshooting

**Q: CORS error when logging in?**
A: Add CORS headers to your FastAPI backend (see above)

**Q: Login fails but no error message?**
A: Check browser console (F12) for detailed error

**Q: Form keeps showing error?**
A: Check network tab to see API response

**Q: Tokens not persisting?**
A: Verify localStorage is enabled (not in private/incognito)

**Q: Can't see auth page?**
A: Make sure you're on http://localhost:3000/auth/login.html

## 📚 File Reference

### auth.js - Available Functions

```javascript
// Get/set API URL
getApiUrl()
setApiUrl(url)

// Check auth
isAuthenticated()
getAuthToken()
getRefreshToken()
getDoctorInfo()

// Logout
logout()

// API calls
apiCall('/endpoint', { method: 'POST', body: {} })

// Validation
isValidEmail(email)
validateField(fieldId, validator)
clearFormErrors(formId)

// Utility
formatErrorMessage(error)
```

## 🔄 Next Steps

1. ✅ Create HTML pages (DONE)
2. ✅ Add form validation (DONE)
3. ✅ Add styling (DONE)
4. ⏳ Test with backend API
5. ⏳ Deploy to production
6. ⏳ Add password reset
7. ⏳ Add 2FA

## 📞 Support

See `web/auth/README.md` for detailed documentation.

---

**Ready to test?** Run your backend and visit http://localhost:3000/auth/login.html 🚀
