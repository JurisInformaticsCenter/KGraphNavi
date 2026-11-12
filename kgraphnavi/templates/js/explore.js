// 探索グラフ（/explore。kgraphnavi/explore.py）を Cytoscape.js で描き、クリックで広げる。2026.11.9
//
//   種 → ノードをクリック → 右の欄に「次に広げられる関係」と件数 → 関係を選ぶと、その先のノードが加わる
//   たどった手順（steps）を左の欄に残し、URL の #s=… に入れる（読み直す・共有すると同じ図を作り直す）
//   形 = 種類、色・大きさ = 画面で選ぶ（templates/js/encode.js）
(function () {
    "use strict";

    var KIND_SHAPES = ["ellipse", "round-rectangle", "diamond", "hexagon", "triangle", "barrel", "tag", "star", "vee"];

    function el(tag, className, text) {
        var e = document.createElement(tag);
        if (className) { e.className = className; }
        if (text !== undefined && text !== null) { e.textContent = text; }
        return e;
    }

    function fetchJson(url) {
        return fetch(url, { headers: { "Accept": "application/json" } }).then(function (r) {
            return r.json().then(function (body) {
                if (!r.ok || body.error) { throw new Error(body.error || ("HTTP " + r.status)); }
                return body;
            });
        });
    }

    function short(text, n) {
        text = String(text || "");
        return text.length <= n ? text : text.slice(0, n - 1) + "…";
    }

    // 手順を URL に入れる形（短く）: [["s", uri], ["e", uri, rel, offset], ["x", uri]]
    function encodeSteps(steps) {
        return steps.map(function (s) {
            if (s.type === "seed") { return ["s", s.uri]; }
            if (s.type === "expand") { return ["e", s.uri, s.rel, s.offset || 0]; }
            return ["x", s.uri];
        });
    }

    function decodeSteps(list) {
        return (list || []).map(function (s) {
            if (s[0] === "s") { return { type: "seed", uri: s[1] }; }
            if (s[0] === "e") { return { type: "expand", uri: s[1], rel: s[2], offset: s[3] || 0 }; }
            return { type: "remove", uri: s[1] };
        });
    }

    window.kgExplore = function (id) {
        var root = document.getElementById(id);
        var payload = JSON.parse(document.getElementById(id + "-data").textContent);
        var config = payload.config;
        var container = document.getElementById(id + "-cy");
        if (typeof window.cytoscape !== "function") {
            container.textContent = "ネットワーク図の部品（Cytoscape.js）を読み込めませんでした。ネットワークの接続を確かめてください。";
            return;
        }
        var kinds = {};
        config.kinds.forEach(function (k, i) {
            kinds[k.name] = { shape: k.shape || KIND_SHAPES[i % KIND_SHAPES.length], color: k.color };
        });
        var relations = {};
        config.relations.forEach(function (r) { relations[r.name] = r; });
        var panel = root.querySelector(".kg-explore-panel");
        var stepsEl = root.querySelector(".kg-explore-steps");
        var summary = root.querySelector(".kg-explore-summary");
        var busy = root.querySelector(".kg-explore-busy");
        var undoButton = root.querySelector(".kg-explore-undo");

        // ---- 色・大きさ ----
        var kindColors = {};
        config.kinds.forEach(function (k) { if (k.color) { kindColors[k.name] = k.color; } });
        var colorOptions = [{ name: "kind", label: "種類", type: "category" },
                            { name: "step", label: "たどった順", type: "category" },
                            { name: "year", label: "年", type: "number" }]
            .concat(config.attrs.map(function (a) { return { name: a.name, label: a.label, type: a.type === "number" ? "number" : "category" }; }));
        var sizeOptions = [{ name: "degree", label: "図の中のつながり" },
                           { name: "count", label: "全体の件数" },
                           { name: "none", label: "同じ大きさ" }];
        var encoder = new window.kgEncode.Encoder({ color: colorOptions, size: sizeOptions, colorDefault: "kind",
                                                    sizeDefault: "degree", colors: { kind: kindColors } });

        var cy = window.cytoscape({
            container: container,
            elements: [],
            minZoom: 0.05, maxZoom: 4, wheelSensitivity: 0.25,
            boxSelectionEnabled: true, selectionType: "additive",
            style: [
                { selector: "node", style: {
                    "shape": "data(shape)", "background-color": "data(_color)", "width": "data(_size)", "height": "data(_size)",
                    "border-width": 1.5, "border-color": "#ffffff", "label": "", "font-size": 10, "color": "#1e293b",
                    "text-valign": "bottom", "text-margin-y": 3, "text-background-color": "#ffffff",
                    "text-background-opacity": 0.8, "text-background-padding": 1, "min-zoomed-font-size": 7,
                    "text-max-width": 140, "text-wrap": "ellipsis"
                } },
                // 名前は、判例以外・種・広げたノード・つながりの多いノードと、マウスを乗せた・選んだノードだけに出す
                { selector: "node.labelled, node.hover, node.focus, node.neighbor, node:selected", style: { "label": "data(short)" } },
                { selector: "node.seed", style: { "border-color": "#0f172a", "border-width": 3 } },
                { selector: "node.expanded", style: { "border-color": "#475569", "border-width": 2.5, "border-style": "double" } },
                { selector: "node.fresh", style: { "underlay-color": "#f59e0b", "underlay-opacity": 0.22, "underlay-padding": 4 } },
                { selector: "node:selected", style: { "border-color": "#f59e0b", "border-width": 4 } },
                { selector: "node.focus", style: { "border-color": "#dc2626", "border-width": 4, "z-index": 20 } },
                { selector: "edge", style: {
                    "width": "mapData(weight, 1, 10, 1.2, 5)", "line-color": "#cbd5e1", "curve-style": "bezier", "opacity": 0.9,
                    "target-arrow-color": "#94a3b8", "arrow-scale": 0.7
                } },
                { selector: "edge.directed", style: { "target-arrow-shape": "triangle" } },
                { selector: "edge.weak", style: { "line-style": "dashed", "line-dash-pattern": [5, 4] } },
                { selector: "edge.hover, edge.neighbor", style: {
                    "line-color": "#2563eb", "target-arrow-color": "#2563eb", "label": "data(label)", "font-size": 9,
                    "color": "#1e3a8a", "text-background-color": "#ffffff", "text-background-opacity": 0.85, "z-index": 10
                } },
                { selector: ".faded", style: { "opacity": 0.12 } }
            ]
        });
        container.kgCy = cy;

        var steps = [];             // たどった手順
        var cache = {};             // 問い合わせの結果（手順をやり直すときに使う）
        var origin = {};            // ノード → 加えた手順の番号（最初のもの）
        var expandedRel = {};       // "uri|rel" → 次の offset と全体の数
        var highlighted = null;
        var focused = null;

        function setBusy(on) { busy.hidden = !on; }

        function updateDegree() {
            cy.nodes().forEach(function (n) {
                var deg = n.degree(false);
                n.toggleClass("labelled", n.data("kind") !== config.saveKind || n.hasClass("seed") || n.hasClass("expanded") || deg >= 2);
                n.data("m_degree", deg);
                n.data("m_count", n.data("count") || 0);
                n.data("a_step", origin[n.id()] !== undefined ? String(origin[n.id()] + 1) : "");
            });
        }

        function redraw() {
            updateDegree();
            var legend = encoder.apply(cy);
            cy.style().update();
            var legendEl = root.querySelector(".kg-explore-legend");
            window.kgEncode.renderLegend(legendEl, legend, {
                filterable: true, alwaysShapes: true, maxItems: 14,
                valueLabel: encoder.colorName === "step" ? function (v) { return v + ". " + stepTitle(Number(v) - 1, 18); } : null
            });
            var saveCount = cy.nodes().filter(function (n) { return n.data("kind") === config.saveKind; }).length;
            // 種だけのときは、次に何をするかを図の上に出す
            var start = root.querySelector(".kg-explore-start");
            if (start) { start.hidden = !(cy.nodes().length > 0 && cy.edges().length === 0); }
            summary.textContent = "ノード " + cy.nodes().length + "・辺 " + cy.edges().length +
                "（" + config.saveKind + " " + saveCount + "）";
        }

        function nodeData(n, stepIndex) {
            var k = kinds[n.kind] || {};
            var data = { id: n.id, label: n.label, short: short(n.label, 22), kind: n.kind, shape: k.shape || "ellipse",
                         href: n.href, count: n.count, x: n.x, _color: "#94a3b8", _size: 22 };
            Object.keys(n.attrs || {}).forEach(function (a) { data["a_" + a] = n.attrs[a]; });
            return data;
        }

        // ノードと辺を加える。新しいノードは親のまわり（図の中心から離れる側）に扇形に置く
        function addElements(result, parentId, stepIndex) {
            var parent = parentId ? cy.getElementById(parentId) : null;
            var fresh = [];
            var limitHit = false;
            result.nodes.forEach(function (n) {
                if (cy.getElementById(n.id).nonempty()) {
                    var old = cy.getElementById(n.id);
                    Object.keys(n.attrs || {}).forEach(function (a) { if (!old.data("a_" + a)) { old.data("a_" + a, n.attrs[a]); } });
                    if (n.count !== undefined && old.data("count") === undefined) { old.data("count", n.count); }
                    return;
                }
                if (cy.nodes().length + fresh.length >= config.maxNodes) { limitHit = true; return; }
                fresh.push(n);
            });
            var center = cy.nodes().length ? cy.nodes().boundingBox() : { x1: 0, x2: 0, y1: 0, y2: 0 };
            var cx = (center.x1 + center.x2) / 2, cyy = (center.y1 + center.y2) / 2;
            var px = parent && parent.nonempty() ? parent.position("x") : cx;
            var py = parent && parent.nonempty() ? parent.position("y") : cyy;
            var away = Math.atan2(py - cyy, px - cx);
            if (!isFinite(away) || (px === cx && py === cyy)) { away = 0; }
            var spread = fresh.length > 12 ? 2 * Math.PI : Math.min(2 * Math.PI, 0.5 + fresh.length * 0.35);
            var radius = 110 + Math.min(fresh.length, 40) * 4;
            var added = cy.collection();
            fresh.forEach(function (n, i) {
                var angle = away + (fresh.length === 1 ? 0 : (i / (fresh.length - (spread >= 2 * Math.PI ? 0 : 1)) - 0.5) * spread);
                var r = radius + (i % 2) * 28;
                var node = cy.add({ group: "nodes", data: nodeData(n, stepIndex),
                                    position: { x: px + r * Math.cos(angle), y: py + r * Math.sin(angle) } });
                origin[n.id] = stepIndex;
                added = added.union(node);
            });
            result.edges.forEach(function (e) {
                if (cy.getElementById(e.source).empty() || cy.getElementById(e.target).empty()) { return; }
                if (cy.getElementById(e.id).nonempty()) { return; }
                cy.add({ group: "edges", data: { id: e.id, source: e.source, target: e.target, label: e.label + (e.conf ? "（" + e.conf + "）" : ""),
                                                 rel: e.rel, weight: e.weight || 1 },
                         classes: (e.directed ? "directed " : "") + (e.weak ? "weak" : "") });
            });
            return { added: added, limitHit: limitHit };
        }

        // 新しいノードだけを少し動かして重なりを減らす（それまでのノードは固定）
        function settle(added, animate) {
            if (!added || added.empty()) { return; }
            var old = cy.nodes().difference(added);
            old.lock();
            var layout = cy.layout({ name: "cose", randomize: false, animate: animate !== false, animationDuration: 400,
                                     fit: false, nodeRepulsion: function () { return 14000; },
                                     idealEdgeLength: function () { return 110; }, numIter: 800,
                                     eles: cy.elements() });
            layout.one("layoutstop", function () {
                old.unlock();
                // 加えたノードが画面の外に出たら、全体が見えるように動かす
                var ext = cy.extent();
                var outside = added.some(function (n) {
                    var p = n.position();
                    return p.x < ext.x1 || p.x > ext.x2 || p.y < ext.y1 || p.y > ext.y2;
                });
                if (outside) { cy.animate({ fit: { eles: cy.elements(), padding: 30 } }, { duration: 400 }); }
            });
            layout.run();
        }

        function stepTitle(i, n) {
            var s = steps[i];
            if (!s) { return ""; }
            var node = cy.getElementById(s.uri);
            var name = node.nonempty() ? node.data("label") : (s.label || s.uri);
            if (s.type === "seed") {
                return short(name, n || 40) + (node.nonempty() ? "（" + node.data("kind") + "）" : "") + " を種に";
            }
            if (s.type === "remove") { return short(name, n || 40) + " を外す"; }
            var rel = relations[s.rel] || { label: s.rel };
            return short(name, n || 24) + " → " + rel.label;
        }

        function renderSteps() {
            stepsEl.innerHTML = "";
            steps.forEach(function (s, i) {
                var li = el("li", "kg-explore-step");
                var b = el("button", "kg-explore-step-button");
                b.type = "button";
                b.appendChild(el("span", "kg-explore-step-title", stepTitle(i)));
                if (s.type === "expand" && s.result) {
                    var shown = Math.min(s.result.offset + s.result.nodes.length, s.result.total);
                    b.appendChild(el("span", "kg-explore-step-count",
                        (s.result.offset ? (s.result.offset + 1) + "〜" : "") + shown + " / " + s.result.total + " 件"));
                }
                b.title = "この手順で加わったノードを強調します";
                b.addEventListener("click", function () { highlightStep(i); });
                li.appendChild(b);
                stepsEl.appendChild(li);
            });
            undoButton.disabled = steps.length <= 1;
            var url = location.pathname + location.search + "#s=" + encodeURIComponent(JSON.stringify(encodeSteps(steps)));
            history.replaceState(null, "", url);
            renderSave();
        }

        function highlightStep(i) {
            cy.elements().removeClass("faded neighbor focus");
            stepsEl.querySelectorAll(".kg-explore-step").forEach(function (li, j) { li.classList.toggle("active", j === i && highlighted !== i); });
            if (highlighted === i) { highlighted = null; return; }
            highlighted = i;
            var hit = cy.nodes().filter(function (n) { return origin[n.id()] === i; });
            var s = steps[i];
            if (s && s.uri) { hit = hit.union(cy.getElementById(s.uri)); }
            cy.elements().addClass("faded");
            hit.union(hit.edgesWith(hit)).removeClass("faded").addClass("neighbor");
        }

        // ---- 手順の実行 ----

        function seedNode(uri) {
            var key = "node|" + uri;
            if (cache[key]) { return Promise.resolve(cache[key]); }
            return fetchJson("/explore/node?uri=" + encodeURIComponent(uri)).then(function (body) { cache[key] = body; return body; });
        }

        function expandData(uri, rel, offset) {
            var key = "expand|" + uri + "|" + rel + "|" + (offset || 0);
            if (cache[key]) { return Promise.resolve(cache[key]); }
            return fetchJson("/explore/expand?uri=" + encodeURIComponent(uri) + "&rel=" + encodeURIComponent(rel) +
                             "&offset=" + (offset || 0) + "&limit=" + config.limit)
                .then(function (body) { cache[key] = body; return body; });
        }

        function runStep(step, index, animate) {
            if (step.type === "seed") {
                var known = (payload.seeds || []).filter(function (s) { return s.id === step.uri; })[0];
                var p = known ? Promise.resolve({ node: known }) : seedNode(step.uri);
                return p.then(function (body) {
                    step.label = body.node.label;
                    var r = addElements({ nodes: [body.node], edges: [] }, null, index);
                    cy.getElementById(step.uri).addClass("seed");
                    return r;
                });
            }
            if (step.type === "remove") {
                cy.getElementById(step.uri).remove();
                return Promise.resolve({ added: cy.collection() });
            }
            return expandData(step.uri, step.rel, step.offset).then(function (result) {
                step.result = result;
                var r = addElements(result, step.uri, index);
                cy.getElementById(step.uri).addClass("expanded");
                expandedRel[step.uri + "|" + step.rel] = { next: result.offset + result.nodes.length, total: result.total };
                return r;
            });
        }

        function perform(step) {
            setBusy(true);
            cy.nodes().removeClass("fresh");
            var index = steps.length;
            steps.push(step);
            return runStep(step, index, true).then(function (r) {
                redraw();
                if (step.type === "seed" && steps.filter(function (s) { return s.type === "seed"; }).length > 1) {
                    settle(r.added, true);
                } else {
                    settle(r.added, true);
                }
                r.added.addClass("fresh");
                renderSteps();
                if (r.limitHit) { alert("図に出せるノードの上限（" + config.maxNodes + "）に達しました。不要なノードを外すか、新しく始めてください。"); }
                if (focused && cy.getElementById(focused).nonempty()) { openPanel(cy.getElementById(focused)); }
                return r;
            }).catch(function (e) {
                steps.pop();
                alert("広げられませんでした: " + e.message);
            }).then(function (r) { setBusy(false); return r; });
        }

        // 手順を初めからやり直す（1つ戻す・URL から作り直す）
        function replay(list) {
            setBusy(true);
            cy.elements().remove();
            origin = {}; expandedRel = {}; steps = [];
            var chain = Promise.resolve();
            list.forEach(function (step) {
                chain = chain.then(function () {
                    var index = steps.length;
                    steps.push(step);
                    return runStep(step, index, false).catch(function (e) { steps.pop(); console.warn(e); });
                });
            });
            return chain.then(function () {
                redraw();
                cy.layout({ name: "cose", animate: false, randomize: true, fit: true, padding: 30,
                            nodeRepulsion: function () { return 7000; }, idealEdgeLength: function () { return 80; } }).run();
                if (cy.zoom() > 1.3) { cy.zoom(1.3); cy.center(); }    // ノードが少ないときに大きくなりすぎない
                renderSteps();
                setBusy(false);
            });
        }

        // ---- 右の欄（ノードの情報と、次に広げられる関係）----

        function openPanel(node) {
            focused = node.id();
            cy.nodes().removeClass("focus");
            node.addClass("focus");
            panel.innerHTML = "";
            var title = el("h3", "kg-explore-panel-title");
            title.appendChild(el("span", "kg-explore-kind", node.data("kind")));
            var a = el("a", "", node.data("label"));
            a.href = node.data("href"); a.target = "_blank"; a.rel = "noopener";
            title.appendChild(a);
            panel.appendChild(title);
            var facts = el("dl", "kg-graph-facts");
            function fact(name, value) {
                if (value === undefined || value === null || value === "") { return; }
                facts.appendChild(el("dt", "", name));
                facts.appendChild(el("dd", "", String(value)));
            }
            fact("年", node.data("x"));
            config.attrs.forEach(function (attr) { fact(attr.label, node.data("a_" + attr.name)); });
            fact("全体の件数", node.data("count"));
            fact("図の中のつながり", node.degree(false));
            if (origin[node.id()] !== undefined) { fact("加えた手順", (origin[node.id()] + 1) + ". " + stepTitle(origin[node.id()], 30)); }
            panel.appendChild(facts);
            panel.appendChild(el("h4", "kg-explore-panel-sub", "次に広げられる関係"));
            var list = el("ul", "kg-explore-relations");
            list.appendChild(el("li", "kg-explore-hint", "件数を数えています…"));
            panel.appendChild(list);
            var tools = el("div", "kg-explore-node-tools");
            var open = el("a", "kg-explore-open", "ページを開く");
            open.href = node.data("href"); open.target = "_blank"; open.rel = "noopener";
            tools.appendChild(open);
            var remove = el("button", "", "図から外す");
            remove.type = "button";
            remove.addEventListener("click", function () {
                panel.innerHTML = '<p class="kg-explore-hint">ノードを選んでください。</p>';
                focused = null;
                perform({ type: "remove", uri: node.id() });
            });
            tools.appendChild(remove);
            var restart = el("a", "", "これを種に新しく始める");
            restart.href = "/explore?uri=" + encodeURIComponent(node.id());
            tools.appendChild(restart);
            panel.appendChild(tools);
            var uri = node.id();
            seedNode(uri).then(function (body) {
                if (focused !== uri) { return; }
                list.innerHTML = "";
                var rels = body.relations || [];
                if (!rels.length) { list.appendChild(el("li", "kg-explore-hint", "広げられる関係はありません")); }
                // 件数の多い順ではなく、設定の順（よく使う順に並べておく）。0 件は下へ
                rels.slice().sort(function (x, y) { return (y.count > 0) - (x.count > 0); }).forEach(function (r) {
                    var li = el("li");
                    var done = expandedRel[uri + "|" + r.name];
                    var b = el("button", "kg-explore-rel");
                    b.type = "button";
                    b.appendChild(el("span", "kg-explore-rel-shape")).innerHTML =
                        window.kgEncode.shapeIcon((kinds[r.to] || {}).shape, kindColors[r.to]);
                    b.appendChild(el("span", "kg-explore-rel-label", r.label));
                    var countText = r.error ? "エラー" : (r.count === null || r.count === undefined ? "" : r.count.toLocaleString());
                    if (done) { countText = Math.min(done.next, done.total) + " / " + done.total; }
                    b.appendChild(el("span", "kg-explore-rel-count", countText));
                    if (r.error) { b.title = r.error; }
                    if (!r.count || (done && done.next >= done.total)) {
                        b.disabled = true;
                        if (done) { b.classList.add("done"); }
                    }
                    b.addEventListener("click", function () {
                        perform({ type: "expand", uri: uri, rel: r.name, offset: done ? done.next : 0 });
                    });
                    li.appendChild(b);
                    if (done && done.next < done.total) {
                        b.lastChild.textContent = "次の " + Math.min(config.limit, done.total - done.next) + " 件（" +
                            done.next + " / " + done.total + "）";
                    }
                    list.appendChild(li);
                });
            }).catch(function (e) {
                list.innerHTML = "";
                list.appendChild(el("li", "kg-explore-error", "数えられませんでした: " + e.message));
            });
        }

        // ---- 集める（保存・比べる）----

        function renderSave() {
            var box = root.querySelector(".kg-explore-save");
            box.innerHTML = "";
            var selected = cy.nodes(":selected").filter(function (n) { return n.data("kind") === config.saveKind; });
            var all = cy.nodes().filter(function (n) { return n.data("kind") === config.saveKind; });
            var target = selected.length ? selected : all;
            var label = (selected.length ? "選んだ" : "図の") + config.saveKind + " " + target.length + " 件";
            box.appendChild(el("p", "kg-explore-save-count", label));
            if (payload.save && target.length) {
                var form = el("form", "kg-explore-save-form");
                form.method = "POST"; form.action = payload.save.action;
                var input = el("input"); input.type = "text"; input.name = "name"; input.required = true; input.maxLength = 60;
                input.placeholder = "コレクションの名前";
                form.appendChild(input);
                function hidden(name, value) { var h = el("input"); h.type = "hidden"; h.name = name; h.value = value; form.appendChild(h); }
                if (config.saveClass) { hidden("class", config.saveClass); }
                hidden("selected_from", "explore");
                var sourceInput = el("input"); sourceInput.type = "hidden"; sourceInput.name = "source"; form.appendChild(sourceInput);
                var overwrite = el("label", "kg-explore-overwrite");
                var check = el("input"); check.type = "checkbox"; check.name = "overwrite"; check.value = "1";
                overwrite.appendChild(check); overwrite.appendChild(document.createTextNode("上書き"));
                form.appendChild(overwrite);
                var button = el("button", "", "保存してコレクションで開く");
                button.type = "submit";
                form.appendChild(button);
                form.addEventListener("submit", function (event) {
                    if (target.length > payload.save.max) {
                        event.preventDefault(); alert("保存できるのは " + payload.save.max + " 件までです"); return;
                    }
                    sourceInput.value = location.href;     // 探索の手順（#s=…）を含む URL
                    form.querySelectorAll('input[name="uris"]').forEach(function (h) { h.remove(); });
                    target.forEach(function (n) { hidden("uris", n.id()); });
                });
                box.appendChild(form);
            }
            if (selected.length >= 2 && selected.length <= 4) {
                var cmp = el("a", "kg-explore-compare", "選んだ " + selected.length + " 件を並べて比べる");
                cmp.href = "/compare?" + selected.map(function (n) { return "uri=" + encodeURIComponent(n.id()); }).join("&");
                cmp.target = "_blank";
                box.appendChild(cmp);
            }
            if (!selected.length && all.length) {
                box.appendChild(el("p", "kg-explore-hint", "Shift を押しながらドラッグで囲むと、選んだものだけを保存・比べられます。"));
            }
        }

        // ---- 画面の操作 ----

        cy.on("tap", "node", function (event) { highlighted = null; openPanel(event.target); });
        cy.on("dbltap", "node", function (event) {
            var node = event.target;
            seedNode(node.id()).then(function (body) {
                var r = (body.relations || []).filter(function (x) {
                    var done = expandedRel[node.id() + "|" + x.name];
                    return x.count > 0 && !(done && done.next >= done.total);
                })[0];
                if (r) {
                    var done = expandedRel[node.id() + "|" + r.name];
                    perform({ type: "expand", uri: node.id(), rel: r.name, offset: done ? done.next : 0 });
                }
            });
        });
        cy.on("tap", function (event) {
            if (event.target === cy) {
                cy.elements().removeClass("faded neighbor focus");
                highlighted = null;
                stepsEl.querySelectorAll(".active").forEach(function (x) { x.classList.remove("active"); });
            }
        });
        cy.on("mouseover", "node", function (event) {
            event.target.addClass("hover");
            event.target.connectedEdges().addClass("hover");
            container.style.cursor = "pointer";
        });
        cy.on("mouseout", "node", function (event) {
            event.target.removeClass("hover");
            event.target.connectedEdges().removeClass("hover");
            container.style.cursor = "";
        });
        var pending = null;
        cy.on("select unselect", "node", function () {
            window.clearTimeout(pending);
            pending = window.setTimeout(renderSave, 40);
        });

        var tools = root.querySelector(".kg-graph-encode");
        var c = window.kgEncode.selectBox("色", colorOptions, encoder.colorName, function (v) { encoder.colorName = v; redraw(); });
        var s = window.kgEncode.selectBox("大きさ", sizeOptions, encoder.sizeName, function (v) { encoder.sizeName = v; redraw(); });
        if (c) { tools.appendChild(c); }
        if (s) { tools.appendChild(s); }
        var legendEl = root.querySelector(".kg-explore-legend");
        legendEl.addEventListener("click", function (event) {
            var item = event.target.closest ? event.target.closest("[data-legend-value]") : null;
            if (!item) { return; }
            var value = item.getAttribute("data-legend-value");
            var active = item.classList.contains("active");
            legendEl.querySelectorAll(".active").forEach(function (x) { x.classList.remove("active"); });
            cy.elements().removeClass("faded neighbor");
            if (active) { return; }
            item.classList.add("active");
            var hit = cy.nodes().filter(function (n) { return String(window.kgEncode.valueOf(n, encoder.colorName)) === value; });
            cy.elements().addClass("faded");
            hit.union(hit.edgesWith(hit)).removeClass("faded").addClass("neighbor");
        });
        root.querySelector(".kg-graph-fit").addEventListener("click", function () { cy.fit(undefined, 30); });
        root.querySelector(".kg-explore-relayout").addEventListener("click", function () {
            cy.layout({ name: "cose", animate: true, randomize: true, fit: true, padding: 30,
                        nodeRepulsion: function () { return 7000; }, idealEdgeLength: function () { return 80; } }).run();
        });
        root.querySelector(".kg-explore-png").addEventListener("click", function () {
            var blob = cy.png({ output: "blob", bg: "#ffffff", full: true, scale: 2, maxWidth: 8000, maxHeight: 8000 });
            var link = document.createElement("a");
            link.href = URL.createObjectURL(blob);
            link.download = "explore.png";
            document.body.appendChild(link); link.click(); link.remove();
        });
        undoButton.addEventListener("click", function () {
            if (steps.length <= 1) { return; }
            panel.innerHTML = '<p class="kg-explore-hint">ノードを選んでください。</p>';
            focused = null;
            replay(steps.slice(0, -1).map(function (st) { return { type: st.type, uri: st.uri, rel: st.rel, offset: st.offset }; }));
        });
        root.querySelector(".kg-explore-copy").addEventListener("click", function () {
            var text = location.href;
            if (navigator.clipboard) { navigator.clipboard.writeText(text); }
            this.textContent = "コピーしました";
            var self = this;
            window.setTimeout(function () { self.textContent = "URL をコピー"; }, 1500);
        });
        root.querySelectorAll(".kg-explore-seed").forEach(function (box) {
            box.addEventListener("change", function () {
                if (box.checked) {
                    perform({ type: "seed", uri: box.value });
                } else {
                    perform({ type: "remove", uri: box.value });
                }
            });
        });

        // ---- 始める: URL の #s=… があればそれを、なければ種を ----
        var initial = null;
        var m = /[#&]s=([^&]+)/.exec(location.hash);
        if (m) {
            try { initial = decodeSteps(JSON.parse(decodeURIComponent(m[1]))); } catch (e) { initial = null; }
        }
        if (!initial || !initial.length) {
            initial = (payload.seeds || []).filter(function (sd) { return sd.start !== false; })
                .map(function (sd) { return { type: "seed", uri: sd.id }; });
        }
        if (initial.length) {
            replay(initial).then(function () {
                if (initial.length === 1 && cy.nodes().length === 1) {
                    cy.zoom(1); cy.center();
                    openPanel(cy.nodes()[0]);
                }
            });
        } else {
            redraw();
            renderSteps();
        }
    };
})();
