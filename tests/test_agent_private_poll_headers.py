"""The rendered long-poll UI sends credentials in headers, never in a URL."""
from playwright.sync_api import sync_playwright

from tests import browser
import main as wrapper


def test_rendered_result_and_trace_poll_keep_the_current_credentials():
    with browser.serve(wrapper.app, 18391) as url:
        with sync_playwright() as playwright:
            instance = playwright.chromium.launch(executable_path=str(browser.chromium_or_skip()))
            page = instance.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded")
                result = page.evaluate("""async () => {
                  projectsAdminKey='synthetic-admin-header';
                  localStorage.setItem('developaid_web_session','synthetic-signed-session');
                  const calls=[];let results=0;
                  window.fetch=async (url, options) => {
                    calls.push({url:String(url),headers:options.headers,cache:options.cache});
                    if(String(url).includes('/agent/result/')){
                      results++;
                      return {ok:true,json:async()=>results===1?{pending:true}:{answer:'own result',pending:false}};
                    }
                    return {ok:true,json:async()=>({stage:'working',label:'Own work'})};
                  };
                  const answer=await awaitAgentResult('0123456789abcdef0123456789abcdef',null,true);
                  return {answer,calls};
                }""")
            finally:
                instance.close()
    assert result["answer"]["answer"] == "own result"
    assert any("/agent/trace/" in call["url"] for call in result["calls"])
    for call in result["calls"]:
        if not any(route in call["url"] for route in ("/agent/result/", "/agent/trace/")):
            continue
        assert call["headers"]["X-Plato-Session"] == "synthetic-signed-session"
        assert call["headers"]["X-Developaid-Admin-Key"] == "synthetic-admin-header"
        assert call["cache"] == "no-store"
        assert "synthetic-admin-header" not in call["url"]
        assert "synthetic-signed-session" not in call["url"]
