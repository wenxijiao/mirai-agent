"""Shared UI constants: default server URL, injected scripts, theme CSS, palette."""

DEFAULT_SERVER_URL = "http://127.0.0.1:8000"

SCROLL_SCRIPT = """
(function(){
    function init(){
        var el=document.getElementById('msg-scroll');
        if(!el){setTimeout(init,300);return}
        new MutationObserver(function(){
            if(el.scrollHeight-el.scrollTop-el.clientHeight<250)
                el.scrollTop=el.scrollHeight;
        }).observe(el,{childList:true,subtree:true,characterData:true});
    }
    if(document.readyState==='loading')
        document.addEventListener('DOMContentLoaded',init);
    else init();
})();
"""

TEXTAREA_SCRIPT = """
(function(){
    function resolveTa(){
        var n=document.getElementById('chat-input');
        if(!n)return null;
        if(n.tagName&&n.tagName.toLowerCase()==='textarea')return n;
        return n.querySelector?n.querySelector('textarea'):null;
    }
    function setup(){
        var el=resolveTa();
        if(!el){setTimeout(setup,300);return}
        var composing=false;
        el.addEventListener('compositionstart',function(){composing=true});
        el.addEventListener('compositionend',function(){composing=false});
        el.addEventListener('keydown',function(e){
            if(e.key==='Enter'&&!e.shiftKey&&!composing&&!e.isComposing){
                e.preventDefault();
                setTimeout(function(){
                    var btn=document.getElementById('send-btn');
                    if(btn&&!btn.disabled)btn.click();
                },0);
            }
        });
        function resize(){
            el.style.height='auto';
            el.style.height=Math.min(el.scrollHeight,160)+'px';
        }
        el.addEventListener('input',resize);
    }
    if(document.readyState==='loading')
        document.addEventListener('DOMContentLoaded',setup);
    else setup();
})();
"""

# ``#chat-input`` may be a DebounceInput wrapper; the real control is the inner ``textarea``.
CHAT_INPUT_RESIZE_FOCUS_JS = (
    "var ta=(function(){var n=document.getElementById('chat-input');"
    "if(!n)return null;"
    "if(n.tagName&&n.tagName.toLowerCase()==='textarea')return n;"
    "return n.querySelector?n.querySelector('textarea'):null;}());"
    "if(ta){ta.style.height='auto';ta.style.height=Math.min(ta.scrollHeight,160)+'px';ta.focus();}"
)

CHAT_INPUT_RESET_HEIGHT_JS = (
    "var ta=(function(){var n=document.getElementById('chat-input');"
    "if(!n)return null;"
    "if(n.tagName&&n.tagName.toLowerCase()==='textarea')return n;"
    "return n.querySelector?n.querySelector('textarea'):null;}());"
    "if(ta){ta.style.height='auto';}"
)

_TIMER_POLL_JS = "new Promise(function(r){setTimeout(function(){r('poll')},3000)})"

# Monitor page: refresh topology + traces (Topology v2 light polling).
_MONITOR_POLL_JS = "new Promise(function(r){setTimeout(function(){r('m')},4500)})"

CUSTOM_CSS = """
:root{
    --bg-page:#ffffff;--bg-surface:#f8fafc;--bg-card:#ffffff;
    --bg-hover:#f1f5f9;--text-1:#0f172a;--text-2:#64748b;
    --text-3:#94a3b8;--border:#e2e8f0;--border-hover:#cbd5e1;
    --accent-soft:#eef2ff;--error-bg:#fef2f2;
    --code-bg:#1e293b;--tool-bg:#f1f5f9;--tool-text:#64748b;
    --heading:#1e293b;--shadow-sm:0 1px 2px rgba(0,0,0,.04);
    --shadow-md:0 2px 8px rgba(0,0,0,.06);
}
.dark{
    --bg-page:#09090b;--bg-surface:#111113;--bg-card:#18181b;
    --bg-hover:#1c1c1f;--text-1:#f4f4f5;--text-2:#a1a1aa;
    --text-3:#52525b;--border:#27272a;--border-hover:#3f3f46;
    --accent-soft:#1e1b4b;--error-bg:#451a1a;
    --code-bg:#111113;--tool-bg:#1c1c1f;--tool-text:#a1a1aa;
    --heading:#e4e4e7;--shadow-sm:0 1px 2px rgba(0,0,0,.2);
    --shadow-md:0 2px 8px rgba(0,0,0,.3);
}
*{box-sizing:border-box}
body{font-family:'Inter',system-ui,-apple-system,sans-serif;-webkit-font-smoothing:antialiased}
@keyframes cursor-blink{0%,50%{opacity:1}51%,100%{opacity:0}}
.cursor-blink{display:inline-block;animation:cursor-blink 1s step-end infinite;margin-left:2px}
.msg-actions{opacity:0;transition:opacity .15s}
.msg-row:hover .msg-actions{opacity:1}
#chat-input,#chat-input textarea{font-family:'Inter',system-ui,-apple-system,sans-serif}
#chat-input textarea{
    border-color:var(--border)!important;
    box-shadow:var(--shadow-sm)!important;
    transition:border-color .15s,box-shadow .15s!important;
}
#chat-input textarea:focus{
    border-color:#6366f1!important;
    box-shadow:0 0 0 3px rgba(99,102,241,.12)!important;
}
#chat-input textarea:disabled{opacity:.5;cursor:not-allowed}
#chat-input textarea::placeholder{color:var(--text-3)}
::-webkit-scrollbar{width:6px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
::-webkit-scrollbar-thumb:hover{background:var(--border-hover)}
"""

SB_BG = "#0f172a"
SB_HOVER = "#1e293b"
SB_TEXT = "#94a3b8"
SB_TEXT_HI = "#f1f5f9"
SB_BORDER = "#1e293b"
ACCENT = "#6366f1"
