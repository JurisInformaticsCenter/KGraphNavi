// 実行中の表示: フォームの送信（検索・適用）やリンクで次のページを待っている間、
// 画面の上端に「実行しています…（経過秒数）」を表示し、押したボタンを「検索中…」などにする。
(function () {
    "use strict";

    var bar = null;
    var timer = null;

    function start(message) {
        if (bar) {
            return;
        }
        document.body.classList.add("kg-busy");
        bar = document.createElement("div");
        bar.className = "kg-busy-bar";
        bar.setAttribute("role", "status");
        bar.setAttribute("aria-live", "polite");
        bar.innerHTML = '<span class="kg-spinner" aria-hidden="true"></span><span class="kg-busy-text"></span>';
        document.body.appendChild(bar);
        var text = bar.querySelector(".kg-busy-text");
        var started = Date.now();
        function tick() {
            var seconds = Math.floor((Date.now() - started) / 1000);
            text.textContent = message + (seconds >= 2 ? "（" + seconds + "秒）" : "");
        }
        tick();
        timer = window.setInterval(tick, 1000);
    }

    function reset() {
        if (timer) {
            window.clearInterval(timer);
            timer = null;
        }
        if (bar) {
            bar.remove();
            bar = null;
        }
        document.body.classList.remove("kg-busy");
        document.querySelectorAll("[data-kg-label]").forEach(function (button) {
            button.innerHTML = button.dataset.kgLabel;
            button.classList.remove("kg-busy-button");
            delete button.dataset.kgLabel;
        });
        document.querySelectorAll("form[data-kg-busy]").forEach(function (form) {
            delete form.dataset.kgBusy;
        });
    }

    var BUTTON_TEXT = { "検索": ["検索中…", "検索しています…"], "適用": ["適用中…", "絞り込んでいます…"] };

    document.addEventListener("submit", function (event) {
        var form = event.target;
        if (event.defaultPrevented || form.target === "_blank") {
            return;
        }
        if (form.dataset.kgBusy) {
            event.preventDefault(); // 二重送信を防ぐ
            return;
        }
        form.dataset.kgBusy = "1";
        var button = event.submitter || form.querySelector('button[type="submit"], button:not([type])');
        var label = button ? button.textContent.trim() : "";
        var texts = BUTTON_TEXT[label] || ["実行中…", "実行しています…"];
        if (button && button.tagName === "BUTTON") {
            button.dataset.kgLabel = button.innerHTML;
            button.innerHTML = '<span class="kg-spinner" aria-hidden="true"></span>' + texts[0];
            button.classList.add("kg-busy-button");
        }
        start(texts[1]);
    });

    document.addEventListener("click", function (event) {
        if (event.defaultPrevented || event.button !== 0 ||
            event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
            return;
        }
        var link = event.target.closest ? event.target.closest("a[href]") : null;
        if (!link || link.hasAttribute("download") || (link.target && link.target !== "_self")) {
            return;
        }
        var href = link.getAttribute("href");
        if (!href || href.charAt(0) === "#" || /^(javascript|mailto|tel):/i.test(href)) {
            return;
        }
        var url = new URL(link.href, window.location.href);
        if (url.origin !== window.location.origin || url.pathname.indexOf("/data/") === 0) {
            return; // 他のサイトや判決文書のファイルは待たない
        }
        if (url.pathname === window.location.pathname && url.search === window.location.search) {
            return; // 同じページ内の移動
        }
        start("読み込んでいます…");
    });

    // 戻るボタンでキャッシュから表示されたときは、実行中の表示を消す
    window.addEventListener("pageshow", function (event) {
        if (event.persisted) {
            reset();
        }
    });
})();
