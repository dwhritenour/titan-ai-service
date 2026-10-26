# e21 Search Criteria and Operators — How-To Guide
Owner: Dave · System: e21 (ERP) · Updated: 2026-09-17

## What this guide is for
How to filter and search in e21 screens using its operators — relational comparisons, ranges, wildcards, and alternation. Questions like "how do I search a range of order numbers in e21?" or "what does the pipe symbol do in an e21 search?" answer from here.

**Character-field gotcha:** in character fields, lowercase letters sort GREATER than uppercase letters, and both sort greater than numbers. Keep that in mind with `>` / `<` on text columns.

## Relational operators
Entered IN FRONT of the field value:

- `>` — greater than the specified value
- `<` — less than the specified value
- `>=` — greater than or equal to
- `<=` — less than or equal to
- `<>` — not equal to (less than AND greater than)
- `=` — equal to the value; `=` on its own also matches a BLANK field

## Range operator
- `:` — a specific range of values; entered BETWEEN the range values. Example: `1000:2000` finds everything from 1000 through 2000.

## Wildcards
- `*` — wildcard comparison on character fields; entered AFTER the value. Example: `YS61*` matches everything starting with YS61.
- `?` — matches a pattern where the number of characters is fixed; enter one `?` per unknown character. Example: `YS6?` matches YS61, YS62, …

## Alternation operator
- `|` — either/or. Example: searching a last-name field for `Jones | Wilson` returns rows with either name.

## Placement summary
- `:` goes **between** the two range values
- `*` goes **after** the value
- `?` replaces **one character each** inside the value
- All other symbols (`>` `<` `>=` `<=` `<>` `=`) go **in front of** the value
