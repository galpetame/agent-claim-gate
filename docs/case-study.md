# Case study: an 83-page pack that reported success two pages too long

This is the run that the gate was written after. Names, amounts and the subject of the documents are left out. The counts are real.

## The job

A formal filing pack in two languages, to be printed in four sets and signed on almost every page. Python scripts assembled it from 37 photographs, e-mail printouts, statements and several generated documents. The pack existed in three layouts for different print budgets: 91, 83 and 72 pages. A coding agent ran the scripts and reported the result. I read the report on a phone.

Three properties had to hold before anything went to a print shop:

| Property | Why it matters |
|---|---|
| The page count is exactly the planned one | Every page carries a stamp "page N of total"; the index and the cross-references use those numbers |
| One total appears unchanged in every place it is quoted | Six documents in the pack repeat it |
| The number of signature places is known | 79 per set, 316 across four sets; a missed signature means a rejected page |

## What went wrong

**1. The build "succeeded" with two extra pages.** A new one-page document was added. In the first build, that page and one other each spilled a few lines onto a second sheet. The three layouts came out at 93, 85 and 74 pages. Nothing crashed. Every stamp now showed the wrong total, and the index pointed one or two pages off for everything after the insert. A page-count check caught it. The fix was typographic: a two-line signature block, a slightly smaller font on one translation, narrower margins on one page.

**2. A checklist kept going back to an old number.** The print checklist said 82 pages after the pack had been corrected. It was fixed by hand, and the next build put the old number back: the checklist was generated from a source file that still described the earlier layout, and each build overwrote the corrected copy. The output was right for a few minutes at a time.

**3. A report said more than had been checked.** After one rebuild the summary read as if the whole pack had been verified. What had been verified was the page count and the total. Whether the new text in the second language was correct had not been checked by anyone who reads it. That sentence was true only with a qualifier, and the qualifier was missing.

## What the gate does with each

`examples/pack/build.py` reproduces the three faults on a toy pack.

| Fault | Flag | Result |
|---|---|---|
| Two sections spill over | `--overflow` | `CONTRADICTED C-1 (counted 85, expected 83)` and `CONTRADICTED C-2`: no page carries a correct "N/83" stamp |
| Source newer than output | `--stale` | `STALE C-6: src/checklist.md changed after print/checklist.txt was produced: rebuild, then check again` |
| Report runs ahead | `--boast` | `REPORT line 8: says 'delivered' without citing a claim` |

The honest build passes with six verified claims and one estimate. The estimate is the printing cost, and the report has to call it an estimate.

## What I took from it

- The checks that mattered were all cheap: a count, a string that must appear six times, a string that must not appear. None needed a model.
- The expensive part was remembering to run them after every rebuild. A gate that fails the run does not forget.
- The hedged sentence is the useful one. "Verified: page count and total. Not verified: the translated text" tells the reader what to do next. The gate does not forbid uncertainty. It forbids hiding it.
