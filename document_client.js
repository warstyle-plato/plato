/* Shared transport: the document job survives a dropped HTTP connection. */
(() => {
  'use strict';
  const unavailable = 'Модель обновляется. Подтверждение действия сейчас недоступно. Обновите страницу и повторно проверьте данные.';
  function contract() {
    const value = window.PlatoDocumentProtocol;
    if (!value || value.schema !== 1 || typeof value.protocol !== 'string' || !value.protocol) throw new Error(unavailable);
    return value;
  }
  function matches(value) {
    const expected = contract();
    return value && typeof value === 'object' && !Array.isArray(value)
      && Object.keys(value).sort().join(',') === 'protocol,schema'
      && value.schema === 1 && value.protocol === expected.protocol;
  }
  async function available() {
    try {
      const response = await fetch(contract().capabilityPath, {cache: 'no-store'});
      const value = await response.json().catch(() => null);
      if (!response.ok || !matches(value)) throw new Error(unavailable);
    } catch (error) { throw new Error(unavailable); }
  }
  function binding(card, payload) {
    if (!card || typeof card.id !== 'string' || card.id !== payload.intake_id
        || !Number.isSafeInteger(card.queue_revision) || card.queue_revision < 0
        || typeof card.question_token !== 'string' || !/^[0-9a-f]{64}$/.test(card.question_token)) {
      throw new Error(unavailable);
    }
  }
  async function post(path, payload) {
    await available();
    const response = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload), cache: 'no-store'});
    if ([404, 405, 501].includes(response.status)) throw new Error(unavailable);
    const data = await response.json().catch(() => null);
    if (response.ok && (!data || !matches(data.document_protocol))) throw new Error(unavailable);
    if (response.status === 409 && data && data.detail && data.detail.code === 'intake_queue_changed'
        && !matches(data.detail.document_protocol)) throw new Error(unavailable);
    return {response, data: data || {}};
  }
  window.PlatoDocumentClient = {
    async answer(card, payload) {
      binding(card, payload);
      if (payload.queue_revision !== card.queue_revision || payload.question_token !== card.question_token) throw new Error(unavailable);
      return post(contract().answerPath, payload);
    },
    async apply(card, payload) {
      binding(card, payload);
      if (card.ready !== true || typeof card.card_key !== 'string' || !/^[0-9a-f]{64}$/.test(card.card_key)
          || payload.card_key !== card.card_key) throw new Error(unavailable);
      return post(contract().applyPath, payload);
    },
    async sessionData(payload) {
      return post(contract().sessionPath, payload);
    },
    async read(payload) {
      await available();
      const pollHeaders = {
        'x-plato-session': payload.session || '',
        'x-developaid-admin-key': payload.access_key || '',
      };
      const response = await fetch('/agent/document/start', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload), cache: 'no-store',
      });
      const start = await response.json();
      if (!response.ok) throw new Error(start.detail || 'Не удалось начать разбор документа.');
      const deadline = Date.now() + 10 * 60 * 1000;
      let failures = 0;
      while (Date.now() < deadline) {
        await new Promise(resolve => setTimeout(resolve, 1000));
        let result, state;
        try {
          result = await fetch('/agent/result/' + encodeURIComponent(start.trace_id), { cache: 'no-store', headers: pollHeaders });
          state = await result.json();
        } catch (error) {
          if (++failures > 5) throw new Error('Связь прервалась. Разбор продолжает выполняться на сервере. Повторите загрузку позднее.');
          continue;
        }
        if (!result.ok) throw new Error(state.detail || 'Не удалось получить результат разбора.');
        if (state.pending) continue;
        if (state.error) throw new Error(state.error);
        return state;
      }
      throw new Error('Разбор не завершился за отведённое время. Пришлите нужные страницы отдельно.');
    },
  };
})();
