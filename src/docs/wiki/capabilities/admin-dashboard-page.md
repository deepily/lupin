---
capability: admin-dashboard-page
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.html.admin.js.admin-dashboard.AdminDashboard@812636d1c8
---
# Admin dashboard page

`AdminDashboard` is the script of the admin landing page. It guards the page and shows the signed-in email. It builds itself once the page has loaded, and uses the globals of [[auth-token-handling]].

## What it does
- The constructor finds the `userEmail` and `logoutBtn` elements and calls `init`. `init` runs `checkAuth` and then `setupEventListeners`.
- `checkAuth` sends a visitor without a token to `/app/auth/login`. It then loads the user with `getCurrentUser`, and clears the tokens and redirects if that gives nothing.
- A user without the `admin` role gets an alert and goes to `/app/auth/profile`. Any error clears the tokens and redirects to login.
- `displayUserInfo` writes the email into the `userEmail` element when both exist.
- `setupEventListeners` binds the logout button to `handleLogout`, which clears the tokens and goes to the login page. It does not call the logout endpoint.

## Don't
- Don't rely on this check for security. It runs in the browser, and the server must enforce the admin role.
