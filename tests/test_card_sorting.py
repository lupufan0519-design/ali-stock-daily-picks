import json
import shutil
import subprocess
import unittest
from html.parser import HTMLParser

from simple_report_ui import SCRIPT, render_report


class _SortControlParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.section_ids = []
        self.controls = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "section":
            self.section_ids.append(attrs.get("id"))
        if attrs.get("id") in {"sort-key", "sort-direction"}:
            self.controls[attrs["id"]] = (tag, attrs, list(self.section_ids))

    def handle_endtag(self, tag):
        if tag == "section" and self.section_ids:
            self.section_ids.pop()


class CardSortingStructureTests(unittest.TestCase):
    def test_sort_controls_belong_to_today_view_and_have_touch_targets(self):
        page = render_report([], {"line_gap_max_abs": 0.5}, 0, [])
        parsed = _SortControlParser()
        parsed.feed(page)
        self.assertEqual(set(parsed.controls), {"sort-key", "sort-direction"})
        for control_id, (_, attrs, ancestors) in parsed.controls.items():
            with self.subTest(control=control_id):
                self.assertIn("today-view", ancestors)
                self.assertNotIn("history-view", ancestors)
                if control_id == "sort-key":
                    self.assertTrue(attrs.get("aria-label") or f'for="{control_id}"' in page)
        self.assertEqual(parsed.controls["sort-key"][0], "select")
        self.assertEqual(parsed.controls["sort-direction"][0], "button")
        self.assertEqual(parsed.controls["sort-direction"][1].get("type"), "button")
        self.assertRegex(page, r"min-height:\s*44px")


