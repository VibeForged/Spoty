/**
 * PO-token refresh sidecar for the Lavalink youtube-source plugin.
 *
 * YouTube blocks anonymous requests from datacenter IPs (e.g. Hugging Face
 * Spaces) unless they carry a "Proof of Origin" (PO) token. This process
 * generates a fresh poToken + visitorData (browserless, via BotGuard) and
 * pushes them to Lavalink's `POST /youtube` runtime endpoint, then repeats on
 * an interval so the token never goes stale. No login / no cookies required.
 *
 * Started by launcher.py once Lavalink is healthy. It is non-critical: if it
 * dies, Lavalink keeps running (just without a fresh token).
 *
 * Env:
 *   LAVALINK_HOST            (default 127.0.0.1)
 *   LAVALINK_PORT            (required)
 *   LAVALINK_PASSWORD        (default youshallnotpass)
 *   YOUTUBE_POT_REFRESH_HOURS(default 6)
 */

import { BG } from 'bgutils-js';
import { JSDOM } from 'jsdom';
import { Innertube } from 'youtubei.js';

const HOST = process.env.LAVALINK_HOST || '127.0.0.1';
const PORT = process.env.LAVALINK_PORT;
const PASSWORD = process.env.LAVALINK_PASSWORD || 'youshallnotpass';
const REFRESH_HOURS = Number(process.env.YOUTUBE_POT_REFRESH_HOURS || '6');

// YouTube web client request key (well-known public constant used by BotGuard).
const REQUEST_KEY = 'O43z0dpjhgX20SCx4KAo';

const RETRY_MS = 5 * 60 * 1000; // back off 5 min after a failed cycle
const REFRESH_MS = Math.max(1, REFRESH_HOURS) * 60 * 60 * 1000;

function log(msg) {
  console.info(`[potoken] ${msg}`);
}

function logErr(msg) {
  console.error(`[potoken] ${msg}`);
}

/** Generate a fresh { poToken, visitorData } using BotGuard, no browser. */
async function generateToken() {
  const innertube = await Innertube.create({ retrieve_player: false });
  const visitorData = innertube.session.context.client.visitorData;
  if (!visitorData) throw new Error('could not obtain visitorData from Innertube');

  // BotGuard expects a DOM; JSDOM provides one without a real browser.
  const dom = new JSDOM();
  Object.assign(globalThis, { window: dom.window, document: dom.window.document });

  const bgConfig = {
    fetch: (input, init) => fetch(input, init),
    globalObj: globalThis,
    identifier: visitorData,
    requestKey: REQUEST_KEY,
  };

  const challenge = await BG.Challenge.create(bgConfig);
  if (!challenge) throw new Error('could not create BotGuard challenge');

  const interpreterJs =
    challenge.interpreterJavascript.privateDoNotAccessOrElseSafeScriptWrappedValue;
  if (!interpreterJs) throw new Error('could not load BotGuard VM');
  new Function(interpreterJs)();

  const result = await BG.PoToken.generate({
    program: challenge.program,
    globalName: challenge.globalName,
    bgConfig,
  });

  if (!result?.poToken) throw new Error('BotGuard returned no poToken');
  return { poToken: result.poToken, visitorData };
}

/** Push the token to Lavalink's youtube-source plugin without a restart. */
async function pushToLavalink({ poToken, visitorData }) {
  const url = `http://${HOST}:${PORT}/youtube`;
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: PASSWORD,
    },
    body: JSON.stringify({ poToken, visitorData }),
  });
  // youtube-source returns 204 No Content on success.
  if (res.status !== 204 && !res.ok) {
    throw new Error(`Lavalink POST /youtube returned HTTP ${res.status}`);
  }
}

async function cycle() {
  const token = await generateToken();
  await pushToLavalink(token);
  log(
    `pushed fresh poToken to Lavalink (visitorData ${token.visitorData.slice(0, 12)}…); ` +
      `next refresh in ${REFRESH_HOURS}h`,
  );
}

async function main() {
  if (!PORT) {
    logErr('LAVALINK_PORT is not set; refusing to start');
    process.exit(1);
  }
  log(`starting — target http://${HOST}:${PORT}/youtube, interval ${REFRESH_HOURS}h`);

  // Loop forever: on success wait REFRESH_MS, on failure retry sooner.
  for (;;) {
    let waitMs = REFRESH_MS;
    try {
      await cycle();
    } catch (err) {
      waitMs = RETRY_MS;
      logErr(`cycle failed: ${err?.message || err}; retrying in ${RETRY_MS / 60000}min`);
    }
    await new Promise((resolve) => setTimeout(resolve, waitMs));
  }
}

main();
