"""Anonymous Spotify metadata scraper using SEO SSR and OEmbed."""

import asyncio
import re

import aiohttp
from loguru import logger


class SpotifyScraper:
    _session: aiohttp.ClientSession | None = None

    @classmethod
    async def _get_session(cls) -> aiohttp.ClientSession:
        if cls._session is None or cls._session.closed:
            cls._session = aiohttp.ClientSession()
        return cls._session

    @classmethod
    async def extract_queries(cls, url: str) -> tuple[str, list[str]]:
        """
        Extracts playlist name and track titles (including artists) from a Spotify URL using server-side rendered SEO tags.
        Bypasses the Web API and Premium restrictions.
        Returns: (playlist_name, list_of_search_queries)
        """
        session = await cls._get_session()
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
        }

        playlist_name = "Spotify Import"
        try:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    logger.error("Failed to fetch Spotify HTML: HTTP {}", resp.status)
                    return playlist_name, []
                html = await resp.text()

            # Extract playlist/album name
            import html as html_lib

            title_match = re.search(r'<meta property="og:title" content="(.*?)"', html)
            if title_match:
                playlist_name = (
                    html_lib.unescape(title_match.group(1))
                    .replace("&#183;", "·")
                    .replace("&middot;", "·")
                )

            track_urls = re.findall(r'<meta name="music:song" content="(.*?)"', html)

            # If it's a single track, it might not have the music:song array
            if not track_urls and "track/" in url:
                track_urls = [url]

            if not track_urls:
                logger.warning("No tracks found in Spotify URL: {}", url)
                return playlist_name, []

            logger.info("Discovered {} tracks via Spotify SSR.", len(track_urls))

            # Limit to 200
            track_urls = track_urls[:200]

            # Use a semaphore to prevent IP blocks from Spotify
            sem = asyncio.Semaphore(15)

            async def fetch_track_meta(track_url: str) -> str | None:
                async with sem:
                    for attempt in range(3):
                        try:
                            # Use a timeout so it doesn't hang forever on bad Windows sockets
                            timeout = aiohttp.ClientTimeout(total=10)
                            async with session.get(
                                track_url, headers=headers, timeout=timeout
                            ) as tr_resp:
                                if tr_resp.status == 200:
                                    tr_html = await tr_resp.text()
                                    t_match = re.search(
                                        r'<meta property="og:title" content="(.*?)"', tr_html
                                    )
                                    d_match = re.search(
                                        r'<meta property="og:description" content="(.*?)"', tr_html
                                    )

                                    t_val = html_lib.unescape(t_match.group(1)) if t_match else None
                                    d_val = html_lib.unescape(d_match.group(1)) if d_match else None

                                    if t_val and d_val:
                                        # Extract artist (usually before the first " · " or " - ")
                                        d_val = d_val.replace("&#183;", "·").replace(
                                            "&middot;", "·"
                                        )
                                        artist_segment = d_val.split("·")[0].split("-")[0].strip()
                                        return f"{t_val} {artist_segment}"
                                    elif t_val:
                                        return t_val
                                elif tr_resp.status in (429, 500, 502, 503, 504):
                                    # Rate limit or server error - wait and retry
                                    await asyncio.sleep(2**attempt)
                                    continue
                                else:
                                    break  # Other HTTP error, don't retry
                        except TimeoutError:
                            logger.debug("Timeout fetching {}, attempt {}", track_url, attempt + 1)
                            await asyncio.sleep(1)
                        except Exception as e:
                            logger.debug(
                                "Track meta fetch failed for {} (attempt {}): {}",
                                track_url,
                                attempt + 1,
                                e,
                            )
                            await asyncio.sleep(1)
                    return None

            tasks = [fetch_track_meta(t) for t in track_urls]
            results = await asyncio.gather(*tasks)

            queries = [q for q in results if q]
            logger.info("Successfully resolved {} track queries from Spotify.", len(queries))
            return playlist_name, queries

        except Exception as e:
            logger.error("Spotify extraction failed: {}", e)
            return playlist_name, []

    @classmethod
    async def close(cls):
        if cls._session and not cls._session.closed:
            await cls._session.close()
