// パンくずリスト（履歴型。2026.11.9）
//   たどったページを sessionStorage（タブごと）の "kgTrail" に記録し、<nav class="kg-breadcrumb"> に表示する。
//   - 直前の段と data-key（パス＋対象を決める引数）が同じページ（絞り込み・ページ送り・タブの切り替え）は
//     段を増やさず、その段の URL を新しいものに置き換える
//   - 経路の途中のページと同じ URL に来たら（リンク・ブラウザの戻る）、そこより後ろの段を切り捨てる
//     （同じクラスでも条件の違う一覧へ別のページから移ったときは、新しい段にする）
//   - トップ（/）に来たら経路をはじめからにする（index.html）
//   - history.replaceState で URL が変わったとき（タブ、探索グラフの手順 #s=…）は今の段の URL も更新する
(function () {
    "use strict";
    var STORE = "kgTrail";
    var KEEP = 30;      // 記録する段の数
    var SHOW = 8;       // 表示する段の数（超えたら途中を「…」にまとめる）
    var nav = document.querySelector("nav.kg-breadcrumb");
    if (!nav) { return; }
    var list = nav.querySelector("ol.kg-crumbs");
    var expanded = false;

    function load() {
        try {
            var v = JSON.parse(window.sessionStorage.getItem(STORE) || "[]");
            return Array.isArray(v) ? v : [];
        } catch (e) { return []; }
    }
    function save(trail) {
        try { window.sessionStorage.setItem(STORE, JSON.stringify(trail)); } catch (e) {}
    }
    function strip(url) {
        // 戻ったかの判定では #… と tab（タブの選択）を区別しない
        var u = new URL(url, location.origin);
        u.hash = "";
        u.searchParams.delete("tab");
        return u.pathname + u.search;
    }
    function here() {
        return location.pathname + location.search + location.hash;
    }

    var current = {
        key: nav.dataset.key,
        url: here(),
        title: nav.dataset.title || document.title || location.pathname,
        kind: nav.dataset.kind || "",
        mark: nav.dataset.mark || ""
    };

    function record() {
        var trail = load().filter(function (c) { return c && c.key && c.url; });
        var last = trail[trail.length - 1];
        if (last && last.key === current.key) {
            trail.pop();                        // 同じ対象のまま（絞り込み・ページ送り）: 今の段を置き換える
        } else {
            var url = strip(current.url);
            for (var i = trail.length - 1; i >= 0; i--) {
                if (strip(trail[i].url) === url) {
                    trail = trail.slice(0, i);  // 経路の途中のページに戻った: そこより後ろを切り捨てる
                    break;
                }
            }
        }
        trail.push(current);
        if (trail.length > KEEP) { trail = trail.slice(trail.length - KEEP); }
        save(trail);
        return trail;
    }

    function item(crumb, isCurrent) {
        var li = document.createElement("li");
        li.className = "kg-crumb kg-crumb-" + (crumb.kind || "other") + (isCurrent ? " kg-crumb-current" : "");
        if (crumb.mark) {
            var mark = document.createElement("span");
            mark.className = "kg-crumb-mark";
            mark.textContent = crumb.mark;
            li.appendChild(mark);
        }
        var label;
        if (isCurrent) {
            label = document.createElement("span");
            label.setAttribute("aria-current", "page");
        } else {
            label = document.createElement("a");
            label.href = crumb.url;
        }
        label.className = "kg-crumb-label";
        label.textContent = crumb.title;
        label.title = crumb.title;
        li.appendChild(label);
        return li;
    }

    function render(trail) {
        list.textContent = "";
        var home = document.createElement("li");
        home.className = "kg-crumb kg-crumb-home";
        var a = document.createElement("a");
        a.href = "/";
        a.className = "kg-crumb-label";
        a.textContent = "トップ";
        home.appendChild(a);
        list.appendChild(home);
        var shown = trail.map(function (c, i) { return {crumb: c, index: i}; });
        if (!expanded && trail.length > SHOW) {
            // 最初の1段と最後の SHOW-2 段を出し、あいだは「…」（クリックで全部出す）
            var hidden = trail.length - (SHOW - 1);
            var more = document.createElement("li");
            more.className = "kg-crumb kg-crumb-more";
            var b = document.createElement("button");
            b.type = "button";
            b.textContent = "…";
            b.title = "ほかに " + hidden + " 件。クリックですべて表示";
            b.addEventListener("click", function () { expanded = true; render(load()); });
            more.appendChild(b);
            shown = [shown[0], null].concat(shown.slice(trail.length - (SHOW - 2)));
            shown[1] = {more: more};
        }
        shown.forEach(function (s) {
            if (s.more) { list.appendChild(s.more); return; }
            list.appendChild(item(s.crumb, s.index === trail.length - 1));
        });
        if (trail.length > 1) {
            var clear = document.createElement("li");
            clear.className = "kg-crumb-clear";
            var x = document.createElement("button");
            x.type = "button";
            x.textContent = "×";
            x.title = "たどった経路を消す（今のページから始める）";
            x.addEventListener("click", function () {
                current.url = here();
                save([current]);
                expanded = false;
                render([current]);
            });
            clear.appendChild(x);
            list.appendChild(clear);
        }
        nav.classList.add("kg-breadcrumb-ready");
    }

    // URL を書き換えたとき（タブ・探索グラフ）は今の段の URL を新しくする
    var originalReplace = window.history.replaceState;
    window.history.replaceState = function () {
        var result = originalReplace.apply(this, arguments);
        var trail = load();
        var last = trail[trail.length - 1];
        if (last && last.key === current.key) {
            last.url = here();
            current.url = last.url;
            save(trail);
        }
        return result;
    };

    render(record());
    // ブラウザの戻る・進むでキャッシュから表示されたとき（bfcache）も記録し直す
    window.addEventListener("pageshow", function (e) {
        if (e.persisted) { current.url = here(); render(record()); }
    });
})();
