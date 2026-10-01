# Game server (Cloudflare Worker)

Holds the answers of the two decks, reveals each card only once it has been answered, times
the answers (hardcore timer) and keeps the top 10 of each mode. The top 10s are also committed
to `docs/data/leaderboard.json`. Free Cloudflare plan: Workers + one D1 database.

Until it is set up, the site still works: the answers stay sealed in the decks, and the
leaderboard shows "Le classement ouvre bientôt".

## One-time setup (about 10 minutes)

1. **Cloudflare account** (free): <https://dash.cloudflare.com/sign-up>. Your **Account ID** is
   shown on the right of the account home page (Workers & Pages).
2. **Cloudflare API token**: My Profile → API Tokens → Create Token → template
   "Edit Cloudflare Workers", then add the permission *Account → D1 → Edit*. Copy the token.
3. **GitHub token for the leaderboard file**: GitHub → Settings → Developer settings →
   Fine-grained tokens → Generate: repository access *Only select repositories* →
   `mtg-ai-or-not-ai`; permissions *Contents: Read and write*. Copy it.
4. **Repository secrets** (repo → Settings → Secrets and variables → Actions → Secrets):
   - `CLOUDFLARE_API_TOKEN`: token of step 2
   - `CLOUDFLARE_ACCOUNT_ID`: account id of step 1
   - `LEADERBOARD_GH_TOKEN`: token of step 3
   - `QUIZ_ADMIN_TOKEN`: any long random string you make up (shared by CI and the server)
5. **Deploy**: Actions → « Déployer le serveur de jeu » → Run workflow. The run's summary shows
   the Worker URL (`https://mtg-quiz.<your-subdomain>.workers.dev`).
6. **Repository variable** (same page, tab *Variables*): `QUIZ_API_URL` = that URL.
7. **Regenerate both decks** (« Générer les cartes », mode *normal*, then mode *hardcore*): from
   now on their answers go to the server and the leaderboards open.

## Endpoints

| | |
|---|---|
| `POST /start {mode}` | deals 10 cards → `{game, cards, limits}` (limits: hardcore timer per card, ms) |
| `POST /answer {game, index, answer}` | `answer`: `ai`, `real` or `timeout` → `{truth, correct, timeout, secret}` |
| `POST /result {game}` | finished game → `{score, total, ms, qualifies}` |
| `POST /submit {game, name}` | saves a top-10 result → `{entered, rank, leaderboard}` |
| `GET /leaderboard` | `{normal: [...], hardcore: [...]}` |
| `POST /admin/deck {mode, key}` | CI only (`Authorization: Bearer QUIZ_ADMIN_TOKEN`) |

Scores are computed on the server: correct answers, then total answering time (the
first 0.3 s of the verdict between cards are not counted). A hardcore answer later than the card's limit + 2.5 s counts
as wrong. Test: `python worker/test/smoke.py <url> <admin token>` (run in CI against `wrangler dev`).
