// ネットワーク図（show: type: graph）を Cytoscape.js で描く。
// サーバ（kgraphnavi/graph.py）がページに埋め込んだ JSON（<script type="application/json" id="<id>-data">）を読む。
// 2026.10.28
(function () {
    "use strict";

    var graphs = [];

    function nodeSize(range) {
        var lo = range[0], hi = range[1];
        return hi > lo ? "mapData(size, " + lo + ", " + hi + ", 14, 56)" : 22;
    }

    function edgeWidth(range) {
        var lo = (range || [1, 1])[0], hi = (range || [1, 1])[1];
        return hi > lo ? "mapData(weight, " + lo + ", " + hi + ", 1, 7)" : 1.5;
    }

    function stylesheet(payload) {
        var size = nodeSize(payload.size_range);
        return [
            { selector: "node", style: {
                "background-color": "data(color)", "width": size, "height": size,
                "border-width": 1, "border-color": "#ffffff", "label": "",
                "font-size": 10, "color": "#1e293b", "text-valign": "bottom", "text-margin-y": 3,
                "text-background-color": "#ffffff", "text-background-opacity": 0.75, "text-background-padding": 1,
                "min-zoomed-font-size": 6
            } },
            { selector: "node.labelled, node.hover, node.focus, node.neighbor", style: { "label": "data(short)" } },
            { selector: "node.outside", style: {
                "border-style": "dashed", "border-color": "#6b7280", "border-width": 1.5, "background-opacity": 0.6
            } },
            // 2段に並べるとき、上の段（参照される側）の名前は斜めに上へ
            { selector: "node.top.tilted", style: {
                "text-valign": "top", "text-halign": "right", "text-margin-y": -4, "text-margin-x": -6,
                "text-rotation": -0.6, "font-size": 11, "text-background-opacity": 0
            } },
            // 範囲選択で選んだノード
            { selector: "node:selected", style: {
                "background-color": "data(color)", "border-color": "#f59e0b", "border-width": 4, "label": "data(short)"
            } },
            { selector: "edge:selected", style: { "line-color": "#cbd5e1", "target-arrow-color": "#94a3b8" } },
            { selector: "node.focus", style: { "border-color": "#0f172a", "border-width": 3, "z-index": 20 } },
            { selector: "edge", style: {
                "width": edgeWidth(payload.weight_range), "line-color": "#cbd5e1", "curve-style": "straight",
                "opacity": 0.85
            } },
            // 年で並べるときは、辺を弧にする（同じ高さのノードの間の辺が重ならないように）
            { selector: "edge.arc", style: {
                "curve-style": "unbundled-bezier", "control-point-distances": "data(arc)", "control-point-weights": 0.5
            } },
            { selector: "edge.directed", style: {
                "target-arrow-shape": "triangle", "target-arrow-color": "#94a3b8", "arrow-scale": 0.8
            } },
            { selector: "edge.hover, edge.neighbor", style: {
                "line-color": "#2563eb", "target-arrow-color": "#2563eb", "opacity": 1, "z-index": 10
            } },
            { selector: ".faded", style: { "opacity": 0.12 } },
            // 年の目盛り
            { selector: "node.axis", style: {
                "width": 1, "height": 1, "background-opacity": 0, "border-width": 0, "label": "data(label)",
                "font-size": 12, "color": "#64748b", "text-valign": "center", "text-background-opacity": 0,
                "events": "no", "opacity": 1, "display": "none"
            } }
        ];
    }

    // positions: サーバで計算した配置ごとの位置 {配置: {ノード: {x, y}}}（年で並べる・2段）
    function layoutOptions(name, positions) {
        switch (name) {
        case "timeline":
        case "bipartite":
            return { name: "preset", fit: true, padding: 40,
                     positions: function (node) { return (positions[name] || {})[node.id()] || node.position(); } };
        case "circle":
            return { name: "circle", fit: true, padding: 30, sort: function (a, b) { return b.data("size") - a.data("size"); } };
        case "grid":
            return { name: "grid", fit: true, padding: 30, sort: function (a, b) { return b.data("size") - a.data("size"); } };
        default:
            return { name: "cose", animate: false, fit: true, padding: 30, randomize: true,
                     nodeRepulsion: function () { return 9000; }, idealEdgeLength: function () { return 60; },
                     numIter: 1500 };
        }
    }

    function element(tag, className, text) {
        var el = document.createElement(tag);
        if (className) { el.className = className; }
        if (text !== undefined) { el.textContent = text; }
        return el;
    }

    // ノードの詳しい情報（右の欄）
    function showPanel(panel, node, focus) {
        panel.innerHTML = "";
        panel.hidden = false;
        var data = node.data();
        var title = element("h3", "kg-graph-panel-title");
        if (data.href) {
            var link = element("a", "", data.label);
            link.href = data.href;
            title.appendChild(link);
        } else {
            title.textContent = data.label;
        }
        panel.appendChild(title);
        var facts = element("dl", "kg-graph-facts");
        function fact(name, value) {
            if (value === undefined || value === null || value === "") { return; }
            facts.appendChild(element("dt", "", name));
            facts.appendChild(element("dd", "", String(value)));
        }
        fact("種類", data.kind + (node.hasClass("outside") ? "（コレクション外）" : ""));
        fact("年", data.x);
        var directed = node.connectedEdges(".directed").length > 0;
        if (directed) {
            fact("参照されている", data.indegree + " 件");
            fact("参照している", data.outdegree + " 件");
        }
        panel.appendChild(facts);
        if (data.filter) {
            // その値で絞り込んだコレクションへ（コレクションのページでは今の条件に加える）
            var filter = element("a", "kg-graph-filter", "この" + data.kind + "で絞り込む");
            filter.href = data.filter;
            panel.appendChild(filter);
        }

        function neighborList(label, nodes) {
            if (!nodes.length) { return; }
            panel.appendChild(element("h4", "kg-graph-panel-sub", label + "（" + nodes.length + "）"));
            var list = element("ul", "kg-graph-neighbors");
            // 辺の重み（一緒に参照された判例の数など）が 1 より大きければ、重みの大きい順に並べて添える
            function weight(n) { return node.edgesWith(n).max(function (e) { return e.data("weight"); }).value || 1; }
            nodes.sort(function (a, b) { return weight(b) - weight(a) || b.data("size") - a.data("size"); })
                .slice(0, 30).forEach(function (n) {
                    var item = element("li");
                    var button = element("button", "kg-graph-neighbor", n.data("label"));
                    button.type = "button";
                    button.addEventListener("click", function () { focus(n); });
                    var w = weight(n);
                    if (w > 1) { button.appendChild(element("span", "kg-graph-weight", String(w))); }
                    item.appendChild(button);
                    list.appendChild(item);
                });
            panel.appendChild(list);
            if (nodes.length > 30) { panel.appendChild(element("p", "kg-graph-more", "ほか " + (nodes.length - 30) + " 件")); }
        }
        if (directed) {
            neighborList("参照している", node.outgoers("node").toArray());
            neighborList("参照されている", node.incomers("node").toArray());
        } else {
            // 向きのない辺（判例と条など）は、つながるノードを種類ごとに
            var byKind = {};
            node.neighborhood("node").forEach(function (n) {
                (byKind[n.data("kind")] = byKind[n.data("kind")] || []).push(n);
            });
            Object.keys(byKind).forEach(function (kind) { neighborList(kind, byKind[kind]); });
        }
        if (data.href) {
            panel.appendChild(element("p", "kg-graph-hint", "ダブルクリックでこのページを開きます"));
        }
    }

    // ---- 書き出し（画像・CSV・GraphML）----

    function download(blob, filename) {
        var link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        window.setTimeout(function () { URL.revokeObjectURL(link.href); link.remove(); }, 1000);
    }

    function baseName(title) {
        var d = new Date();
        var stamp = d.getFullYear() + String(d.getMonth() + 1).padStart(2, "0") + String(d.getDate()).padStart(2, "0");
        return String(title || "graph").replace(/[\\/:*?"<>|\s]+/g, "_") + "_" + stamp;
    }

    function csvCell(value) {
        var text = value === undefined || value === null ? "" : String(value);
        return /[",\r\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
    }

    function csv(rows) {
        // Excel で文字化けしないよう BOM を付ける
        return new Blob(["\ufeff" + rows.map(function (r) { return r.map(csvCell).join(","); }).join("\r\n") + "\r\n"],
                        { type: "text/csv;charset=utf-8" });
    }

    function xml(text) {
        return String(text === undefined || text === null ? "" : text)
            .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }

    function graphNodes(cy) { return cy.nodes().not(".axis").filter(function (n) { return n.visible(); }); }
    function graphEdges(cy) { return cy.edges().filter(function (e) { return e.visible(); }); }

    function edgesCsv(cy) {
        var rows = [["source", "source_label", "target", "target_label", "weight", "directed"]];
        graphEdges(cy).forEach(function (e) {
            rows.push([e.source().id(), e.source().data("label"), e.target().id(), e.target().data("label"),
                       e.data("weight"), e.hasClass("directed") ? "true" : "false"]);
        });
        return csv(rows);
    }

    function nodesCsv(cy) {
        var rows = [["id", "label", "kind", "year", "indegree", "outdegree", "pagerank", "component", "outside"]];
        graphNodes(cy).forEach(function (n) {
            var d = n.data();
            rows.push([d.id, d.label, d.kind, d.x, d.indegree, d.outdegree, d.pagerank, d.component,
                       n.hasClass("outside") ? "true" : "false"]);
        });
        return csv(rows);
    }

    function graphml(cy) {
        var directed = graphEdges(cy).some(function (e) { return e.hasClass("directed"); });
        var keys = [["label", "node", "string"], ["kind", "node", "string"], ["year", "node", "double"],
                    ["pagerank", "node", "double"], ["component", "node", "int"], ["outside", "node", "boolean"],
                    ["weight", "edge", "double"]];
        var out = ['<?xml version="1.0" encoding="UTF-8"?>',
                   '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">'];
        keys.forEach(function (k) {
            out.push('  <key id="' + k[0] + '" for="' + k[1] + '" attr.name="' + k[0] + '" attr.type="' + k[2] + '"/>');
        });
        out.push('  <graph id="G" edgedefault="' + (directed ? "directed" : "undirected") + '">');
        graphNodes(cy).forEach(function (n) {
            var d = n.data();
            out.push('    <node id="' + xml(d.id) + '">');
            out.push('      <data key="label">' + xml(d.label) + "</data>");
            out.push('      <data key="kind">' + xml(d.kind) + "</data>");
            if (d.x !== undefined) { out.push('      <data key="year">' + xml(d.x) + "</data>"); }
            if (d.pagerank !== undefined) { out.push('      <data key="pagerank">' + xml(d.pagerank) + "</data>"); }
            if (d.component !== undefined) { out.push('      <data key="component">' + xml(d.component) + "</data>"); }
            out.push('      <data key="outside">' + (n.hasClass("outside") ? "true" : "false") + "</data>");
            out.push("    </node>");
        });
        graphEdges(cy).forEach(function (e, i) {
            out.push('    <edge id="e' + i + '" source="' + xml(e.source().id()) + '" target="' + xml(e.target().id()) + '">');
            out.push('      <data key="weight">' + xml(e.data("weight")) + "</data>");
            out.push("    </edge>");
        });
        out.push("  </graph>", "</graphml>");
        return new Blob([out.join("\n") + "\n"], { type: "application/graphml+xml" });
    }

    // 画面の図を SVG にする（ノードは円、辺は直線か弧、出ている名前も書く）
    function svg(cy) {
        var nodes = graphNodes(cy);
        var axis = cy.nodes(".axis").filter(function (n) { return n.visible(); });
        var box = nodes.union(axis).boundingBox({ includeLabels: true });
        var pad = 20;
        var x0 = box.x1 - pad, y0 = box.y1 - pad, w = box.w + 2 * pad, h = box.h + 2 * pad;
        function num(v) { return Math.round(v * 10) / 10; }
        var out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="' + [num(x0), num(y0), num(w), num(h)].join(" ") +
                   '" width="' + num(w) + '" height="' + num(h) + '" font-family="sans-serif">',
                   '<defs><marker id="arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="6" markerHeight="6" ' +
                   'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#94a3b8"/></marker></defs>',
                   '<rect x="' + num(x0) + '" y="' + num(y0) + '" width="' + num(w) + '" height="' + num(h) + '" fill="#ffffff"/>'];
        graphEdges(cy).forEach(function (e) {
            var s = e.source().position(), t = e.target().position();
            var stroke = e.style("line-color"), width = parseFloat(e.style("width")) || 1;
            var opacity = parseFloat(e.style("opacity"));
            var cp = e.hasClass("arc") && e.controlPoints ? e.controlPoints() : null;
            var d = cp && cp.length ? "M" + num(s.x) + "," + num(s.y) + " Q" + num(cp[0].x) + "," + num(cp[0].y) + " " + num(t.x) + "," + num(t.y)
                                    : "M" + num(s.x) + "," + num(s.y) + " L" + num(t.x) + "," + num(t.y);
            out.push('<path d="' + d + '" fill="none" stroke="' + stroke + '" stroke-width="' + num(width) + '" opacity="' +
                     (isNaN(opacity) ? 1 : opacity) + '"' + (e.hasClass("directed") ? ' marker-end="url(#arrow)"' : "") + "/>");
        });
        nodes.forEach(function (n) {
            var p = n.position(), r = n.width() / 2;
            var opacity = parseFloat(n.style("opacity"));
            out.push('<circle cx="' + num(p.x) + '" cy="' + num(p.y) + '" r="' + num(r) + '" fill="' + n.style("background-color") +
                     '" stroke="' + n.style("border-color") + '" stroke-width="' + (parseFloat(n.style("border-width")) || 0) + '"' +
                     (n.hasClass("outside") ? ' stroke-dasharray="3,2" fill-opacity="0.6"' : "") +
                     ' opacity="' + (isNaN(opacity) ? 1 : opacity) + '"/>');
        });
        nodes.union(axis).forEach(function (n) {
            var label = n.style("label");
            if (!label) { return; }
            var p = n.position(), r = n.hasClass("axis") ? 0 : n.width() / 2;
            if (n.hasClass("tilted")) {
                out.push('<text x="' + num(p.x) + '" y="' + num(p.y - r - 4) + '" font-size="11" fill="#1e293b" ' +
                         'transform="rotate(-34 ' + num(p.x) + " " + num(p.y - r - 4) + ')">' + xml(label) + "</text>");
            } else {
                out.push('<text x="' + num(p.x) + '" y="' + num(p.y + r + (n.hasClass("axis") ? 4 : 12)) + '" font-size="' +
                         (n.hasClass("axis") ? 12 : 10) + '" text-anchor="middle" fill="' + (n.hasClass("axis") ? "#64748b" : "#1e293b") + '">' +
                         xml(label) + "</text>");
            }
        });
        out.push("</svg>");
        return new Blob([out.join("\n")], { type: "image/svg+xml" });
    }

    function exportGraph(cy, kind, title) {
        var name = baseName(title);
        if (kind === "png") {
            download(cy.png({ output: "blob", bg: "#ffffff", full: true, scale: 2, maxWidth: 8000, maxHeight: 8000 }), name + ".png");
        } else if (kind === "svg") {
            download(svg(cy), name + ".svg");
        } else if (kind === "edges") {
            download(edgesCsv(cy), name + "_edges.csv");
        } else if (kind === "nodes") {
            download(nodesCsv(cy), name + "_nodes.csv");
        } else if (kind === "graphml") {
            download(graphml(cy), name + ".graphml");
        }
    }

    // ---- 範囲選択と、選んだノードの保存 ----

    function selectionBar(bar, cy, payload, selecting) {
        var selected = cy.nodes(":selected").not(".axis");
        bar.innerHTML = "";
        if (!selecting && selected.length < 2) {
            bar.hidden = true;
            return;
        }
        bar.hidden = false;
        var elements = selected.filter(function (n) { return n.data("element") && n.data("href"); });
        var kind = elements.length ? elements[0].data("kind") : "";
        var text = selected.length
            ? "選んだノード " + selected.length + " 件" + (elements.length !== selected.length && elements.length ? "（うち" + kind + " " + elements.length + " 件）" : "")
            : "ドラッグで囲むか、クリックしてノードを選んでください";
        bar.appendChild(element("span", "kg-graph-selection-count", text));
        var save = payload.save;
        if (elements.length && save) {
            var form = element("form", "kg-graph-save");
            form.method = "POST";
            form.action = save.action;
            var input = element("input");
            input.type = "text"; input.name = "name"; input.required = true; input.maxLength = 60;
            input.placeholder = "名前";
            form.appendChild(input);
            var overwrite = element("label");
            var check = element("input");
            check.type = "checkbox"; check.name = "overwrite"; check.value = "1";
            overwrite.appendChild(check);
            overwrite.appendChild(document.createTextNode("上書き"));
            form.appendChild(overwrite);
            function hidden(name, value) {
                var h = element("input");
                h.type = "hidden"; h.name = name; h.value = value;
                form.appendChild(h);
            }
            if (save["class"]) { hidden("class", save["class"]); }
            hidden("source", save.source || "");
            var button = element("button", "", (kind || "選んだもの") + "をコレクションとして保存");
            button.type = "submit";
            form.appendChild(button);
            form.addEventListener("submit", function (event) {
                if (elements.length > save.max) {
                    event.preventDefault();
                    window.alert("保存できるのは " + save.max + " 件までです");
                    return;
                }
                form.querySelectorAll('input[name="uris"]').forEach(function (h) { h.remove(); });
                elements.forEach(function (n) { hidden("uris", n.id()); });
            });
            bar.appendChild(form);
        }
        if (elements.length >= 2 && elements.length <= 4) {
            var compare = element("a", "kg-graph-compare", "並べて比べる");
            compare.href = "/compare?" + elements.map(function (n) { return "uri=" + encodeURIComponent(n.id()); }).join("&");
            bar.appendChild(compare);
        }
        if (selected.length) {
            var clearButton = element("button", "kg-graph-unselect", "選択を解除");
            clearButton.type = "button";
            clearButton.addEventListener("click", function () { cy.nodes().unselect(); });
            bar.appendChild(clearButton);
        }
    }

    window.kgDrawGraph = function (id) {
        var container = document.getElementById(id);
        var source = document.getElementById(id + "-data");
        if (!container || !source) { return; }
        if (typeof window.cytoscape !== "function") {
            container.textContent = "ネットワーク図の部品（Cytoscape.js）を読み込めませんでした。ネットワークの接続を確かめてください。";
            container.classList.add("kg-graph-error");
            return;
        }
        var payload = JSON.parse(source.textContent);
        var positions = payload.positions || {};
        var cy = window.cytoscape({
            container: container,
            elements: payload.elements,
            style: stylesheet(payload),
            layout: layoutOptions(payload.layout, positions),
            minZoom: 0.03,
            maxZoom: 4,
            wheelSensitivity: 0.25,
            boxSelectionEnabled: true,      // Shift（または「範囲を選ぶ」）を押してドラッグで囲んで選ぶ
            selectionType: "single"
        });
        cy.nodes(".axis").unselectify();
        function setArcs(layout) {
            if (layout === "timeline") { cy.edges().addClass("arc"); } else { cy.edges().removeClass("arc"); }
            if (layout === "bipartite") { cy.nodes(".top").addClass("tilted"); } else { cy.nodes(".top").removeClass("tilted"); }
            // 年の目盛りは、年で並べるときだけ出す
            cy.nodes(".axis").style("display", layout === "timeline" ? "element" : "none");
        }
        setArcs(payload.layout);
        cy.fit(cy.elements(":visible"), 40);
        graphs.push(cy);
        container.kgCy = cy;
        var wrap = container.closest(".kg-graph-wrap");
        var panel = document.getElementById(id + "-panel");

        function clear() {
            cy.elements().removeClass("faded neighbor focus");
            if (!panel.hidden) {
                panel.hidden = true;
                cy.resize();   // 右の欄を閉じると図の幅が変わる
            }
        }
        function focus(node) {
            cy.elements().not(".axis").removeClass("neighbor focus").addClass("faded");
            var around = node.closedNeighborhood();
            around.removeClass("faded").addClass("neighbor");
            node.addClass("focus");
            var opening = panel.hidden;
            showPanel(panel, node, function (n) { focus(n); cy.animate({ center: { eles: n } }, { duration: 300 }); });
            if (opening) {
                cy.resize();   // 右の欄を開くと図の幅が変わる。選んだノードが見えるようにする
                if (node.renderedPosition().x > container.clientWidth - 20) {
                    cy.animate({ center: { eles: node } }, { duration: 300 });
                }
            }
        }

        var selecting = false;
        var bar = wrap ? wrap.querySelector(".kg-graph-selection") : null;
        var pending = null;
        function updateBar() {
            if (!bar) { return; }
            window.clearTimeout(pending);
            pending = window.setTimeout(function () { selectionBar(bar, cy, payload, selecting); }, 30);
        }
        cy.on("select unselect", "node", updateBar);

        cy.on("tap", "node", function (event) {
            if (selecting) { return; }      // 範囲を選ぶあいだは、クリックで選ぶ・外すだけ
            focus(event.target);
        });
        cy.on("tap", function (event) { if (event.target === cy) { clear(); } });
        cy.on("dbltap", "node", function (event) {
            var href = event.target.data("href");
            if (href) { window.location.href = href; }
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

        if (wrap) {
            // 指標の表の「図で見る」
            wrap.addEventListener("click", function (event) {
                var button = event.target.closest ? event.target.closest(".kg-graph-locate") : null;
                if (!button) { return; }
                var node = cy.getElementById(button.dataset.node);
                if (!node || node.empty()) { return; }
                container.scrollIntoView({ behavior: "smooth", block: "center" });
                focus(node);
                cy.animate({ center: { eles: node }, zoom: Math.max(cy.zoom(), 1) }, { duration: 400 });
            });
            var selectButton = wrap.querySelector(".kg-graph-select");
            if (selectButton) {
                selectButton.addEventListener("click", function () {
                    selecting = !selecting;
                    selectButton.setAttribute("aria-pressed", selecting ? "true" : "false");
                    selectButton.classList.toggle("active", selecting);
                    container.classList.toggle("kg-graph-selecting", selecting);
                    cy.userPanningEnabled(!selecting);   // ドラッグで図を動かす代わりに、囲んで選ぶ
                    cy.selectionType(selecting ? "additive" : "single");
                    if (selecting) { clear(); }
                    updateBar();
                });
            }
            wrap.querySelectorAll("[data-export]").forEach(function (button) {
                button.addEventListener("click", function () {
                    exportGraph(cy, button.dataset.export, payload.title);
                    var menu = button.closest("details");
                    if (menu) { menu.open = false; }
                });
            });
            var fit = wrap.querySelector(".kg-graph-fit");
            if (fit) { fit.addEventListener("click", function () { cy.fit(undefined, 30); }); }
            var select = wrap.querySelector(".kg-graph-layout");
            if (select) {
                select.addEventListener("change", function () {
                    setArcs(select.value);
                    cy.elements().not(".axis").layout(layoutOptions(select.value, positions)).run();
                });
            }
        }
    };

    // 隠れたタブの中で描いた図は大きさが 0 になるので、タブを開いたときに描き直す
    document.addEventListener("click", function (event) {
        if (event.target.closest && event.target.closest("button.kg-tab-button")) {
            window.setTimeout(function () {
                graphs.forEach(function (cy) { cy.resize(); cy.fit(undefined, 30); });
            }, 50);
        }
    });
})();
