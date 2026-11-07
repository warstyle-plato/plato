/* Shared transport: the document job survives a dropped HTTP connection. */
(() => {
  'use strict';
  window.PlatoDocumentClient = {
    async read(payload) {
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
          result = await fetch('/agent/result/' + encodeURIComponent(start.trace_id), { cache: 'no-store' });
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
