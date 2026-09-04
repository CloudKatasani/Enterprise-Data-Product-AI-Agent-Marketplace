import { apiBaseUrl } from '@/lib/env';
import { BAD_GATEWAY } from '@/lib/http-status';

/**
 * Same-origin proxy for the answer stream.
 *
 * The browser cannot reach the API directly — it is server-side configuration,
 * not a public address — so the pulse stream comes through here. The proxy
 * forwards the body untouched and adds nothing: no identity, no filtering, no
 * enrichment. Anything the hero should not show has already not been sent,
 * because the endpoint behind this serves an unauthenticated visitor by design.
 *
 * If the stream is unavailable the response says so rather than hanging. The
 * ticker's rule is that a dead channel hides the band, and a request that never
 * resolves is how a band ends up frozen instead.
 */
export const dynamic = 'force-dynamic';

export async function GET(request: Request): Promise<Response> {
  const upstream = `${apiBaseUrl()}/events/stream`;
  try {
    const response = await fetch(upstream, {
      signal: request.signal,
      headers: { accept: 'text/event-stream' },
      cache: 'no-store',
    });
    if (!response.ok || response.body === null) {
      return new Response('the answer stream is unavailable', { status: BAD_GATEWAY });
    }
    return new Response(response.body, {
      headers: {
        'content-type': 'text/event-stream',
        'cache-control': 'no-store',
        connection: 'keep-alive',
      },
    });
  } catch {
    return new Response('the answer stream is unavailable', { status: BAD_GATEWAY });
  }
}
