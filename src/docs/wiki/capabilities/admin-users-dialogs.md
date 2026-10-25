---
capability: admin-users-dialogs
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.html.auth.admin.js.admin-users.showUserDetails@508e68f19f
  - src.lupin_app.static.html.auth.admin.js.admin-users.closeUserModal@3648fc7419
  - src.lupin_app.static.html.auth.admin.js.admin-users.showRoleEditor@5e527a0d30
  - src.lupin_app.static.html.auth.admin.js.admin-users.closeRoleModal@74e5ff4288
  - src.lupin_app.static.html.auth.admin.js.admin-users.saveRoles@954c3d8e91
  - src.lupin_app.static.html.auth.admin.js.admin-users.confirmToggleStatus@b7bb4cc5a4
  - src.lupin_app.static.html.auth.admin.js.admin-users.confirmResetPassword@d64cdc2711
  - src.lupin_app.static.html.auth.admin.js.admin-users.showPasswordModal@f109ac85c0
  - src.lupin_app.static.html.auth.admin.js.admin-users.closePasswordModal@5f8c87e652
  - src.lupin_app.static.html.auth.admin.js.admin-users.copyPassword@051daa5cd2
  - src.lupin_app.static.html.auth.admin.js.admin-users.showCreateUserModal@d320ceaae9
  - src.lupin_app.static.html.auth.admin.js.admin-users.closeCreateUserModal@d943fc0deb
  - src.lupin_app.static.html.auth.admin.js.admin-users.submitCreateUser@eaf7f7d0fb
  - src.lupin_app.static.html.auth.admin.js.admin-users.showRoleEditorForUser@4124ae93be
  - src.lupin_app.static.html.auth.admin.js.admin-users.confirmToggleStatusForUser@db31a8051c
  - src.lupin_app.static.html.auth.admin.js.admin-users.confirmResetPasswordForUser@7f1cd5ccb7
  - src.lupin_app.static.html.auth.admin.js.admin-users.confirmDeleteUserForUser@40218f57ae
---
# Admin users: dialogs

The detail, role, status, password and create dialogs of the admin users script. They keep the user on screen in the script variables `currentUser` and `selectedUserId`. Deletion is on [[admin-users-delete-and-confirm]].

## Details and roles
- `showUserDetails` fetches the user and fills the detail panel: email, id, roles, verified, status, dates, audit log count and failed logins. `closeUserModal` closes it and forgets the user.
- `showRoleEditor` fills the role checkboxes from the user and swaps the detail panel for the editor. `closeRoleModal` brings the detail panel back.
- `saveRoles` refuses an empty choice, sends the roles, then closes both dialogs and reloads the current page.

## Status and password
- `confirmToggleStatus` asks first, saying a deactivated user is logged out at once. `confirmResetPassword` asks first, then shows the server's temporary password in a dialog and closes the detail panel.
- `showPasswordModal` and `closePasswordModal` open and close that dialog, and closing clears the password field. `copyPassword` copies it with `execCommand`.

## Create
- `showCreateUserModal` clears the form and ticks user only. `submitCreateUser` needs an email with an at sign, a password of at least 8 characters and one role, then creates the user and reloads. `closeCreateUserModal` closes it.

## Row buttons
- `showRoleEditorForUser`, `confirmToggleStatusForUser`, `confirmResetPasswordForUser` and `confirmDeleteUserForUser` fetch the user for the row, store it, and call the matching dialog function above.
