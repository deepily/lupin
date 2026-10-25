---
capability: admin-time-formatter
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.html.auth.admin.js.admin-time.formatRelativeTime@cb9ecd7238
---
# Admin relative-time formatter

`formatRelativeTime` is the one relative-time function of the admin pages. It is a global of a plain script, so a page must load `admin-time.js` before the script that calls it. It replaced two identical copies in [[proxy-trust-dashboard]] and [[proxy-ratify-page]].

## Output
- A falsy input gives the dash character. A future time, or one under 60 seconds old, gives `just now`.
- Under an hour it gives `Nm ago`, under a day `Nh ago`, under seven days `Nd ago`. At seven days or older it gives the locale date string.

## Don't
- Don't snapshot a table that shows it without fixing the clock. Every branch except the date moves between runs. The visual test normalizes both admin tables first.
