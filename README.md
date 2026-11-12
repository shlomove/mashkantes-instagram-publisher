# Mashkantes Instagram publisher

Dedicated automation for `eliran_mashkantes`. Facebook and Windsor are not used.

Status: implementation prepared, publication disabled until cloud verification and secret setup are complete.

## Public content only

This repository is public. Store only code, fonts under their license, and approved marketing content. Never include credentials, customer information, private documents, or personal financial data. The Instagram token belongs only in the encrypted Actions secret `IG_ACCESS_TOKEN`.

## Daily input

The existing content preparation worker writes `content/YYYY-MM-DD.json` after verifying the day's Woller sources. Dates use Asia/Jerusalem. The schema is demonstrated in `example.json`, which is not a scheduled input.

Formats: `image` has one slide, `carousel` has 2 to 10 slides, `reel` has 5 or 6 slides, each displayed for six seconds. Keep titles short and bodies under approximately 180 Hebrew characters per slide. The renderer rejects overflow and shows complete text from the first video frame. Reels are silent text videos, not generated avatars or voiceovers.

The caption is limited to 2,200 characters. Source URLs are audit evidence and are not added automatically to the public caption. `qa_passed` and `source_verified` are explicit attestations by the preparation worker, not automatic fact checking by this repository.

## Cloud execution

The workflow uses standard Ubuntu runners in a public repository, no paid runners, artifact uploads or cache. These runners are free according to https://docs.github.com/en/billing/concepts/product-billing/github-actions . It prepares on a content commit and checks publication at 7 and 37 minutes past UTC hours 12 to 15, Sunday to Thursday. Publishing is allowed only between 16:00 and 18:00 Asia/Jerusalem, with daylight saving handled by the time zone database. GitHub schedule timing is best effort.

The repository variable `IG_PUBLICATION_ENABLED` must be `true` before publishing. The default is disabled. No current approved input also means no publication. Only the repository owner or authorized writers should create daily input.

Rendered files are committed to `media/`. Their immutable public URLs and hashes are recorded in `prepared/`. Every publication stage is committed to `state/YYYY-MM-DD.json` before any corresponding Meta action. A claimed or uncertain record prevents automatic retries across workflow runs. Do not delete or overwrite it to retry. Inspect the actual Instagram account first.

The workflow is never triggered by pull requests or issue contents. The token is provided only to the publisher step. Normal publishing errors never print token values or raw Meta response bodies.

## Checks

Install `Pillow==11.3.0` and `python-bidi==0.6.7`. Video rendering also requires ffmpeg. Run `python -m unittest -v test_publisher test_cloud`.

The bundled Heebo fonts retain their original SIL Open Font License in `assets/OFL.txt`.
