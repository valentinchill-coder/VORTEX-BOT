# VORTEX BOT release validation

The GitHub Actions workflow runs the following checks on pushes and pull requests:

1. Compile every Python module with \`python -m compileall -q .\`.
2. Run the asynchronous SQLite tests with \`python -m unittest discover -s tests -v\`.

The database tests cover:
- user activity and profile counters;
- one reputation point per giver and target per UTC day;
- daily reward idempotency;
- wallet transfers and insufficient-balance protection.

## Telegram smoke test

After a successful Render deployment, verify in a test group:

- \`/start\` and \`/help\` open the inline menu;
- \`/profile\` and reply-based \`/profile\` show the correct member;
- reply-based \`/rep\` grants one daily reputation point;
- \`/toprep\` and \`/topactivity\` show leaderboards;
- \`/daily\`, \`/balance\`, reply-based \`/pay 50\`, and \`/topmoney\` work;
- \`/stats\` reports activity and moderation counters;
- moderation commands still work only for group administrators;
- anti-flood is active in groups and does not interfere with private chat.

## Storage note

The current Render Free web service uses an ephemeral filesystem. SQLite data can be lost when the service restarts or redeploys. Durable user balances, reputation, profiles, and warning history require persistent storage or an external database.


## Games smoke test

In a test group, verify:

- \`/games\` opens the game menu and its three game buttons;
- number game starts from the menu or \`/guessgame\`, accepts \`/guess 50\`, gives hints, ends after seven misses, and awards 10 points for a win;
- rock-paper-scissors buttons accept only the player who started that round, resolve once, and award 5 points for a win or 1 for a draw;
- quiz buttons accept only the player who received the question and resolve once, awarding 3 points for a correct answer;
- \`/topgames\` and the in-menu leaderboard show scores for the current group only;
- scores persist across bot restarts while the SQLite database file is retained.

Ongoing rounds are held in memory and are reset by a bot restart. Long-term game scores are stored in the \`game_stats\` SQLite table.
