---
capability: admin-users-api-and-table
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.html.auth.admin.js.admin-users.loadUsers@c509aca888
  - src.lupin_app.static.html.auth.admin.js.admin-users.getUserDetails@bb833719cb
  - src.lupin_app.static.html.auth.admin.js.admin-users.updateUserRoles@12471d6a2f
  - src.lupin_app.static.html.auth.admin.js.admin-users.toggleUserStatus@a6092763bf
  - src.lupin_app.static.html.auth.admin.js.admin-users.resetUserPassword@1a61d43863
  - src.lupin_app.static.html.auth.admin.js.admin-users.createUser@f52232f7c8
  - src.lupin_app.static.html.auth.admin.js.admin-users.deleteUser@429507af43
  - src.lupin_app.static.html.auth.admin.js.admin-users.renderUsersTable@373415f5fd
  - src.lupin_app.static.html.auth.admin.js.admin-users.getRoleBadges@cb5d63e8a1
  - src.lupin_app.static.html.auth.admin.js.admin-users.getStatusBadge@414704b3da
  - src.lupin_app.static.html.auth.admin.js.admin-users.getVerifiedBadge@9989de0c17
---
# Admin users: calls and table

`admin-users.js` is the script of the admin user-management page. It is a plain script of globals and needs `auth.js` ([[auth-token-handling]]). This page covers the server calls and the table. Paging, filters and selection are on [[admin-users-paging-and-selection]], dialogs on [[admin-users-dialogs]] and deletion on [[admin-users-delete-and-confirm]].

## Calls
- `loadUsers( page )` gets `/admin/users` with `limit` 50, an offset, and `search`, `role` and `status_filter` when set. Rows go to `renderUsersTable` and the pager, else the no-results panel shows. An error shows a message.
- `getUserDetails`, `updateUserRoles`, `toggleUserStatus`, `resetUserPassword`, `createUser` and `deleteUser` call `/admin/users/<id>`, its `/roles` (PUT), `/status` (PUT), `/reset-password` (POST), `/admin/users` (POST) and `/admin/users/<id>` (DELETE with a reason).
- Each shows an error message and rethrows, so a caller must catch.

## Table and badges
- `renderUsersTable` keeps the page's users and draws a row each. A row holds a checkbox, email, role badges, status, verified, created and last login (or "Never"). It ends with five icon buttons: view, roles, activate or deactivate, reset password and delete. A click on the row opens the details.
- `getRoleBadges` shows an admin badge for the `admin` role and a user badge for any other role or none. `getStatusBadge` shows Active or Inactive, and `getVerifiedBadge` shows Verified or "Not Verified".
