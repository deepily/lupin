---
capability: timestamps-clock-and-dm-word-count
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.utils.edt_timestamp.format_edt_timestamp@0b2abf3db7
  - cosa.utils.edt_timestamp.format_outreach_ts@3334fdcfcc
  - cosa.utils.edt_timestamp.is_already_stamped@1e3153252f
  - cosa.utils.edt_timestamp.resolve_tz@8fb01f1025
  - cosa.utils.edt_timestamp.split_leading_stamp@18f546ec90
  - cosa.utils.dm_text.dm_word_count@78c72de502
  - cosa.utils.util.get_current_date@3f0f1939c1
  - cosa.utils.util.get_current_datetime@5823c3bf3d
  - cosa.utils.util.get_current_datetime_iso@ac31ca5a50
  - cosa.utils.util.get_current_datetime_raw@eb7bad529b
  - cosa.utils.util.get_current_time@b562121a3f
  - cosa.utils.util.get_timestamp_ms@37b56f36a1
---
# Time stamps, clock helpers and direct message word counts

`edt_timestamp`, `dm_text` and the clock helpers in `cosa.utils.util`. See also [[shared-utilities]].

## What it does
- `edt_timestamp.resolve_tz( name )` returns `( ZoneInfo, None )`, or `( UTC, error text )` for an unknown name. The default is `America/New_York`.
- `format_outreach_ts( dt, tz )` gives `2026.06.24 at 18:44:09`. `format_edt_timestamp( dt=None, tz_name=None )` wraps that in brackets.
- `is_already_stamped( text )` and `split_leading_stamp( text )` recognise that bracketed shape at the start of a string, allowing one leading space.
- `dm_text.dm_word_count( text )` is `len( text.split() )`. `WORD_COUNT_VERSION` is 1.
- `get_current_datetime_raw( tz_name="US/Eastern", days_offset=0 )` returns an aware datetime. `get_current_datetime` and `get_current_datetime_iso` format it.
- `get_current_date( return_prose, offset )` and `get_current_time( include_timezone, format )` format the date or time.
- `get_timestamp_ms()` returns the local naive `datetime.now()` with microseconds cut to milliseconds.

## Don't
- Do not read `get_timestamp_ms` as Eastern time. It uses the host's local clock and carries no timezone.
- Do not call `dm_word_count` with None. It raises `AttributeError`.
- Do not treat a bracket like `[URGENT]` as a stamp. Only `[YYYY.MM.DD at HH:MM:SS]` at the start matches.

## Invariants
- `format_edt_timestamp` and `resolve_tz` never raise on a bad zone name. The stamp is then in UTC and carries no marker, because two readers parse its shape. `format_edt_timestamp` names the bad zone once on stderr.
- The stamp has no zone abbreviation. `get_current_datetime` has no `days_offset`: only `get_current_datetime_raw` and `get_current_date` take one.
