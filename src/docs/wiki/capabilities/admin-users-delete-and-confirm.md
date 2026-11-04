---
capability: admin-users-delete-and-confirm
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.html.auth.admin.js.admin-users.confirmDeleteUser@25b472d782
  - src.lupin_app.static.html.auth.admin.js.admin-users.closeDeleteConfirmModal@ebffe70a9c
  - src.lupin_app.static.html.auth.admin.js.admin-users.validateDeleteConfirmation@7fda139df7
  - src.lupin_app.static.html.auth.admin.js.admin-users.submitDeleteUser@791263a747
  - src.lupin_app.static.html.auth.admin.js.admin-users.showConfirmDialog@b383a22ff2
  - src.lupin_app.static.html.auth.admin.js.admin-users.confirmYes@6f11655221
  - src.lupin_app.static.html.auth.admin.js.admin-users.closeConfirmModal@61d1d4712c
  - src.lupin_app.static.html.auth.admin.js.admin-users.confirmBatchDelete@2b73e6de6f
  - src.lupin_app.static.html.auth.admin.js.admin-users.closeBatchDeleteModal@957687bc0b
  - src.lupin_app.static.html.auth.admin.js.admin-users.validateBatchDeleteConfirmation@e99fe642f0
  - src.lupin_app.static.html.auth.admin.js.admin-users.submitBatchDelete@a1008f567d
---
# Admin users: deletion and confirmation

The delete dialogs and the shared yes-or-no dialog of the admin users script. Deletion is permanent, so both kinds make the person type a phrase first.

## One user
- `confirmDeleteUser` shows the target email, clears the typed text and disables the confirm button. `validateDeleteConfirmation` enables it only when the trimmed text equals the email.
- `submitDeleteUser` sends the delete with the reason "Admin UI deletion", shows a message, forgets the user and reloads. `closeDeleteConfirmModal` closes the dialog and brings the detail panel back.

## Many users
- `confirmBatchDelete` does nothing with no selection. It lists the emails of selected users on the current page and "User ID: <id>" for selected users elsewhere.
- `validateBatchDeleteConfirmation` enables the button only when the trimmed text is `DELETE`.
- `submitBatchDelete` posts the ids to `/admin/users/batch-delete` with a reason. The message gives the deleted and failed counts and each failure's text. Any failure shows as an error. It then closes, clears the selection and reloads.
- `closeBatchDeleteModal` only hides the dialog and keeps the selection.

## Yes or no
- `showConfirmDialog( message, callback )` hides the detail panel, shows the message and keeps the callback. `confirmYes` runs the callback once, then closes. `closeConfirmModal` hides the dialog and brings the detail panel back when a user is set.
