const crypto = require("crypto");

const WORKFLOW = "pickem-refresh.yml";
const DEFAULT_REPO = "watercam/cfb-pickem";
const DEFAULT_REF = "main";

exports.handler = async (event) => {
  const expected = String(process.env.PICKEM_REFRESH_SECRET || "");
  const provided = String((event.queryStringParameters || {}).token || "");
  if (!expected || !safeEqual(provided, expected)) {
    return page(401, "Refresh not authorized", "This link needs the shared refresh token.");
  }
  const githubToken = String(process.env.GITHUB_DISPATCH_TOKEN || "");
  if (!githubToken) {
    return page(500, "Refresh not configured", "Set GITHUB_DISPATCH_TOKEN on the Netlify site.");
  }
  const repo = String(process.env.GITHUB_REPOSITORY || DEFAULT_REPO);
  const ref = String(process.env.PICKEM_REFRESH_REF || DEFAULT_REF);
  const url = `https://api.github.com/repos/${repo}/actions/workflows/${WORKFLOW}/dispatches`;
  const response = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${githubToken}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "Content-Type": "application/json",
      "User-Agent": "cfb-pickem-refresh",
    },
    body: JSON.stringify({ ref }),
  });
  if (response.status === 204) {
    return page(
      200,
      "Refresh started",
      `Queued the same GitHub Action as the schedule (${WORKFLOW} on ${repo}). Slack and the dashboard will show the same Updated stamp and run id when it finishes.`
    );
  }
  const detail = escapeHtml(await response.text());
  return page(502, "GitHub dispatch failed", `HTTP ${response.status}: ${detail}`);
};

function safeEqual(left, right) {
  const a = Buffer.from(left);
  const b = Buffer.from(right);
  if (a.length !== b.length) {
    return false;
  }
  return crypto.timingSafeEqual(a, b);
}

function page(statusCode, title, message) {
  return {
    statusCode,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
    },
    body: `<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>${escapeHtml(title)}</title></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;max-width:40rem;margin:2rem auto;padding:0 1rem;line-height:1.45">
  <h1>${escapeHtml(title)}</h1>
  <p>${escapeHtml(message)}</p>
  <p><a href="/">Open dashboard</a></p>
</body>
</html>`,
  };
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
