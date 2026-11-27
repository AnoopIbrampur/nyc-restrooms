# Phase 3 audit protocol

You'll check 200 NYC places (plus reserves if needed) and record, for each, whether a member of the public can use a restroom there. This is the test set for the restroom model, so **consistency matters more than speed.**

## The three answers
| Code | Meaning |
|---|---|
| `free` | Anyone can walk in and use it without buying anything |
| `customers` | Only customers, patrons or patients. Includes "if you buy something", "for guests", a posted "customers only" sign, a key or code you get after a purchase |
| `none` | No restroom, or employees/staff only |

Unsure between two? Use the more restrictive one (`none` beats `customers`, and `customers` beats `free`), and write why in `notes`.

## How to check
1. **Phone** (number in the sheet, or look the place up by name and address). Script:
   > "Hi, quick question: does your location have a restroom that customers can use? … And could someone use it without buying anything?"
   - "Yes, for customers": `customers`
   - "Yes, anyone can": `free`
   - "No" or "employees only": `none`
2. **Visit** if there's no number, or nobody answers after 2 calls on different days or times. Look for a restroom sign or ask staff the same two questions. A posted "restrooms for customers only" sign means `customers`, whatever staff say.
3. **Don't use** online reviews, Google Maps attributes or websites as the answer. They're stale and are the kind of data the model is trained to fill in.

## When you can't get an answer
| Situation | `outcome` | What happens |
|---|---|---|
| Answered | `answered` | Fill in `answer` |
| 2 calls on different days, no answer, can't visit | `no_answer` | Use the next reserve for that group |
| Permanently closed / doesn't exist at that address | `closed` | Use the next reserve for that group |
| Place exists but refused to say | `refused` | Use the next reserve for that group |

Reserves **must be used in the listed order** (`reserve_rank` 1, 2, 3, …) within the same group. Never skip one or pick a convenient one.

## Columns to fill
`outcome`, `answer`, `method` (`phone` / `visit`), `checked_on` (YYYY-MM-DD), `notes`.

Don't edit any other column.
