# Instructions for AI sessions in this repo

**Read `docs/CHECKPOINT.md` first.** It records what has been built, the key measured
numbers, what is pending, and the traps already hit. When you finish a meaningful piece
of work, add an entry to its checkpoint log and update its "Status sekarang" and
"Pekerjaan tertunda" sections before reporting back.

Standing rules (details and reasons are in the checkpoint):

- Do not commit or stage unless the user asks.
- Never add Claude/AI attribution to commits or PR descriptions.
- Never edit `data/ground_truth/*.xlsx` without the user's approval; log every correction
  in `data/ground_truth/CORRECTIONS.md`.
- Every number you report must come from a real run; say "not measured" otherwise.
- Do not work around Google API quotas with extra accounts or projects.
- The user writes in Indonesian; reply in Indonesian.
