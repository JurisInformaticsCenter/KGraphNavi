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
            { selector: "node.focus", style: { "border-color": "#0f172a", "border-width": 3, "z-index": 20 } },
            { selector: "edge", style: {
                "width": "mapData(weight, 1, 5, 1, 4)", "line-color": "#cbd5e1", "curve-style": "straight",
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
                "events": "no", "opacity": 1
            } }
        ];
    }

    function layoutOptions(name, positions) {
        switch (name) {
        case "timeline":
            return { name: "preset", positions: function (node) { return positions[node.id()]; }, fit: true, padding: 30 };
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
        } else {
            fact("つながり", (data.indegree + data.outdegree) + " 件");
        }
        panel.appendChild(facts);

        function neighborList(label, nodes) {
            if (!nodes.length) { return; }
            panel.appendChild(element("h4", "kg-graph-panel-sub", label + "（" + nodes.length + "）"));
            var list = element("ul", "kg-graph-neighbors");
            nodes.sort(function (a, b) { return b.data("size") - a.data("size"); }).slice(0, 30).forEach(function (n) {
                var item = element("li");
                var button = element("button", "kg-graph-neighbor", n.data("label"));
                button.type = "button";
                button.addEventListener("click", function () { focus(n); });
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
            neighborList("つながっている", node.neighborhood("node").toArray());
        }
        if (data.href) {
            panel.appendChild(element("p", "kg-graph-hint", "ダブルクリックでこのページを開きます"));
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
        var positions = {};
        payload.elements.forEach(function (e) {
            if (e.position) { positions[e.data.id] = e.position; }
        });
        var cy = window.cytoscape({
            container: container,
            elements: payload.elements,
            style: stylesheet(payload),
            layout: layoutOptions(payload.layout, positions),
            minZoom: 0.03,
            maxZoom: 4,
            wheelSensitivity: 0.25
        });
        function setArcs(layout) {
            if (layout === "timeline") { cy.edges().addClass("arc"); } else { cy.edges().removeClass("arc"); }
            // 年の目盛りは、年で並べるときだけ出す
            cy.nodes(".axis").style("display", layout === "timeline" ? "element" : "none");
        }
        setArcs(payload.layout);
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

        cy.on("tap", "node", function (event) { focus(event.target); });
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
