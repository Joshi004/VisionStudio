# Sound bite test script: notes

`script.txt` is a short test explainer for the video evidence (sound bite) feature. It holds only spoken words: about 100 words, so roughly 35 to 45 seconds with both clips.

It has two sound bites. Each is a famous line from a commencement speech that the university posted on its own YouTube channel, so the agent should find an official upload with English captions.

## The two sound bites

| Claim (mark exactly this, quotation marks included) | Speaker (type this) | Event | Expected clip |
|---|---|---|---|
| `"Your time is limited, so don't waste it living someone else's life."` | Steve Jobs | Stanford commencement, 12 June 2005 | about 4 s |
| `"If you want to change the world, start off by making your bed."` | William H. McRaven | University of Texas at Austin commencement, 17 May 2014 | about 4 s |

The script is written to pass the app's sound bite rules:
- each quote is a whole sentence in double quotation marks;
- each lead-in ends with a colon;
- the speaker is named before the quote;
- the lead-in doesn't repeat the quote's words;
- there is no filler such as "here's what he said".

So "Make sound bite" should show no warnings.

**Not checked by me against the videos.** I am confident of the wording, but I did not watch the clips. The speaker may add a word, for example McRaven may say "So," before the line. That should still grade as `exact` or `near`, which can both be accepted. I also expect the uploads to be on the official Stanford and UT Austin channels, but the agent has to confirm that.

## How to run the test

1. Create a **continuous explainer** project with evidence switched on, and paste `script.txt` as its script.
2. In the evidence claims, select each quote above (from the opening to the closing quotation mark). Choose **Make sound bite** and type the speaker's name.
3. Press **Write the brief**. Copy the round folder path and the prompt that the evidence panel shows.
4. Open that folder in Cursor or Claude Code and paste the prompt. The agent should search YouTube, capture each clip with the capture tool, run `validate` and start the import.
5. In the app, wait for both clips to say they were heard (Parakeet transcription).
6. Review each clip, then press **Review done** and carry on to the render.

## What to check

**Research and capture**
- Both claims are `found`, with a `video` piece from the official channel.
- The recording date, role and venue are filled in (they appear on the lower third).

**Review card**
- The grade is `Exact words` or `Nearly the same words`.
- The proposed cut is about 4 s, and the player plays only the quote.
- The lower third reads, for example, "Steve Jobs" and then the role and venue with "June 2005".

**Cut buttons (SB-017)**
- Press **Start earlier** a few times: the cut grows and the length updates.
- Keep going past 15 s: Accept is blocked, with the reason shown.
- Press **Back to the proposed cut**, then **Start later** until the cut is under 3 s: Accept is blocked again.
- Go back to a good cut, press **Accept**, then move the cut again: **Save new cut** appears.

**Clip note (SB-017)**
- After Accept, the card shows "Why this clip: Official channel (...), 4.x s excerpt, used with commentary, licence: ..., words: exact."

**Risky flags (SB-017)**
- These two clips will probably have no risky flag, so the red box and the "Are you sure?" step may not appear.
- If one does appear (for example `channel_not_publisher` because the agent used a re-upload), Accept should ask once more before saving.

**Render**
- The narrator stops after each lead-in, the clip plays with its own sound, and the narrator carries on.
- Captions show the speaker's own words.
- The description lists both sources, with links that start at the right second (`?t=`).

**Fallback**
- Reject one clip and tick **No proof on screen**. The narrator then reads that quote, and the lead-in still sounds complete.
