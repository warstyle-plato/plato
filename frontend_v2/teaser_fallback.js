(() => {
  'use strict';

  const primaryFetch = window.fetch.bind(window);

  function requestPath(input) {
    const raw = typeof input === 'string' ? input : String((input && input.url) || '');
    try { return new URL(raw, location.href).pathname; } catch (error) { return raw; }
  }

  async function parsedClone(response) {
    try { return await response.clone().json(); } catch (error) { return null; }
  }

  async function localFallback(body) {
    return primaryFetch('/api/v2/teaser-fallback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      cache: 'no-store',
      body: JSON.stringify({
        filename: body.filename || '',
        content_b64: body.content_b64 || '',
      }),
    });
  }

  // /agent/document intentionally remains the primary parser: it understands
  // arbitrary project documents and asks clarifying questions. A broker teaser
  // with explicit labels must not become unusable, however, merely because the
  // LLM provider returned 5xx or malformed JSON. In that case a narrow local
  // parser copies only labelled source values (КН, площадь, стоимость, СПП/ГНС)
  // and still requires the user's normal checkbox confirmation before apply.
  window.fetch = async function developAidTeaserFallback(input, init) {
    const options = init || {};
    const method = String(options.method || 'GET').toUpperCase();
    if (requestPath(input) !== '/agent/document' || method !== 'POST' || !options.body) {
      return primaryFetch(input, init);
    }

    let body = null;
    try { body = JSON.parse(options.body); } catch (error) { return primaryFetch(input, init); }

    // The second /agent/document call applies an already reviewed extraction.
    // Never intercept it: document_intake.apply_intake is authoritative there.
    if (!body || body.accept || !body.content_b64) return primaryFetch(input, init);

    let response;
    try {
      response = await primaryFetch(input, init);
    } catch (error) {
      const fallback = await localFallback(body);
      if (fallback.ok) return fallback;
      throw error;
    }

    // Authentication/validation failures are not parser failures and must not
    // be bypassed by the local route.
    if (!response.ok && response.status < 500) return response;

    if (!response.ok) {
      const fallback = await localFallback(body);
      return fallback.ok ? fallback : response;
    }

    const parsed = await parsedClone(response);
    const hasFields = parsed && Array.isArray(parsed.fields) && parsed.fields.length > 0;
    const parserRefused = parsed && !hasFields && Boolean(parsed.reason);
    if (!parserRefused) return response;

    const fallback = await localFallback(body);
    return fallback.ok ? fallback : response;
  };
})();