@unittest.skipUnless(shutil.which("node"), "Node.js is required to exercise sorting JavaScript")
class CardSortingBehaviorTests(unittest.TestCase):
    """Execute the shipped script; the DOM/storage doubles perform no I/O."""

    HARNESS = r"""
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
class Element {
  constructor(tag) {
    this.tag = tag; this.className = ''; this.childNodes = []; this.attributes = {};
    this.dataset = {}; this._text = ''; this.value = ''; this.hidden = false; this.listeners = {};
    this.classList = {add() {}, remove() {}, toggle() {}};
  }
  set textContent(value) { this._text = String(value); this.childNodes = []; }
  get textContent() { return this._text + this.childNodes.map(child => child.textContent).join(''); }
  appendChild(child) { this.childNodes.push(child); return child; }
  append(...children) { children.forEach(child => this.appendChild(child)); }
  replaceChildren(...children) { this._text = ''; this.childNodes = children; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(type, handler) { (this.listeners[type] ||= []).push(handler); }
  dispatch(type) { (this.listeners[type] || []).forEach(handler => handler({target: this})); }
}
const elements = new Map();
global.document = {
  createElement: tag => new Element(tag),
  getElementById: id => {
    if (!elements.has(id)) elements.set(id, new Element('div'));
    return elements.get(id);
  },
  querySelectorAll: () => []
};
const values = new Map();
if (input.stored !== null) values.set('stock-card-sort-v1', input.stored);
const storage = {
  values,
  getItem(key) {
    if (input.storageMode === 'blocked') throw new Error('Storage access denied');
    return values.has(key) ? values.get(key) : null;
  },
  setItem(key, value) {
    if (input.storageMode === 'blocked' || input.storageMode === 'quota') throw new Error('Storage unavailable');
    values.set(key, String(value));
  }
};
global.localStorage = storage;
global.window = {setInterval() {}, localStorage: storage};
document.getElementById('initial-data').textContent = JSON.stringify(input.state || {
  live_trade_date: '2026-09-18', live_pools: {first: [], second: [], third: []}
});
global.fetch = async () => ({ok: false, status: 503});
const end = input.script.lastIndexOf('}());');
if (end < 0) throw new Error('Cannot find script closure');
eval(input.script.slice(0, end) + '\n globalThis.sortHelpers = {SORT_OPTIONS, sortValue, sortedRows, readSortPreference, saveSortPreference, updateToday};\n' + input.script.slice(end));
const result = new Function('h', 'data', 'storage', 'elements', input.action)(global.sortHelpers, input.data, storage, elements);
process.stdout.write(JSON.stringify(result));
"""

    def run_js(self, action, data=None, *, stored=None, storage_mode="normal", state=None):
        result = subprocess.run(
            [shutil.which("node"), "-e", self.HARNESS],
            input=json.dumps({
                "script": SCRIPT,
                "action": action,
                "data": data,
                "stored": stored,
                "storageMode": storage_mode,
                "state": state,
            }, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_supported_sort_options_and_default_directions(self):
        options = self.run_js("return h.SORT_OPTIONS;")
        self.assertEqual(set(options), {"gap", "change", "revenue", "parent", "adjusted", "cash"})
        self.assertTrue(options["gap"]["label"].startswith("见底后差额"))
        self.assertEqual(options["gap"]["direction"], "asc")
        self.assertTrue(all(options[key]["direction"] == "desc" for key in options if key != "gap"))

    def test_sort_value_maps_all_financial_metrics_and_preserves_negative_and_zero(self):
        result = self.run_js("""
const row = {change_pct: -1.2, bottom_price_gap_abs: 0, financials: {
  revenue_yoy_pct: 0, parent_profit_yoy_pct: -15.25, adjusted_profit_yoy_pct: 21.5,
  operating_cash_to_parent_profit: -0.5, cash_ratio_status: 'ok'
}};
return Object.fromEntries(Object.keys(h.SORT_OPTIONS).map(key => [key, h.sortValue(row, key)]));
""")
        self.assertEqual(result, {"gap": 0, "change": -1.2, "revenue": 0, "parent": -15.25, "adjusted": 21.5, "cash": -0.5})

    def test_gap_uses_recorded_absolute_gap_then_valid_price_fallback(self):
        rows = [
            {"bottom_price_gap_abs": 0, "price": 12, "bottom_price": 10},
            {"bottom_price_gap_abs": 3, "price": 12, "bottom_price": 10},
            {"price": 8, "close": 20, "bottom_price": 10},
            {"close": 12, "bottom_price": 10},
            {"bottom_price_gap_abs": None, "price": 11.5, "bottom_price": 10},
            {"price": 10, "bottom_price": 10},
            {"price": 0, "bottom_price": 10},
            {"price": -1, "bottom_price": 10},
            {"price": 12, "bottom_price": 0},
            {"price": 12},
            {"price": 0, "close": 12, "bottom_price": 10},
            {"price": "12", "close": 11, "bottom_price": 10},
            {"bottom_price_gap_abs": -1, "price": 12, "bottom_price": 10},
            {"bottom_price_gap_abs": "1", "price": 12, "bottom_price": 10},
            {},
        ]
        result = self.run_js("return data.map(row => h.sortValue(row, 'gap'));", rows)
        self.assertEqual(result, [0, 3, 2, 2, 1.5, 0, None, None, None, None, 2, 1, 2, 2, None])

    def test_non_numeric_and_nonfinite_values_are_missing_not_zero(self):
        result = self.run_js("""
const invalid = [undefined, null, '', '0', '12.3', false, true, [], {}, NaN, Infinity, -Infinity];
return invalid.map(value => ['change', 'revenue', 'parent', 'adjusted', 'cash'].map(key => h.sortValue({
  change_pct: value,
  financials: {revenue_yoy_pct: value, parent_profit_yoy_pct: value, adjusted_profit_yoy_pct: value,
    operating_cash_to_parent_profit: value, cash_ratio_status: 'ok'}
}, key)));
""")
        self.assertEqual(result, [[None] * 5 for _ in range(12)])

    def test_cash_ratio_requires_ok_status_even_when_a_number_exists(self):
        result = self.run_js("""
return [undefined, 'missing', 'nonpositive_profit', 'unknown', 'ok'].map(status => h.sortValue({
  financials: {operating_cash_to_parent_profit: 0, cash_ratio_status: status}
}, 'cash'));
""")
        self.assertEqual(result, [None, None, None, None, 0])

    def test_missing_rows_are_last_in_both_directions_and_ties_remain_stable(self):
        rows = [
            {"code": "missing-a"},
            {"code": "zero", "change_pct": 0},
            {"code": "positive-a", "change_pct": 2},
            {"code": "negative", "change_pct": -3},
            {"code": "positive-b", "change_pct": 2},
            {"code": "missing-b", "change_pct": None},
        ]
        result = self.run_js("return ['asc', 'desc'].map(direction => h.sortedRows(data, 'change', direction).map(row => row.code));", rows)
        self.assertEqual(result[0], ["negative", "zero", "positive-a", "positive-b", "missing-a", "missing-b"])
        self.assertEqual(result[1], ["positive-a", "positive-b", "zero", "negative", "missing-a", "missing-b"])

    def test_sorted_rows_returns_a_copy_without_mutating_rows_or_financials(self):
        result = self.run_js("""
const rows = [{code: 'a', financials: {revenue_yoy_pct: 1}}, {code: 'b', financials: {revenue_yoy_pct: 3}}];
const before = JSON.stringify(rows);
rows.forEach(row => {Object.freeze(row.financials); Object.freeze(row);});
Object.freeze(rows);
const sorted = h.sortedRows(rows, 'revenue', 'desc');
return {copied: sorted !== rows, untouched: JSON.stringify(rows) === before,
  codes: sorted.map(row => row.code), sameItems: sorted[0] === rows[1] && sorted[1] === rows[0]};
""")
        self.assertEqual(result, {"copied": True, "untouched": True, "codes": ["b", "a"], "sameItems": True})

    def test_empty_and_all_missing_arrays_keep_order(self):
        result = self.run_js("""
return {empty: h.sortedRows([], 'gap', 'asc'), missing: h.sortedRows([{code: 'a'}, {code: 'b'}], 'cash', 'desc').map(row => row.code)};
""")
        self.assertEqual(result, {"empty": [], "missing": ["a", "b"]})

    def test_each_tier_is_sorted_independently_when_cards_render(self):
        state = {
            "live_trade_date": "2026-09-18",
            "live_pools": {
                "first": [{"name": "一甲", "code": "600001", "bottom_price_gap_abs": 8}, {"name": "一乙", "code": "600002", "bottom_price_gap_abs": 2}],
                "second": [{"name": "二甲", "code": "600003", "bottom_price_gap_abs": 6}, {"name": "二乙", "code": "600004", "bottom_price_gap_abs": 1}],
                "third": [{"name": "三甲", "code": "600005", "bottom_price_gap_abs": 7}, {"name": "三乙", "code": "600006", "bottom_price_gap_abs": 3}],
            },
        }
        result = self.run_js("""
function names(root) { return (root.className || '').split(' ').includes('stock-name') ? [root.textContent] : root.childNodes.flatMap(names); }
h.updateToday();
return ['first-picks', 'second-picks', 'third-picks'].map(id => names(elements.get(id)));
""", state=state)
        self.assertEqual(result, [["一乙", "一甲"], ["二乙", "二甲"], ["三乙", "三甲"]])

    def test_saved_sort_preference_applies_to_the_rendered_cards(self):
        state = {"live_trade_date": "2026-09-18", "live_pools": {"first": [
            {"name": "负增长", "code": "600001", "financials": {"revenue_yoy_pct": -5}},
            {"name": "缺失", "code": "600002"},
            {"name": "正增长", "code": "600003", "financials": {"revenue_yoy_pct": 10}},
        ]}}
        result = self.run_js("""
function names(root) { return root.className === 'stock-name' ? [root.textContent] : root.childNodes.flatMap(names); }
return names(elements.get('first-picks'));
""", state=state, stored=json.dumps({"key": "revenue", "direction": "desc"}))
        self.assertEqual(result, ["正增长", "负增长", "缺失"])

    def test_invalid_sort_key_falls_back_to_default_gap_order(self):
        result = self.run_js("""
const rows = [{code: 'far', bottom_price_gap_abs: 3}, {code: 'near', bottom_price_gap_abs: 1}, {code: 'missing'}];
return ['unknown', '__proto__', 'constructor', 'toString'].map(key => h.sortedRows(rows, key, 'asc').map(row => row.code));
""")
        self.assertEqual(result, [["near", "far", "missing"]] * 4)

    def test_missing_corrupt_or_invalid_storage_falls_back_to_default(self):
        for stored in [None, "{broken", "null", "[]", '"revenue"', "{}", '{"key":"bogus","direction":"asc"}', '{"key":"__proto__","direction":"desc"}']:
            with self.subTest(stored=stored):
                result = self.run_js("return h.readSortPreference();", stored=stored)
                self.assertEqual(result, {"key": "gap", "direction": "asc"})

    def test_sort_value_rejects_invalid_keys_even_with_unexpected_financial_fields(self):
        result = self.run_js("""
return ['unknown', '__proto__', 'constructor', 'toString', null].map(key => h.sortValue({financials: {undefined: 123}}, key));
""")
        self.assertEqual(result, [None] * 5)

    def test_invalid_direction_preserves_valid_key_and_uses_its_default(self):
        for key, expected_direction in [("gap", "asc"), ("revenue", "desc"), ("cash", "desc")]:
            with self.subTest(key=key):
                result = self.run_js("return h.readSortPreference();", stored=json.dumps({"key": key, "direction": "sideways"}))
                self.assertEqual(result, {"key": key, "direction": expected_direction})

    def test_controls_change_sort_key_toggle_direction_and_persist_both(self):
        result = self.run_js("""
const select = elements.get('sort-key');
const button = elements.get('sort-direction');
const initial = {key: select.value, label: button.attributes['aria-label'], count: select.childNodes.length};
select.value = 'revenue';
select.dispatch('change');
const changed = h.readSortPreference();
button.dispatch('click');
return {initial, changed, toggled: h.readSortPreference(), label: button.attributes['aria-label']};
""")
        self.assertEqual(result["initial"]["key"], "gap")
        self.assertEqual(result["initial"]["count"], 6)
        self.assertIn("从小到大", result["initial"]["label"])
        self.assertEqual(result["changed"], {"key": "revenue", "direction": "desc"})
        self.assertEqual(result["toggled"], {"key": "revenue", "direction": "asc"})
        self.assertIn("从小到大", result["label"])

    def test_valid_preferences_round_trip_under_versioned_storage_key(self):
        for preference in [{"key": "gap", "direction": "desc"}, {"key": "cash", "direction": "asc"}, {"key": "adjusted", "direction": "desc"}]:
            with self.subTest(preference=preference):
                result = self.run_js("""
h.saveSortPreference(data);
return {read: h.readSortPreference(), saved: JSON.parse(storage.values.get('stock-card-sort-v1')), keys: [...storage.values.keys()]};
""", preference)
                self.assertEqual(result, {"read": preference, "saved": preference, "keys": ["stock-card-sort-v1"]})

    def test_restricted_or_full_storage_does_not_break_sorting(self):
        for mode in ["blocked", "quota"]:
            with self.subTest(mode=mode):
                result = self.run_js("""
h.saveSortPreference({key: 'cash', direction: 'desc'});
return {read: h.readSortPreference(), sorted: h.sortedRows([{change_pct: -1}, {change_pct: 0}], 'change', 'desc').map(row => row.change_pct)};
""", storage_mode=mode)
                self.assertEqual(result, {"read": {"key": "gap", "direction": "asc"}, "sorted": [0, -1]})


if __name__ == "__main__":
    unittest.main()
