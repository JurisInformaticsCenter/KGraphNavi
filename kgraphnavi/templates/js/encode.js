// ノードの見た目の割り当て（形・色・大きさ）と凡例。ネットワーク図（graph.js）と探索グラフ（explore.js）で共通。
// 2026.11.9
//
//   形   = ノードの種類（判例・条・語…）。種類ごとに固定（data.shape）
//   色   = 画面で選ぶ1つの意味（種類・年・属性）。値の種類なら色分け、数なら濃淡
//   大きさ = 画面で選ぶ1つの指標（被参照数・PageRank・全体の件数…）。面積が値に比例するよう平方根で目盛る
//
// ノードの data に置くもの（サーバ・explore.js が付ける）
//   kind, shape, x（年）, a_<名前>（属性）, m_<名前>（大きさの指標）
// この部品が付けるもの: _color, _size（スタイルシートは data(_color)・data(_size) を使う）
(function () {
    "use strict";

    // 色覚の違いに配慮した色（Okabe & Ito をもとに、白い背景で見分けやすい順）
    var PALETTE = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9", "#D55E00", "#7A5195", "#999933"];
    var OTHER = "#b8bec7";      // 上の色に収まらない値（その他）
    var MISSING = "#e2e8f0";    // 値が無い
    var OUTSIDE = "#9ca3af";    // コレクション外（種類で色分けするとき）
    // 数の濃淡（薄い青 → 濃い青）
    var LOW = [222, 235, 247], HIGH = [8, 48, 107];
    var SHAPES = ["ellipse", "round-rectangle", "diamond", "hexagon", "triangle", "barrel", "tag", "star", "vee"];
    var MIN_PX = 12, MAX_PX = 56;

    function hex(rgb) {
        return "#" + rgb.map(function (v) { return Math.round(v).toString(16).padStart(2, "0"); }).join("");
    }

    function ramp(t) {
        t = Math.max(0, Math.min(1, t));
        return hex([0, 1, 2].map(function (i) { return LOW[i] + (HIGH[i] - LOW[i]) * t; }));
    }

    function valueOf(node, name) {
        var d = node.data();
        if (name === "kind") { return d.kind; }
        if (name === "year") { return d.x; }
        if (name === "component") { return d.component; }
        var v = d["a_" + name];
        return v === undefined || v === null || v === "" ? undefined : v;
    }

    function isNumber(v) { return v !== undefined && v !== null && v !== "" && !isNaN(Number(v)); }

    // 色の割り当て。カテゴリの色は呼び出しをまたいで覚える（探索グラフで広げても色が変わらないように）
    function Encoder(options) {
        this.color = options.color || [];       // [{name, label, type: "category"|"number"}]
        this.size = options.size || [];         // [{name, label}]
        this.colorName = options.colorDefault || (this.color[0] || {}).name || "kind";
        this.sizeName = options.sizeDefault || (this.size[0] || {}).name || "none";
        this.fixed = options.colors || {};      // {色の名前: {値: 色}}（種類の色など、設定で決めたもの）
        this.maps = {};                         // {色の名前: {値: 色}}
        this.range = null;
    }

    Encoder.prototype.option = function (list, name) {
        for (var i = 0; i < list.length; i++) { if (list[i].name === name) { return list[i]; } }
        return { name: name, label: name };
    };

    Encoder.prototype.colorType = function (nodes) {
        var opt = this.option(this.color, this.colorName);
        if (opt.type) { return opt.type; }
        if (this.colorName === "year") { return "number"; }
        if (this.colorName === "kind" || this.colorName === "component") { return "category"; }
        var values = nodes.map(function (n) { return valueOf(n, opt.name); }).filter(function (v) { return v !== undefined; });
        return values.length && values.every(isNumber) ? "number" : "category";
    };

    // カテゴリの値に色を割り当てる（多い順。新しい値は空いている色、なければ「その他」）
    Encoder.prototype.categoryMap = function (nodes) {
        var name = this.colorName;
        var map = this.maps[name] = this.maps[name] || {};
        var fixed = this.fixed[name] || {};
        var counts = {};
        nodes.forEach(function (n) {
            var v = valueOf(n, name);
            if (v !== undefined) { counts[v] = (counts[v] || 0) + 1; }
        });
        var used = {};
        Object.keys(map).forEach(function (v) { used[map[v]] = true; });
        Object.keys(counts).sort(function (a, b) { return counts[b] - counts[a] || (a < b ? -1 : 1); })
            .forEach(function (v) {
                if (map[v]) { return; }
                if (fixed[v]) { map[v] = fixed[v]; used[fixed[v]] = true; return; }
                var free = PALETTE.filter(function (c) { return !used[c]; })[0];
                map[v] = free || OTHER;
                if (free) { used[free] = true; }
            });
        return { map: map, counts: counts };
    };

    // ノードに _color・_size を付ける。返り値は凡例の情報
    Encoder.prototype.apply = function (cy) {
        var nodes = cy.nodes().not(".axis").toArray();
        var self = this;
        var legend = { color: null, size: null, shapes: [] };
        var type = this.colorType(nodes);
        if (type === "number") {
            var nums = nodes.map(function (n) { return valueOf(n, self.colorName); }).filter(isNumber).map(Number);
            var lo = nums.length ? Math.min.apply(null, nums) : 0, hi = nums.length ? Math.max.apply(null, nums) : 0;
            nodes.forEach(function (n) {
                var v = valueOf(n, self.colorName);
                n.data("_color", isNumber(v) ? ramp(hi > lo ? (Number(v) - lo) / (hi - lo) : 0.6) : MISSING);
            });
            legend.color = { type: "number", label: this.option(this.color, this.colorName).label, low: lo, high: hi,
                             lowColor: ramp(0), highColor: ramp(1), missing: nodes.some(function (n) { return !isNumber(valueOf(n, self.colorName)); }) };
        } else {
            var cat = this.categoryMap(nodes);
            var other = false, missing = false;
            nodes.forEach(function (n) {
                var v = valueOf(n, self.colorName);
                var c = v === undefined ? MISSING : (cat.map[v] || OTHER);
                if (self.colorName === "kind" && n.hasClass("outside")) { c = OUTSIDE; }
                if (c === OTHER) { other = true; }
                if (c === MISSING) { missing = true; }
                n.data("_color", c);
            });
            var items = Object.keys(cat.counts)
                .filter(function (v) { return cat.map[v] && cat.map[v] !== OTHER; })
                .sort(function (a, b) { return cat.counts[b] - cat.counts[a]; })
                .map(function (v) { return { value: v, color: cat.map[v], count: cat.counts[v] }; });
            legend.color = { type: "category", label: this.option(this.color, this.colorName).label,
                             items: items, other: other, missing: missing,
                             outside: self.colorName === "kind" && nodes.some(function (n) { return n.hasClass("outside"); }) };
        }
        // 大きさ（面積が値に比例するよう、半径を平方根で目盛る）
        var sizeName = this.sizeName;
        var values = nodes.map(function (n) { return Number(n.data("m_" + sizeName)) || 0; });
        var top = Math.max.apply(null, values.concat([0]));
        nodes.forEach(function (n, i) {
            n.data("_size", sizeName === "none" || top <= 0 ? 22 : MIN_PX + (MAX_PX - MIN_PX) * Math.sqrt(values[i] / top));
        });
        if (sizeName !== "none" && top > 0) {
            legend.size = { label: this.option(this.size, sizeName).label, max: top };
        }
        // 形 = 種類
        var shapes = {};
        nodes.forEach(function (n) { shapes[n.data("kind")] = n.data("shape") || "ellipse"; });
        legend.shapes = Object.keys(shapes).map(function (k) { return { kind: k, shape: shapes[k] }; });
        this.lastLegend = legend;
        return legend;
    };

    // ---- 凡例 ----

    // 形の小さな絵（SVG）
    function shapeIcon(shape, color) {
        var c = color || "#64748b";
        var path;
        switch (shape) {
        case "round-rectangle": case "rectangle": case "barrel":
            path = '<rect x="2" y="3" width="12" height="10" rx="' + (shape === "rectangle" ? 0 : 3) + '" fill="' + c + '"/>'; break;
        case "diamond": path = '<polygon points="8,1 15,8 8,15 1,8" fill="' + c + '"/>'; break;
        case "triangle": case "round-triangle": path = '<polygon points="8,2 15,14 1,14" fill="' + c + '"/>'; break;
        case "hexagon": path = '<polygon points="4,2 12,2 15,8 12,14 4,14 1,8" fill="' + c + '"/>'; break;
        case "tag": path = '<polygon points="1,3 11,3 15,8 11,13 1,13" fill="' + c + '"/>'; break;
        case "star": path = '<polygon points="8,1 10,6 15,6 11,9 13,15 8,11 3,15 5,9 1,6 6,6" fill="' + c + '"/>'; break;
        case "vee": path = '<polygon points="1,2 8,7 15,2 8,15" fill="' + c + '"/>'; break;
        default: path = '<circle cx="8" cy="8" r="6" fill="' + c + '"/>';
        }
        return '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">' + path + "</svg>";
    }

    function esc(text) {
        return String(text === undefined || text === null ? "" : text)
            .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }

    function fmt(v) {
        var n = Number(v);
        if (isNaN(n)) { return esc(v); }
        return Math.abs(n) >= 1000 || Number.isInteger(n) ? Math.round(n).toLocaleString() : n.toFixed(2);
    }

    function renderLegend(el, legend, opts) {
        if (!el || !legend) { return; }
        opts = opts || {};
        var parts = [];
        if (legend.shapes.length > 1 || opts.alwaysShapes) {
            parts.push('<span class="kg-legend-group"><span class="kg-legend-head">形</span>' +
                legend.shapes.map(function (s) {
                    return '<span class="kg-legend-item">' + shapeIcon(s.shape) + esc(s.kind) + "</span>";
                }).join("") + "</span>");
        }
        var c = legend.color;
        if (c && c.type === "number") {
            parts.push('<span class="kg-legend-group"><span class="kg-legend-head">色: ' + esc(c.label) + "</span>" +
                '<span class="kg-legend-item">' + fmt(c.low) +
                '<span class="kg-legend-ramp" style="background:linear-gradient(90deg,' + c.lowColor + "," + c.highColor + ')"></span>' +
                fmt(c.high) + "</span>" +
                (c.missing ? '<span class="kg-legend-item"><span class="kg-legend-swatch" style="background:' + MISSING + '"></span>値なし</span>' : "") +
                "</span>");
        } else if (c) {
            var max = opts.maxItems || 12;
            var items = c.items.slice(0, max);
            parts.push('<span class="kg-legend-group"><span class="kg-legend-head">色: ' + esc(c.label) + "</span>" +
                items.map(function (it) {
                    var filter = opts.filterable ? ' data-legend-value="' + esc(it.value) + '" role="button" tabindex="0" title="クリックでこの値のノードを強調"' : "";
                    return '<span class="kg-legend-item"' + filter + '><span class="kg-legend-swatch" style="background:' + it.color + '"></span>' +
                        esc(opts.valueLabel ? opts.valueLabel(it.value) : it.value) + ' <span class="kg-legend-count">' + it.count + "</span></span>";
                }).join("") +
                (c.items.length > max || c.other ? '<span class="kg-legend-item"><span class="kg-legend-swatch" style="background:' + OTHER + '"></span>その他</span>' : "") +
                (c.missing ? '<span class="kg-legend-item"><span class="kg-legend-swatch" style="background:' + MISSING + '"></span>値なし</span>' : "") +
                (c.outside ? '<span class="kg-legend-item"><span class="kg-legend-swatch" style="background:' + OUTSIDE + ';outline:1px dashed #6b7280"></span>コレクション外</span>' : "") +
                "</span>");
        }
        if (legend.size) {
            parts.push('<span class="kg-legend-group"><span class="kg-legend-head">大きさ: ' + esc(legend.size.label) + "</span>" +
                '<span class="kg-legend-item"><span class="kg-legend-circle" style="width:8px;height:8px"></span>小' +
                '<span class="kg-legend-circle" style="width:18px;height:18px"></span>' + fmt(legend.size.max) + "</span></span>");
        }
        el.innerHTML = parts.join("");
    }

    // 色・大きさを選ぶ <select> を作る（選択肢が1つなら作らない）
    function selectBox(label, options, current, onChange) {
        if (!options || options.length < 2) { return null; }
        var wrap = document.createElement("label");
        wrap.className = "kg-encode-choice";
        wrap.appendChild(document.createTextNode(label + " "));
        var select = document.createElement("select");
        options.forEach(function (o) {
            var opt = document.createElement("option");
            opt.value = o.name; opt.textContent = o.label || o.name;
            if (o.name === current) { opt.selected = true; }
            select.appendChild(opt);
        });
        select.addEventListener("change", function () { onChange(select.value); });
        wrap.appendChild(select);
        return wrap;
    }

    window.kgEncode = {
        Encoder: Encoder,
        renderLegend: renderLegend,
        selectBox: selectBox,
        shapeIcon: shapeIcon,
        SHAPES: SHAPES,
        PALETTE: PALETTE,
        valueOf: valueOf
    };
})();
