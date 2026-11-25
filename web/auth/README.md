# Authentication Pages

Simple HTML + CSS + JavaScript authentication system for the Elbow Rehab doctor dashboard.

## Files

- **login.html** - Doctor login page
- **signup.html** - Doctor account creation page
- **styles.css** - Shared styling for all auth pages
- **auth.js** - Shared utility functions for authentication

## Features

✅ **Login Page**
- Email and password validation
- "Remember me" checkbox
- Error messages
- Smooth loading state

✅ **Signup Page**
- Email validation
- Password strength check (min 8 chars)
- Password confirmation
- Terms acceptance
- Real-time password match validation

✅ **Security**
- Client-side form validation
- Secure token storage in localStorage
- Auto-refresh expired tokens
- Redirect to login on unauthorized access

✅ **User Experience**
- Beautiful gradient background
- Smooth animations
- Error and success alerts
- Responsive design (mobile-friendly)

## Usage

### Direct Access

```
http://localhost:3000/auth/login.html
http://localhost:3000/auth/signup.html
```

### From JavaScript

```javascript
// Check if authenticated
if (isAuthenticated()) {
  // User is logged in
}

// Get user info
const doctor = getDoctorInfo();
console.log(doctor.doctor_id);

// Make API calls
apiCall('/api/patients')
  .then(data => console.log(data))
  .catch(error => console.error(error));

// Logout
logout();
```

## API Endpoints Required

### Login
```
POST /auth/login
Body: { email, password }
Response: { token, refreshToken, uid }
```

### Signup
```
POST /auth/signup
Body: { email, password }
Response: { message, doctor_id, warning? }
```

### Refresh Token (optional)
```
POST /auth/refresh
Body: { refreshToken }
Response: { token }
```

## Configuration

### Set Custom API URL

Option 1: Via URL parameter
```
http://localhost:3000/auth/login.html?api=https://api.example.com
```

Option 2: Programmatically
```javascript
setApiUrl('https://api.example.com');
```

Option 3: Default (localhost:8000)
```javascript
// No configuration needed, defaults to http://localhost:8000
```

## Error Handling

The auth system automatically handles:

- ❌ Invalid email format
- ❌ Weak passwords
- ❌ Password mismatch
- ❌ Network errors
- ❌ 401 Unauthorized (auto-refresh)
- ❌ Server errors (displays message)

## Data Storage

Uses `localStorage` to persist:

- `token` - JWT authentication token
- `refreshToken` - Token for refreshing expired tokens
- `doctor` - Doctor info (ID, email)
- `rememberEmail` - Saved email (if "remember me" checked)
- `apiUrl` - API base URL

## Integration with React Dashboard

The React dashboard (`../index.html`) automatically:

1. Checks for auth token
2. Redirects to login if missing
3. Uses stored token for API calls
4. Auto-refreshes expired tokens

No additional setup needed!

## Security Notes

⚠️ localStorage is readable by any script on the page
⚠️ For production, consider using httpOnly cookies
⚠️ Always use HTTPS in production
⚠️ Implement proper CORS on backend

## Customization

### Change Colors

Edit `styles.css`:
```css
:root {
  --primary-color: #3498db;      /* Your brand color */
  --danger-color: #e74c3c;       /* Error color */
  --success-color: #27ae60;      /* Success color */
}
```

### Change Logo

Edit HTML:
```html
<div class="app-logo">💪</div>  <!-- Change emoji or add image -->
```

### Modify Form Fields

Add fields to login.html or signup.html:
```html
<div class="form-group">
  <label for="phone">Phone Number</label>
  <input type="tel" id="phone" placeholder="555-1234" />
  <span class="error-message">Invalid phone</span>
</div>
```

## Troubleshooting

**Q: Login redirects to login again?**
A: Check that your backend is running on http://localhost:8000

**Q: Can't submit form?**
A: Check browser console for validation errors

**Q: Getting CORS error?**
A: Add CORS headers to your FastAPI backend

**Q: Forgot password link doesn't work?**
A: It's just a placeholder. Implement forgot password flow separately.

---

**Next Steps:**
1. Test login/signup locally
2. Implement backend endpoints
3. Deploy to production (use HTTPS)
4. Add password reset flow
5. Add 2FA for extra security
